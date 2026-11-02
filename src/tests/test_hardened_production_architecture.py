"""
Unit and integration tests for the Hardened Production Architecture Specification:
- Deterministic Run State Ledger
- Pillar 1: Content-Addressed Read Cache with Context Residency Awareness
- Pillar 2: Progress-Aware Loop Detection Engine
- Pillar 3: Structured Process Execution Boundary
- Pillar 4: Adaptive Greenfield Scaffolding Policy
- Pillar 5 & 6: Dynamic Reasoning Budgeting & Multi-Vector Scorecard
"""

import os
import sys
import tempfile
from pathlib import Path
import pytest

from src.runtime.run_state_ledger import AgentRunState, get_run_state_ledger
from src.tools.read_cache import HardenedReadCache
from src.graphs.progress_guard import evaluate_operation_progress
from src.tools.process_boundary import execute_sandboxed_command, detect_conversational_leak
from src.runtime.scaffolding_policy import (
    validate_syntax_tree,
    analyze_code_structural_complexity,
    evaluate_scaffolding_requirement,
)
from src.runtime.reasoning_budget import resolve_reasoning_budget
from src.runtime.multi_vector_scorecard import MultiVectorScorecard


def test_deterministic_run_state_ledger():
    state = AgentRunState(session_id="test_sess_01", objective="Build e-commerce startup")
    assert state.current_revision == 0
    assert len(state.execution_history) == 0

    # 1. Non-mutating read
    rec1 = state.record_tool_call(
        tool_name="read_file",
        target="schema.sql",
        state_mutated=False,
        new_info=True,
        output_text="CREATE TABLE users...",
    )
    assert rec1.sequence == 1
    assert rec1.revision_before == 0
    assert rec1.revision_after == 0
    assert state.current_revision == 0

    # 2. Mutating write
    rec2 = state.record_tool_call(
        tool_name="write_file",
        target="db.py",
        state_mutated=True,
        new_info=True,
        output_text="Wrote 500 lines",
    )
    assert rec2.sequence == 2
    assert rec2.revision_before == 0
    assert rec2.revision_after == 1
    assert state.current_revision == 1

    # 3. Verification debt tracking
    state.add_verification_debt("test_user_signup")
    assert len(state.verification_debt) == 1
    state.resolve_verification_debt("test_user_signup")
    assert len(state.verification_debt) == 0


def test_hardened_read_cache_context_residency(tmp_path):
    test_file = tmp_path / "app.py"
    test_file.write_text("print('hello world')", encoding="utf-8")

    state = AgentRunState(session_id="sess_cache_01")
    cache = HardenedReadCache(run_state=state)

    # First read: Not in active context -> Full text returned (Cache miss)
    content, hit = cache.execute_read(test_file, active_prompt_text="")
    assert hit is False
    assert "print('hello world')" in content

    # File hash is now tracked in active_context_files
    # But if active_prompt_text does NOT contain the filename or hash -> still context miss (re-hydrate)
    content2, hit2 = cache.execute_read(test_file, active_prompt_text="unrelated prompt text")
    assert hit2 is False

    # Second read: Filename is confirmed resident in active prompt text -> Returns lightweight receipt!
    prompt_with_file = f"Here is the context of app.py from earlier turn"
    receipt, hit3 = cache.execute_read(test_file, active_prompt_text=prompt_with_file)
    assert hit3 is True
    assert "[CONTENT RESIDENT]" in receipt
    assert "app.py" in receipt

    # File is mutated on disk -> Forces fresh read even if in prompt
    test_file.write_text("print('mutated code')", encoding="utf-8")
    mutated_content, hit4 = cache.execute_read(test_file, active_prompt_text=prompt_with_file)
    assert hit4 is False
    assert "print('mutated code')" in mutated_content


def test_progress_aware_loop_detection():
    state = AgentRunState(session_id="sess_loop_01")

    # 1. Repeated calls with new information -> NO loop detected
    for i in range(3):
        state.record_tool_call("read_file", f"file_{i}.py", state_mutated=False, new_info=True)
    assert evaluate_operation_progress(state, "read_file", "file_0.py") is None

    # 2. Repeated calls to SAME target with ZERO mutation and ZERO new info -> Loop Intercepted!
    loop_state = AgentRunState(session_id="sess_loop_02")
    for _ in range(3):
        loop_state.record_tool_call("read_file", "schema.sql", state_mutated=False, new_info=False)

    decision = evaluate_operation_progress(loop_state, "read_file", "schema.sql")
    assert decision is not None
    assert decision["status"] == "loop_detected"
    assert "executed 3 times without modifying workspace" in decision["reason"]


def test_process_boundary_monologue_leak_detection():
    # Conversational commentary detected and rejected
    leak1 = "Sure, I will run the tests now: pytest"
    assert detect_conversational_leak(leak1) is not None

    leak2 = "Okay, let's list the directory contents."
    assert detect_conversational_leak(leak2) is not None

    leak3 = "Now I will install dependencies."
    assert detect_conversational_leak(leak3) is not None

    # Legitimate shell commands accepted
    assert detect_conversational_leak("pytest tests/") is None
    assert detect_conversational_leak("python app.py --port 8000") is None
    assert detect_conversational_leak("git status --short") is None


def test_process_boundary_sandboxed_execution(tmp_path):
    # Monologue rejection
    res1 = execute_sandboxed_command("Certainly! I will run python", tmp_path)
    assert res1["exit_code"] == 2
    assert "Rejected prose command" in res1["stderr"]

    # Traversal escape rejection
    res2 = execute_sandboxed_command("cd ../../../etc", tmp_path)
    assert res2["exit_code"] == 3
    assert "Directory traversal outside workspace" in res2["stderr"]

    # Valid execution
    res3 = execute_sandboxed_command(f"{sys.executable} -V", tmp_path)
    assert res3["exit_code"] == 0
    assert "Python" in (res3["stdout"] + res3["stderr"])


def test_adaptive_greenfield_scaffolding():
    # 1. Invalid syntax code
    broken_code = "def foo(\n   print('unclosed'"
    ok, msg = validate_syntax_tree(broken_code, "test.py")
    assert ok is False
    assert "SyntaxError" in msg

    # 2. Simple clean script
    simple_code = "def add(a, b):\n    return a + b\n"
    res_simple = evaluate_scaffolding_requirement(simple_code, "math_utils.py")
    assert res_simple["status"] == "approved"

    # 3. Complex multi-endpoint API -> Scaffolding recommended
    complex_api = """
import db

class AuthController:
    pass

class ProductController:
    pass

class CartController:
    pass

class OrderController:
    pass

@route("GET", "/api/v1")
def ep1(): pass

@route("POST", "/api/v2")
def ep2(): pass

@route("GET", "/api/v3")
def ep3(): pass

@route("PUT", "/api/v4")
def ep4(): pass

@route("DELETE", "/api/v5")
def ep5(): pass

@route("PATCH", "/api/v6")
def ep6(): pass
"""
    res_complex = evaluate_scaffolding_requirement(complex_api, "server.py")
    assert res_complex["status"] == "scaffolding_recommended"
    assert res_complex["metrics"]["class_count"] == 4
    assert res_complex["metrics"]["endpoint_count"] == 6


def test_reasoning_budget_and_scorecard():
    # Budget tiers
    b_explore = resolve_reasoning_budget(phase="explore", turn_sequence=1)
    assert b_explore.thinking_budget_tokens == 12000
    assert b_explore.output_cap_tokens == 4096

    b_verify = resolve_reasoning_budget(phase="verification", turn_sequence=5)
    assert b_verify.thinking_budget_tokens == 2000

    # Scorecard
    scorecard = MultiVectorScorecard(
        run_id="test_run_99",
        model="z-ai/glm-5.3-flash",
        total_checks_defined=10,
        checks_passed=10,
        checks_regressed=0,
        tokens_consumed=45000,
        wall_clock_seconds=22.5,
        request_latencies_ms=[1200.0, 1500.0, 1100.0, 2400.0],
        total_actions=8,
        repetitive_actions=0,
        headless_completed=True,
    )
    d = scorecard.to_dict()
    assert d["correctness_pass_rate"] == 1.0
    assert d["integrity_regression_rate"] == 0.0
    assert d["stability_repetitive_ratio"] == 0.0
    assert d["autonomy_completed"] is True
    assert d["speed_p50_ms"] == 1350.0


def test_tool_middleware_run_state_integration():
    from src.runtime.tool_middleware import execute_tool_transaction
    from src.runtime.run_state_ledger import get_run_state_ledger

    session_id = 'test_session_middleware_1'
    config = {'configurable': {'thread_id': session_id, 'workspace': '.'}}

    # Execute a tool
    outcome = execute_tool_transaction(
        name='write_file',
        args={'path': 'server.py', 'content': 'print(1)'},
        tool_call_id='tc_1',
        config=config,
        invoke=lambda: 'Written 8 bytes to server.py',
        project=False,
    )
    assert outcome.status == 'ok'
    ledger = get_run_state_ledger(session_id)
    assert ledger.current_revision == 1
    assert len(ledger.execution_history) == 1
    assert ledger.execution_history[0].tool_name == 'write_file'


def test_progress_observation_distinguishes_repeated_reads_and_changes():
    from src.runtime.tool_middleware import _progress_observation
    state = AgentRunState(session_id="progress-read")
    command = "sed -n '1,20p' app.py"
    for _ in range(3):
        mutation, info = _progress_observation(state, "terminal", command, "same\nExit code: 0", "ok")
        state.record_tool_call("terminal", command, state_mutated=mutation, new_info=info,
                               output_text="same\nExit code: 0")
    assert state.current_revision == 0
    assert [r.new_information_provided for r in state.execution_history] == [True, False, False]
    assert _progress_observation(state, "terminal", command, "changed\nExit code: 0", "ok") == (False, True)
    state.record_tool_call("write_file", "app.py", state_mutated=True)
    assert _progress_observation(state, "terminal", command, "same\nExit code: 0", "ok") == (False, True)


def test_progress_command_classifier_is_conservative():
    from src.runtime.tool_middleware import _progress_read_only_command
    assert _progress_read_only_command("sed -n '1,20p' app.py")
    assert _progress_read_only_command("cat app.py")
    for command in ("cat app.py; rm app.py", "cat app.py > out", "sed -i 's/a/b/' app.py",
                    "python inspect.py", "cat $(touch x)", "echo hello", "cat a | tee b"):
        assert not _progress_read_only_command(command), command


def test_middleware_repeated_terminal_reads_eventually_advise_without_blocking(tmp_path):
    import uuid
    from src.runtime.tool_middleware import execute_tool_transaction
    session_id = "progress-" + uuid.uuid4().hex
    config = {"configurable": {"thread_id": session_id, "workspace": str(tmp_path)}}
    calls = []
    for index in range(10):
        outcome = execute_tool_transaction(
            name="terminal", args={"command": "cat app.py"},
            tool_call_id=f"read-{index}", config=config, project=False,
            invoke=lambda: calls.append(1) or "same\nExit code: 0",
        )
    assert len(calls) == 10  # advisory never suppresses an execution
    assert "PROGRESS GUARD ADVISORY" in outcome.content
    state = get_run_state_ledger(session_id)
    assert state.current_revision == 0
    assert state.execution_history[-1].new_information_provided is False


def test_overlapping_sed_ranges_are_advisory_and_only_when_fully_known(tmp_path):
    import uuid
    from src.runtime.tool_middleware import execute_tool_transaction
    session_id = "overlap-" + uuid.uuid4().hex
    config = {"configurable": {"thread_id": session_id, "workspace": str(tmp_path)}}
    calls = []
    def run(command, output):
        return execute_tool_transaction(name="terminal", args={"command": command},
            tool_call_id=str(len(calls)), config=config, project=False,
            invoke=lambda: calls.append(command) or output)
    run("sed -n '1,4p' app.py", "STDOUT:\na\nb\nc\nd\n\nExit code: 0")
    run("sed -n '2,3p' app.py", "STDOUT:\nb\nc\n\nExit code: 0")
    ledger = get_run_state_ledger(session_id)
    assert [r.new_information_provided for r in ledger.execution_history] == [True, False]
    run("sed -n '3,5p' app.py", "STDOUT:\nc\nd\ne\n\nExit code: 0")
    assert ledger.execution_history[-1].new_information_provided  # one genuinely new line
    run("sed -n '2,3p' app.py", "STDOUT:\nchanged\nc\n\nExit code: 0")
    assert ledger.execution_history[-1].new_information_provided
    run("sed -n '2,3p' other.py", "STDOUT:\nb\nc\n\nExit code: 0")
    assert ledger.execution_history[-1].new_information_provided
    # A successful write invalidates the local revision's old observations.
    execute_tool_transaction(name="write_file", args={"path": "app.py"}, tool_call_id="w", config=config, project=False, invoke=lambda: "wrote")
    run("sed -n '2,3p' app.py", "STDOUT:\nb\nc\n\nExit code: 0")
    assert ledger.execution_history[-1].new_information_provided
    assert len(calls) == 6  # never blocks a read


def test_sed_overlap_declines_ambiguous_or_truncated_results():
    from src.runtime.tool_middleware import _sed_line_observation
    for command, result in [
        ("sed -n '1,3p' app.py", "one\ntwo\nExit code: 0"),
        ("sed -n '1,3p' *.py", "a\nb\nc\nExit code: 0"),
        ("sed -n '1,3p' app.py; rm x", "a\nb\nc\nExit code: 0"),
        ("sed -n '1,3p' app.py", "a\nb\nc\nExit code: 1"),
    ]:
        assert _sed_line_observation("terminal", command, result, "ok") == ("", 0, ())
