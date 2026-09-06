import asyncio
import os
import re
import threading
import time
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from src.config.settings import (
    CUSTOM_API_KEY,
    CUSTOM_BASE_URL,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    NVIDIA_API_KEY,
    OPENAI_API_KEY,
)

from src.runtime.turn_control import active_session, turn_controls


class TurnCancelledError(RuntimeError):
    """Raised when Stop wins before a request, retry, or failover."""


class _AbortState:
    """One request-family abort state shared by all LangChain bindings.

    ``bind()``, ``bind_tools()``, and ``with_structured_output()`` return
    runnable wrappers around the same provider client. Keeping the raw model
    as the owner lets any derived proxy close the actual transport exactly
    once instead of trying to discover a client on a RunnableBinding.
    """

    def __init__(self, owner: Any):
        self.owner = owner
        self.lock = threading.Lock()
        self.event = threading.Event()
        self.aborted = False
        self._async_targets: set[tuple[asyncio.AbstractEventLoop, asyncio.Task]] = set()

    @staticmethod
    def _cancel_task(loop: asyncio.AbstractEventLoop, task: asyncio.Task) -> None:
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            # The request completed and closed its loop between snapshot and
            # delivery; its invoke() finally path will already be unwinding.
            pass

    def attach_async(
        self,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Task,
    ) -> None:
        with self.lock:
            abort_now = self.aborted
            if not abort_now:
                self._async_targets.add((loop, task))
        if abort_now:
            self._cancel_task(loop, task)

    def detach_async(
        self,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Task,
    ) -> None:
        with self.lock:
            self._async_targets.discard((loop, task))

    def abort(self) -> None:
        with self.lock:
            if self.aborted:
                return
            self.aborted = True
            self.event.set()
            targets = tuple(self._async_targets)
        for loop, task in targets:
            self._cancel_task(loop, task)
        # Sync-only providers/fakes still need a transport-close fallback.
        self._close_owner_transport()

    def _close_owner_transport(self) -> None:
        """Close the deepest synchronous client exactly once."""
        root = getattr(self.owner, "client", None)
        if root is None:
            root = getattr(self.owner, "_client", None)
        if root is None:
            return

        candidate = None
        current = root
        seen: set[int] = set()
        for _ in range(5):
            if current is None or id(current) in seen:
                break
            seen.add(id(current))
            if callable(getattr(current, "close", None)):
                candidate = current
            current = getattr(current, "_client", None)
        if candidate is not None:
            try:
                candidate.close()
            except Exception:
                pass


def _bound_tool_schemas(runnable: Any) -> list[dict[str, Any]]:
    """Extract OpenAI-style schemas from nested LangChain bindings."""
    current = runnable
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        kwargs = getattr(current, "kwargs", None)
        if isinstance(kwargs, dict) and isinstance(kwargs.get("tools"), list):
            return [tool for tool in kwargs["tools"] if isinstance(tool, dict)]
        current = getattr(current, "bound", None) or getattr(current, "_llm", None)
    return []


def build_request_snapshot(messages: Any, runnable: Any) -> dict[str, Any]:
    """Build a deterministic, JSON-safe provider-boundary snapshot.

    This contains the complete messages and tool schemas after sanitization and
    prompt trimming, so a failed desktop run can be inspected/replayed without
    another paid call. It is emitted only when payload capture is explicitly
    enabled; compact counts/fingerprints are always safe telemetry.
    """
    import hashlib
    import json

    serialized_messages: list[dict[str, Any]] = []
    if isinstance(messages, list):
        for message in messages:
            if isinstance(message, dict):
                item = dict(message)
            else:
                item = {
                    "role": getattr(message, "type", "unknown"),
                    "content": getattr(message, "content", ""),
                }
                tool_calls = getattr(message, "tool_calls", None)
                if tool_calls:
                    item["tool_calls"] = tool_calls
                tool_call_id = getattr(message, "tool_call_id", None)
                if tool_call_id:
                    item["tool_call_id"] = tool_call_id
                name = getattr(message, "name", None)
                if name:
                    item["name"] = name
            serialized_messages.append(item)
    tools_payload = _bound_tool_schemas(runnable)
    canonical = json.dumps(
        {"messages": serialized_messages, "tools": tools_payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    names = []
    for tool in tools_payload:
        fn = tool.get("function", tool)
        if isinstance(fn, dict) and fn.get("name"):
            names.append(str(fn["name"]))
    return {
        "messages": serialized_messages,
        "tools": tools_payload,
        "message_chars": sum(len(str(m.get("content", ""))) for m in serialized_messages),
        "tool_schema_chars": len(json.dumps(tools_payload, sort_keys=True, default=str)),
        "tool_names": names,
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


_INCOMPLETE_FINISH_REASONS = frozenset({
    "length", "max_tokens", "max_output_tokens", "token_limit", "incomplete",
})
_CANONICAL_FINISH_REASONS = _INCOMPLETE_FINISH_REASONS | frozenset({
    "stop", "tool_calls", "function_call", "content_filter", "end_turn",
})


def normalize_finish_reason(value: Any) -> tuple[str, str]:
    """Return ``(raw, canonical)`` provider completion reasons.

    LangChain merges streaming ``response_metadata`` dictionaries with generic
    string concatenation. If two terminal chunks both carry ``length``, the
    final AIMessage contains ``lengthlength`` (reproduced with
    ``AIMessageChunk + AIMessageChunk`` and observed in Test 5 Attempt 10).
    Canonicalize only *exact repetitions* of known reasons; broad substring
    matching could turn unrelated provider values into false output limits.
    """
    raw = str(value or "").strip()
    normalized = raw.lower()
    if not raw:
        return "", ""
    for reason in sorted(_CANONICAL_FINISH_REASONS, key=len, reverse=True):
        if len(normalized) < len(reason) or len(normalized) % len(reason):
            continue
        repeats = len(normalized) // len(reason)
        if 1 <= repeats <= 8 and normalized == reason * repeats:
            return raw, reason
    return raw, normalized


def _response_usage(response: Any, metadata: dict[str, Any]) -> dict[str, int | None]:
    """Normalize bounded token counters from LangChain/provider metadata."""
    usage = getattr(response, "usage_metadata", None)
    usage = usage if isinstance(usage, dict) else {}
    provider_usage = metadata.get("token_usage")
    provider_usage = provider_usage if isinstance(provider_usage, dict) else {}

    def value(*names: str) -> int | None:
        for source in (usage, provider_usage):
            for name in names:
                candidate = source.get(name)
                if isinstance(candidate, int) and not isinstance(candidate, bool):
                    return max(0, candidate)
        return None

    return {
        "input_tokens": value("input_tokens", "prompt_tokens"),
        "output_tokens": value("output_tokens", "completion_tokens"),
        "total_tokens": value("total_tokens"),
    }


def _reasoning_chars(response: Any, additional: dict[str, Any]) -> int:
    """Count hidden-reasoning text without exposing it in telemetry."""
    reasoning = (
        additional.get("reasoning_content")
        or additional.get("reasoning")
        or getattr(response, "reasoning_content", None)
        or ""
    )
    if isinstance(reasoning, str):
        return len(reasoning)
    return len(str(reasoning)) if reasoning else 0


def _nested_runnable_attr(runnable: Any, name: str) -> Any:
    """Read an attribute through nested LangChain RunnableBinding views."""
    current = runnable
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        value = getattr(current, name, None)
        if value is not None:
            return value
        current = getattr(current, "bound", None) or getattr(current, "_llm", None)
    return None


def runnable_uses_streaming(runnable: Any) -> bool:
    """Whether a bound provider is configured to consume a native stream."""
    return bool(_nested_runnable_attr(runnable, "streaming"))


def provider_response_info(response: Any) -> dict[str, Any]:
    """Normalize provider completion metadata without trusting one adapter key."""
    metadata = getattr(response, "response_metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    additional = getattr(response, "additional_kwargs", None)
    additional = additional if isinstance(additional, dict) else {}
    raw_finish_reason, finish_reason = normalize_finish_reason(
        metadata.get("finish_reason")
        or metadata.get("stop_reason")
        or additional.get("finish_reason")
        or additional.get("stop_reason")
        or ""
    )
    tool_calls = list(getattr(response, "tool_calls", None) or [])
    content = getattr(response, "content", "")
    return {
        "raw_finish_reason": raw_finish_reason,
        "finish_reason": finish_reason,
        "incomplete": finish_reason in _INCOMPLETE_FINISH_REASONS,
        "tool_call_count": len(tool_calls),
        "tool_names": [
            str(call.get("name") or "")[:80] for call in tool_calls[:32]
            if isinstance(call, dict)
        ],
        "content_chars": len(content) if isinstance(content, str) else len(str(content)),
        "reasoning_chars": _reasoning_chars(response, additional),
        **_response_usage(response, metadata),
    }


def _request_heads(messages: Any, *, first_limit: int = 3000,
                   rest_limit: int = 800, max_messages: int = 4) -> list[dict]:
    """Bounded, honest heads of an outgoing message list for llm.request telemetry.

    The FIRST message (system + context prefix) gets the largest head so the
    repo-map/context content is visible — that is what proves which workspace
    reached the model boundary. Never raises; telemetry must not break sends.
    """
    try:
        if not isinstance(messages, list):
            return []
        heads: list[dict] = []
        for i, m in enumerate(messages[:max_messages]):
            role = getattr(m, "type", None) or (m.get("role") if isinstance(m, dict) else None) or "unknown"
            content = getattr(m, "content", None)
            if content is None and isinstance(m, dict):
                content = m.get("content")
            if not isinstance(content, str):
                content = str(content)
            heads.append({"role": role, "head": content[:first_limit if i == 0 else rest_limit]})
        return heads
    except Exception:
        return []


class RetryLLMProxy:
    """Provider proxy with bounded retry and session-scoped cancellation."""

    def __init__(
        self,
        llm: Any,
        max_attempts: int = 5,
        *,
        _abort_state: _AbortState | None = None,
    ):
        self._llm = llm
        self._max_attempts = max_attempts
        self._abort_state = _abort_state or _AbortState(llm)
        # Lazily resolved when PROVIDER_SAFE_LIMIT=0 (auto mode); memoized
        # so per-invoke guard checks never re-read the disk cache.
        self._auto_limit: int | None = None
        # Explicit model name extraction — do NOT rely on __getattr__
        # fall-through. langchain providers differ: ChatOpenAI/ChatGroq
        # historically exposed model_name (alias "model"), newer versions
        # expose model; ChatGoogleGenerativeAI uses model. Grab whichever
        # exists so count_tokens() always gets a real model string.
        self.model = (
            getattr(llm, "model", None)
            or getattr(llm, "model_name", None)
            or getattr(llm, "model_id", None)
        )
        if self.model is None:
            # A provider that exposes none of the three attrs must not leave
            # self.model as None: with PROVIDER_SAFE_LIMIT=0 (auto), the
            # guard would resolve the UNKNOWN-model default (4,096) while the
            # engine budgets the real discovered window — a silent amputator.
            # Fall back to the same source of truth the factory builds from.
            # (settings is fully loaded by factory import time — no circular
            # risk — so there is no excuse for a silent except: pass here.)
            from src.config.settings import LLM_MODEL
            self.model = LLM_MODEL
            print(
                f"[RetryLLMProxy] {type(llm).__name__} exposes no model "
                f"attr; falling back to LLM_MODEL={self.model!r}"
            )
        if not self.model:
            # Last-resort honesty: nothing about this proxy may fail silently.
            # An empty LLM_MODEL leaves the guard conservative-by-default.
            print(
                "[RetryLLMProxy] WARNING: no model name available "
                f"(provider={type(llm).__name__}, LLM_MODEL empty) — token "
                "guard/auto-limit will use conservative fallbacks"
            )
        # Guards auto-limit resolution (double-checked in _safe_limit);
        # the dashboard can invoke this proxy from worker threads.
        self._limit_lock = threading.Lock()

    @property
    def is_aborted(self) -> bool:
        return self._abort_state.aborted

    def _invoke_provider(
        self,
        provider_loop: asyncio.AbstractEventLoop | None,
        *args,
        **kwargs,
    ):
        """Run native async providers in a request-cancellable task.

        Closing a synchronous httpx client from another thread does not
        reliably interrupt a response-body read. LangChain provider runnables
        expose ``ainvoke`` backed by their async clients; cancelling that task
        is request-specific and immediately unwinds the socket operation.
        One loop is retained across this invocation's retry attempts so pooled
        async clients are never reused on a closed loop.
        """
        ainvoke = getattr(self._llm, "ainvoke", None)
        if provider_loop is None or not callable(ainvoke):
            return self._llm.invoke(*args, **kwargs)

        async def _call():
            loop = asyncio.get_running_loop()
            task = asyncio.current_task()
            assert task is not None
            self._abort_state.attach_async(loop, task)
            try:
                return await ainvoke(*args, **kwargs)
            finally:
                self._abort_state.detach_async(loop, task)

        try:
            return provider_loop.run_until_complete(_call())
        except asyncio.CancelledError as error:
            raise TurnCancelledError(
                "LLM request cancelled by the user (Stop pressed)."
            ) from error

    def invoke(self, *args, **kwargs):
        """
        Invoke with retry logic AND a pre-send token guard.
        If messages exceed the provider's safe limit, trim from the middle
        (preserve system + recent history) before sending.

        Automatically registers/unregisters this proxy's abort handle against
        the active session so every proxied model request is covered by the
        cancellation lifecycle, not just ai_node.
        """
        last_error = None

        # Register before any request preparation. If Stop already won,
        # register_abort() fires this handle immediately and the pre-attempt
        # gate below raises without starting provider traffic.
        sid = active_session()
        abort_handle = self.abort
        # LangChain's synchronous invoke() owns and drains its configured
        # streaming iterator. Wrapping streaming=True in a fresh async loop
        # left Response.aiter_raw pending in desktop Attempt 8 and obscured
        # whether all tool-argument chunks had arrived. Match Hermes' single
        # stream owner: use the sync stream consumer; reserve the cancellable
        # async task path for genuinely non-streaming providers.
        native_streaming = runnable_uses_streaming(self._llm)
        provider_loop = (
            asyncio.new_event_loop()
            if callable(getattr(self._llm, "ainvoke", None)) and not native_streaming
            else None
        )
        if sid is not None:
            turn_controls.register_abort(sid, abort_handle)

        try:

            # ------------------------------------------------------------------
            # PRE-SEND SANITIZER (D36): lossless cleanup of the outgoing message
            # list — collapse duplicate tool_calls within an assistant message,
            # drop re-used tool_call_id results, dedup byte-identical tool
            # results. Mirrors hermes' pre-call sanitizer. Never raises.
            # ------------------------------------------------------------------
            sanitized = None
            messages_arg = None
            if args:
                messages_arg = args[0]
            elif "messages" in kwargs:
                messages_arg = kwargs["messages"]

            if isinstance(messages_arg, list):
                from src.llm.request_sanitizer import sanitize_request_messages
                sanitized = sanitize_request_messages(messages_arg)
                if sanitized is not messages_arg:
                    if args:
                        args = (sanitized,) + args[1:]
                    else:
                        kwargs["messages"] = sanitized
                    messages_arg = sanitized

            # ------------------------------------------------------------------
            # P1 PROMPT-CACHE PLAN: decorate the byte-stable prefix head with
            # cache breakpoints (hermes prompt_caching.py shape). DEFAULT OFF —
            # only applied when PULSEAI_PROMPT_CACHE=1 AND the provider/model is
            # allowlisted (an OpenAI-compatible endpoint that rejects unknown
            # content fields must never 4xx a turn). Pure, never raises; the
            # failover stripper (cache_preservation.py) can always undo it.
            # ------------------------------------------------------------------
            if isinstance(messages_arg, list):
                cls = type(self._llm).__name__.lower()
                provider = (
                    "gemini" if "google" in cls
                    else "groq" if "groq" in cls
                    else "custom" if "openai" in cls  # includes the base_url custom route
                    else cls
                )
                try:
                    from src.context.prompt_cache_plan import build_prompt_cache_plan
                    planned, _info = build_prompt_cache_plan(messages_arg, provider, self.model)
                    if planned is not messages_arg:
                        if args:
                            args = (planned,) + args[1:]
                        else:
                            kwargs["messages"] = planned
                        messages_arg = planned
                except Exception:
                    pass  # cache decoration must never break a send

            # ------------------------------------------------------------------
            # PRE-SEND TOKEN GUARD (503 mitigation)
            # Guard ONLY the messages arg — never any other positional arg.
            # ------------------------------------------------------------------
            if isinstance(messages_arg, list):
                # trim_limit semantics: >=0 = enforce this limit; -1 = guard
                # unavailable, send untrimmed (with a loud warning, never silent).
                trim_limit = -1
                try:
                    from src.context.token_budget import count_tokens
                    total_tokens = count_tokens(messages_arg, self.model)
                    trim_limit = self._safe_limit()
                except Exception as guard_error:
                    # NEVER silently disable the guard: a token-counting failure
                    # would otherwise zero the limit and ship oversized payloads
                    # straight to providers (the 503 the guard exists to prevent).
                    print(
                        f"[RetryLLMProxy] Token guard unavailable (model={self.model!r}): "
                        f"{guard_error!r} — sending untrimmed"
                    )
                    total_tokens = 0

                if trim_limit >= 0 and total_tokens > trim_limit:
                    trimmed = self._trim_to_limit(messages_arg, trim_limit)
                    print(
                        f"[RetryLLMProxy] Trimmed {total_tokens} -> ~{trim_limit} "
                        f"tokens to avoid provider 503"
                    )
                    if args:
                        args = (trimmed,) + args[1:]
                    else:
                        kwargs["messages"] = trimmed
                    messages_arg = trimmed

            request_snapshot = build_request_snapshot(messages_arg, self._llm)
            capture_payload = os.environ.get(
                "PULSEAI_CAPTURE_REQUEST_PAYLOADS", ""
            ).strip().lower() in {"1", "true", "yes", "on"}

            for attempt in range(self._max_attempts):
                # Cancellation gate BEFORE every attempt: a Stop that fired while
                # the previous attempt was blocked must never launch a new request.
                self._raise_if_cancelled()

                # LLM request telemetry (benchmark evidence, PBR-002/012): one
                # event per ACTUAL provider request attempt, emitted after the
                # cancellation gate — a cancelled turn never records a send it
                # did not make. Session-filtered so the bridge forwards it only
                # to the owning session's subscriber. Never raises.
                try:
                    from src.dashboard.event_bus import event_bus
                    event_bus.emit("llm.request", {
                        "session_id": sid,
                        "model": self.model,
                        "attempt": attempt + 1,
                        "message_count": len(messages_arg) if isinstance(messages_arg, list) else None,
                        "messages": _request_heads(messages_arg),
                        "message_chars": request_snapshot["message_chars"],
                        "tool_count": len(request_snapshot["tools"]),
                        "tool_names": request_snapshot["tool_names"],
                        "tool_schema_chars": request_snapshot["tool_schema_chars"],
                        "request_sha256": request_snapshot["sha256"],
                        **({"request_payload": request_snapshot} if capture_payload else {}),
                    })
                except Exception:
                    pass  # telemetry must never break a send

                try:
                    response = self._invoke_provider(provider_loop, *args, **kwargs)
                    # Hermes records the provider's completion boundary before
                    # dispatching tools. Pulse previously retained only request
                    # metadata, so a token-limited tool call was
                    # indistinguishable from a complete one. Emit bounded
                    # response facts—never tool arguments or assistant text.
                    try:
                        from src.dashboard.event_bus import event_bus
                        event_bus.emit("llm.response", {
                            "session_id": sid,
                            "model": self.model,
                            "attempt": attempt + 1,
                            **provider_response_info(response),
                        })
                    except Exception:
                        pass
                    return response
                except Exception as error:
                    # A Stop pressed while this HTTP request was in flight wins
                    # over any retry/failover logic: surface the cancellation and
                    # do NOT fire another (now-unwanted) request.
                    self._raise_if_cancelled(error)
                    last_error = error

                    # Hermes discipline: a failing call is VISIBLE. One line
                    # per failed attempt into the bridge log
                    # (desktop-stdout.log) — model, attempt, error class — so
                    # a blackholed network or a dead key is diagnosable from
                    # the log alone.
                    print(
                        f"[PulseAI LLM] attempt {attempt + 1}/{self._max_attempts} "
                        f"failed on {self.model!r}: {type(error).__name__}: "
                        f"{str(error)[:200]}"
                    )

                    if not self._is_retryable(error) or attempt == self._max_attempts - 1:
                        raise

                    # Wait on the shared abort event instead of time.sleep().
                    # Stop therefore interrupts a long provider backoff now,
                    # rather than waiting up to 30 seconds for the next gate.
                    self._raise_if_cancelled()
                    delay = self._retry_delay(error, attempt)
                    print(f"[PulseAI LLM] retrying in {delay:.1f}s ...")
                    if sid is None:
                        time.sleep(delay)
                    else:
                        self._abort_state.event.wait(delay)
                    self._raise_if_cancelled()

            raise last_error
        finally:
            if sid is not None:
                turn_controls.unregister_abort(sid, abort_handle)
            if provider_loop is not None:
                # streaming=True can leave the HTTP response async generator
                # awaiting aclose even after ainvoke returns an accumulated
                # tool-call message. Closing the loop immediately produced
                # Attempt-8's "Task was destroyed but it is pending" warning
                # and an un-awaited Response.aiter_raw aclose. Drain generators
                # with a hard bound; cleanup must not become another wedge.
                try:
                    provider_loop.run_until_complete(
                        asyncio.wait_for(
                            provider_loop.shutdown_asyncgens(), timeout=5.0
                        )
                    )
                except Exception:
                    pass
                provider_loop.close()

    def _raise_if_cancelled(self, error: Exception | None = None) -> None:
        """Raise TurnCancelledError when the active session was cancelled or
        this proxy was aborted. Safe no-op when no session is bound to this
        thread (e.g. dashboard-internal background helper threads)."""
        if self.is_aborted:
            raise TurnCancelledError(
                "LLM request aborted by the user (Stop pressed)."
            ) from error
        sid = active_session()
        if sid is not None and turn_controls.cancelled(sid):
            raise TurnCancelledError(
                "LLM request cancelled by the user (Stop pressed)."
            ) from error

    def abort(self) -> None:
        """Interrupt this binding's request family exactly once."""
        self._abort_state.abort()

    def _safe_limit(self) -> int:
        """The pre-send input cap for this proxy.

        PROVIDER_SAFE_LIMIT > 0  → explicit cap (free/combo tiers).
        PROVIDER_SAFE_LIMIT = 0  → AUTO: trust the dynamically discovered
        model window (minus reply headroom). Use on paid/unlimited tiers —
        the ContextEngine resolves the identical number, so engine-built
        context and this guard can never disagree.
        """
        from src.config.settings import PROVIDER_SAFE_LIMIT
        if PROVIDER_SAFE_LIMIT > 0:
            return PROVIDER_SAFE_LIMIT
        if self._auto_limit is None:
            with self._limit_lock:
                if self._auto_limit is None:
                    from src.context.model_budgets import (
                        resolve_context_window,
                        usable_window_budget,
                    )
                    window, _source = resolve_context_window(self.model)
                    self._auto_limit = usable_window_budget(window)
        return self._auto_limit

    def _trim_to_limit(self, messages: list, limit: int) -> list:
        """
        Trim message list to fit within token limit.
        Strategy: preserve system message (index 0) and the most recent
        messages at the tail. Drop from the middle (oldest history first).
        """
        try:
            from src.context.token_budget import count_tokens
        except Exception:
            return messages

        if not messages:
            return messages

        # Always keep the first message (system prompt).
        keep_head = 1
        head_tokens = count_tokens(messages[:keep_head], self.model)

        # Binary search for how many tail messages we can keep.
        low, high = 0, len(messages) - keep_head
        best = 0
        while low <= high:
            mid = (low + high) // 2
            tail = messages[-mid:] if mid > 0 else []
            t = head_tokens
            if tail:
                try:
                    t = count_tokens(messages[:keep_head] + tail, self.model)
                except Exception:
                    t = head_tokens
            if t <= limit:
                best = mid
                low = mid + 1
            else:
                high = mid - 1

        result = messages[:keep_head]
        if best > 0:
            result.extend(messages[-best:])
        return result

    def _wrap_binding(self, runnable: Any) -> "RetryLLMProxy":
        return RetryLLMProxy(
            runnable,
            max_attempts=self._max_attempts,
            _abort_state=self._abort_state,
        )

    def bind_tools(self, *args, **kwargs):
        return self._wrap_binding(self._llm.bind_tools(*args, **kwargs))

    def bind(self, *args, **kwargs):
        # LangChain bindings are runnable views over the same provider client.
        # Preserve the proxy and share the root transport's one-shot abort state.
        return self._wrap_binding(self._llm.bind(*args, **kwargs))

    def with_structured_output(self, *args, **kwargs):
        return self._wrap_binding(
            self._llm.with_structured_output(*args, **kwargs)
        )

    def __getattr__(self, name: str):
        return getattr(self._llm, name)

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        try:
            from src.llm.error_classifier import classify_api_error, FailoverReason
            c = classify_api_error(error)
            if c.reason in (FailoverReason.auth, FailoverReason.auth_permanent, FailoverReason.billing): return False
            if c.reason in (FailoverReason.context_overflow,): return False
            return c.retryable
        except Exception:
            pass
        text = str(error).lower()
        return (
            "rate limit" in text
            or "rate_limit" in text
            or "429" in text
            or "temporarily unavailable" in text
            or "connection error" in text
            or "connecterror" in text
            or "503" in text
            or "combo retry limit" in text
            # Some custom auto routers may briefly route to a backend model
            # their OpenAI-compatible endpoint cannot serve. Retrying can select
            # a different backend for the same configured model id.
            or "unsupported model" in text
        )

    @staticmethod
    def _retry_delay(error: Exception, attempt: int) -> float:
        text = str(error)

        # Groq often says: "Please try again in 3.33s" or "405ms".
        seconds_match = re.search(r"try again in ([0-9.]+)s", text, re.IGNORECASE)
        if seconds_match:
            return min(float(seconds_match.group(1)) + 0.5, 30.0)

        millis_match = re.search(r"try again in ([0-9.]+)ms", text, re.IGNORECASE)
        if millis_match:
            return min(float(millis_match.group(1)) / 1000.0 + 0.5, 30.0)

        return min(2.0 * (attempt + 1), 30.0)


def default_request_timeout() -> float:
    """Provider request timeout in seconds — env-driven, read per call.

    PULSEAI_LLM_REQUEST_TIMEOUT_S (default 60). A hung provider must never
    wedge a turn forever, but the number is a deployment decision, not a
    hardcoded one.
    """
    import os as _os
    try:
        return max(10.0, min(float(_os.environ.get("PULSEAI_LLM_REQUEST_TIMEOUT_S", "60")), 600.0))
    except (TypeError, ValueError):
        return 60.0


def _stream_stall_timeout() -> float:
    """Per-attempt SILENCE budget for streaming calls (hermes run.py: extend
    while tokens move — a fixed wall-clock punishes SLOW and HUNG equally,
    and only silence is the enemy). On a streaming request the transport read
    timeout is the gap BETWEEN received chunks, so sizing it to silence means
    a slow-but-alive generation never trips it while a dead endpoint fails
    the attempt within the budget. Field proof: the owner's endpoint hung
    after a tool call and the generation-sized 180s timeout handed it 3
    minutes of silent "Waiting on the model" per attempt. Env:
    PULSEAI_LLM_STALL_TIMEOUT_S, default 45, clamp 10..300, read per call."""
    raw = os.environ.get("PULSEAI_LLM_STALL_TIMEOUT_S", "")
    try:
        value = float(raw) if raw.strip() else 45.0
    except (TypeError, ValueError):
        value = 45.0
    return max(10.0, min(value, 300.0))


def streaming_enabled(default: bool) -> bool:
    """Token streaming on/off -- env-driven, read per client construction.

    PULSEAI_LLM_STREAMING: "1/true/yes/on" forces ON, anything else forces
    OFF; unset falls back to the per-provider default. Hermes doctrine (the
    single stream owner): streaming is the NORMAL posture -- the user watches
    words arrive instead of staring at a frozen panel for the whole
    generation. First-token latency is the UX; total wall time is unchanged.
    ALL provider branches default ON -- including `custom`: the owner's
    deployment routes every turn through a custom OpenAI-compatible endpoint
    whose model streams fine, and words-arrive-as-words is the product
    posture. LangChain's sync invoke() owns and aggregates the stream
    (tool-call chunks included) -- the single-owner shape this file already
    pins in its comments. PULSEAI_LLM_STREAMING=off is the escape hatch for
    a server that mishandles `stream:true`.
    """
    raw = os.environ.get("PULSEAI_LLM_STREAMING")
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def get_llm(provider, model, max_attempts: int | None = None, request_timeout: float | None = None):
    """Build a retry-bounded provider client.

    ``max_attempts`` / ``request_timeout``: optional PER-CALL overrides for
    management-class lanes (the hermes auxiliary discipline, issue #54465:
    hidden retries silently multiply wall time on slow endpoints -- the SDK's
    answer was max_retries=0 and Hermes-owned retry budgets). None = the
    historical defaults (5 attempts, default_request_timeout) -- untouched.
    """
    # Hard timeouts: a hung provider must NEVER wedge a dashboard worker
    # thread forever. Retries stay with RetryLLMProxy (single owner).
    if provider == "groq":
        llm = ChatGroq(
            model=model,
            api_key=GROQ_API_KEY,
            request_timeout=request_timeout if request_timeout is not None else default_request_timeout(),
            streaming=streaming_enabled(default=True),
            max_retries=0,  # hermes #54465: hidden SDK retries multiply wall time; RetryLLMProxy owns the policy
        )
        return RetryLLMProxy(llm) if max_attempts is None else RetryLLMProxy(llm, max_attempts=max_attempts)

    if provider == "gemini":
        llm = ChatGoogleGenerativeAI(
            model=model,
            api_key=GEMINI_API_KEY,
            timeout=request_timeout if request_timeout is not None else default_request_timeout(),
            streaming=streaming_enabled(default=True),
            max_retries=0,
        )
        return RetryLLMProxy(llm) if max_attempts is None else RetryLLMProxy(llm, max_attempts=max_attempts)

    if provider == "nvidia":
        llm = ChatOpenAI(
            model=model,
            api_key=NVIDIA_API_KEY,
            base_url="https://integrate.api.nvidia.com/v1",
            request_timeout=request_timeout if request_timeout is not None else default_request_timeout(),
            streaming=streaming_enabled(default=True),
            max_retries=0,
        )
        return RetryLLMProxy(llm) if max_attempts is None else RetryLLMProxy(llm, max_attempts=max_attempts)

    if provider == "openai":
        llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=model,
            request_timeout=request_timeout if request_timeout is not None else default_request_timeout(),
            streaming=streaming_enabled(default=True),
            max_retries=0,
        )
        return RetryLLMProxy(llm) if max_attempts is None else RetryLLMProxy(llm, max_attempts=max_attempts)

    if provider == "cheap":
        # Owner directive 2026-09-06: the low tier is a FULLY env-configured
        # OpenAI-compatible offload — PULSEAI_CHEAP_API_KEY / _BASE_URL /
        # _MODEL. No provider name is hardcoded; the endpoint just has to
        # speak the OpenAI API (groq, together, openrouter, local servers).
        # Env is read per call (standing rule) so rotation needs no restart.
        import os as _os
        cheap_key = (_os.environ.get("PULSEAI_CHEAP_API_KEY") or "").strip()
        cheap_url = (_os.environ.get("PULSEAI_CHEAP_BASE_URL") or "").strip()
        if not cheap_key or not cheap_url:
            raise ValueError(
                "provider 'cheap' requires PULSEAI_CHEAP_API_KEY and "
                "PULSEAI_CHEAP_BASE_URL (and PULSEAI_CHEAP_MODEL in the router)"
            )
        llm = ChatOpenAI(
            api_key=cheap_key,
            base_url=cheap_url,
            model=model,
            request_timeout=request_timeout if request_timeout is not None else default_request_timeout(),
            streaming=streaming_enabled(default=True),
            max_retries=0,  # hermes #54465: RetryLLMProxy owns the retry policy
        )
        return RetryLLMProxy(llm) if max_attempts is None else RetryLLMProxy(llm, max_attempts=max_attempts)

    if provider == "custom":
        streaming = streaming_enabled(default=True)
        try:
            # Sized to GENERATION length for NON-streaming calls (hermes
            # doctrine): a 100B-class model writing a large first response
            # legitimately needs >60s wall time when no stream is running.
            timeout = float(os.environ.get("PULSEAI_LLM_TIMEOUT", "180"))
        except (TypeError, ValueError):
            timeout = 180.0
        if request_timeout is not None:
            effective_timeout = request_timeout
        elif streaming:
            # Streaming: the read timeout is the gap BETWEEN chunks — size it
            # to SILENCE, not generation (hermes extend-while-tokens-move).
            # The generation-sized 180s gave a hung endpoint 3 silent minutes
            # per attempt (x attempts = the "died after a tool call" panel).
            effective_timeout = _stream_stall_timeout()
        else:
            effective_timeout = max(10.0, min(timeout, 300.0))
        llm = ChatOpenAI(
            api_key=CUSTOM_API_KEY,
            base_url=CUSTOM_BASE_URL,
            model=model,
            request_timeout=effective_timeout,
            streaming=streaming,
            max_retries=0,  # hermes #54465: the proxy owns retries; SDK-hidden ones multiply wall time
        )
        return RetryLLMProxy(llm) if max_attempts is None else RetryLLMProxy(llm, max_attempts=max_attempts)

    raise ValueError(f"Unknown provider: {provider}")


# =========================================================
# AUXILIARY CLIENT (D21)
# =========================================================
class RequestScopedAuxLLM:
    """Reusable facade that creates one provider client per invocation.

    Context engines may retain their summarizer LLM across turns. Retaining a
    real provider client would let cancellation poison that future turn. This
    facade retains only binding instructions; invoke() builds a fresh
    RetryLLMProxy and request-owned transport every time.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        bindings: tuple[tuple[str, tuple, dict], ...] = (),
    ):
        self.provider = provider
        self.model = model
        self._bindings = bindings

    def _bind(self) -> RetryLLMProxy:
        llm = get_llm(provider=self.provider, model=self.model)
        for method, args, kwargs in self._bindings:
            llm = getattr(llm, method)(*args, **kwargs)
        return llm

    def invoke(self, *args, **kwargs):
        return self._bind().invoke(*args, **kwargs)

    def _with_binding(self, method: str, args: tuple, kwargs: dict):
        return RequestScopedAuxLLM(
            self.provider,
            self.model,
            (*self._bindings, (method, args, dict(kwargs))),
        )

    def bind_tools(self, *args, **kwargs):
        return self._with_binding("bind_tools", args, kwargs)

    def bind(self, *args, **kwargs):
        return self._with_binding("bind", args, kwargs)

    def with_structured_output(self, *args, **kwargs):
        return self._with_binding("with_structured_output", args, kwargs)


def get_auxiliary_llm() -> RequestScopedAuxLLM:
    """Return a reusable facade with request-owned management transports."""
    from src.config.settings import AUX_LLM_MODEL, AUX_LLM_PROVIDER

    return RequestScopedAuxLLM(AUX_LLM_PROVIDER, AUX_LLM_MODEL)


# =========================================================
# EMBEDDING FACTORY
# =========================================================
class EmbeddingFactory:
    """Singleton embedder — loads once, reused across the agent."""
    _instance: Any = None
    _model: Any = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_model(self):
        if self._model is not None:
            return self._model
        from src.config.settings import EMBEDDING_PROVIDER, EMBEDDING_MODEL, EMBEDDING_DEVICE
        if EMBEDDING_PROVIDER == "local":
            from sentence_transformers import SentenceTransformer
            # Agent startup and ordinary retrieval must be network-inert. An
            # operator may explicitly opt into the one-time model download;
            # otherwise a missing cache cleanly disables optional memory via
            # LazyMemoryManager instead of retrying Hugging Face at import/use.
            allow_downloads = os.environ.get(
                "PULSEAI_ALLOW_MODEL_DOWNLOADS", ""
            ).strip().lower() in {"1", "true", "yes", "on"}
            self._model = SentenceTransformer(
                EMBEDDING_MODEL,
                device=EMBEDDING_DEVICE,
                local_files_only=not allow_downloads,
            )
        elif EMBEDDING_PROVIDER == "openai":
            raise NotImplementedError("OpenAI embeddings not yet implemented")
        else:
            raise ValueError(f"Unknown embedding provider: {EMBEDDING_PROVIDER}")
        return self._model

def get_embedder():
    """Return the shared embedder instance."""
    return EmbeddingFactory().get_model()

