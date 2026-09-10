"""The todo_list args-schema boundary delivers DICTS to the store.

Field 2026-09-10 (engine cfa4d421, owner screenshot): the model's four
well-formed todo items — every one carrying id, content, status — rendered
as four "(invalid item)" rows. Cause: with ``args_schema=_TodoListArgs``,
LangChain hands the tool validated ``_TodoItem`` MODEL OBJECTS, and
``TodoStore._validate`` (isinstance dict) condemned every one of them.
hermes' provider layer delivers plain dicts; the boundary below restores
that wire shape. Reproduced live through ``todo_list.invoke`` before the
fix: four "(invalid item)" rows, byte-identical to the owner's card.
"""
import json

from langchain_core.runnables import RunnableConfig
from pydantic import ValidationError

from src.tools.todo_tool import _TodoItem, _TodoListArgs, todo_list, todo_stores

OWNER_ITEMS = [
    {"id": "inspect", "content": "Inspect project structure and Base UI API compatibility",
     "status": "in_progress"},
    {"id": "integrate", "content": "Add card, integration component, and demo route",
     "status": "pending"},
    {"id": "verify-code", "content": "Run typecheck/build and fix integration issues",
     "status": "pending"},
    {"id": "verify-ui", "content": "Run browser verification and capture screenshot",
     "status": "pending"},
]


def _invoke(todos, thread="boundary-test"):
    return todo_list.invoke({"todos": todos}, {"configurable": {"thread_id": thread}})


def test_owner_field_call_yields_real_rows_through_the_schema_boundary():
    out = _invoke(OWNER_ITEMS)
    payload = json.loads(out)
    rows = payload["todos"]
    assert [r["id"] for r in rows] == ["inspect", "integrate", "verify-code", "verify-ui"]
    assert all(r["content"] and r["content"] != "(invalid item)" for r in rows)
    assert rows[0]["status"] == "in_progress"
    todo_stores.clear("boundary-test")


def test_ui_event_carries_the_real_rows():
    from src.dashboard.event_bus import event_bus

    q = event_bus.subscribe("boundary-event")
    try:
        _invoke(OWNER_ITEMS[:1], thread="boundary-event")
        seen = q.get(timeout=5)
    finally:
        event_bus.unsubscribe(q)
    assert seen["type"] == "todo.updated", seen
    rows = seen["payload"]["todos"]
    assert rows and rows[0]["content"] == OWNER_ITEMS[0]["content"]
    assert rows[0]["id"] == "inspect"
    todo_stores.clear("boundary-event")


def test_schema_still_rejects_id_only_items():
    """Layer-20's prevention is untouched: missing required fields die at the
    schema (hermes TODO_SCHEMA), not as placeholder rows."""
    with __import__("pytest").raises(ValidationError):
        _TodoListArgs(todos=[{"id": "only"}])


def test_store_still_rejects_true_garbage():
    """The '(invalid item)' placeholder stays for genuinely non-item junk
    (the store's own law) — the boundary fix must not weaken it."""
    from src.tools.todo_tool import todo_tool

    out = todo_tool(todos=["just a string"], session_id="boundary-garbage")
    rows = json.loads(out)["todos"]
    assert rows == [{"id": "?", "content": "(invalid item)", "status": "pending"}]
    todo_stores.clear("boundary-garbage")


def test_validate_accepts_a_model_directly():
    """Defense in depth: _validate dumps a pydantic item instead of
    condemning it."""
    from src.tools.todo_tool import TodoStore

    row = TodoStore._validate(_TodoItem(id="a", content="b", status="pending"))
    assert row == {"id": "a", "content": "b", "status": "pending"}
