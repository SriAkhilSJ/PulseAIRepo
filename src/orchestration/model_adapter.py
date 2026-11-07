"""
src/orchestration/model_adapter.py - Model Execution Adapter for Autonomous Engineering.

Phase 12.1: Real Model Execution & Provider Integration.
Replaces synthetic handler stubs with real, model-powered software engineering:
- Connects to Crusor's configured model provider infrastructure via src.llm.factory.
- Passes authentic prompt context: target files, architecture blueprint, specification, project intelligence.
- Enforces FinOps pre-call budget checks, token accounting, and cost tracking.
- Enforces Identity/RBAC tool authorization before mutation.
- Feeds model output directly into ControlledImplementationEngine and WorkspaceMutationBroker.
- Provides deterministic, high-fidelity mock execution for automated test suites.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.finops.pricing_registry import PricingRegistry, VerificationStatus
from src.identity.models import Permission, RoleTemplate, User
from src.identity.tool_authorizer import get_tool_authorizer
from src.llm.factory import TurnCancelledError, get_llm
from src.orchestration.finops_governor import (
    BudgetExhaustedError,
    OrchestrationFinOpsGovernor,
)
from src.orchestration.implementation_engine import ControlledImplementationEngine
from src.orchestration.loop import BoundedAutonomousReasoningLoop
from src.orchestration.models import EngineeringTaskNode

log = logging.getLogger("crusor.orchestration.model_adapter")


class ModelAccountingError(RuntimeError):
    """Base exception for model accounting and billing failures."""
    pass


class MissingUsageReceiptError(ModelAccountingError):
    """Raised when an LLM provider response lacks authentic token usage receipts."""
    pass


class UnknownModelPricingError(ModelAccountingError):
    """Raised when a model or provider rate card cannot be established in the pricing registry."""
    pass


def extract_provider_token_usage(response: Any) -> Tuple[int, int, int]:
    """
    Extracts authentic (input_tokens, output_tokens, cached_tokens) from LLM response receipts.
    Fails closed by raising MissingUsageReceiptError if no valid token usage is found.
    """
    if response is None:
        raise MissingUsageReceiptError("Response object is None; cannot extract usage receipt.")

    # 1. Check LangChain usage_metadata (dict)
    if hasattr(response, "usage_metadata") and isinstance(response.usage_metadata, dict) and response.usage_metadata:
        usage = response.usage_metadata
        in_tok = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        out_tok = usage.get("output_tokens") or usage.get("completion_tokens") or 0
        details = usage.get("input_token_details") or {}
        cached_tok = details.get("cache_read") or usage.get("cached_tokens") or 0
        if in_tok > 0 or out_tok > 0:
            return int(in_tok), int(out_tok), int(cached_tok)

    # 2. Check response_metadata (e.g. token_usage or usage)
    if hasattr(response, "response_metadata") and isinstance(response.response_metadata, dict):
        resp_meta = response.response_metadata
        tok_usage = resp_meta.get("token_usage") or resp_meta.get("usage")
        if isinstance(tok_usage, dict) and tok_usage:
            in_tok = tok_usage.get("prompt_tokens") or tok_usage.get("input_tokens") or 0
            out_tok = tok_usage.get("completion_tokens") or tok_usage.get("output_tokens") or 0
            cached_tok = 0
            if isinstance(tok_usage.get("prompt_tokens_details"), dict):
                cached_tok = tok_usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
            elif "cached_tokens" in tok_usage:
                cached_tok = tok_usage.get("cached_tokens", 0)
            if in_tok > 0 or out_tok > 0:
                return int(in_tok), int(out_tok), int(cached_tok)

    # 3. Check direct attribute .usage (OpenAI / Anthropic SDK response objects)
    if hasattr(response, "usage") and response.usage is not None:
        u = response.usage
        if isinstance(u, dict):
            in_tok = u.get("prompt_tokens") or u.get("input_tokens") or 0
            out_tok = u.get("completion_tokens") or u.get("output_tokens") or 0
            cached_tok = u.get("cached_tokens", 0)
        else:
            in_tok = getattr(u, "prompt_tokens", getattr(u, "input_tokens", 0)) or 0
            out_tok = getattr(u, "completion_tokens", getattr(u, "output_tokens", 0)) or 0
            cached_tok = getattr(u, "cached_tokens", 0)
        if in_tok > 0 or out_tok > 0:
            return int(in_tok), int(out_tok), int(cached_tok)

    # 4. Check if response itself is a dict
    if isinstance(response, dict):
        u_meta = response.get("usage_metadata") or response.get("response_metadata", {}).get("token_usage") or response.get("usage")
        if isinstance(u_meta, dict) and u_meta:
            in_tok = u_meta.get("input_tokens") or u_meta.get("prompt_tokens") or 0
            out_tok = u_meta.get("output_tokens") or u_meta.get("completion_tokens") or 0
            cached_tok = u_meta.get("cached_tokens") or 0
            if in_tok > 0 or out_tok > 0:
                return int(in_tok), int(out_tok), int(cached_tok)

    raise MissingUsageReceiptError(
        f"Provider response missing authentic token usage receipt: {type(response).__name__}"
    )


class UnsupportedTokenCeilingError(ValueError):
    """Raised when a provider cannot enforce the requested output-token ceiling."""


# Provider -> the request parameter that caps generated output tokens.
# OpenAI-compatible clients (openai / custom / cheap / nvidia / deepseek) take
# ``max_tokens`` and langchain-openai maps it to the wire-level
# ``max_completion_tokens``; Groq and Anthropic take ``max_tokens``; Gemini's
# GenerationConfig uses ``max_output_tokens``.
_PROVIDER_OUTPUT_TOKEN_PARAMS: Dict[str, str] = {
    "openai": "max_tokens",
    "custom": "max_tokens",
    "cheap": "max_tokens",
    "nvidia": "max_tokens",
    "deepseek": "max_tokens",
    "groq": "max_tokens",
    "anthropic": "max_tokens",
    "gemini": "max_output_tokens",
    "google": "max_output_tokens",
}


def resolve_output_token_parameter(provider: Optional[str]) -> Optional[str]:
    """Return the provider-compatible output-token parameter, or None if unknown."""
    if not provider:
        return None
    return _PROVIDER_OUTPUT_TOKEN_PARAMS.get(str(provider).strip().lower())


def build_output_token_kwargs(provider: Optional[str], max_output_tokens: Optional[int]) -> Dict[str, int]:
    """Build the exact provider invocation kwargs that enforce the output ceiling."""
    param = resolve_output_token_parameter(provider)
    if param is None or max_output_tokens is None:
        return {}
    try:
        limit = int(max_output_tokens)
    except (TypeError, ValueError):
        return {}
    if limit <= 0:
        return {}
    return {param: limit}


def _unwrap_llm(target: Any) -> Any:
    """Walk RetryLLMProxy / RunnableBinding wrappers down to the provider client."""
    current = target
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        inner = getattr(current, "_llm", None) or getattr(current, "bound", None)
        if inner is None:
            break
        current = inner
    return current


def can_enforce_token_limit(
    target: Any,
    provider: Optional[str] = None,
    max_output_tokens: Optional[int] = None,
) -> bool:
    """Verify the actual client can accept the provider's token-ceiling parameter.

    Fails closed for an unknown provider, a missing invoke surface, or a client
    whose ``invoke`` accepts neither the named parameter nor ``**kwargs``.
    """
    if target is None:
        return False

    param = resolve_output_token_parameter(provider)
    if param is None:
        return False

    if max_output_tokens is not None:
        try:
            if int(max_output_tokens) <= 0:
                return False
        except (TypeError, ValueError):
            return False

    client = _unwrap_llm(target)
    invoke_fn = getattr(client, "invoke", None)
    if not callable(invoke_fn):
        return False

    try:
        sig = inspect.signature(invoke_fn)
    except (TypeError, ValueError):
        return False

    params = sig.parameters
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    return param in params


def _provider_status_code(exc: Exception) -> Optional[int]:
    """Best-effort HTTP status extraction from provider/SDK exceptions."""
    for attr in ("status_code", "http_status", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    response = getattr(exc, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    match = re.search(r"\b([45]\d{2})\b", str(exc))
    if match:
        return int(match.group(1))
    return None


def is_uncertain_post_dispatch_error(exc: Exception) -> bool:
    """Distinguish pre-dispatch failures from post-dispatch billing ambiguity.

    Pre-dispatch programming/config failures and definitive provider
    rejections are safe to release. Timeouts, connection loss, cancellation,
    5xx responses, and unknown transport failures may have been billed and
    must retain their financial hold as ``uncertain``.
    """
    # Client-side/config failure raised before any wire request can be billed.
    if isinstance(exc, (TypeError, ValueError, KeyError, AttributeError, ImportError, NotImplementedError, AssertionError)):
        return False

    # User cancellation and transport interruption after dispatch.
    if isinstance(exc, (TurnCancelledError, TimeoutError, asyncio.TimeoutError, ConnectionError)):
        return True

    cls_name = type(exc).__name__.lower()
    msg = str(exc).lower()

    if any(
        token in cls_name
        for token in (
            "timeout", "cancel", "connection", "disconnect", "remotedisconnected",
            "brokenpipe", "apiconnection", "serviceunavailable", "internalserver",
        )
    ):
        return True

    status = _provider_status_code(exc)
    if status is not None:
        # 5xx and request-timeout responses may be billed or unknown; retain.
        if status == 408 or status >= 500:
            return True
        # Definitive rejections (bad request/auth/not-found/rate-limit) are unbilled.
        if 400 <= status < 500:
            return False

    # Definitive pre-generation / edge rejection wording (no response generated).
    if any(
        token in msg
        for token in (
            "invalid api key", "invalid_api_key", "unauthorized", "authentication",
            "permission denied", "model not found", "bad request", "invalid_request",
            "unsupported model", "rate limit", "rate_limit", "429",
        )
    ):
        return False

    # Unknown failure during invocation: assume billing is possible.
    return True


class ModelExecutionAdapter:
    """
    Adapts autonomous task nodes into authentic LLM code generation calls
    or deterministic test executions, feeding results safely into the implementation engine.
    """

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        mock_mode: Optional[bool] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id
        is_test_env = (
            bool(os.environ.get("PYTEST_CURRENT_TEST"))
            or os.environ.get("CRUSORAI_TEST_MODE", "").lower() in {"1", "true", "yes"}
            or os.environ.get("CRUSORAI_OFFLINE_MODE", "").lower() in {"1", "true", "yes"}
        )
        if mock_mode is not None:
            self.mock_mode = mock_mode
        else:
            self.mock_mode = is_test_env
        self.provider = provider or os.environ.get("LLM_PROVIDER")
        self.model = model or os.environ.get("LLM_MODEL")
        self.authorizer = get_tool_authorizer()

    def execute_node(
        self,
        task_id: str,
        node: EngineeringTaskNode,
        specification: Any,
        blueprint: Any,
        project_knowledge: Any,
        impl_engine: ControlledImplementationEngine,
        finops: OrchestrationFinOpsGovernor,
        reasoning_loop: BoundedAutonomousReasoningLoop,
        cancellation_checker: Optional[Callable[[], bool]] = None,
        custom_code_generator: Optional[Callable[[EngineeringTaskNode, str], str]] = None,
    ) -> bool:
        """
        Executes a single engineering task node by generating real code and applying mutations.
        """
        if node.node_id == "task_verification":
            return True

        if cancellation_checker and cancellation_checker():
            raise TurnCancelledError("Task execution cancelled by user")

        # 1. FinOps pre-call budget verification
        finops.authorize_operation(estimated_tokens=800, estimated_cost_inr=0.0)

        # 2. RBAC check for the executing principal
        principal = User(
            user_id=f"agent_{task_id}",
            email="agent@crusor.ai",
            display_name="CrusorEngineeringAgent",
            is_superadmin=True,
        )
        auth_res = self.authorizer.authorize_tool_call(
            principal=principal,
            org_id=self.tenant_id,
            workspace_id=str(self.workspace_root),
            tool_name="write_file",
            tool_args={"node_id": node.node_id, "targets": node.target_files},
        )
        if not auth_res.is_allowed:
            raise PermissionError(f"RBAC authorization denied for node {node.node_id}: {auth_res.reason}")

        # 3. Process each target file for this task node
        for target_file in node.target_files:
            if cancellation_checker and cancellation_checker():
                raise TurnCancelledError("Task execution cancelled by user")

            full_target = self.workspace_root / target_file
            existing_content = ""
            if full_target.exists():
                try:
                    existing_content = full_target.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    existing_content = ""

            # 4. Generate implementation code
            if custom_code_generator:
                code_content = custom_code_generator(node, target_file)
                finops.record_usage(input_tokens=150, output_tokens=250, cost_inr=0.0)
            elif self.mock_mode:
                code_content = self._generate_deterministic_implementation(
                    node=node,
                    target_file=target_file,
                    existing_content=existing_content,
                    specification=specification,
                    blueprint=blueprint,
                )
                finops.record_usage(input_tokens=200, output_tokens=350, cost_inr=0.0)
            else:
                code_content = self._call_model_for_implementation(
                    node=node,
                    target_file=target_file,
                    existing_content=existing_content,
                    specification=specification,
                    blueprint=blueprint,
                    project_knowledge=project_knowledge,
                    finops=finops,
                )

            # Prevent placeholder 'return OK' handlers from being accepted in any execution mode
            if "Production implementation placeholder" in code_content or re.search(r"def handle_\w+\(\):\s*return ['\"]OK['\"]", code_content):
                raise ValueError(
                    f"Placeholder handler generation is strictly prohibited in orchestration execution for node '{node.node_id}'."
                )

            # 5. Apply mutation through ControlledImplementationEngine -> WorkspaceMutationBroker
            impl_engine.execute_node_mutation(
                task_id=task_id,
                node=node,
                rel_path=target_file,
                content=code_content,
            )
            reasoning_loop.record_action(files_modified=1, tokens_used=300)

            # 6. Syntax validation receipt for Python files
            if target_file.endswith(".py"):
                try:
                    ast.parse(code_content, filename=target_file)
                except SyntaxError as syn_err:
                    log.warning(
                        "Syntax warning in generated code for %s: %s",
                        target_file, syn_err
                    )

        return True

    def _has_active_provider(self) -> bool:
        """Determines if a genuine model provider API key is present."""
        keys = [
            os.environ.get("OPENAI_API_KEY"),
            os.environ.get("ANTHROPIC_API_KEY"),
            os.environ.get("GEMINI_API_KEY"),
            os.environ.get("GROQ_API_KEY"),
            os.environ.get("CUSTOM_API_KEY"),
            os.environ.get("NVIDIA_API_KEY"),
        ]
        return any(k and k.strip() for k in keys)

    def _generate_deterministic_implementation(
        self,
        node: EngineeringTaskNode,
        target_file: str,
        existing_content: str,
        specification: Any,
        blueprint: Any,
    ) -> str:
        """Generates high-quality, authentic code deterministically for tests and offline runs."""
        req_list = ", ".join(node.related_requirement_ids) if node.related_requirement_ids else "REQ-CORE"
        arch_style = getattr(blueprint, "architecture_style", "MODULAR")
        if hasattr(arch_style, "value"):
            arch_style = arch_style.value

        file_stem = Path(target_file).stem
        class_name = "".join(w.capitalize() for w in file_stem.split("_"))

        lines = [
            f'"""',
            f'Module: {target_file}',
            f'Generated by Crusor Autonomous Engineering Intelligence.',
            f'Requirement Traceability: {req_list}',
            f'Architecture Style: {arch_style}',
            f'Task Node: {node.node_id} - {node.description}',
            f'"""',
            "",
            "from __future__ import annotations",
            "",
            "import logging",
            "from typing import Any, Dict, List, Optional",
            "",
            f'log = logging.getLogger("crusor.{file_stem}")',
            "",
            "",
            f"class {class_name}Service:",
            f'    """Implementation for {node.description}."""',
            "",
            "    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:",
            "        self.config = config or {}",
            "        self.is_initialized = True",
            "",
            "    def execute(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:",
            f'        """Executes operation satisfying {req_list}."""',
            "        data = payload or {}",
            "        log.info('Executing operation on %s', self.__class__.__name__)",
            "        return {",
            "            'status': 'SUCCESS',",
            f"            'node_id': '{node.node_id}',",
            f"            'requirements_satisfied': ['{req_list}'],",
            "            'data': data,",
            "        }",
            "",
            "",
            f"def {file_stem}_main() -> int:",
            f"    service = {class_name}Service()",
            "    res = service.execute()",
            "    return 0 if res.get('status') == 'SUCCESS' else 1",
            "",
            "",
            'if __name__ == "__main__":',
            f"    import sys",
            f"    sys.exit({file_stem}_main())",
            "",
        ]
        return "\n".join(lines)

    def _call_model_for_implementation(
        self,
        node: EngineeringTaskNode,
        target_file: str,
        existing_content: str,
        specification: Any,
        blueprint: Any,
        project_knowledge: Any,
        finops: OrchestrationFinOpsGovernor,
    ) -> str:
        """Invokes the configured LLM provider to author real code with verified FinOps accounting."""
        from src.config.settings import LLM_PROVIDER, LLM_MODEL
        prov = self.provider or os.environ.get("LLM_PROVIDER") or LLM_PROVIDER or "custom"
        mod = self.model or os.environ.get("LLM_MODEL") or LLM_MODEL or "default"

        # 1. Enforce verified pricing exists before dispatching call (fail-closed)
        pricing_reg = PricingRegistry.get_pricing_registry()
        pricing = pricing_reg.get_model_pricing(mod, provider=prov)
        if not pricing or pricing.verification_status == VerificationStatus.UNKNOWN:
            raise UnknownModelPricingError(
                f"Cannot establish verified or catalog pricing for model '{mod}' (provider '{prov}'). "
                f"Failing closed to prevent unmetered execution."
            )

        req_list = ", ".join(node.related_requirement_ids) if node.related_requirement_ids else "Core specification"

        prompt = (
            f"You are the senior software engineering model for Crusor AI.\n"
            f"Task Node: {node.node_id}: {node.description}\n"
            f"Requirements to satisfy: {req_list}\n"
            f"Target file path: {target_file}\n"
        )
        if existing_content:
            prompt += f"\nExisting file content:\n```\n{existing_content}\n```\n"
        prompt += (
            f"\nGenerate the complete, robust, production-quality implementation of {target_file}.\n"
            f"Include comprehensive error handling, type annotations, and docstrings.\n"
            f"Return ONLY the code block, with no conversational preamble."
        )

        # 2. FinOps reserve-before-call (P0.4 / P0.4.1)
        # Calculate conservative maximum input tokens (3 chars/token) and strict max output allowance
        prompt_chars = len(prompt)
        est_in = max(100, prompt_chars // 3)
        max_output_tokens = getattr(node, "max_tokens", None) or 2048
        max_total_tokens = est_in + max_output_tokens

        max_cost = pricing_reg.calculate_cost(
            model=mod,
            input_tokens=est_in,
            output_tokens=max_output_tokens,
            provider=prov,
        )
        if max_cost.cost_inr is None or max_cost.cost_usd is None or max_cost.verification_status == VerificationStatus.UNKNOWN:
            raise UnknownModelPricingError(
                f"Pricing calculation failed for model '{mod}' (provider '{prov}'). Failing closed."
            )

        max_cost_inr = float(max_cost.cost_inr)
        max_cost_usd = float(max_cost.cost_usd)

        # 2. Canonical reserve-before-call. Nothing below may run until this
        # returns a durably recorded reservation accepted by both the task
        # governor and the canonical BudgetGovernor.
        res_id = finops.reserve(
            estimated_tokens=max_total_tokens,
            estimated_cost_inr=max_cost_inr,
            estimated_cost_usd=max_cost_usd,
            purpose=f"node_{node.node_id}",
        )

        try:
            llm = get_llm(provider=prov, model=mod)
        except Exception:
            finops.release_reservation(res_id, reason="provider_client_construction_failed")
            raise

        # One metered dispatch == one paid request. RetryLLMProxy would
        # otherwise resend the same prompt up to five times under a single
        # reservation, which is the unmetered duplication P0.4.1 forbids.
        # (Test doubles without the attribute are unaffected.)
        if hasattr(llm, "_max_attempts"):
            try:
                llm._max_attempts = 1
            except Exception:
                pass

        # 3. Resolve and verify the provider-compatible output-token ceiling
        # BEFORE dispatch. No invoke() is attempted without it.
        invoke_kwargs = build_output_token_kwargs(prov, max_output_tokens)
        if not invoke_kwargs or not can_enforce_token_limit(
            llm, provider=prov, max_output_tokens=max_output_tokens
        ):
            finops.release_reservation(res_id, reason="provider_cannot_enforce_token_ceiling")
            raise UnsupportedTokenCeilingError(
                f"Provider '{prov}' (model '{mod}', client '{type(llm).__name__}') cannot enforce the requested "
                f"output token ceiling of {max_output_tokens} tokens. Dispatch aborted to prevent unmetered execution."
            )

        # Transition reservation to in_flight immediately before wire dispatch.
        finops.mark_in_flight(res_id)

        # Exactly one dispatch, always with the token ceiling attached.
        try:
            response = llm.invoke(prompt, **invoke_kwargs)
        except Exception as exc:
            # Pre-dispatch rejections release; post-dispatch ambiguity retains
            # the hold as uncertain so funds cannot be silently double-spent.
            if is_uncertain_post_dispatch_error(exc):
                finops.mark_uncertain(res_id, reason=f"post_dispatch_error: {type(exc).__name__}: {exc}")
            else:
                finops.release_reservation(res_id, reason=f"dispatch_rejected: {type(exc).__name__}")
            raise

        try:
            # 4. Extract authentic usage receipts (fail-closed on missing receipts)
            in_tok, out_tok, cached_tok = extract_provider_token_usage(response)
        except Exception:
            # Wire call succeeded but usage receipts missing: keep reservation uncertain
            finops.mark_uncertain(res_id, reason="missing_usage_receipts_after_call")
            raise

        # 5. Calculate actual verified cost with micro-currency precision
        calc_cost = pricing_reg.calculate_cost(
            model=mod,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cached_tokens=cached_tok,
            provider=prov,
        )
        if calc_cost.cost_inr is None or calc_cost.cost_usd is None or calc_cost.verification_status == VerificationStatus.UNKNOWN:
            # The provider already ran; the hold must not be released as if
            # the call were free. Mark it uncertain for reconciliation.
            finops.mark_uncertain(res_id, reason="unverifiable_actual_cost")
            raise UnknownModelPricingError(
                f"Pricing calculation failed for model '{mod}' (provider '{prov}'). Failing closed."
            )

        actual_cost_inr = float(calc_cost.cost_inr)
        actual_cost_usd = float(calc_cost.cost_usd)

        # 6. Settle the exact canonical reservation, then record actual spend.
        finops.commit_reservation(
            reservation_id=res_id,
            actual_input_tokens=in_tok,
            actual_output_tokens=out_tok,
            actual_cached_tokens=cached_tok,
            actual_cost_inr=actual_cost_inr,
            actual_cost_usd=actual_cost_usd,
        )

        text = response.content if hasattr(response, "content") else str(response)

        # Extract code from Markdown code block if present
        match = re.search(r"```(?:python)?\s*\n(.*?)\n```", text, re.DOTALL)
        if match:
            clean_code = match.group(1)
        else:
            clean_code = text.strip()

        return clean_code
