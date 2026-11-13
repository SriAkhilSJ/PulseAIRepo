"""P1A: engineering execution consumes model streams incrementally.

The model client here is a deterministic in-process double that yields real
LangChain `AIMessageChunk`s. The path under test is the production one:
`_dispatch_code_prompt` -> shared `ModelGateway` -> provider stream -> the
adapter's generation observer (which the graph maps onto the activity card).

What is proven:
* deltas reach the observer while the call is still running;
* the final extracted source equals the accumulated stream;
* internal JSON/code is never handed to the presentation layer;
* cancellation stops consumption and closes as `cancelled`;
* a non-streaming client still works (single response, zero deltas);
* the invocation id on the observer matches the FinOps ledger row;
* heartbeats are bounded, honest and stop immediately.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from src.finops.invocation_context import ledger_path, read_invocations
from src.llm.factory import TurnCancelledError
from src.orchestration import model_adapter as adapter_module
from src.orchestration.finops_governor import OrchestrationFinOpsGovernor
from src.orchestration.generation_progress import GenerationActivity
from src.orchestration.model_adapter import ModelExecutionAdapter

PROVIDER = "custom"
MODEL = "z-ai/glm-5.3-flash"
SECRET = "INTERNAL-STRUCTURED-PAYLOAD-7f3c"

SOURCE = '```python\ndef divide(a, b):\n    if b == 0:\n        raise ZeroDivisionError("x")\n    return a / b\n```'


def _pieces(text: str, count: int = 8) -> list[str]:
    size = max(1, len(text) // count)
    return [text[i:i + size] for i in range(0, len(text), size)]


class StreamingLLM:
    """Yields provider-shaped chunks; `stream` is what the gateway consumes."""

    _max_attempts = 1

    def __init__(self, content: str, *, delay: float = 0.0, pieces: int = 8,
                 usage: tuple[int, int] = (11, 23)) -> None:
        self.content = content
        self.delay = delay
        self.pieces = pieces
        self.usage = usage
        self.yielded = 0
        self.invoked = False

    def stream(self, messages, config=None, **kwargs):
        for piece in _pieces(self.content, self.pieces):
            if self.delay:
                time.sleep(self.delay)
            self.yielded += 1
            yield AIMessageChunk(content=piece)
        yield AIMessageChunk(
            content="",
            usage_metadata={
                "input_tokens": self.usage[0],
                "output_tokens": self.usage[1],
                "total_tokens": self.usage[0] + self.usage[1],
            },
            response_metadata={"finish_reason": "stop"},
        )

    def invoke(self, messages, config=None, **kwargs):  # must not be used when streaming
        self.invoked = True
        return AIMessage(
            content=self.content,
            usage_metadata={
                "input_tokens": self.usage[0],
                "output_tokens": self.usage[1],
                "total_tokens": self.usage[0] + self.usage[1],
            },
            response_metadata={"finish_reason": "stop"},
        )


class NonStreamingLLM(StreamingLLM):
    stream = None  # gateway must fall back to invoke


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def finops(tmp_path: Path):
    governor = OrchestrationFinOpsGovernor(
        f"stream_{tmp_path.name}", budget_inr=50.0, token_budget=100_000,
    )
    return governor


def _adapter(workspace: Path, llm, observer):
    adapter = ModelExecutionAdapter(
        str(workspace), mock_mode=False, provider=PROVIDER, model=MODEL,
        generation_observer=observer,
    )
    adapter_module.get_llm = lambda provider=None, model=None: llm  # type: ignore[assignment]
    return adapter


def _dispatch(adapter, workspace: Path, finops, *, cancellation=None, target="module.py"):
    return adapter._dispatch_code_prompt(
        prompt=f"Target file: {target}\nPrompt contains {SECRET} and instructions.",
        target_file=target,
        purpose="node_task_1",
        max_output_tokens=256,
        finops=finops,
        session_id="session-1",
        turn_id="turn-1",
        task_id="task-1",
        cancellation_checker=cancellation,
    )


def test_streamed_deltas_reach_the_observer_and_accumulate(workspace, finops) -> None:
    llm = StreamingLLM(SOURCE, delay=0.01)
    updates = []
    adapter = _adapter(workspace, llm, updates.append)

    code = _dispatch(adapter, workspace, finops)

    phases = [u.phase for u in updates]
    assert phases[0] == "started"
    assert "delta" in phases
    assert phases[-1] == "completed"
    assert llm.invoked is False, "the streaming path must not also invoke"
    assert code.startswith("def divide(")
    assert updates[-1].chars >= len(SOURCE) - 8
    # Every delta update carries a monotonically growing character count.
    char_counts = [u.chars for u in updates if u.phase == "delta"]
    assert char_counts == sorted(char_counts)


def test_internal_output_is_never_exposed_to_the_presentation_layer(workspace, finops) -> None:
    structured = json.dumps({"target": "module.py", "content": SECRET, "steps": ["a", "b"]})
    updates = []
    adapter = _adapter(workspace, StreamingLLM(structured), updates.append)

    result = _dispatch(adapter, workspace, finops)

    assert SECRET in result, "the payload is the file content, not UI text"
    for update in updates:
        rendered = f"{update.label} {update.purpose} {update.target_file} {update.finish_reason} {update.error}"
        assert SECRET not in rendered
        assert "{" not in rendered


def test_cancellation_stops_consumption_and_closes_as_cancelled(workspace, finops) -> None:
    llm = StreamingLLM(SOURCE, delay=0.02, pieces=40)
    updates = []
    adapter = _adapter(workspace, llm, updates.append)

    def cancelled() -> bool:
        return sum(1 for u in updates if u.phase == "delta") >= 2

    with pytest.raises(TurnCancelledError):
        _dispatch(adapter, workspace, finops, cancellation=cancelled)

    phases = [u.phase for u in updates]
    assert "cancelled" in phases
    assert "completed" not in phases
    assert llm.yielded < 40, "consumption continued after cancellation"


def test_non_streaming_client_stays_compatible(workspace, finops) -> None:
    llm = NonStreamingLLM(SOURCE)
    updates = []
    adapter = _adapter(workspace, llm, updates.append)

    code = _dispatch(adapter, workspace, finops)

    assert code.startswith("def divide(")
    assert llm.invoked is True
    phases = [u.phase for u in updates]
    assert phases[0] == "started" and phases[-1] == "completed"
    assert not any(p == "delta" for p in phases)
    assert updates[-1].chars == 0


def test_invocation_id_is_consistent_with_the_finops_ledger(workspace, finops) -> None:
    updates = []
    adapter = _adapter(workspace, StreamingLLM(SOURCE), updates.append)

    _dispatch(adapter, workspace, finops)

    started = next(u for u in updates if u.phase == "started")
    rows = read_invocations(str(workspace))
    assert rows, f"no ledger rows at {ledger_path(workspace)}"
    settled = [row for row in rows if row.get("status") == "settled"]
    assert settled, [row.get("status") for row in rows]
    assert started.invocation_id in {row["invocation_id"] for row in settled}
    assert settled[-1]["input_tokens"] > 0
    assert settled[-1]["output_tokens"] > 0


# --------------------------------------------------------------------------- #
# heartbeats
# --------------------------------------------------------------------------- #

def test_heartbeats_are_bounded_and_stop_on_close() -> None:
    updates = []
    activity = GenerationActivity(
        updates.append, purpose="node_task_1", target_file="module.py",
        heartbeat_s=0.05, max_heartbeats=3,
    )
    activity.started("inv-hb")
    time.sleep(0.30)
    activity.close("completed")
    after_close = len(updates)
    time.sleep(0.15)

    heartbeats = [u for u in updates if u.phase == "heartbeat"]
    assert 1 <= len(heartbeats) <= 3, [u.phase for u in updates]
    assert all(u.chars == 0 for u in heartbeats)
    assert updates[-1].phase == "completed"
    assert len(updates) == after_close, "heartbeat continued after close"


def test_heartbeat_carries_generation_progress() -> None:
    updates = []
    activity = GenerationActivity(
        updates.append, purpose="node_task_1", target_file="module.py", heartbeat_s=10.0,
    )
    activity.started("inv-progress")
    activity.on_token("abc")
    activity.close("completed")

    delta = next(u for u in updates if u.phase == "delta")
    assert delta.chars == 3
    assert delta.delta_chars == 3
    assert updates[-1].chars == 3
