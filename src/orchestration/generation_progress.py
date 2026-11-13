"""Truthful generation activity for engineering model calls (P1A).

One model request can take tens of seconds before its first token, and the
orchestrator only publishes stage cards at node boundaries. That gap is what
made the panel look frozen during a real engineering run.

This module is the data contract between the model execution adapter and the
event pipeline. It carries *facts about the request* (elapsed time, characters
received, terminal phase) — never prompt text, never model output. The adapter
stays free of the event bus; the graph maps these updates onto the existing
activity card.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

#: How often a still-running generation reports that it is still running.
DEFAULT_HEARTBEAT_S = 3.0
#: Upper bound on heartbeat emissions for one generation (≈10 minutes at 3s).
MAX_HEARTBEATS = 200
#: Minimum spacing between token-driven updates (the UI needs liveness, not
#: every provider chunk; the full count is carried on the update).
DELTA_THROTTLE_S = 0.25


@dataclass(frozen=True)
class GenerationUpdate:
    """One observable fact about an in-flight generation."""

    phase: str  # started | delta | heartbeat | completed | failed | cancelled
    purpose: str
    target_file: str
    invocation_id: str
    elapsed_s: float
    chars: int
    delta_chars: int = 0
    finish_reason: str = ""
    error: str = ""
    node_id: str = ""

    @property
    def label(self) -> str:
        target = (self.target_file or "").strip()
        if target:
            verb = "Repairing" if self.purpose.startswith("repair") else "Generating"
            return f"{verb} {target}"
        return "Waiting on the model"


GenerationObserver = Callable[[GenerationUpdate], None]


class GenerationActivity:
    """Counts streamed output and emits bounded, thread-safe updates.

    Every update is a fact: the provider has (or has not) sent data, how long the
    request has been open, and how many characters arrived. No partially parsed
    JSON or generated source is ever handed to this layer.
    """

    def __init__(
        self,
        observer: Optional[GenerationObserver],
        *,
        purpose: str,
        target_file: str,
        node_id: str = "",
        heartbeat_s: Optional[float] = None,
        max_heartbeats: int = MAX_HEARTBEATS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._observer = observer
        self._purpose = purpose
        self._target = target_file
        self._node_id = node_id
        self._heartbeat_s = max(float(DEFAULT_HEARTBEAT_S if heartbeat_s is None else heartbeat_s), 0.2)
        self._max_heartbeats = max(int(max_heartbeats), 0)
        self._clock = clock
        self._lock = threading.Lock()
        self._started = clock()
        self._last_delta_notice = 0.0
        self._chars = 0
        self._chunks = 0
        self._heartbeats = 0
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.invocation_id = ""

    @property
    def chars(self) -> int:
        with self._lock:
            return self._chars

    @property
    def chunks(self) -> int:
        with self._lock:
            return self._chunks

    def _notify(self, update: GenerationUpdate) -> None:
        if self._observer is None:
            return
        try:
            self._observer(update)
        except Exception:
            # Presentation must never fail a paid request.
            pass

    def started(self, invocation_id: str) -> None:
        self.invocation_id = invocation_id
        self._notify(GenerationUpdate(
            phase="started", purpose=self._purpose, target_file=self._target,
            invocation_id=invocation_id, elapsed_s=0.0, chars=0, node_id=self._node_id,
        ))
        self._thread = threading.Thread(target=self._run_heartbeat, name="crusor-generation-heartbeat", daemon=True)
        self._thread.start()

    def on_token(self, token: str) -> None:
        now = self._clock()
        with self._lock:
            self._chars += len(token)
            self._chunks += 1
            chars = self._chars
            if now - self._last_delta_notice < DELTA_THROTTLE_S:
                return
            self._last_delta_notice = now
        self._notify(GenerationUpdate(
            phase="delta", purpose=self._purpose, target_file=self._target,
            invocation_id=self.invocation_id, elapsed_s=round(now - self._started, 3),
            chars=chars, delta_chars=len(token), node_id=self._node_id,
        ))

    def _run_heartbeat(self) -> None:
        while not self._stop.wait(self._heartbeat_s):
            with self._lock:
                if self._heartbeats >= self._max_heartbeats:
                    return
                self._heartbeats += 1
                chars = self._chars
            self._notify(GenerationUpdate(
                phase="heartbeat", purpose=self._purpose, target_file=self._target,
                invocation_id=self.invocation_id,
                elapsed_s=round(self._clock() - self._started, 3), chars=chars,
                node_id=self._node_id,
            ))

    def close(self, phase: str, *, finish_reason: str = "", error: str = "") -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._notify(GenerationUpdate(
            phase=phase, purpose=self._purpose, target_file=self._target,
            invocation_id=self.invocation_id,
            elapsed_s=round(self._clock() - self._started, 3),
            chars=self.chars, finish_reason=finish_reason, error=error,
            node_id=self._node_id,
        ))

    def as_dict(self) -> Dict[str, float]:
        return {
            "chars": self.chars,
            "chunks": self.chunks,
            "elapsed_s": round(self._clock() - self._started, 3),
        }


def generation_card(
    update: GenerationUpdate,
    *,
    session_id: str,
    turn_id: str,
) -> Dict[str, Any]:
    """Project one generation fact onto the existing ``activity`` card.

    Only live phases are projected. The orchestrator's stage reporter owns the
    terminal card states, so a generation completing must not claim the turn's
    activity is over. No prompt text, model output or reasoning ever enters this
    payload: it is elapsed time, received characters and the target path.
    """
    from src.regression.persistence import redact_secrets_from_dict

    detail_parts = [f"{max(0.0, update.elapsed_s):.0f}s"]
    if update.chars:
        detail_parts.append(f"{update.chars} chars received")
    if update.phase == "started" and not update.chars:
        detail_parts.append("waiting for first token")
    return redact_secrets_from_dict({
        "schema_version": 1,
        "card_type": "activity",
        "card_id": f"{turn_id}:activity",
        "session_id": session_id,
        "turn_id": turn_id,
        "data": {
            "stage": "generating",
            "label": update.label,
            "status": "running",
            "detail": " · ".join(detail_parts),
        },
    })
