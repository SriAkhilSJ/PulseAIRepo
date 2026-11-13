"""One model execution gateway (Increment 2).

Both the LangGraph ``ai_node`` and the delegated engineering adapter call
through this module. It is a thin, provider-free wrapper around the existing
``src.llm.factory.get_llm`` / ``RetryLLMProxy`` stack:

* provider/model selection: already performed by ``get_llm``;
* retry policy, transport timeouts and cancellation: owned by
  ``RetryLLMProxy`` (single owner, not duplicated here);
* usage metadata / token usage: normalized from the provider response;
* invocation correlation IDs: attached to the LangChain run metadata and
  emitted on one deterministic log line per call;
* cost attribution metadata: the ids are carried alongside the existing
  FinOps ledger records (Increment 3 consolidates the ledgers themselves).

No network is performed here beyond the caller-provided client.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from src.llm.factory import TurnCancelledError, provider_response_info


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text") or "") for block in content if isinstance(block, dict)
        )
    return str(content or "")


def _can_stream(llm: Any) -> bool:
    """Honest capability check before opting into incremental delivery.

    ``RetryLLMProxy`` reports the wrapped client's real capability; a bare
    client is judged by the presence of a callable ``stream``. Test doubles that
    only implement ``invoke`` keep the non-streaming path.
    """
    advertised = getattr(llm, "supports_streaming", None)
    if isinstance(advertised, bool):
        return advertised
    return callable(getattr(llm, "stream", None))


@dataclass(frozen=True)
class InvocationContext:
    """Correlation identity for one provider invocation."""

    session_id: str
    turn_id: str
    task_id: str
    provider: str
    model: str
    subsystem: str = "graph"
    invocation_id: str = field(default_factory=lambda: f"inv-{uuid.uuid4().hex[:16]}")
    workspace: str = ""
    purpose: str = ""

    def as_metadata(self) -> dict[str, str]:
        return {
            "crusor_session_id": str(self.session_id or ""),
            "crusor_turn_id": str(self.turn_id or ""),
            "crusor_task_id": str(self.task_id or ""),
            "crusor_invocation_id": self.invocation_id,
            "crusor_provider": str(self.provider or ""),
            "crusor_model": str(self.model or ""),
            "crusor_subsystem": str(self.subsystem or ""),
            "crusor_workspace": str(self.workspace or ""),
            "crusor_purpose": str(self.purpose or ""),
        }


@dataclass
class InvocationResult:
    response: Any
    context: InvocationContext
    elapsed_s: float
    usage: dict[str, Any]
    #: Incremental-delivery facts when the caller opted into `on_token`.
    streamed_chunks: int = 0
    streamed_chars: int = 0
    first_token_s: float | None = None

    @property
    def text(self) -> str:
        content = getattr(self.response, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        return str(content)


def new_invocation_context(
    *,
    session_id: str,
    turn_id: str = "",
    task_id: str = "",
    provider: str = "",
    model: str = "",
    subsystem: str = "graph",
    workspace: str = "",
    purpose: str = "",
) -> InvocationContext:
    return InvocationContext(
        session_id=str(session_id or "default"),
        turn_id=str(turn_id or session_id or "default"),
        task_id=str(task_id or turn_id or session_id or "default"),
        provider=str(provider or ""),
        model=str(model or ""),
        subsystem=subsystem,
        workspace=str(workspace or ""),
        purpose=str(purpose or ""),
    )


def invoke_model(
    llm: Any,
    messages: Any,
    *,
    context: InvocationContext,
    config: Mapping[str, Any] | None = None,
    cancellation_checker: Callable[[], bool] | None = None,
    timeout_s: float | None = None,
    record_telemetry: bool = False,
    invoke_kwargs: Mapping[str, Any] | None = None,
    on_token: Callable[[str], None] | None = None,
    invocation_id: str | None = None,
) -> InvocationResult:
    """Invoke one provider call with correlation metadata attached.

    ``on_token`` opts the call into incremental delivery: the provider's deltas
    are forwarded through a ``TokenTap`` while the client streams, and the call
    still returns the same accumulated response. Callers that omit it keep the
    exact non-streaming behaviour they had.

    ``timeout_s`` is advisory metadata for the single timeout owner
    (RetryLLMProxy / provider SDK); it is never enforced by a second watchdog
    here. Cancellation is checked before dispatch and surfaced after the
    response so a stopped turn cannot keep spending.
    """
    if cancellation_checker is not None and cancellation_checker():
        raise TurnCancelledError("LLM request cancelled by the user (Stop pressed).")

    # One provider invocation gets exactly one correlation id, even when a
    # caller reuses a context object across calls. A caller that already
    # published the id (the engineering adapter's generation activity) passes
    # it explicitly so the live updates and the settled ledger row agree.
    from dataclasses import replace as _replace

    context = _replace(
        context,
        invocation_id=invocation_id or f"inv-{uuid.uuid4().hex[:16]}",
    )

    call_config: dict[str, Any] = dict(config or {})
    metadata = dict(call_config.get("metadata") or {})
    metadata.update(context.as_metadata())
    if timeout_s is not None:
        metadata["crusor_timeout_s"] = str(timeout_s)
    call_config["metadata"] = metadata
    call_config.setdefault(
        "run_name",
        f"crusor:{context.subsystem}:{context.purpose or 'call'}",
    )

    started = time.monotonic()
    streamed_chunks = 0
    streamed_chars = 0
    first_token_s: float | None = None
    response: Any = None

    if on_token is not None and _can_stream(llm):
        # Incremental delivery: consume the provider's native stream so the
        # callback receives deltas AS THEY ARRIVE and cancellation can stop
        # consumption between chunks. The chunks are merged back into one
        # response, so callers that need a complete message keep working.
        aggregate: Any = None
        produced = False

        def _chunks():
            try:
                yield from llm.stream(messages, config=call_config, **dict(invoke_kwargs or {}))
            except TypeError as exc:
                if "config" not in str(exc) or produced:
                    raise
                yield from llm.stream(messages, **dict(invoke_kwargs or {}))

        try:
            for chunk in _chunks():
                produced = True
                text = _message_text(chunk)
                if text:
                    if first_token_s is None:
                        first_token_s = time.monotonic() - started
                    streamed_chunks += 1
                    streamed_chars += len(text)
                    try:
                        on_token(text)
                    except TurnCancelledError:
                        raise
                    except Exception:
                        # Presentation must never break a paid generation.
                        pass
                aggregate = chunk if aggregate is None else aggregate + chunk
                if cancellation_checker is not None and cancellation_checker():
                    raise TurnCancelledError(
                        "LLM request cancelled by the user (Stop pressed during streaming)."
                    )
        except (AttributeError, NotImplementedError):
            # The client advertised a stream but cannot provide one (a test
            # double behind a proxy, an older adapter). Fall back to invoke
            # exactly as a non-streaming caller would.
            if produced:
                raise
            aggregate = None
        if aggregate is not None:
            response = aggregate

    if response is None:
        try:
            response = llm.invoke(messages, config=call_config, **dict(invoke_kwargs or {}))
        except TypeError as exc:
            # Test doubles and older clients may not accept LangChain's `config`
            # keyword. Retry once without it; anything else is a real error.
            if "config" not in str(exc):
                raise
            response = llm.invoke(messages, **dict(invoke_kwargs or {}))
    elapsed = time.monotonic() - started

    try:
        usage = provider_response_info(response)
    except Exception:
        usage = {}

    print(
        "[model-gateway] "
        f"invocation={context.invocation_id} "
        f"session={context.session_id} "
        f"turn={context.turn_id} "
        f"task={context.task_id} "
        f"subsystem={context.subsystem} "
        f"provider={context.provider} "
        f"model={context.model} "
        f"elapsed={elapsed:.3f}s "
        f"input={usage.get('input_tokens')} "
        f"output={usage.get('output_tokens')} "
        f"total={usage.get('total_tokens')}",
        flush=True,
    )

    if record_telemetry:
        try:
            from src.finops.invocation_context import record_invocation

            attempts = list(getattr(llm, "_attempt_records", []) or [])
            record_invocation(
                context.workspace or ".",
                {
                    "invocation_id": context.invocation_id,
                    "session_id": context.session_id,
                    "turn_id": context.turn_id,
                    "task_id": context.task_id,
                    "subsystem": context.subsystem,
                    "operation_type": context.purpose or "model_call",
                    "provider": context.provider,
                    "model": context.model,
                    "status": "settled",
                    "input_tokens": int(usage.get("input_tokens") or 0),
                    "output_tokens": int(usage.get("output_tokens") or 0),
                    "cached_tokens": int(usage.get("cached_tokens") or 0),
                    "attempt_number": len(attempts) or 1,
                    "retry_count": max(0, len(attempts) - 1),
                    "attempts": attempts,
                    "latency_ms": round(elapsed * 1000.0, 3),
                    "provider_reported_cost": usage.get("reported_cost"),
                    "cost_unknown": usage.get("reported_cost") is None,
                    "started_at": time.time() - elapsed,
                    "completed_at": time.time(),
                    "purpose": context.purpose,
                },
            )
        except Exception:
            pass

    if cancellation_checker is not None and cancellation_checker():
        raise TurnCancelledError("LLM request cancelled by the user (Stop pressed).")

    return InvocationResult(
        response=response,
        context=context,
        elapsed_s=elapsed,
        usage=usage,
        streamed_chunks=streamed_chunks,
        streamed_chars=streamed_chars,
        first_token_s=first_token_s,
    )
