"""Hermes task + ask tool pipeline (todo_list, clarify) — ports with receipts.

Upstream sources (read fully before writing):
- tools/todo_tool.py: one revisioned session store, ONE tool (pass ``todos``
  to write / merge by id / omit to read), full list + revision + counts back,
  active-only re-injection (format_for_injection), hermes caps (4000 chars,
  256 items), subtask parents sanitized, in_progress lifted ahead of pending.
- tools/clarify_tool.py: batch of 1-5 questions, <=4 choices with the
  recommended option FIRST marked "(Recommended)" (presentation stripped from
  the stored answer), multi_select, the canonical timeout sentinel, and a
  result of {responses:[...]} in question order (+ timed_out only when true).
"""

import json
import threading

from src.dashboard.event_bus import clarify_queue
from src.tools.clarify_tool import (
    RECOMMENDED_LABEL,
    TIMEOUT_RESPONSE,
    clarify_tool,
    mark_recommended,
    strip_recommended,
)
from src.tools.todo_tool import (
    MAX_TODO_ITEMS,
    TODO_INJECTION_HEADER,
    TodoStore,
    inject_active_todos,
    todo_tool,
)


# ── todo_list: the hermes task tool ──────────────────────────────────────────

def test_todo_store_write_read_and_revision_bump():
    store = TodoStore()
    items = store.write([{"id": "1", "content": "scaffold", "status": "in_progress"}])
    assert store.snapshot()["revision"] == 1
    assert items[0]["status"] == "in_progress"
    # A no-op write must NOT bump the revision (UI clients reject stale updates
    # on the monotonic revision, so noise revisions break that reconciliation).
    store.write(items)
    assert store.snapshot()["revision"] == 1


def test_todo_store_merge_patches_only_given_fields():
    store = TodoStore()
    store.write([
        {"id": "1", "content": "scaffold", "status": "pending"},
        {"id": "2", "content": "test", "status": "pending"},
    ])
    merged = store.write([{"id": "1", "status": "completed"}], merge=True)
    by_id = {item["id"]: item for item in merged}
    assert by_id["1"]["status"] == "completed"
    assert by_id["1"]["content"] == "scaffold", "merge must not touch absent fields"
    assert by_id["2"]["status"] == "pending"


def test_todo_store_caps_and_normalize_order():
    store = TodoStore()
    items = store.write([
        {"id": "a", "content": "pending first", "status": "pending"},
        {"id": "b", "content": "the active one", "status": "in_progress"},
    ])
    assert items[0]["id"] == "b", "in_progress lifts ahead of earlier pending"
    flood = [{"id": str(i), "content": "x" * 20, "status": "pending"} for i in range(MAX_TODO_ITEMS + 10)]
    assert len(store.write(flood)) == MAX_TODO_ITEMS


def test_todo_store_parent_sanitizing():
    store = TodoStore()
    items = store.write([
        {"id": "1", "content": "parent", "status": "pending"},
        {"id": "2", "content": "sub", "status": "pending", "parent": "missing"},
        {"id": "3", "content": "loop a", "status": "pending", "parent": "4"},
        {"id": "4", "content": "loop b", "status": "pending", "parent": "3"},
    ])
    parents = {item["id"]: item.get("parent") for item in items}
    assert parents["2"] is None, "dangling parent ref becomes a root"
    # The 3<->4 cycle breaks the same way hermes' walk does: one item keeps a
    # parent edge into the other, which has become a root — the GRAPH is a
    # forest again (no item is reachable from itself), which is the invariant.
    assert parents["3"] is None
    assert parents["4"] == "3"


def test_injection_keeps_only_active_items():
    store = TodoStore()
    assert store.format_for_injection() is None
    store.write([
        {"id": "1", "content": "done deal", "status": "completed"},
        {"id": "2", "content": "the live one", "status": "in_progress"},
        {"id": "3", "content": "queued behind", "status": "pending"},
    ])
    block = store.format_for_injection()
    assert block and block.startswith(TODO_INJECTION_HEADER)
    assert "the live one" in block and "queued behind" in block
    assert "done deal" not in block, "finished items make the model re-do work"


def test_todo_tool_end_to_end_via_registry_shape():
    result = json.loads(todo_tool(todos=[{"id": "1", "content": "x", "status": "pending"}], store=TodoStore()))
    assert set(result) == {"todos", "revision", "summary"}
    assert result["summary"]["pending"] == 1
    read = json.loads(todo_tool(todos=None, store=result and TodoStore()))
    assert read["todos"] == []


def test_tool_invoke_roundtrip_and_event(tmp_path):
    from src.tools.todo_tool import todo_list
    result = json.loads(todo_list.invoke(
        {"todos": [{"id": "1", "content": "ship", "status": "in_progress"}]},
        config={"configurable": {"thread_id": "evt-t1"}},
    ))
    assert result["revision"] == 1
    assert inject_active_todos("evt-t1") is not None


# ── clarify: the hermes ask tool ─────────────────────────────────────────────

def test_mark_recommended_is_first_choice_and_idempotent():
    once = mark_recommended(["FastAPI", "Flask"])
    assert once[0] == f"FastAPI {RECOMMENDED_LABEL}"
    assert mark_recommended(once) == once, "idempotent"
    assert mark_recommended(["Only"]) == ["Only"], "a lone choice has nothing to prefer"
    assert strip_recommended(f"FastAPI {RECOMMENDED_LABEL}") == "FastAPI"


def test_clarify_batch_result_shape_and_recommendation_strip():
    questions = [{
        "question": "Which framework?",
        "choices": ["FastAPI", "Flask"],
        "multi_select": False,
    }]
    answers = {}

    def callback(question, choices, multi_select, questions=None):
        # Batch-capable callbacks get the WHOLE normalized list once; the
        # decorated choices ride the entries (recommended already marked).
        assert questions and questions[0]["choices"][0].endswith(RECOMMENDED_LABEL)
        answers["shown"] = questions[0]["choices"]
        return json.dumps({"answers": {"q0": questions[0]["choices"][0]}})

    result = json.loads(clarify_tool(questions=questions, callback=callback))
    assert result["responses"][0]["user_response"] == "FastAPI", (
        "the (Recommended) label is presentation only — never stored"
    )
    assert result["responses"][0]["choices_offered"] == ["FastAPI", "Flask"]
    assert "timed_out" not in result


def test_clarify_timeout_returns_canonical_sentinel_flag():
    questions = [{"question": "Pick", "choices": ["A", "B"]}]

    def callback(question, choices, multi_select, questions=None):
        return TIMEOUT_RESPONSE  # the canonical walk-away text

    result = json.loads(clarify_tool(questions=questions, callback=callback))
    assert result["timed_out"] is True
    assert result["responses"][0]["user_response"] == ""


def test_clarify_validation_errors():
    assert "error" in json.loads(clarify_tool(questions="nope", callback=lambda *a, **k: ""))
    assert "error" in json.loads(clarify_tool(questions=[], callback=None))
    assert "error" in json.loads(clarify_tool(callback=lambda *a, **k: ""))
    assert "error" in json.loads(clarify_tool(questions=[{"choices": [1, 2]}], callback=lambda *a, **k: ""))


def test_clarify_queue_roundtrip_and_session_isolation():
    item = clarify_queue.request("req-1", [{"qid": "q0", "question": "Q?"}], session_id="s1")
    assert item["status"] == "pending"
    assert clarify_queue.resolve("req-1", {}, session_id="other") is False, (
        "another session must not resolve a clarify it does not own"
    )
    assert clarify_queue.resolve("req-1", {"q0": "yes"}, session_id="s1") is True
    assert clarify_queue.get_pending("s1") == []


def test_clarify_queue_timeout_marks_walk_away():
    item = clarify_queue.request("req-2", [{"qid": "q0", "question": "Q?"}], session_id="s2")
    decision = clarify_queue.wait_for_answers("req-2", timeout=0.05)
    assert decision is not None and decision["timed_out"] is True
    assert clarify_queue.get_pending("s2") == []


def test_clarify_tool_invoke_blocks_until_reply():
    from src.tools.clarify_tool import clarify

    def answerer():
        for _ in range(100):
            pending = clarify_queue.get_pending("invoke-t")
            if pending:
                clarify_queue.resolve(pending[0]["id"], {"q0": "B"}, session_id="invoke-t")
                return
            threading.Event().wait(0.05)
        raise AssertionError("clarify request never landed")

    thread = threading.Thread(target=answerer, daemon=True)
    thread.start()
    out = json.loads(clarify.invoke(
        {"questions": [{"question": "A or B?", "choices": ["A", "B"]}]},
        config={"configurable": {"thread_id": "invoke-t"}},
    ))
    thread.join(timeout=5)
    assert out["responses"][0]["user_response"] == "B"
