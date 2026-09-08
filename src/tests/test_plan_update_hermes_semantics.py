"""plan_update carries hermes todo_tool's write semantics (owner 2026-09-08:
"implement the same as hermes, go deep in the files, as it is").

Verified in hermes source (tools/todo_tool.py): writes are validated,
deduped (last occurrence in its position), capped (4000 chars/item, 256
items), and the in_progress step is lifted ahead of earlier pending
placeholders. Pulse keeps its wire vocab (description/status list, no
id store) but the semantics below are hermes' own, renamed only where
pulse's vocab demands it.
"""
from __future__ import annotations

import json

from src.tools.plan_tool import plan_update


def _invoke(steps):
    return json.loads(plan_update.invoke({"steps": steps}))


def test_dedupe_keeps_last_occurrence_in_its_position():
    result = _invoke([
        {"description": "inspect", "status": "pending"},
        {"description": "build", "status": "in_progress"},
        {"description": "inspect", "status": "completed"},   # dup: wins
    ])
    assert [s["description"] for s in result["steps"]] == ["build", "inspect"]
    assert result["steps"][1]["status"] == "completed"


def test_in_progress_lifts_ahead_of_earlier_pending():
    result = _invoke([
        {"description": "first", "status": "pending"},
        {"description": "second", "status": "in_progress"},
    ])
    assert [s["description"] for s in result["steps"]] == ["second", "first"]


def test_long_description_is_capped_with_marker():
    result = _invoke([{"description": "x" * 5000, "status": "pending"}])
    desc = result["steps"][0]["description"]
    assert len(desc) == 4000
    assert desc.endswith("… [truncated]")


def test_bare_string_keeps_text_and_truly_invalid_gets_placeholder():
    result = _invoke([
        {"description": "one", "status": "yolo"},
        {"status": "pending"},
        "a bare string",          # hermes parse layer: text is kept
        42,                        # non-dict non-str: placeholder
    ])
    steps = result["steps"]
    # invalid status -> pending (then the single in_progress normalization
    # promotes the first pending step, exactly as start_next_plan_step does)
    assert steps[0]["status"] == "in_progress"
    assert steps[1]["description"] == "(no description)"
    assert steps[1]["status"] == "pending"
    assert steps[2]["description"] == "a bare string"
    assert steps[2]["status"] == "pending"
    assert steps[3]["description"] == "(invalid step)"
    assert steps[3]["status"] == "pending"


def test_list_is_capped_at_256_items():
    result = _invoke([
        {"description": f"step {i}", "status": "pending"} for i in range(300)
    ])
    assert result["summary"]["total"] == 256


def test_read_mode_and_string_form_unchanged():
    empty = json.loads(plan_update.invoke({}))
    assert empty["summary"]["total"] == 0
    stringed = _invoke(json.dumps(
        [{"description": "via string", "status": "pending"}]))
    assert stringed["steps"][0]["description"] == "via string"
