"""Checkpoint-backed graph segments for opt-in continuous turns.

A LangGraph recursion limit is a per-invocation safety backstop, not a task
completion condition.  On that specific boundary, resume the *pending* graph
from its synchronously persisted checkpoint; never submit the user input again.
This does not retry node exceptions or resume a crashed process automatically.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from langgraph.errors import GraphRecursionError


def _is_framework_boundary(exc: GraphRecursionError) -> bool:
    """Reject errors raised inside nodes, including spoofed boundary text."""
    tb = exc.__traceback__
    if tb is None:
        return False
    while tb.tb_next is not None:
        tb = tb.tb_next
    code = tb.tb_frame.f_code
    filename = code.co_filename.replace("\\", "/")
    return (
        "Recursion limit of" in str(exc)
        and filename.endswith("/langgraph/pregel/main.py")
        and code.co_name == "stream"
    )


def stream_checkpointed_segments(
    graph: Any,
    initial_state: Any,
    *,
    config: dict,
    stream_mode: str,
    on_segment: Callable[[int], None] | None = None,
) -> Iterator[Any]:
    """Stream one turn across recursion boundaries without replaying its input.

    Sync durability ensures the preceding superstep has been persisted before
    another executes. Only the framework recursion error is intercepted; a
    failing node, permission denial, cancellation, or provider error remains
    under the existing graph/bridge handling. A missing or non-advancing
    checkpoint fails closed rather than replaying an uncertain side effect.
    """
    pending_input = initial_state
    # A pre-existing checkpoint is not proof that this invocation advanced.
    # Compare against it before the first resume too.
    before = graph.get_state(config)
    before_metadata = getattr(before, "metadata", None) or {}
    before_step = before_metadata.get("step")
    previous_step: int | None = before_step if isinstance(before_step, int) else None
    segment = 0
    while True:
        try:
            yield from graph.stream(
                pending_input, config=config, stream_mode=stream_mode,
                durability="sync",
            )
            return
        except GraphRecursionError as exc:
            # Do not mistake a GraphRecursionError raised inside a node for
            # the framework's own per-invocation recursion boundary.
            if not _is_framework_boundary(exc):
                raise
            snapshot = graph.get_state(config)
            metadata = getattr(snapshot, "metadata", None) or {}
            step = metadata.get("step")
            if (
                snapshot is None
                or not getattr(snapshot, "next", ())
                or not isinstance(step, int)
                or (previous_step is not None and step <= previous_step)
            ):
                raise
            previous_step = step
            pending_input = None  # continue pending checkpoint; never resubmit
            segment += 1
            if on_segment is not None:
                on_segment(segment)
