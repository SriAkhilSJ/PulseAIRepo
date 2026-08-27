"""Harness tests: recorder, bridge/echo driver, scenarios, CDP helpers,
report card, and the CLI — all deterministic, zero model calls."""

from __future__ import annotations

import json
import os
import sys

import pytest

from benchmarks.pulse_reliability_v1.contract import load_suite
from benchmarks.pulse_reliability_v1.evaluator import (
    CheckClassification,
    evaluate_suite,
)
from benchmarks.pulse_reliability_v1.harness.cli import main as cli_main
from benchmarks.pulse_reliability_v1.harness.drivers.base import DriverError
from benchmarks.pulse_reliability_v1.harness.drivers.bridge import BridgeDriver
from benchmarks.pulse_reliability_v1.harness.drivers.cdp import (
    dom_snapshot_expression,
    parse_targets,
    pick_page_target,
)
from benchmarks.pulse_reliability_v1.harness.orchestrator import run_task
from benchmarks.pulse_reliability_v1.harness.recorder import Recorder
from benchmarks.pulse_reliability_v1.harness.report import render_report
from benchmarks.pulse_reliability_v1.harness.scenarios import covered_check_ids

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
SUITE = REPO_ROOT / "benchmarks/pulse_reliability_v1/manifest.json"
PY = (sys.executable,)


def _suite():
    return load_suite(SUITE)


def _task(task_id):
    return next(t for t in _suite().tasks if t.id == task_id)


@pytest.fixture()
def workspace(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "workspace_proof.py").write_text("def proof():\n    return 42\n", encoding="utf-8")
    return ws


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


def test_recorder_builds_valid_run_record(workspace):
    rec = Recorder()
    rec.record_frame("hello", {"protocol": 2})
    rec.record_frame("turn_done", {"completed": True}, cancelled=False)
    rec.record_event("llm.request", {"model": "echo"})
    rec.record_dom("textarea.x", enabled=False, visible=True, text="hi", count=1)
    rec.observe("additional_workers", 0)
    rec.add_usage(model_calls=2, input_tokens=10, output_tokens=5, cache_tokens=0)
    rec.first_token_ms = 111
    rec.completion_ms = 222
    record = rec.build_run_record(
        run_id="test-run", task_id="PBR-012", task_version=1,
        pulse_commit="abc123", fixture_root=str(workspace),
    )
    assert record.schema_id == "pulse-benchmark-run/v1"
    assert len(record.frames) == 2
    assert record.frames[-1].cancelled is False
    assert record.model_calls == 2
    assert record.first_token_ms == 111
    assert record.completion_ms == 222


# ---------------------------------------------------------------------------
# Bridge driver (echo lane) — real subprocess, real protocol v2
# ---------------------------------------------------------------------------


def test_bridge_echo_handshake():
    rec = Recorder()
    driver = BridgeDriver(rec, python_command=PY, echo=True)
    driver.connect(timeout_s=15.0)
    assert rec.frames[0].type == "hello"
    assert rec.frames[0].payload.get("protocol") == 2
    assert rec.frames[0].payload.get("engine") == "pulseai"
    driver.shutdown()


def test_bridge_echo_full_turn(workspace):
    rec = Recorder()
    driver = BridgeDriver(rec, python_command=PY, echo=True)
    driver.connect(timeout_s=15.0)
    driver.open_workspace(str(workspace))
    driver.send_prompt("Reply with exactly: OK")
    summary = driver.wait_turn(timeout_s=15.0)
    types = [f.type for f in rec.frames]
    assert "turn_started" in types and "token" in types
    assert types[-1] == "turn_done"
    assert summary.completed is True and summary.cancelled is False
    assert summary.first_token_ms is not None
    assert rec.first_token_ms == summary.first_token_ms
    assert rec.completion_ms is not None
    driver.shutdown()


def test_bridge_echo_cancel_mid_turn(workspace):
    rec = Recorder()
    driver = BridgeDriver(rec, python_command=PY, echo=True, echo_delay_ms=2000)
    driver.connect(timeout_s=15.0)
    driver.open_workspace(str(workspace))
    driver.send_prompt("Slow turn, then cancel me.")
    assert driver.wait_for_frame("turn_started", 10.0)
    driver.cancel()
    summary = driver.wait_turn(timeout_s=15.0)
    assert summary.cancelled is True and summary.completed is False
    assert rec.cancelled_at_ms is not None
    assert rec.frames[-1].type == "turn_done"
    assert rec.frames[-1].cancelled is True
    driver.shutdown()


def test_bridge_workspace_is_enforced(workspace):
    """The bridge refuses session_create without a workspace (P0 contract)."""
    rec = Recorder()
    driver = BridgeDriver(rec, python_command=PY, echo=True)
    driver.connect(timeout_s=15.0)
    driver._send({"type": "session_create", "session_id": "x"})
    frames = driver._collect(10.0)
    assert frames[-1]["type"] == "error"
    assert "workspace required" in frames[-1]["message"]
    driver.shutdown()


def test_bridge_shutdown_clean():
    rec = Recorder()
    driver = BridgeDriver(rec, python_command=PY, echo=True)
    driver.connect(timeout_s=15.0)
    driver.shutdown()
    assert driver._proc is None


# ---------------------------------------------------------------------------
# Coverage model
# ---------------------------------------------------------------------------


def test_coverage_echo_pbr012():
    caps = BridgeDriver(Recorder(), python_command=PY, echo=True).capabilities
    covered = covered_check_ids(_task("PBR-012"), caps)
    assert "cancelled-protocol" in covered          # protocol: final turn_done cancelled
    assert "no-post-cancel-model-call" in covered   # event absence check
    assert "cancelled-ui" not in covered            # dom needs the desktop lane
    assert "no-worker-growth" not in covered        # process needs host observation


def test_coverage_cdp_covers_dom():
    from benchmarks.pulse_reliability_v1.harness.drivers.cdp import CdpDriver
    caps = CdpDriver(Recorder(), port=1).capabilities
    assert caps.dom is True
    covered = covered_check_ids(_task("PBR-001"), caps)
    assert covered == {"composer-disabled", "no-workspace-hint", "no-prompt-frame"}


# ---------------------------------------------------------------------------
# Scenarios + orchestrator end-to-end (echo lane, zero cost)
# ---------------------------------------------------------------------------


def test_pbr012_echo_end_to_end(workspace, monkeypatch, tmp_path):
    monkeypatch.chdir(REPO_ROOT)
    record, result, run_dir = run_task(
        task_id="PBR-012", driver_kind="echo", workspace=str(workspace),
        suite_path=str(SUITE), python_command=PY,
        echo_delay_ms=2000, cancel_after_start_ms=50,
        run_id="test-pbr012-echo",
        results_root=str(tmp_path / "results"),  # never pollute bench-results/
    )
    by_id = {c.check_id: c for c in result.checks}
    assert by_id["cancelled-protocol"].classification == CheckClassification.PASSED
    assert by_id["no-post-cancel-model-call"].classification == CheckClassification.PASSED
    # DOM + process checks are not coverable on the echo lane: they grade as
    # not_run (a lane evidence gap, never a product failure) and the outcome
    # is computed over the coverable checks only.
    assert by_id["cancelled-ui"].classification == CheckClassification.NOT_RUN
    assert by_id["no-worker-growth"].classification == CheckClassification.NOT_RUN
    assert result.outcome.value == "passed"
    assert result.hard_failure is None
    assert (run_dir / "run-record.json").exists()
    assert (run_dir / "result.json").exists()
    payload = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert payload["lane"] == "echo"
    assert payload["checks_covered"] == 2
    # The turn really was cancelled over a live protocol connection.
    assert record.cancelled_at_ms is not None
    assert record.frames[-1].cancelled is True


def test_scenario_refuses_weak_lane(workspace, monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    with pytest.raises(DriverError, match="needs at least"):
        run_task(task_id="PBR-001", driver_kind="echo", workspace=str(workspace),
                 suite_path=str(SUITE), python_command=PY)
    with pytest.raises(DriverError, match="needs at least"):
        run_task(task_id="PBR-002", driver_kind="echo", workspace=str(workspace),
                 suite_path=str(SUITE), python_command=PY)


def test_workspace_must_exist(monkeypatch, tmp_path):
    monkeypatch.chdir(REPO_ROOT)
    with pytest.raises(DriverError, match="does not exist"):
        run_task(task_id="PBR-012", driver_kind="echo",
                 workspace=str(tmp_path / "nope"),
                 suite_path=str(SUITE), python_command=PY)


# ---------------------------------------------------------------------------
# CDP driver helpers (unit level; live window runs on the host machine)
# ---------------------------------------------------------------------------


def test_dom_expression_embeds_selector():
    expr = dom_snapshot_expression("textarea.pulseai-composer-input")
    assert "textarea.pulseai-composer-input" in expr
    assert "querySelectorAll" in expr
    assert "getBoundingClientRect" in expr


def test_cdp_parse_and_pick_targets():
    payload = json.dumps([
        {"type": "page", "url": "file:///C:/ws", "webSocketDebuggerUrl": "ws://a"},
        {"type": "page", "url": "about:blank", "webSocketDebuggerUrl": "ws://b"},
        {"type": "node", "url": "ws://c"},
    ])
    targets = parse_targets(payload)
    assert len(targets) == 2
    picked = pick_page_target(targets, prefer_url="C:/ws")
    assert picked["webSocketDebuggerUrl"] == "ws://a"
    assert pick_page_target(targets)["webSocketDebuggerUrl"] in ("ws://a", "ws://b")
    with pytest.raises(DriverError):
        parse_targets("not json")


# ---------------------------------------------------------------------------
# Report card
# ---------------------------------------------------------------------------


def _fake_result(task_id, outcome="passed", lane="echo", checks=4, passed=4,
                 first_token=120, completion=800, calls=0, cost=0.0):
    return {
        "task_id": task_id, "outcome": outcome, "hard_failure": None,
        "pulse_commit": "abc123", "lane": lane, "checks_covered": checks,
        "checks": [
            {"check_id": f"c{i}", "classification": "passed" if i < passed else "failed_new"}
            for i in range(checks)
        ],
        "timing_ms": {"first_token": first_token, "completion": completion},
        "usage": {"model_calls": calls, "tool_calls": 0, "input_tokens": 0,
                  "output_tokens": 0, "cache_tokens": 0,
                  "estimated_cost_usd": cost},
    }


def test_report_render_honest(tmp_path):
    d = tmp_path / "res"
    d.mkdir()
    (d / "r1" / "result.json").parent.mkdir()
    (d / "r1" / "result.json").write_text(
        json.dumps(_fake_result("PBR-012", outcome="failed_functional",
                                passed=2, checks=4)), encoding="utf-8")
    (d / "r2" / "result.json").parent.mkdir()
    (d / "r2" / "result.json").write_text(
        json.dumps(_fake_result("PBR-006", lane="bridge", calls=14, cost=0.02)),
        encoding="utf-8")
    md = render_report(d, suite_path=str(SUITE))
    assert "PBR-012" in md and "PBR-006" in md
    assert "failed_functional" in md
    assert "2/4" in md
    assert "No desktop-lane" in md          # honest: no cdp runs
    assert "no real model calls" not in md  # PBR-006 had calls
    assert "14" in md                       # axis table shows model calls


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_run_all_keyless(workspace, tmp_path, monkeypatch, capsys):
    """run-all: PBR-012 on echo runs; cdp tasks fail loudly without an IDE;
    the report card is still produced and lists what is pending."""
    monkeypatch.chdir(REPO_ROOT)
    out_dir = tmp_path / "ra"
    code = cli_main([
        "run-all", "--workspace", str(workspace),
        "--suite", str(SUITE), "--python", sys.executable,
        "--cancel-after-start-ms", "50",
        "--connect-timeout", "3",
        "--out-dir", str(out_dir),
    ])
    captured = capsys.readouterr().out
    assert "task=PBR-012 lane=echo outcome=" in captured
    assert "PBR-001 lane=cdp ERROR" in captured
    assert "PBR-003 lane=cdp ERROR" in captured
    assert code == 1
    card = out_dir / "report-card.md"
    assert card.exists()
    md = card.read_text(encoding="utf-8")
    assert "PBR-012" in md
    assert "## Not yet run" in md


def test_cli_run_and_report(workspace, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(REPO_ROOT)
    out = tmp_path / "results"
    code = cli_main([
        "run", "--task", "PBR-012", "--driver", "echo", "--workspace", str(workspace),
        "--suite", str(SUITE), "--python", sys.executable,
        "--echo-delay-ms", "1500", "--cancel-after-start-ms", "50",
        "--run-id", "cli-pbr012",
        "--results-root", str(out),  # test runs never pollute the real scoreboard
    ])
    assert code == 0  # coverable checks passed; DOM/process graded not_run
    captured = capsys.readouterr().out
    assert "outcome=passed" in captured

    # The report card must also render from an isolated results dir.
    assert cli_main(["report", "--results-dir", str(out),
                     "--out", str(tmp_path / "report-card.md"), "--suite", str(SUITE)]) == 0
    report_path = tmp_path / "report-card.md"
    assert report_path.exists()
    md = report_path.read_text(encoding="utf-8")
    assert "Reliability Benchmark Report Card" in md
    assert "PBR-012" in md


# ------------------------------------------------ observability wiring (PBR-002)

def test_bridge_driver_records_events_and_usage_deltas():
    """Event-like frames become RunEvents; cumulative telemetry frames add
    usage as a DELTA (repeated snapshots never double-count)."""
    from benchmarks.pulse_reliability_v1.harness.drivers.bridge import (
        BridgeDriver, EVENT_FRAME_TYPES,
    )
    from benchmarks.pulse_reliability_v1.harness.recorder import Recorder

    rec = Recorder()
    drv = BridgeDriver(rec, python_command=("python",))
    assert "workspace.bound" in EVENT_FRAME_TYPES
    assert "llm.request" in EVENT_FRAME_TYPES

    drv._record_frame({"type": "workspace.bound", "session_id": "s",
                       "workspace": "/tmp/pbr-ws", "hops": "/tmp/pbr-ws"})
    drv._record_frame({"type": "llm.request", "model": "m", "attempt": 1,
                       "messages": [{"role": "system", "head": "... workspace_proof.py ..."}]})
    drv._record_frame({"type": "token", "text": "hi"})
    assert [e.type for e in rec.events] == ["workspace.bound", "llm.request"]
    assert rec.events[0].payload["hops"] == "/tmp/pbr-ws"
    assert "workspace_proof.py" in json.dumps(rec.events[1].payload)
    # token frames are frames, not events:
    assert [f.type for f in rec.frames][-1] == "token"

    # Cumulative telemetry: 2 snapshots -> usage counted ONCE as deltas.
    drv._record_frame({"type": "telemetry", "apiCalls": 1, "tokensIn": 100,
                       "tokensOut": 20, "totalCost": 0.01})
    drv._record_frame({"type": "telemetry", "apiCalls": 2, "tokensIn": 250,
                       "tokensOut": 60, "totalCost": 0.03})
    record = rec.build_run_record(
        run_id="t", task_id="PBR-002", task_version=1, pulse_commit="x",
    )
    assert record.model_calls == 2
    assert record.input_tokens == 250
    assert record.output_tokens == 60
    assert abs(record.estimated_cost_usd - 0.03) < 1e-9


def test_bridge_driver_session_id_is_unique_per_instance():
    """Cross-run pollution pin: a FIXED session id made every benchmark run
    replay all prior runs' durable checkpoint history (7->11->14->17 calls,
    linear). Each driver instance must mint a fresh thread id."""
    from benchmarks.pulse_reliability_v1.harness.drivers.bridge import BridgeDriver
    a = BridgeDriver(Recorder(), python_command=("python",))
    b = BridgeDriver(Recorder(), python_command=("python",))
    assert a._session_id != b._session_id
    assert a._session_id.startswith("bench-")


def test_turn_control_stale_cancel_never_poisons_reuse():
    """External review #15 pin: a cancelled turn's cancel_event must not
    outlive the turn — an unmanaged caller reusing the id without begin()
    would have admit_action() refuse forever."""
    from src.runtime.turn_control import TurnControlRegistry

    tc = TurnControlRegistry()
    sid = "poison-test"
    tc.begin(sid)
    assert tc.cancel(sid) is True          # event set, turn cancelled
    tc.end(sid)                            # last owner releases
    # Unmanaged reuse (no begin): admission must succeed — stale cleared.
    assert tc.admit_action(sid) is True
    # And a late cancel after end is still rejected (inactive session):
    assert tc.cancel(sid) is False



def test_windows_posix_guard_rejects_every_test5_dialect_before_spawn(monkeypatch):
    import src.tools.terminal_tools as terminal_tools

    monkeypatch.setattr(terminal_tools, "_IS_WINDOWS", True)
    for command, verb in (
        ("ls -la && find . -maxdepth 2 -type f | head", "ls"),
        ("pwd && ls -la", "pwd"),
        ("find . -type f", "find"),
        ("head -20 app.js", "head"),
    ):
        violations = terminal_tools._posix_violations(command)
        assert violations, f"{command!r} must be rejected before cmd.exe spawn"
        assert any(verb in item for item in violations)


def test_test5_curl_download_is_not_intrinsically_destructive(monkeypatch):
    """Do not weaken safety based on an imprecise transcript diagnosis: the
    exact direct curl command from Test5-5 already passes the safety guard."""
    from src.context.safety_guard import SafetyGuard
    from src.tools import terminal_tools

    command = "curl -sL https://unpkg.com/three@0.160.0/build/three.min.js -o three.min.js"
    assert SafetyGuard(".").check_tool_call(
        "run_terminal", {"command": command}
    ) == (True, "")
    monkeypatch.setattr(terminal_tools, "_IS_WINDOWS", True)
    assert terminal_tools._posix_violations(command) == []


def test_no_delivery_breaker_ignores_dependency_trees_but_sees_source(tmp_path):
    from scripts.run_bridge_turn import (
        should_stop_for_no_delivery,
        workspace_has_delivered_file,
    )

    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("dependency")
    assert workspace_has_delivered_file(str(tmp_path)) is False
    assert should_stop_for_no_delivery(11, 12, str(tmp_path)) is False
    assert should_stop_for_no_delivery(12, 12, str(tmp_path)) is True
    (tmp_path / "index.html").write_text("<!doctype html>")
    assert workspace_has_delivered_file(str(tmp_path)) is True
    assert should_stop_for_no_delivery(20, 12, str(tmp_path)) is False


def test_test5_headless_approval_is_workspace_scoped_and_payload_size_independent(tmp_path):
    """A 30KB write must not strand the headless runner on safety_request."""
    from scripts.run_bridge_turn import should_auto_approve_safety_request

    workspace = str(tmp_path)
    large = "const shader = `" + ("x" * 35_000) + "`;"
    frame = {
        "type": "safety_request",
        "name": "write_file",
        "warning": "",
        "arguments": {"path": "src/main.js", "content": large},
    }
    assert should_auto_approve_safety_request(frame, workspace) is True
    assert should_auto_approve_safety_request(
        {**frame, "arguments": {"path": "../escape.js", "content": large}}, workspace
    ) is False
    assert should_auto_approve_safety_request(
        {**frame, "arguments": {"path": ".env", "content": large}}, workspace
    ) is False
    assert should_auto_approve_safety_request(
        {**frame, "warning": "dangerous operation"}, workspace
    ) is False
    assert should_auto_approve_safety_request(
        {**frame, "name": "run_terminal", "arguments": {"command": "rm -rf x"}}, workspace
    ) is False


def test_terminal_timeout_tree_kills_and_returns_promptly(monkeypatch, tmp_path):
    """test5-2 pin: a hung command must produce a bounded tool result via
    TREE kill -- the old Windows path killed only the wrapper, orphaned
    children held the pipes, and the unbounded communicate() hung forever
    (322s silence, watchdog killed a healthy build)."""
    import sys
    import time as _time

    import src.tools.terminal_tools as tt

    killed = []
    monkeypatch.setattr(tt, "_IS_WINDOWS", True)
    import src.context.git_context as gc
    monkeypatch.setattr(
        gc, "_taskkill_tree",
        lambda pid: (killed.append(pid), True)[1],
    )
    monkeypatch.setenv("PULSEAI_TERMINAL_TIMEOUT", "1")
    hang = f'"{sys.executable}" -c "import time; time.sleep(60)"'
    t0 = _time.monotonic()
    runner = getattr(tt.run_terminal, "func", tt.run_terminal)  # StructuredTool -> raw fn
    result = runner(hang, {"configurable": {"thread_id": "t5-pin", "workspace": str(tmp_path)}})
    elapsed = _time.monotonic() - t0
    assert "timed out" in result, result[:200]
    assert elapsed < 15, f"timeout path must return promptly, took {elapsed:.1f}s"
    assert killed, "Windows timeout must consult the tree-kill (not wrapper kill)"
    assert killed[0] > 0
