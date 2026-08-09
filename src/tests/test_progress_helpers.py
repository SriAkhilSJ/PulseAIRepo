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
    # generic markers on any other tool — matched at LINE STARTS only
    assert ph.classify_tool_outcome("read_file", "error: not found") == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome("read_file", "Traceback (most recent") == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome(
        "read_file", "unknown process id") == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome(
        "write_file", "path escapes workspace") == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome("read_file", "file contents here") == ph.OUTCOME_SUCCESS
    # regression (lab run 5): mid-line "error:" inside real content is DATA,
    # not a failed tool — `except ValueError:` and test names like
    # test_divide_by_zero_raises_value_error: previously false-positived and
    # burned recovery attempts on successful reads/think calls.
    assert ph.classify_tool_outcome(
        "read_file",
        'def test_x():\n'
        '    try:\n'
        '        calc.divide(1, 0)\n'
        '    except ValueError:\n'
        '        return\n'
        '    raise AssertionError("boom")\n',
    ) == ph.OUTCOME_SUCCESS
    assert ph.classify_tool_outcome(
        "think",
        "The bug: test_divide_by_zero_raises_value_error: divide does not check "
        "b == 0.\nFix: raise ValueError.",
    ) == ph.OUTCOME_SUCCESS
    # a genuine langchain ToolNode error still opens a line and must be FAILED
    assert ph.classify_tool_outcome(
        "read_file", "Error: File not found: calc.py") == ph.OUTCOME_FAILED
    assert ph.classify_tool_outcome(
        "read_file", "ok line\nTraceback (most recent call last):\n  File \"a.py\"") == ph.OUTCOME_FAILED


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
    assert up == {"tool_failures_inc": 1, "recovery_attempts_inc": 1,
                  "recovery_mode": True, "recovery_command": "make",
                  "env_failure": False}

    # already in recovery: command slot NOT stolen
    f, up = ph.build_failure("run_terminal", "x", {"command": "make2"},
                             True, "make")
    assert up["recovery_command"] == "make"
    assert up["recovery_attempts_inc"] == 1
    assert up["env_failure"] is False

    # environment-level failure (missing binary / PATH shim): flagged
    f, up = ph.build_failure(
        "run_terminal",
        "'create-vite' is not recognized as an internal or external command",
        {"command": "npx create-vite ."}, False, None)
    assert up["env_failure"] is True

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


# ---------------------------------------------------------------------
# strategy pivot (lab run 10: env-level failures must pivot, not retry)
# ---------------------------------------------------------------------

def test_env_failure_classifier():
    assert ph.classify_env_failure(
        "'create-vite' is not recognized as an internal or external command"
    ) is True
    assert ph.classify_env_failure(
        "'create-react-app' is not recognized as an internal or external command"
    ) is True
    assert ph.classify_env_failure(
        "npm notice run create-vite . --template react-ts"
    ) is False  # npm's own notice is data, not the env failure
    assert ph.classify_env_failure("command not found: docker") is True
    assert ph.classify_env_failure("bash: ls: No such file or directory") is True
    assert ph.classify_env_failure("permission denied: /root/x") is True
    # ordinary failures are NOT environment-level
    assert ph.classify_env_failure(
        "Traceback (most recent call last):\n  File \"a.py\""
    ) is False
    assert ph.classify_env_failure("boom\nexit code: 1") is False
    assert ph.classify_env_failure(
        "npx: error: unknown option '--template'"
    ) is False
    assert ph.classify_env_failure("make: *** No rule to make target 'x'") is False


def test_next_after_progress_routing_matrix():
    # recovery budget exhausted + env failures + pivots left -> pivot
    assert ph.next_after_progress(True, 3, False, False, 2, 0) == "pivot"
    assert ph.next_after_progress(True, 3, False, False, 2, 1) == "pivot"
    # pivot budget exhausted -> recovery_limit (bounded, never infinite)
    assert ph.next_after_progress(True, 3, False, False, 2, 2) == "recovery_limit"
    assert ph.next_after_progress(True, 3, False, False, 2, 9) == "recovery_limit"
    # env failures below threshold -> old recovery_limit behavior
    assert ph.next_after_progress(True, 3, False, False, 0, 0) == "recovery_limit"
    assert ph.next_after_progress(True, 3, False, False, 1, 0) == "recovery_limit"
    # below the attempt budget: normal flow wins
    assert ph.next_after_progress(True, 2, False, False, 2, 0) == "ai"
    assert ph.next_after_progress(True, 2, True, False, 0, 0) == "replanner"
    assert ph.next_after_progress(False, 0, True, False, 0, 0) == "replanner"
    assert ph.next_after_progress(False, 0, False, True, 0, 0) == "finalize"
    assert ph.next_after_progress(False, 0, False, False, 0, 0) == "ai"


def test_progress_node_env_failure_counts_and_skips_replan(monkeypatch):
    from src.graphs.chat_graph import progress_node

    # A replan consult must NOT happen for env-level failures.
    def _should_not_be_called(*args, **kwargs):
        raise AssertionError("replan consulted on an environment-level failure")

    monkeypatch.setattr(ph, "maybe_replan", _should_not_be_called)

    state = {
        "messages": [
            AIMessage(content="", tool_calls=[
                {"id": "t1", "name": "run_terminal",
                 "args": {"command": "npx create-vite . --template react-ts"}},
            ]),
            ToolMessage(
                content=(
                    "STDERR:\n'create-vite' is not recognized as an internal "
                    "or external command\n\nExit code: 1"
                ),
                tool_call_id="t1", name="run_terminal"),
        ],
        "current_task": "build app",
        "plan": [{"id": 1, "description": "scaffold", "status": "in_progress"}],
    }
    out = progress_node(state, _cfg())
    assert out["env_failures"] == 1
    assert out["replan_needed"] is False
    assert out["recovery_mode"] is True
    assert out["recovery_attempts"] == 1


def test_progress_node_regular_failure_still_consults_replan(monkeypatch):
    from src.graphs.chat_graph import progress_node
    from src.context.token_tracker import TokenUsage

    called = {}

    def _fake_replan(task, plan, failure, provider, model):
        called["hit"] = True
        return True, [TokenUsage()]  # non-empty usages: node adopts on usages

    monkeypatch.setattr(ph, "maybe_replan", _fake_replan)

    state = {
        "messages": [
            AIMessage(content="", tool_calls=[
                {"id": "t1", "name": "run_terminal", "args": {"command": "python x.py"}},
            ]),
            ToolMessage(content="Traceback (most recent call last):\nboom\nexit code: 1",
                        tool_call_id="t1", name="run_terminal"),
        ],
        "current_task": "run it",
        "plan": [{"id": 1, "description": "run", "status": "in_progress"}],
    }
    out = progress_node(state, _cfg())
    assert called.get("hit") is True
    assert out["replan_needed"] is True
    assert out["env_failures"] == 0


def test_d9_maybe_replan(monkeypatch):
    needed, usages = ph.maybe_replan("t", [], "f", "p", "m")
    assert needed is False and usages == []

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
    # ...but the reflection message still fires (a tool message DID arrive)
    assert isinstance(out["messages"][0], SystemMessage)
