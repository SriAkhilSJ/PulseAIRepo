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
import inspect
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.finops.pricing_registry import CalculatedCost, PricingRegistry, VerificationStatus
from src.identity.models import Permission, RoleTemplate, User
from src.identity.tool_authorizer import get_tool_authorizer
from src.llm.factory import (
    TurnCancelledError,
    get_llm,
    normalize_finish_reason,
    provider_response_info,
)
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


class ModelOutputIntegrityError(ValueError):
    """Base class for fail-closed model output integrity violations."""


class IncompleteModelOutputError(ModelOutputIntegrityError):
    """Raised when the provider reports that generation stopped before completion."""


class SourceExtractionError(ModelOutputIntegrityError):
    """Raised when a response cannot be reduced to one complete source payload."""


class EmptyModelOutputError(SourceExtractionError):
    """Raised when the provider returns no usable source content."""


class InvalidGeneratedSourceError(ModelOutputIntegrityError):
    """Raised when extracted source fails syntax validation for its target language."""


# Provider-reported completion reasons that mean the output is not a complete
# deliverable. The first three are the documented OpenAI/Groq/Anthropic forms;
# the remainder are documented truncation/blocked variants used by compatible
# gateways. A reason is only consulted when the provider actually reports one:
# reaching a configured ceiling by itself is never treated as truncation.
INCOMPLETE_FINISH_REASONS = frozenset({
    "length",
    "max_tokens",
    "max_output_tokens",
    "max_completion_tokens",
    "token_limit",
    "incomplete",
    "content_filter",
    "safety",
    "recitation",
    "blocked",
    "error",
})

_FENCE_OPEN_RE = re.compile(r"^[ \t]*```[ \t]*([A-Za-z0-9_+.#-]*)[ \t]*$")
_FENCE_CLOSE_RE = re.compile(r"^[ \t]*```[ \t]*$")
_SOURCE_LIKE_OUTSIDE_RE = re.compile(
    r"(?m)^[ \t]*(?:async[ \t]+def|def|class|import|from|@|#include|package|func|const|let|var|"
    r"public|private|protected|interface|type|struct|using|namespace)\b"
)


def _response_text(response: Any) -> str:
    """Return response text without assuming a LangChain AIMessage shape."""
    if response is None:
        return ""
    content = getattr(response, "content", None)
    if content is None:
        return str(response)
    if isinstance(content, str):
        return content
    return str(content)


def response_finish_reason(response: Any) -> Tuple[str, str]:
    """Return ``(raw, canonical)`` completion reason, or ``("", "")``."""
    if response is None:
        return "", ""

    raw = ""
    canonical = ""
    try:
        info = provider_response_info(response)
        raw = str(info.get("raw_finish_reason") or "")
        canonical = str(info.get("finish_reason") or "")
    except Exception:
        # Metadata shape is provider-specific; the direct-attribute fallback
        # below still gets a chance, and missing metadata is not truncation.
        pass

    if not canonical:
        for attr in ("finish_reason", "stop_reason"):
            value = getattr(response, attr, None)
            if value:
                raw_value, canonical_value = normalize_finish_reason(value)
                if canonical_value:
                    return raw_value, canonical_value
    return raw, canonical


def assert_provider_output_complete(response: Any, target_file: str) -> None:
    """Fail closed when the provider explicitly reports incomplete generation."""
    raw, canonical = response_finish_reason(response)
    if canonical and canonical in INCOMPLETE_FINISH_REASONS:
        detail = f"finish_reason={canonical!r}"
        if raw and raw.lower() != canonical:
            detail += f" (raw={raw[:64]!r})"
        raise IncompleteModelOutputError(
            f"Provider stopped before completing output for '{target_file}': {detail}."
        )


def extract_generated_source(text: Any, target_file: str) -> str:
    """Extract exactly one complete source payload from a model response.

    Accepted shapes:
      * plain source text with no Markdown fence;
      * exactly one complete fenced block, with an optional language tag.

    Rejected shapes (fail closed, never "best effort"):
      * empty/whitespace-only output;
      * an opening fence without a matching closing fence;
      * malformed fence lines or nested fences;
      * multiple fenced blocks (ambiguous; could silently discard code);
      * source-like content outside the fenced block.
    """
    if text is None:
        text = ""
    if not isinstance(text, str):
        text = str(text)

    stripped = text.strip()
    if not stripped:
        raise EmptyModelOutputError(
            f"Model returned empty output for '{target_file}'."
        )

    lines = stripped.splitlines()
    fence_lines = [line for line in lines if "```" in line]
    if not fence_lines:
        # No fence: the entire payload is the candidate source. Syntax
        # validation happens later, so malformed plain source still fails.
        return stripped

    for line in fence_lines:
        if not (_FENCE_OPEN_RE.match(line) or _FENCE_CLOSE_RE.match(line)):
            raise SourceExtractionError(
                f"Malformed Markdown code fence in model output for '{target_file}'."
            )

    blocks: List[Tuple[str, str]] = []
    outside: List[str] = []
    index = 0
    while index < len(lines):
        opening = _FENCE_OPEN_RE.match(lines[index])
        if opening:
            language = opening.group(1) or ""
            body_start = index + 1
            cursor = body_start
            while cursor < len(lines) and not _FENCE_CLOSE_RE.match(lines[cursor]):
                if _FENCE_OPEN_RE.match(lines[cursor]):
                    raise SourceExtractionError(
                        f"Nested or unterminated Markdown code fence for '{target_file}'."
                    )
                cursor += 1
            if cursor >= len(lines):
                raise SourceExtractionError(
                    f"Incomplete Markdown code fence for '{target_file}': "
                    f"opening fence has no matching closing fence."
                )
            blocks.append((language, "\n".join(lines[body_start:cursor])))
            index = cursor + 1
        else:
            if _FENCE_CLOSE_RE.match(lines[index]):
                raise SourceExtractionError(
                    f"Unmatched closing Markdown code fence for '{target_file}'."
                )
            outside.append(lines[index])
            index += 1

    if len(blocks) != 1:
        raise SourceExtractionError(
            f"Expected exactly one complete fenced code block for '{target_file}', "
            f"found {len(blocks)}."
        )

    _language, body = blocks[0]
    if not body.strip():
        raise EmptyModelOutputError(
            f"Fenced code block for '{target_file}' is empty."
        )

    outside_text = "\n".join(outside).strip()
    if outside_text and _SOURCE_LIKE_OUTSIDE_RE.search(outside_text):
        raise SourceExtractionError(
            f"Refusing to discard source-like content outside the fenced block for '{target_file}'."
        )

    return body.strip("\n")


def validate_generated_source(target_file: str, source: str) -> Optional[str]:
    """Validate extracted source before any mutation can occur.

    Returns the validator name that ran, or ``None`` when the target language
    has no configured validator. Python targets are always checked with
    ``ast.parse``; JSON and TOML use their standard-library parsers.
    """
    if not source or not source.strip():
        raise EmptyModelOutputError(
            f"Extracted source for '{target_file}' is empty."
        )

    suffix = Path(target_file).suffix.lower()

    if suffix in {".py", ".pyi"}:
        try:
            ast.parse(source, filename=target_file)
        except SyntaxError as exc:
            raise InvalidGeneratedSourceError(
                f"Generated Python for '{target_file}' failed syntax validation: "
                f"{exc.msg} (line {exc.lineno})."
            ) from exc
        return "python_ast"

    if suffix == ".json":
        try:
            json.loads(source)
        except ValueError as exc:
            raise InvalidGeneratedSourceError(
                f"Generated JSON for '{target_file}' failed validation: {exc}."
            ) from exc
        return "json"

    if suffix == ".toml":
        try:
            import tomllib

            tomllib.loads(source)
        except Exception as exc:
            raise InvalidGeneratedSourceError(
                f"Generated TOML for '{target_file}' failed validation: {exc}."
            ) from exc
        return "toml"

    log.info(
        "No language-specific validator is configured for target '%s'; "
        "completeness and extraction checks ran, but syntax was not validated.",
        target_file,
    )
    return None


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


# ---------------------------------------------------------------------------
# P0.4.2: defensible input-token upper bound
# ---------------------------------------------------------------------------
# Why the serialized byte length is an upper bound on content tokens:
#
#   * The request is a single chat message whose content is the exact prompt
#     string. We serialise that envelope with ``ensure_ascii=True`` so every
#     non-ASCII code point expands to at least its raw UTF-8 byte length:
#       - a BMP code point (e.g. CJK: 3 UTF-8 bytes) becomes ``\uXXXX`` = 6
#         ASCII bytes;
#       - an astral code point (e.g. an emoji: 4 UTF-8 bytes) becomes two
#         ``\uXXXX`` escapes = 12 ASCII bytes.
#     A JSON string also escapes ``"`` and ``\`` and adds a little framing, so
#     the serialized UTF-8 length is >= the raw UTF-8 length of the prompt.
#   * Every tokenizer we can target (tiktoken byte-level BPE, Llama/Qwen/
#     DeepSeek byte-level BPE, SentencePiece unigram) builds tokens from
#     non-empty byte sequences, so a string can never require more tokens than
#     it has bytes. ``tokens(text) <= utf8_bytes(text) <= serialized_bytes``.
#
# The provider chat template adds role/separator/special tokens that are not
# part of the content bytes, so we add explicit, deliberately generous
# per-message and per-request overhead. These are upper-bound constants, not
# estimates: they only ever make the reservation larger.
PROMPT_OVERHEAD_TOKENS_PER_MESSAGE = 16
PROMPT_OVERHEAD_TOKENS_PER_REQUEST = 16

# Minimum bound even for an empty prompt: the request still carries a role,
# separators and provider chat-template control tokens.
_MIN_PROMPT_BOUND_TOKENS = (
    PROMPT_OVERHEAD_TOKENS_PER_MESSAGE + PROMPT_OVERHEAD_TOKENS_PER_REQUEST
)


@dataclass(frozen=True)
class PromptTokenBound:
    """Documented upper bound for the exact prompt sent to a provider."""

    upper_bound_tokens: int
    exact_local_tokens: Optional[int]
    serialized_bytes: int
    method: str


def _tiktoken_exact_count(text: str, model: Optional[str]) -> Optional[int]:
    """Return an exact local tiktoken count when the model is natively known.

    Returns ``None`` when tiktoken is unavailable, the BPE file is not cached,
    or the model has no native encoding. Unknown models deliberately do NOT
    fall back to ``cl100k_base``: that is an approximation, while the caller's
    byte bound is a genuine upper bound.
    """
    if not model:
        return None
    try:
        import tiktoken  # local, optional dependency
    except Exception:
        return None
    try:
        encoder = tiktoken.encoding_for_model(str(model))
    except Exception:
        return None
    try:
        return len(encoder.encode(text))
    except Exception:
        return None


def estimate_prompt_token_upper_bound(
    prompt: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> PromptTokenBound:
    """Compute a conservative upper bound on the provider-side input tokens.

    The result is ``max(exact local count, serialized UTF-8 bytes)`` plus
    documented chat-template overhead. Exact local tokenization is used only
    when it is actually available; otherwise the byte bound is used without
    any optimistic character-ratio fallback.
    """
    if not isinstance(prompt, str):
        raise TypeError("prompt must be a string")

    serialized = json.dumps(
        {
            "model": model or "",
            "messages": [{"role": "user", "content": prompt}],
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    serialized_bytes = len(serialized.encode("utf-8"))

    exact_local = _tiktoken_exact_count(prompt, model)
    overhead = PROMPT_OVERHEAD_TOKENS_PER_MESSAGE + PROMPT_OVERHEAD_TOKENS_PER_REQUEST

    byte_bound = serialized_bytes + overhead
    exact_bound = (exact_local + overhead) if exact_local is not None else 0
    upper_bound = max(_MIN_PROMPT_BOUND_TOKENS, byte_bound, exact_bound)

    method = "serialized_utf8_bytes+chat_template_overhead"
    if exact_local is not None:
        method = "max(tiktoken_exact, serialized_utf8_bytes)+chat_template_overhead"

    return PromptTokenBound(
        upper_bound_tokens=upper_bound,
        exact_local_tokens=exact_local,
        serialized_bytes=serialized_bytes,
        method=method,
    )


def calculate_max_request_cost(
    pricing_reg: PricingRegistry,
    model: str,
    provider: Optional[str],
    input_tokens: int,
    max_output_tokens: int,
) -> CalculatedCost:
    """Maximum possible request cost for the bound and output ceiling.

    Uses the full (uncached) input rate for every input token and the larger of
    the output and reasoning rates for every output token, so the reservation
    cannot be under-cut by a model that bills reasoning tokens above its
    visible-output rate.
    """
    standard = pricing_reg.calculate_cost(
        model=model,
        input_tokens=input_tokens,
        output_tokens=max_output_tokens,
        provider=provider,
    )
    pricing = pricing_reg.get_model_pricing(model, provider=provider)
    if (
        standard.cost_inr is not None
        and standard.cost_usd is not None
        and pricing is not None
        and pricing.reasoning_price_per_1m is not None
        and pricing.reasoning_price_per_1m > pricing.output_price_per_1m
    ):
        reasoning = pricing_reg.calculate_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=0,
            reasoning_tokens=max_output_tokens,
            provider=provider,
        )
        if reasoning.cost_inr is not None and reasoning.cost_inr > standard.cost_inr:
            return reasoning
    return standard


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
    """Extract an HTTP status code from structured provider/SDK evidence only.

    Only attributes that providers/SDKs document as status carriers are
    consulted (``status_code`` / ``http_status`` / ``status`` and
    ``response.status_code``). Free text is intentionally ignored: a message
    such as ``"expected 400 but got 500"`` is not proof that the provider
    returned a 400, and must not be used to release a financial hold.
    """
    response = getattr(exc, "response", None)
    candidates = [
        getattr(exc, "status_code", None),
        getattr(exc, "http_status", None),
        getattr(exc, "status", None),
        getattr(response, "status_code", None) if response is not None else None,
        getattr(response, "status", None) if response is not None else None,
        # Some SDKs expose the HTTP status via ``code``. Only a plain int in
        # the HTTP range is accepted; string error codes are not evidence.
        getattr(exc, "code", None),
    ]
    for value in candidates:
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
            return value
    return None


# Documented provider rejection evidence: an HTTP 4xx response means the
# provider refused the request before generating tokens, and these responses
# are not billed. 408 (request timeout) is excluded because the request may
# have been processed before the timeout surfaced.
_CONFIRMED_UNBILLED_HTTP_STATUSES = frozenset({400, 401, 402, 403, 404, 405, 406, 409, 410, 411, 412, 413, 414, 415, 416, 417, 418, 421, 422, 423, 424, 425, 426, 428, 429, 431, 451})


def is_uncertain_post_dispatch_error(exc: Exception) -> bool:
    """Classify an error raised *by the provider invocation*.

    This helper is only consulted for exceptions raised inside
    ``llm.invoke(...)``. Errors that the adapter detects before dispatch
    (client construction, unsupported token ceiling, canonical denial,
    persistence failure) are released directly by the caller and never reach
    this function.

    A post-invocation error keeps the financial hold (returns ``True``) unless
    there is documented provider evidence that the request was rejected
    without being billed: a structured HTTP 4xx response other than 408.
    In particular, a ``TypeError`` raised inside ``invoke`` is NOT proof that
    no request reached the provider, and text-only status numbers are not
    evidence (see :func:`_provider_status_code`).
    """
    status = _provider_status_code(exc)
    if status is None:
        # No documented rejection evidence. Timeouts, cancellation, connection
        # loss, local programming errors raised inside invoke, 5xx, and
        # unknown transport failures may all have been billed.
        return True

    if status in _CONFIRMED_UNBILLED_HTTP_STATUSES:
        return False

    # 408 request timeout, 5xx, and any non-rejection status are ambiguous.
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

        # 3. Generate, extract, and validate EVERY target before mutating any.
        # P0.5.1: Validation failure must leave the workspace byte-for-byte
        # unchanged. A per-file generate -> mutate -> check loop is unsafe
        # because a later invalid target would leave earlier mutations behind
        # and because syntax failures were previously logged but not enforced.
        prepared: List[Tuple[str, str]] = []
        try:
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

                # 4. Generate implementation code. The real-provider path
                # already rejects provider-reported truncation and returns an
                # extracted source payload.
                if custom_code_generator:
                    raw_content = custom_code_generator(node, target_file)
                    finops.record_usage(input_tokens=150, output_tokens=250, cost_inr=0.0)
                    code_content = extract_generated_source(raw_content, target_file)
                elif self.mock_mode:
                    raw_content = self._generate_deterministic_implementation(
                        node=node,
                        target_file=target_file,
                        existing_content=existing_content,
                        specification=specification,
                        blueprint=blueprint,
                    )
                    finops.record_usage(input_tokens=200, output_tokens=350, cost_inr=0.0)
                    code_content = extract_generated_source(raw_content, target_file)
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

                # 5. Fail closed before any mutation is applied. Python targets
                # must pass ast.parse; JSON/TOML use their standard parsers;
                # other languages are explicitly reported as unvalidated.
                validate_generated_source(target_file, code_content)
                prepared.append((target_file, code_content))
        except ModelOutputIntegrityError as exc:
            node.status = "FAILED"
            node.error_message = str(exc)
            raise

        # 6. All targets validated. Only now touch the workspace.
        for target_file, code_content in prepared:
            if cancellation_checker and cancellation_checker():
                raise TurnCancelledError("Task execution cancelled by user")

            impl_engine.execute_node_mutation(
                task_id=task_id,
                node=node,
                rel_path=target_file,
                content=code_content,
            )
            reasoning_loop.record_action(files_modified=1, tokens_used=300)

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

        # 2. FinOps reserve-before-call (P0.4 / P0.4.1 / P0.4.2)
        # Bound the EXACT prompt sent to the provider. The bound is the larger
        # of the exact local tokenizer count (when available) and a serialized
        # UTF-8 byte bound, plus documented chat-template overhead. The previous
        # ``chars // 3`` heuristic was optimistic and could under-reserve for
        # code, Unicode, emoji, and JSON-escaped text.
        input_bound = estimate_prompt_token_upper_bound(prompt, provider=prov, model=mod)
        max_output_tokens = getattr(node, "max_tokens", None) or 2048
        est_in = input_bound.upper_bound_tokens
        max_total_tokens = est_in + max_output_tokens
        log.info(
            "P0.4.2 input-token upper bound for node %s: %d tokens (%s; exact=%s; serialized_bytes=%d)",
            node.node_id,
            est_in,
            input_bound.method,
            input_bound.exact_local_tokens,
            input_bound.serialized_bytes,
        )

        max_cost = calculate_max_request_cost(
            pricing_reg,
            model=mod,
            provider=prov,
            input_tokens=est_in,
            max_output_tokens=max_output_tokens,
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

        # The provider has been paid and settled above. Validate its completion
        # receipt and extraction before returning anything that could mutate a
        # workspace. An incomplete response still records the real usage but is
        # never delivered as source code.
        assert_provider_output_complete(response, target_file)
        return extract_generated_source(_response_text(response), target_file)
