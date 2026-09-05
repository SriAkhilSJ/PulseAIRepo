"""D9 pins (§40): the progress_node split.

Every fork of the pre-D9 god-block is pinned in isolation against
src/graphs/progress_helpers.py, plus integration tests through the real
progress_node. The rest of the plan/replan suite (30+ tests) exercises
the orchestrator end-to-end and must stay green — that is the
no-behavior-change proof.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

import src.graphs.progress_helpers as ph


# ---------------------------------------------------------------------
# extraction / lookup
# ---------------------------------------------------------------------

def test_d9_latest_tool_messages_trailing_run_only():
    msgs = [
        HumanMessage(content="hi"),
        ToolMessage(content="old", tool_call_id="0", name="read_file"),
        AIMessage(content="thinking"),
        ToolMessage(content="a", tool_call_id="1", name="read_file"),
        ToolMessage(content="b", tool_call_id="2", name="list_files"),
    ]
    got = ph.latest_tool_messages(msgs)
    assert [m.tool_call_id for m in got] == ["1", "2"]  # order restored


def test_d9_find_tool_args_matches_call_id():
    msgs = [
        AIMessage(content="", tool_calls=[
            {"id": "aa", "name": "read_file", "args": {"path": "x.py"}},
            {"id": "bb", "name": "run_terminal", "args": {"command": "ls"}},
        ]),
    ]
    assert ph.find_tool_args(msgs, "bb") == {"command": "ls"}
    assert ph.find_tool_args(msgs, "nope") == {}


# ---------------------------------------------------------------------
# outcome classification (every legacy fork)
# ---------------------------------------------------------------------

def test_failed_verification_receipts_are_tool_failures():
    assert ph.classify_tool_outcome(
        "typecheck_workspace", "❌ typecheck_workspace: 1 error"
    ) == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome(
        "typecheck_workspace", "✅ typecheck_workspace: passed with 0 errors"
    ) == ph.OUTCOME_SUCCESS
    assert ph.classify_tool_outcome(
        "typecheck_workspace",
        "ℹ️ typecheck_workspace: no tsconfig.json — nothing to typecheck",
    ) == ph.OUTCOME_SKIP
    assert ph.classify_tool_outcome(
        "verify_ui_routes", "❌ UI ROUTE VERIFICATION FAILED"
    ) == ph.OUTCOME_FAILED


def test_d9_classify_terminal_rules():
    ok = "files listed\nexit code: 0"
    bad = "oops\nexit code: 1"
    assert ph.classify_tool_outcome("run_terminal", ok) == ph.OUTCOME_SUCCESS
    assert ph.classify_tool_outcome("run_terminal", bad) == ph.OUTCOME_FAILED
    # no exit-code line at all is a failure for run_terminal
    assert ph.classify_tool_outcome("run_terminal", "done") == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome(
        "check_terminal", "status: running") == ph.OUTCOME_SKIP
    assert ph.classify_tool_outcome(
        "check_terminal", "status: completed\nexit code: 0") == ph.OUTCOME_SUCCESS
    assert ph.classify_tool_outcome(
        "check_terminal", "status: completed\nexit code: 2") == ph.OUTCOME_FAILED
    # generic markers on any other tool
    assert ph.classify_tool_outcome("read_file", "error: not found") == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome("read_file", "Traceback (most recent") == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome(
        "read_file", "unknown process id") == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome(
        "write_file", "path escapes workspace") == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome("read_file", "file contents here") == ph.OUTCOME_SUCCESS


# ---------------------------------------------------------------------
# tool memory
# ---------------------------------------------------------------------

class _Mem:
    def __init__(self):
        self.calls = []

    def store_tool_memory(self, **kw):
        self.calls.append(kw)


def test_d9_memory_rules():
    mem = _Mem()
    ph.record_tool_memory(mem, "think", "task", "some output", {}, False)
    ph.record_tool_memory(mem, "read_file", "task", "   ", {}, False)
    ph.record_tool_memory(None, "read_file", "task", "data", {}, False)
    assert mem.calls == []

    ph.record_tool_memory(mem, "read_file", "task", "HEAD " + "x" * 400,
                          {"path": "a.py", "command": "ls"}, False)
    ph.record_tool_memory(mem, "run_terminal", "task", "y" * 400 + " TAIL",
                          {"command": "make"}, True)
    ok, fail = mem.calls
    assert ok["summary"].startswith("OK path=a.py | HEAD")  # anchor precedence path>command
    assert fail["summary"].startswith("FAILED command=make |")
    assert fail["summary"].endswith("TAIL")                  # failure keeps the tail
    assert ok["full_output"].startswith("HEAD") and len(ok["full_output"]) == 405


def test_d9_memory_never_raises_even_when_store_explodes():
    class _Boom:
        def store_tool_memory(self, **kw):
            raise RuntimeError("db down")

    ph.record_tool_memory(_Boom(), "read_file", "t", "data", {}, False)


# ---------------------------------------------------------------------
# failure bookkeeping
# ---------------------------------------------------------------------

def test_d9_build_failure_terminal_variants():
    f, up = ph.build_failure("run_terminal", "boom output", {"command": "make"},
                             False, None)
    assert f.startswith("Command failed: make\nActual tool output:\n")
    # env_failure is part of the contract: chat_graph reads updates["env_failure"]
    # to route to a strategy pivot instead of retry-until-dead.
    assert up == {"tool_failures_inc": 1, "recovery_attempts_inc": 1,
                  "recovery_mode": True, "recovery_command": "make",
                  "env_failure": False}

    # already in recovery: command slot NOT stolen
    f, up = ph.build_failure("run_terminal", "x", {"command": "make2"},
                             True, "make")
    assert up["recovery_command"] == "make"
    assert up["recovery_attempts_inc"] == 1

    f, up = ph.build_failure("check_terminal", "x", {"process_id": "p9"},
                             False, None)
    assert f.startswith("Terminal process failed: p9")
    assert up["recovery_command"] == "process:p9"

    # generic tool: attempts only move while already in recovery
    f, up = ph.build_failure("read_file", "x", {}, False, None)
    assert f == "Tool failed: read_file"
    assert up["recovery_attempts_inc"] == 0 and up["recovery_mode"] is False
    f, up = ph.build_failure("read_file", "x", {}, True, "make")
    assert up["recovery_attempts_inc"] == 1 and up["recovery_mode"] is True


def test_d9_maybe_replan(monkeypatch):
    needed, usages = ph.maybe_replan("t", [], "f", "p", "m")
    assert needed is False and usages == []

    def _must_not_call(**kwargs):
        raise AssertionError("deterministic local failure must not call the LLM")

    monkeypatch.setattr(ph, "should_replan", _must_not_call)
    plan = [{"step": 1}]
    for failure in (
        "Tool failed: PHASE POLICY DENIED run_terminal",
        "Command failed: curl\n⛔ BLOCKED (safety policy)",
        "run_terminal uses POSIX-only shell on Windows",
    ):
        assert ph.maybe_replan("build", plan, failure, "p", "m") == (False, [])

    captured = {}

    def _fake(task, plan, failure, provider, model, usage_list):
        captured.update(task=task, failure=failure, provider=provider, model=model)
        usage_list.append("U1")
        return True

    monkeypatch.setattr(ph, "should_replan", _fake)
    needed, usages = ph.maybe_replan("fix auth", [{"step": 1}], "boom", "groq", "llama")
    assert needed is True and usages == ["U1"]
    assert captured["failure"] == "boom" and captured["provider"] == "groq"


# ---------------------------------------------------------------------
# success labels / events / recovery clearing
# ---------------------------------------------------------------------

def test_d9_success_labels_and_events():
    label, events = ph.success_step_label("write_file",
                                          {"path": "a.py", "content": "l1\nl2"}, "tc1")
    assert label == "Wrote file: a.py"
    assert [e for e, _ in events] == ["diff.show", "files.changed"]
    assert events[0][1] == {"file": "a.py", "lines": ["l1", "l2"]}
    assert events[1][1] == {"messageId": "tc1", "files": ["a.py"]}

    label, events = ph.success_step_label("edit_file", {"path": "b.py"}, "tc2")
    assert label == "Edited file: b.py"
    assert [e for e, _ in events] == ["files.changed"]

    label, events = ph.success_step_label("read_file", {"path": "c.py"}, "tc3")
    assert label == "Read file: c.py" and events == []

    label, _ = ph.success_step_label("run_terminal", {"command": "make"}, "t")
    assert label == "Ran command successfully: make"
    label, _ = ph.success_step_label("custom_tool", {}, "t")
    assert label == "Completed tool: custom_tool"


def test_d9_recovery_clears_only_same_command():
    mode, cmd = ph.resolve_recovery_on_success(
        "run_terminal", {"command": "make"}, True, "make")
    assert (mode, cmd) == (False, None)
    mode, cmd = ph.resolve_recovery_on_success(
        "run_terminal", {"command": "make clean"}, True, "make")
    assert (mode, cmd) == (True, "make")
    mode, cmd = ph.resolve_recovery_on_success(
        "read_file", {"path": "a.py"}, True, "make")
    assert (mode, cmd) == (True, "make")


def test_d9_reflection_prompt_bytes():
    assert ph.PROGRESS_REFLECTION_PROMPT.startswith(
        "You just received a tool result. Take a moment to evaluate it:"
    )
    assert ph.PROGRESS_REFLECTION_PROMPT.endswith(
        "Don't verify meta-tools like think(), verify(), or ask_user()."
    )


# ---------------------------------------------------------------------
# integration through the real node
# ---------------------------------------------------------------------

def _cfg():
    return {"configurable": {"provider": "p", "model": "m", "thread_id": "t9"}}


def test_d9_progress_node_success_path():
    from src.graphs.chat_graph import progress_node

    state = {
        "messages": [
            AIMessage(content="", tool_calls=[
                {"id": "t1", "name": "run_terminal", "args": {"command": "ls"}},
            ]),
            ToolMessage(content="files here\nexit code: 0",
                        tool_call_id="t1", name="run_terminal"),
        ],
        "current_task": "list files",
    }
    out = progress_node(state, _cfg())
    assert out["steps_completed"] == ["Ran command successfully: ls"]
    assert out["failed_steps"] == []
    assert out["execution_trace"][0]["status"] == "success"
    assert out["execution_trace"][0]["tool"] == "run_terminal"
    assert isinstance(out["messages"][0], SystemMessage)
    assert out["messages"][0].content == ph.PROGRESS_REFLECTION_PROMPT
    assert "token_usage" in out


def test_autonomous_progress_does_not_initialize_unused_tool_memory(monkeypatch):
    from src.graphs import chat_graph

    class MemoryMustNotRun:
        def store_tool_memory(self, **kwargs):
            raise AssertionError("autonomous progress initialized semantic memory")

    monkeypatch.setattr(chat_graph, "memory_manager", MemoryMustNotRun())
    state = {
        "messages": [
            AIMessage(content="", tool_calls=[
                {"id": "w1", "name": "write_file", "args": {
                    "path": "index.html", "content": "<!doctype html>"
                }},
            ]),
            ToolMessage(content="File written: index.html",
                        tool_call_id="w1", name="write_file"),
        ],
        "current_task": "build a website",
    }
    config = {"configurable": {
        "provider": "custom", "model": "sarvam-test", "thread_id": "auto-memory",
        "approval_policy": "workspace_session",
    }}

    out = chat_graph.progress_node(state, config)

    assert out["execution_trace"][0]["tool"] == "write_file"
    assert out["execution_trace"][0]["status"] == "success"
    assert "messages" not in out  # no generic autonomous reflection either


def test_d9_progress_node_failure_sets_recovery():
    from src.graphs.chat_graph import progress_node

    state = {
        "messages": [
            AIMessage(content="", tool_calls=[
                {"id": "t1", "name": "run_terminal", "args": {"command": "make"}},
            ]),
            ToolMessage(content="boom\nexit code: 1",
                        tool_call_id="t1", name="run_terminal"),
        ],
        "current_task": "build it",
    }
    out = progress_node(state, _cfg())
    assert out["recovery_mode"] is True
    assert out["recovery_command"] == "make"
    assert out["recovery_attempts"] == 1
    assert out["tool_failures"] == 1
    assert out["failed_steps"][0].startswith("Command failed: make")


def test_d9_progress_node_running_check_records_nothing():
    from src.graphs.chat_graph import progress_node

    state = {
        "messages": [
            AIMessage(content="", tool_calls=[
                {"id": "t1", "name": "check_terminal", "args": {"process_id": "p1"}},
            ]),
            ToolMessage(content="status: running",
                        tool_call_id="t1", name="check_terminal"),
        ],
        "current_task": "watch it",
    }
    out = progress_node(state, _cfg())
    assert out["execution_trace"] == []
    assert out["steps_completed"] == []
    assert out["failed_steps"] == []
    # A non-result must not create a phantom progress/reflection heartbeat.
    assert "messages" not in out


# ---------------------------------------------------------------------
# R3-1: identical-retry cap
# ---------------------------------------------------------------------

def test_r3_1_command_fingerprint_extracts_and_normalizes():
    assert ph.command_fingerprint("run_terminal", {"command": "  mkdir -p /tmp/x  "}) \
        == "mkdir -p /tmp/x"
    assert ph.command_fingerprint("execute_code", {"code": "  npm run build "}) \
        == "npm run build"
    assert ph.command_fingerprint("run_terminal", {"cmd": "path/to/script.ps1"}) \
        == "path/to/script.ps1"
    # missing command-like arg -> None (no retry-able identity)
    assert ph.command_fingerprint("run_terminal", {"path": "x"}) is None
    assert ph.command_fingerprint("run_terminal", {}) is None


def test_r3_1_identical_failure_injects_nudge_at_third_attempt():
    from src.graphs.chat_graph import progress_node

    def state(count):
        msgs = [
            AIMessage(content="", tool_calls=[
                {"id": f"t{i}", "name": "run_terminal",
                 "args": {"command": "mkdir -p /tmp/x"}} for i in range(count)
            ]),
        ]
        for i in range(count):
            msgs.append(
                ToolMessage(content="not recognized as an internal or external command\n"
                                    "exit code: 1",
                            tool_call_id=f"t{i}", name="run_terminal")
            )
        return {"messages": msgs, "current_task": "scaffold project"}

    # Second failure: count == 2, still no nudge.
    out2 = progress_node(state(2), _cfg())
    assert out2["command_retries"]["mkdir -p /tmp/x"] == 2
    assert not any("failed the same" in m.content for m in out2["messages"])

    # Third failure: the cap fires exactly once.
    out3 = progress_node(state(3), _cfg())
    assert out3["command_retries"]["mkdir -p /tmp/x"] == 3
    nudges3 = [m for m in out3["messages"]
               if "failed the same" in m.content]
    assert len(nudges3) == 1
    assert "run_terminal" in nudges3[0].content and "3 times" in nudges3[0].content


def test_r3_1_different_commands_do_not_share_a_retry_counter():
    from src.graphs.chat_graph import progress_node

    msgs = [
        AIMessage(content="", tool_calls=[
            {"id": "a", "name": "run_terminal", "args": {"command": "mkdir -p /x"}},
            {"id": "b", "name": "run_terminal", "args": {"command": "cd /x"}},
        ]),
        ToolMessage(content="boom\nexit code: 1",
                    tool_call_id="a", name="run_terminal"),
        ToolMessage(content="boom\nexit code: 1",
                    tool_call_id="b", name="run_terminal"),
    ]
    out = progress_node({"messages": msgs, "current_task": "t"}, _cfg())
    assert out["command_retries"] == {"mkdir -p /x": 1, "cd /x": 1}
    assert not any("failed the same" in m.content for m in out["messages"])


def test_r3_2_successful_identical_reads_trigger_no_progress_nudge():
    from src.graphs.chat_graph import progress_node

    def state(count):
        calls = [
            {"id": f"r{i}", "name": "list_files", "args": {"path": "."}}
            for i in range(count)
        ]
        msgs = [AIMessage(content="", tool_calls=calls)]
        msgs.extend(
            ToolMessage(content="_provided", tool_call_id=f"r{i}", name="list_files")
            for i in range(count)
        )
        return {"messages": msgs, "current_task": "integrate component"}

    out2 = progress_node(state(2), _cfg())
    assert not any("NO-PROGRESS GUARD" in m.content for m in out2["messages"])

    out3 = progress_node(state(3), _cfg())
    nudges = [m for m in out3["messages"] if "NO-PROGRESS GUARD" in m.content]
    assert len(nudges) == 1
    assert "list_files" in nudges[0].content and "3 times" in nudges[0].content


def test_r3_2_changed_read_result_does_not_share_counter():
    assert ph.read_fingerprint("list_files", {"path": "."}, "a") != \
        ph.read_fingerprint("list_files", {"path": "."}, "a\nb")
    assert ph.read_fingerprint("write_file", {"path": "x"}, "ok") is None


def test_r3_1_no_fingerprint_no_retry_tracking():
    from src.graphs.chat_graph import progress_node

    msgs = [
        AIMessage(content="", tool_calls=[
            {"id": "a", "name": "read_file", "args": {"path": "x.py"}},
        ]),
        ToolMessage(content="error: not found",
                    tool_call_id="a", name="read_file"),
    ]
    out = progress_node({"messages": msgs, "current_task": "t"}, _cfg())
    assert "command_retries" not in out
    assert len(out["failed_steps"]) == 1


# ---------------------------------------------------------------------------
# Hermes loop law (field 2026-09-05, "Ended incomplete: verify test2 folder"):
# the model ends its own turn; recovered tool errors never fail a turn.
# ---------------------------------------------------------------------------

def test_next_after_progress_plan_complete_gives_one_wrap_nudge():
    """Plan completion must NOT finalize underneath a live tool batch: the
    first hit routes to finish_gate (wrap nudge), the second (model kept
    tooling) to the bounded shortcut."""
    base = dict(
        recovery_mode=False, recovery_attempts=0, replan_needed=False,
        env_failures=0, pivot_count=0,
    )
    assert ph.next_after_progress(plan_complete=True, plan_wrap_nudges=0, **base) == "finish_gate"
    assert ph.next_after_progress(plan_complete=True, plan_wrap_nudges=1, **base) == "finalize"
    # plan not complete: unchanged
    assert ph.next_after_progress(plan_complete=False, plan_wrap_nudges=0, **base) == "ai"


def test_trailing_batch_failed_detects_unrecovered_failure():
    from langchain_core.messages import AIMessage, ToolMessage
    msgs = [
        AIMessage(content="working..."),
        ToolMessage(content="Error: npm install timed out", tool_call_id="t1", name="run_terminal"),
    ]
    assert ph.trailing_batch_failed(msgs) is True
    recovered = [
        ToolMessage(content="❌ read_file: no such file", tool_call_id="t1", name="read_file"),
        AIMessage(content="retrying"),
        ToolMessage(content="✅ Read file: app/page.tsx", tool_call_id="t2", name="read_file"),
    ]
    assert ph.trailing_batch_failed(recovered) is False
    assert ph.trailing_batch_failed([AIMessage(content="all done")]) is False
    assert ph.trailing_batch_failed([]) is False


def test_finish_gate_plan_wrap_branch_nudges_and_counts():
    """The plan-complete stop in finish_gate_node injects the wrap nudge and
    bumps its own bounded counter (not verify/finish budgets)."""
    from langchain_core.messages import AIMessage
    from src.graphs.gates import finish_gate_node
    state = {
        "messages": [AIMessage(content="x")],
        "steps_completed": ["Ran command successfully: ls"],
        "failed_steps": [],
        "current_task": "list the folders",
        "plan": [{"id": "1", "status": "completed", "description": "list"}],
        "verify_nudges": 0,
        "finish_nudges": 0,
        "plan_wrap_nudges": 0,
        "workspace": ".",
    }
    out = finish_gate_node(state)
    assert "final answer" in out["messages"][0].content
    assert out["plan_wrap_nudges"] == 1
