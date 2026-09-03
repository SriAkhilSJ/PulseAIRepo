"""P8: the history-shaping pipeline, extracted from the layered engine.

The four operations the engine applies to raw conversation history before
it reaches the model:

* **Tool-output summarization** — every ToolMessage through the
  SmartSummarizer (long outputs become short summaries, short ones pass
  through untouched).
* **Prune-first compaction** — the D22 hermes pack (compaction.py):
  protected head/tail, structural dropping only while still over budget,
  dropped turns folded into an iterative AUX-model summary with anti-thrash.
  ``PULSEAI_COMPACTION=off`` restores the legacy structural pipeline (with
  the landed-mutation-payload omission still applied — its own kill switch).
* **Turn-atomic budget trim** — never splits tool pairs, never starts on a
  ToolMessage (the P4 guard lives in trim_messages_to_budget / the
  SmartCompressor validity pass).
* **Per-session compaction telemetry** — prune/structural/LLM-summary
  counters for ``get_status()``.

The per-turn path AND the ABC ``compress()`` entry share ONE
``HistoryCompactor`` through ``ensure_compactor()`` — one anti-thrash state
per session (P3 contract).

Engine-coupling rule: the engine's model, inference policy, current task,
session identity and window are all mutable mid-life (``update_model`` /
``reconfigure_model`` re-point the model; ``_active_thread_id`` moves per
build), so this class receives GETTERS, never values. A shaper that captured
``model`` by value would silently keep token-counting with a dead model
after a mid-session reconfigure.
"""
from __future__ import annotations

import os
from typing import Any, Callable, List, Optional

from langchain_core.messages import BaseMessage, ToolMessage

from src.context.smart_compressor import SmartCompressor
from src.context.token_budget import count_tokens, trim_messages_to_budget

_ZERO_STATS = {
    "prunes": 0,
    "structural_compactions": 0,
    "llm_summary_calls": 0,
    "llm_suppressed": 0,
    "ineffective_streak": 0,
    "summary_chars": 0,
    "placeholders": 0,
    "placeholder_chars_reclaimed": 0,
    # Hygiene counters (shaper-owned, hermes stale-replay/image-retirement
    # parity): part of the canonical zero shape so the pre-use contract and
    # the kill-switch branch report the same keys.
    "stale_replay_pruned": 0,
    "stale_images_retired": 0,
}


class HistoryShaper:
    """Owns the session's history pipeline and its HistoryCompactor."""

    def __init__(
        self,
        model: Callable[[], str],
        allow_embedding_compute: Callable[[], bool],
        summarizer: Any,
        current_task: Callable[[], str],
        session_id: Callable[[], str],
        context_window: Callable[[], Optional[int]],
    ) -> None:
        self._model = model
        self._allow_embedding_compute = allow_embedding_compute
        self.summarizer = summarizer
        self._current_task = current_task
        self._session_id = session_id
        self._context_window = context_window
        # Lazy so the constructor stays I/O-free (engine __init__ contract).
        self._compactor: Optional[Any] = None

    # -- compactor lifecycle -------------------------------------------------

    @property
    def compactor(self) -> Optional[Any]:
        """The shared per-session HistoryCompactor (None until first use)."""
        return self._compactor

    def ensure_compactor(self) -> Any:
        """Lazily create (once per session) the HistoryCompactor shared by
        the per-turn path AND the ABC compress() entry."""
        if self._compactor is None:
            from src.context.compaction import HistoryCompactor
            from src.llm.factory import get_auxiliary_llm

            _ctx_len = self._context_window()
            if _ctx_len is None:
                try:
                    from src.context.model_budgets import resolve_context_window
                    _ctx_len, _ = resolve_context_window(
                        self._model(), allow_network=False
                    )
                except Exception:
                    _ctx_len = None
            self._compactor = HistoryCompactor(
                model=self._model(),
                aux_llm_getter=get_auxiliary_llm,  # D21's janitor client
                session_id=(self._session_id() or ""),
                context_length=_ctx_len,
            )
        else:
            try:
                tid = self._session_id()
                if tid:
                    self._compactor._session_id = tid
            except Exception:
                pass
        return self._compactor

    # -- the pipeline ---------------------------------------------------------

    def summarize_tool_messages(
        self, messages: list[BaseMessage]
    ) -> list[BaseMessage]:
        """Run every ToolMessage through the SmartSummarizer.

        If a tool output is long, replace it with a short summary.
        If it's short, leave it alone.
        """
        result: list[BaseMessage] = []
        for message in messages:
            if isinstance(message, ToolMessage):
                # This might return the same message (if short) or a compressed one
                result.append(self.summarizer.summarize_message(message))
            else:
                # Not a tool message — leave it alone
                result.append(message)
        return result

    def compact(
        self,
        history: list[BaseMessage],
        budget: int,
        kill_switch_trim: Optional[Callable[[list, int], list]] = None,
    ) -> list[BaseMessage]:
        """D22 hermes pack (compaction.py): prune-first with protected
        head/tail, structural dropping only if still over budget, dropped
        turns folded into an iterative AUX-model summary with anti-thrash.
        PULSEAI_COMPACTION=off restores the legacy structural pipeline;
        landed mutation omission has its own diagnostic kill switch.

        ``kill_switch_trim``: the engine passes its own ``_trim_history``
        bound method so the legacy path stays on the engine's public seam
        (and any engine-level override or test spy keeps working).
        """
        if not history:
            return []
        # Hygiene pass — runs on BOTH paths (the kill switch skips the LLM
        # summary, not the hygiene), on the REQUEST-ONLY copy before anything
        # else touches the list (hermes parity: their stale-replay prune and
        # image retirement are also pre-pipeline). Counted, not silent.
        from src.context.compaction import (
            prune_stale_reasoning_replay,
            retire_stale_tool_images,
        )
        self._stale_replay_pruned = getattr(self, "_stale_replay_pruned", 0) + (
            prune_stale_reasoning_replay(history)
        )
        self._stale_images_retired = getattr(self, "_stale_images_retired", 0) + (
            retire_stale_tool_images(history)
        )

        if os.environ.get("PULSEAI_COMPACTION", "").strip().lower() == "off":
            # Even the structural-compaction kill switch must not replay every
            # landed write payload until the run-level token budget is gone.
            from src.context.compaction import compact_file_mutation_arguments
            trim_fn = kill_switch_trim if kill_switch_trim is not None else self.trim
            compacted = compact_file_mutation_arguments(history)
            return trim_fn(self.summarize_tool_messages(compacted), budget)

        self.ensure_compactor()
        compressor = SmartCompressor(
            model=self._model(),
            allow_embedding_compute=self._allow_embedding_compute(),
        )
        return self._compactor.compact(
            history,
            budget,
            summarize_tools=self.summarize_tool_messages,
            structural_compress=lambda h, b: compressor.compress(
                h,
                budget=b,
                token_counter=lambda msgs, model: count_tokens(msgs, model),
                task=self._current_task() or "",
            ),
            fallback_trim=lambda h, b: trim_messages_to_budget(h, b, self._model()),
        )

    def trim(self, history: list[BaseMessage], budget: int) -> list[BaseMessage]:
        """Budget-fit trim with the P4 pairing guard. If the smart
        compression still overshoots, fall back to the turn-atomic trim."""
        if not history:
            return []
        compressor = SmartCompressor(
            model=self._model(),
            allow_embedding_compute=self._allow_embedding_compute(),
        )
        compressed = compressor.compress(
            history,
            budget=budget,
            token_counter=lambda msgs, model: count_tokens(msgs, model),
            task=self._current_task() or "",
        )
        if count_tokens(compressed, self._model()) > budget:
            return trim_messages_to_budget(history, budget, self._model())
        return compressed

    # -- telemetry -------------------------------------------------------------

    def stats(self) -> dict:
        """D22 telemetry: prune/compaction counters for this session."""
        # Hygiene counters are SHAPER-owned (they run pre-pipeline, including
        # on the kill-switch path where no compactor is ever created), so they
        # overlay both branches.
        hygiene = {
            "stale_replay_pruned": getattr(self, "_stale_replay_pruned", 0),
            "stale_images_retired": getattr(self, "_stale_images_retired", 0),
        }
        if self._compactor is None:
            s = dict(_ZERO_STATS)
            s.update(hygiene)
            return s
        s = dict(self._compactor.stats)
        s["summary_chars"] = len(self._compactor.summary)
        s["llm_suppressed_active"] = self._compactor.llm_suppressed
        s.update(hygiene)
        return s
