"""A completed agent turn must be readable back out of durable checkpoint state.

Why this file looks sparse: it used to be a *script* — one top-level import of
``src.graphs.chat_graph`` and a module-level ``invoke_agent(...)`` call, with
bare ``assert`` statements and ``print``s.  Anything at module scope runs while
pytest is **collecting**, which had three consequences, all of them bad:

* the live turn was **billed to whatever provider the host has configured**, so
  a plain ``pytest src/tests`` spent credits without anyone opting in;
* a real multi-step turn takes minutes, so collection looked like a **hung
  interpreter** — which is exactly how it got misattributed to slow imports
  ("scipy is cold on this machine") during a Windows verification round, and
  cost that round its full-suite run;
* on a host without ``langgraph.checkpoint.sqlite`` the top-level import turned
  into a *collection error* for the whole suite instead of one skipped test.

So: heavy imports are now inside the test, the module imports nothing from
``src``, and the live turn is opt-in because it costs money.

    PULSEAI_ALLOW_LIVE_AGENT_TEST=1 pytest src/tests/test_agent_status_checkpoint.py
"""

import os
import uuid
from pathlib import Path

import pytest

# Opt-in only: this test runs a real agent turn against the configured provider
# and therefore spends credits.  It is *skipped*, not failed, when the gate is
# closed — a verifier run must be able to report "provider-free" truthfully.
pytestmark = pytest.mark.skipif(
    os.environ.get("PULSEAI_ALLOW_LIVE_AGENT_TEST") != "1",
    reason=(
        "performs a real, billed provider turn; opt in with "
        "PULSEAI_ALLOW_LIVE_AGENT_TEST=1"
    ),
)


def test_completed_turn_is_reflected_in_checkpoint_status(tmp_path):
    pytest.importorskip(
        "langgraph.checkpoint.sqlite",
        reason="durable checkpointing needs the sqlite checkpointer extra",
    )
    from src.config.settings import LLM_MODEL, LLM_PROVIDER
    from src.graphs.chat_graph import get_agent_status, invoke_agent

    # Relative to `workspace`, so the agent writes inside tmp_path and the
    # checkout is left alone.  (The old version wrote to ./generated/.)
    relative_target = Path("generated") / "status_checkpoint_test.py"
    target = tmp_path / relative_target
    target.parent.mkdir(parents=True, exist_ok=True)
    assert not target.exists()

    # A fresh thread per run: reusing one id let a previous run's checkpoint
    # satisfy `trace_count > 0` on its own.
    thread_id = f"agent-status-checkpoint-test-{uuid.uuid4().hex[:8]}"

    response = invoke_agent(
        message=(
            f"Create {relative_target.as_posix()} that prints "
            "STATUS CHECKPOINT WORKS. Run it and verify the output."
        ),
        thread_id=thread_id,
        provider=LLM_PROVIDER,
        model=LLM_MODEL,
        workspace=str(tmp_path),
        execution_mode="agent",
    )
    assert response, "the agent turn returned nothing to verify against"

    status = get_agent_status(thread_id=thread_id)

    assert status["status"] == "completed", (
        "Successfully finished task was not marked completed."
    )
    assert status["plan"]["completed"] == status["plan"]["total"], (
        "Completed task left unfinished plan steps."
    )
    assert status["task"], "Checkpoint did not preserve current_task."
    assert status["trace_count"] > 0, (
        "Checkpoint did not preserve execution_trace."
    )
    assert status["last_action"] is not None, (
        "Checkpoint has no last tool action."
    )
    assert status["last_action"]["status"] == "success", (
        "Last recorded action was not successful."
    )
    assert status["recovery"]["active"] is False, (
        "Agent remained in recovery mode after success."
    )
    assert target.exists(), "Agent did not create the target file."
