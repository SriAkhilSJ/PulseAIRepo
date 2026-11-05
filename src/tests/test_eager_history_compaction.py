"""
Tests for Phase 9.2.2.5.1: Eager Deterministic Conversation History Compaction.
Covers Stages 1-10:
1. Three-round verbatim retention.
2. Older successful terminal receipt transformation.
3. Successful test-result compaction.
4. Low-information command classification.
5. Meaningful successful output preservation.
6. Older file-read receipt generation.
7. Historical file content protection.
8. Directory listing compaction.
9. Search result preservation.
10. Unresolved traceback retention.
11. Failure resolution detection.
12. Unrelated success not clearing failure.
13. Assistant tool-call argument compaction.
14. Multiple ToolMessage pairing.
15. Partial tool batch preservation.
16. Active unfinished tool-call protection.
17. Persistent checkpoint immutability.
18. Historical anchor digest generation.
19. Prompt-cache stable-prefix preservation.
20. Hard-budget fallback integration.
21. Deterministic receipt generation.
22. Repeated compaction idempotency.
"""

import copy
import os
import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from src.context.compaction import (
    compact_assistant_tool_call_arguments,
    compact_file_mutation_arguments,
    extract_test_metrics,
    generate_historical_anchor_digest,
    is_low_information_command,
    transform_completed_tool_receipts,
    HistoryCompactor,
)
from src.context.history_shaper import HistoryShaper
from src.context.summarizer import SmartSummarizer


def _make_round(call_id: str, tool_name: str, args: dict, result_content: str, ai_response: str = "Proceeding."):
    """Helper to generate a completed interaction round."""
    ai_call = AIMessage(
        content="",
        tool_calls=[{"name": tool_name, "args": args, "id": call_id}],
    )
    tool_msg = ToolMessage(
        content=result_content,
        tool_call_id=call_id,
        name=tool_name,
    )
    ai_resp = AIMessage(content=ai_response)
    return [ai_call, tool_msg, ai_resp]


def test_three_round_verbatim_retention():
    """1. Three-round verbatim retention: newest 3 completed rounds remain verbatim."""
    msgs = [HumanMessage(content="Initialize repo")]
    msgs.extend(_make_round("c1", "run_terminal", {"command": "mkdir src"}, "Exit code: 0\nCreated directory"))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "mkdir tests"}, "Exit code: 0\nCreated directory"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "mkdir docs"}, "Exit code: 0\nCreated directory"))

    # With exactly 3 completed rounds, all 3 rounds are kept verbatim
    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    assert compacted == msgs
    for m in compacted:
        if isinstance(m, ToolMessage):
            assert "Exit code: 0" in m.content
            assert "[Execution Receipt]" not in m.content


def test_older_successful_terminal_receipt():
    """2. Older successful terminal receipt transformation."""
    msgs = [HumanMessage(content="Setup and build")]
    msgs.extend(_make_round("c1", "run_terminal", {"command": "mkdir build"}, "Exit code: 0\nDirectory build created successfully"))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "cd build"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "touch CMakeLists.txt"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo done"}, "Exit code: 0"))

    # c1 is older than the 3 most recent rounds (c2, c3, c4) -> transformed into receipt
    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    c1_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
    assert "[Execution Receipt]" in c1_msg.content
    assert "Command: mkdir build" in c1_msg.content
    assert "Exit code: 0" in c1_msg.content
    assert "Status: Success" in c1_msg.content

    # c2, c3, c4 remain verbatim
    c2_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c2"][0]
    assert c2_msg.content == "Exit code: 0"


def test_successful_test_result_compaction():
    """3. Successful test-result compaction: pytest outputs transformed into structured test receipts."""
    raw_pytest = (
        "============================= test session starts =============================\n"
        "collected 45 items\n"
        "src/tests/test_a.py ......................... [ 55%]\n"
        "src/tests/test_b.py ....................     [100%]\n"
        "============================== 45 passed in 2.34s ==============================\n"
        "Exit code: 0"
    )
    msgs = [HumanMessage(content="Run test suite")]
    msgs.extend(_make_round("c1", "run_terminal", {"command": "pytest src/tests"}, raw_pytest))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    c1_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
    assert "[Test Receipt]" in c1_msg.content
    assert "Framework: pytest" in c1_msg.content
    assert "Passed: 45" in c1_msg.content
    assert "Failed: 0" in c1_msg.content
    assert "Exit code: 0" in c1_msg.content


def test_low_information_command_classification():
    """4. Low-information command classification: mkdir, cd, pwd, touch, rm, echo classified as low info."""
    assert is_low_information_command("mkdir src/utils")
    assert is_low_information_command("cd ..")
    assert is_low_information_command("pwd")
    assert is_low_information_command("touch .env")
    assert is_low_information_command("rm -rf temp")
    assert is_low_information_command("echo hello")
    assert is_low_information_command("cmd.exe /c mkdir dist")
    assert not is_low_information_command("pytest src/tests")
    assert not is_low_information_command("python train.py --epochs 10")
    assert not is_low_information_command("git status")


def test_meaningful_successful_output_preservation():
    """5. Meaningful successful output preservation: git status or warnings retain structural evidence."""
    git_output = "On branch main\nChanges not staged for commit:\n  modified:   src/app.py\n  modified:   src/utils.py\nExit code: 0"
    msgs = [HumanMessage(content="Check git status")]
    msgs.extend(_make_round("c1", "run_terminal", {"command": "git status"}, git_output))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    c1_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
    assert "[Git Status Receipt]" in c1_msg.content
    assert "Status: Modified files present" in c1_msg.content


def test_older_file_read_receipt_generation():
    """6. Older file-read receipt generation."""
    code = "import os\nimport sys\n\ndef run():\n    print('Hello World')\n\nif __name__ == '__main__':\n    run()\n"
    msgs = [HumanMessage(content="Inspect app code")]
    msgs.extend(_make_round("c1", "read_file", {"path": "src/app.py"}, code))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    c1_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
    assert "[File Read Receipt]" in c1_msg.content
    assert "Path: src/app.py" in c1_msg.content
    assert "Original lines: 8" in c1_msg.content
    assert "Status: Resident in workspace" in c1_msg.content


def test_historical_file_content_protection():
    """7. Historical file content protection: superseded status when modified later."""
    read_code = "def add(a, b):\n    return a - b\n"
    msgs = [HumanMessage(content="Fix calculator")]
    msgs.extend(_make_round("c1", "read_file", {"path": "src/calc.py"}, read_code))
    msgs.extend(_make_round("c2", "write_file", {"path": "src/calc.py", "content": "def add(a, b):\n    return a + b\n"}, "File written successfully"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c5", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    c1_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
    assert "[File Read Receipt]" in c1_msg.content
    assert "Status: Superseded by subsequent modification" in c1_msg.content


def test_directory_listing_compaction():
    """8. Directory listing compaction: list_files reduced to entry count."""
    files_list = "file1.txt\nfile2.txt\nfile3.txt\nsub/\n"
    msgs = [HumanMessage(content="List root")]
    msgs.extend(_make_round("c1", "list_files", {"path": "src/"}, files_list))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    c1_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
    assert "[Directory Listing Receipt]" in c1_msg.content
    assert "Path: src/" in c1_msg.content
    assert "Entries: 4" in c1_msg.content


def test_search_result_preservation():
    """9. Search result preservation: query, match count, and matched files preserved."""
    search_output = "src/auth.py:42: def authenticate(user, password):\nsrc/login.py:10: auth = authenticate(u, p)\n"
    msgs = [HumanMessage(content="Find auth function")]
    msgs.extend(_make_round("c1", "search_files", {"query": "authenticate"}, search_output))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    c1_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
    assert "[Search Receipt]" in c1_msg.content
    assert "Query: authenticate" in c1_msg.content
    assert "Matches: 2" in c1_msg.content
    assert "src/auth.py" in c1_msg.content


def test_unresolved_traceback_retention():
    """10. Unresolved traceback retention: failed command without subsequent resolution remains verbatim."""
    tb = "Traceback (most recent call last):\n  File 'app.py', line 12, in <module>\nAssertionError: Expected 200, got 500\nExit code: 1"
    msgs = [HumanMessage(content="Debug test")]
    msgs.extend(_make_round("c1", "run_terminal", {"command": "python app.py"}, tb))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    c1_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
    # UNRESOLVED: Must NOT be compacted to generic receipt!
    assert "Traceback (most recent call last):" in c1_msg.content
    assert "AssertionError: Expected 200, got 500" in c1_msg.content
    assert "[Resolved Failure Receipt]" not in c1_msg.content


def test_failure_resolution_detection():
    """11. Failure resolution detection: failure followed by matching successful run becomes resolved receipt."""
    fail_output = "Traceback (most recent call last):\nAssertionError: Failed\nExit code: 1"
    pass_output = "=== 1 passed in 0.1s ===\nExit code: 0"
    msgs = [HumanMessage(content="Fix test")]
    msgs.extend(_make_round("c1", "run_terminal", {"command": "pytest tests/test_api.py"}, fail_output))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))
    msgs.extend(_make_round("c5", "run_terminal", {"command": "pytest tests/test_api.py"}, pass_output))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    c1_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
    assert "[Resolved Failure Receipt]" in c1_msg.content
    assert "Original exit: 1" in c1_msg.content
    assert "Resolution: Resolved by subsequent execution" in c1_msg.content


def test_unrelated_success_not_clearing_failure():
    """12. Unrelated success not clearing failure: unrelated command success does not clear test failure."""
    fail_tb = "Traceback (most recent call last):\nRuntimeError: DB connection timed out\nExit code: 1"
    msgs = [HumanMessage(content="Investigate crash")]
    msgs.extend(_make_round("c1", "run_terminal", {"command": "python test_db.py"}, fail_tb))
    # Unrelated commands that succeed
    msgs.extend(_make_round("c2", "run_terminal", {"command": "mkdir logs"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "git status"}, "Exit code: 0\nclean"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo done"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    c1_msg = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c1"][0]
    # Unrelated commands must NOT resolve c1!
    assert "RuntimeError: DB connection timed out" in c1_msg.content
    assert "[Resolved Failure Receipt]" not in c1_msg.content


def test_assistant_tool_call_argument_compaction():
    """13. Assistant tool-call argument compaction: large write_file payloads omitted in older turns."""
    huge_code = "x = 1\n" * 100  # 600 chars
    msgs = [HumanMessage(content="Write large module")]
    msgs.extend(_make_round("c1", "write_file", {"path": "src/huge.py", "content": huge_code}, "File written"))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = compact_assistant_tool_call_arguments(msgs, keep_recent=3)
    c1_ai = [m for m in compacted if isinstance(m, AIMessage) and getattr(m, "tool_calls", None) and m.tool_calls[0]["id"] == "c1"][0]
    arg_content = c1_ai.tool_calls[0]["args"]["content"]
    assert "[Persisted file payload omitted" in arg_content
    assert "read workspace for current content" in arg_content
    assert c1_ai.tool_calls[0]["args"]["path"] == "src/huge.py"
    assert c1_ai.tool_calls[0]["id"] == "c1"


def test_multiple_tool_message_pairing():
    """14. Multiple ToolMessage pairing: batched calls maintain exact matching tool_call_ids."""
    batch_ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "run_terminal", "args": {"command": "mkdir a"}, "id": "call_a"},
            {"name": "run_terminal", "args": {"command": "mkdir b"}, "id": "call_b"},
        ]
    )
    t_a = ToolMessage(content="Exit code: 0", tool_call_id="call_a", name="run_terminal")
    t_b = ToolMessage(content="Exit code: 0", tool_call_id="call_b", name="run_terminal")
    ai_after = AIMessage(content="Batch finished.")

    msgs = [HumanMessage(content="Batch creation")]
    msgs.extend([batch_ai, t_a, t_b, ai_after])
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    t_a_comp = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "call_a"][0]
    t_b_comp = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "call_b"][0]
    assert "[Execution Receipt]" in t_a_comp.content
    assert "[Execution Receipt]" in t_b_comp.content
    assert t_a_comp.tool_call_id == "call_a"
    assert t_b_comp.tool_call_id == "call_b"


def test_partial_tool_batch_preservation():
    """15. Partial tool batch preservation: success becomes receipt, failure remains verbatim in same batch."""
    batch_ai = AIMessage(
        content="",
        tool_calls=[
            {"name": "run_terminal", "args": {"command": "mkdir good"}, "id": "c_good"},
            {"name": "run_terminal", "args": {"command": "python bad.py"}, "id": "c_bad"},
        ]
    )
    t_good = ToolMessage(content="Exit code: 0", tool_call_id="c_good", name="run_terminal")
    t_bad = ToolMessage(content="Traceback (most recent call last):\nTypeError: NoneType\nExit code: 1", tool_call_id="c_bad", name="run_terminal")
    ai_after = AIMessage(content="Batch finished with partial error.")

    msgs = [HumanMessage(content="Run batch")]
    msgs.extend([batch_ai, t_good, t_bad, ai_after])
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    t_good_comp = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c_good"][0]
    t_bad_comp = [m for m in compacted if isinstance(m, ToolMessage) and m.tool_call_id == "c_bad"][0]

    assert "[Execution Receipt]" in t_good_comp.content
    assert "TypeError: NoneType" in t_bad_comp.content
    assert "[Resolved Failure Receipt]" not in t_bad_comp.content


def test_active_unfinished_tool_call_protection():
    """16. Active unfinished tool-call protection: pending execution is never compacted."""
    active_ai = AIMessage(
        content="",
        tool_calls=[{"name": "run_terminal", "args": {"command": "long_task"}, "id": "c_active"}]
    )
    # No ToolMessage yet
    msgs = [HumanMessage(content="Start long task"), active_ai]
    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    assert compacted == msgs


def test_persistent_checkpoint_immutability():
    """17. Persistent checkpoint immutability: original message list and message objects are not mutated."""
    orig_output = "Exit code: 0\nSuper long verbose log..."
    t_msg = ToolMessage(content=orig_output, tool_call_id="c1", name="run_terminal")
    msgs = [HumanMessage(content="Task")]
    msgs.extend([
        AIMessage(content="", tool_calls=[{"name": "run_terminal", "args": {"command": "mkdir test"}, "id": "c1"}]),
        t_msg,
        AIMessage(content="Next 1")
    ])
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    # The original ToolMessage object content MUST remain unchanged!
    assert t_msg.content == orig_output
    # The projected list has the receipt
    assert "[Execution Receipt]" in compacted[2].content
    assert compacted[2] is not t_msg


def test_historical_anchor_digest_generation():
    """18. Historical anchor digest generation: extracts objective, files modified, tests passed."""
    msgs = [
        HumanMessage(content="Implement user authentication module"),
        AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "src/auth.py", "content": "pass"}, "id": "c1"}]),
        ToolMessage(content="File written", tool_call_id="c1", name="write_file"),
        AIMessage(content="Created auth file."),
        AIMessage(content="", tool_calls=[{"name": "run_terminal", "args": {"command": "pytest tests/test_auth.py"}, "id": "c2"}]),
        ToolMessage(content="=== 12 passed in 0.4s ===\nExit code: 0", tool_call_id="c2", name="run_terminal"),
        AIMessage(content="Tests passed."),
    ]
    digest = generate_historical_anchor_digest(msgs)
    assert "## Historical Anchor Digest" in digest
    assert "Implement user authentication module" in digest
    assert "src/auth.py" in digest
    assert "pytest tests passed (12)" in digest
    assert "Open Issues" in digest and "None" in digest


def test_prompt_cache_stable_prefix_preservation():
    """19. Prompt-cache stable-prefix preservation: system prompt unchanged, receipts byte-stable."""
    sys_msg = SystemMessage(content="You are CrusorAI. Mandatory policy: execute safely.")
    msgs = [sys_msg, HumanMessage(content="Task")]
    msgs.extend(_make_round("c1", "run_terminal", {"command": "mkdir a"}, "Exit code: 0"))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    compacted = transform_completed_tool_receipts(msgs, keep_recent=3)
    # System message at index 0 is 100% untouched
    assert compacted[0] == sys_msg
    assert compacted[0].content == sys_msg.content


def test_hard_budget_fallback_integration():
    """20. Hard-budget fallback integration: budget limits still enforced if history exceeds threshold."""
    shaper = HistoryShaper(
        model=lambda: "claude-3-5-sonnet-20241022",
        allow_embedding_compute=lambda: False,
        summarizer=SmartSummarizer(),
        current_task=lambda: "Task",
        session_id=lambda: "test_session",
        context_window=lambda: 200_000,
    )
    # Create history with multiple rounds
    msgs = [HumanMessage(content="Long conversation")]
    for i in range(10):
        msgs.extend(_make_round(f"c{i}", "run_terminal", {"command": f"echo {i}"}, f"Exit code: 0\nOutput {i}"))

    # Compact with tight budget
    tight_budget = 300
    res = shaper.compact(msgs, tight_budget)
    assert len(res) > 0
    # Must preserve user message
    assert any(isinstance(m, HumanMessage) for m in res)


def test_deterministic_receipt_generation():
    """21. Deterministic receipt generation: identical runs produce identical output byte-for-byte."""
    msgs = [HumanMessage(content="Task")]
    msgs.extend(_make_round("c1", "run_terminal", {"command": "pytest src/tests"}, "=== 10 passed in 1.2s ===\nExit code: 0"))
    msgs.extend(_make_round("c2", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    run1 = transform_completed_tool_receipts(copy.deepcopy(msgs), keep_recent=3)
    run2 = transform_completed_tool_receipts(copy.deepcopy(msgs), keep_recent=3)

    assert len(run1) == len(run2)
    for m1, m2 in zip(run1, run2):
        assert m1.content == m2.content
        assert getattr(m1, "tool_call_id", None) == getattr(m2, "tool_call_id", None)


def test_repeated_compaction_idempotency():
    """22. Repeated compaction idempotency: compacting already compacted history is a strict no-op."""
    msgs = [HumanMessage(content="Task")]
    msgs.extend(_make_round("c1", "run_terminal", {"command": "mkdir src"}, "Exit code: 0\nCreated"))
    msgs.extend(_make_round("c2", "read_file", {"path": "src/app.py"}, "import sys\nprint(1)\n"))
    msgs.extend(_make_round("c3", "run_terminal", {"command": "echo 1"}, "Exit code: 0"))
    msgs.extend(_make_round("c4", "run_terminal", {"command": "echo 2"}, "Exit code: 0"))
    msgs.extend(_make_round("c5", "run_terminal", {"command": "echo 3"}, "Exit code: 0"))

    first_pass = transform_completed_tool_receipts(msgs, keep_recent=3)
    second_pass = transform_completed_tool_receipts(first_pass, keep_recent=3)

    assert len(first_pass) == len(second_pass)
    for m1, m2 in zip(first_pass, second_pass):
        assert m1.content == m2.content
        assert getattr(m1, "tool_call_id", None) == getattr(m2, "tool_call_id", None)
