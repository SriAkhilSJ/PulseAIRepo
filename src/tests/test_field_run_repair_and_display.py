"""Pins for the 2026-09-09 field-run fixes @7a7111b9 (3 screenshots + log):

1. Repair gate — hermes' grace law: on a call with NO tools bound (D40
   budget-grace or ask), text-dialect tool calls must stay prose. The
   unconditional repair executed the model's post-grace phantom calls
   (Get-ChildItem ❌, `dir -R` ❌, read_file ❌, search_code 1.7MB) and
   turned the budget stop into a zombie turn.
2. Cleaned-text display — hermes ACP (agent/acp_openai_bridge.py:
   ``extract_tool_calls_from_text`` → ``(tool_calls, cleaned_text)``):
   consumed <tool_call> blocks never render. The field run streamed the
   raw markup into the transcript (shots 1-2) because the pump forwards
   every token unfiltered and the repair runs only after the response.

All pure: no LLM, no provider keys, no event-bus assertions beyond shape.
"""

import pytest
from langchain_core.messages import AIMessage

from src.graphs.parallel_tools import parse_text_tool_calls, repair_text_tool_calls
from src.graphs.chat_graph import _AgentTokenPump


TEXT_CALL = (
    "I'll check the files now.\n"
    "<tool_call>\n"
    "terminal\n"
    "<arg_key>command</arg_key>\n"
    "<arg_value>ls -la</arg_value>\n"
    "</tool_call>"
)


# ── 1. Repair gate ──────────────────────────────────────────────────────────


def test_repair_parses_text_dialect_when_tools_bound():
    msg = AIMessage(content=TEXT_CALL)
    out = repair_text_tool_calls(msg, allow=True)
    assert out.tool_calls and out.tool_calls[0]["name"] == "terminal"
    assert out.tool_calls[0]["args"] == {"command": "ls -la"}
    # hermes extract_tool_calls_from_text: consumed blocks never render;
    # surrounding PROSE STAYS (field 2026-09-10 alignment).
    assert "<tool_call>" not in out.content
    assert "I'll check the files now." in out.content


def test_repair_disarmed_on_no_tools_call_keeps_prose():
    """The D40 grace call and ask mode bind NO tools: hermes' law is the
    model cannot act. The text must stay prose for should_continue to
    finalize — never be parsed into executable calls."""
    msg = AIMessage(content=TEXT_CALL)
    out = repair_text_tool_calls(msg, allow=False)
    assert out is msg
    assert not getattr(out, "tool_calls", None)
    assert "<tool_call>" in out.content


def test_repair_disarmed_leaves_structured_calls_alone():
    structured = AIMessage(
        content="", tool_calls=[{"name": "terminal", "args": {"command": "ls"}, "id": "x"}]
    )
    assert repair_text_tool_calls(structured, allow=False) is structured


def test_rearm_after_grace_turn_next_turn_default_allow():
    """allow defaults to True: a NORMAL next call (tools bound) parses the
    dialect again — the gate is per-call, not sticky."""
    msg = AIMessage(content=TEXT_CALL)
    assert repair_text_tool_calls(msg).tool_calls


def test_parse_text_tool_calls_dialect2_not_parsed():
    """The `<dots_function_call><invoke name=…><parameter…>` shape (field
    shot 3) is NOT the taught dialect — hermes parses only its taught
    <tool_call> JSON/XML shape, so this stays unparsed prose (and after
    the gate fix it can never execute)."""
    assert parse_text_tool_calls(
        '<dots_function_call><invoke name="run_terminal">'
        '<parameter name="command">ls -la</parameter></invoke>'
        "</dots_function_call>"
    ) == []


# ── 2. Cleaned-text display (stream filter) ────────────────────────────────


def _pump_armed():
    return _AgentTokenPump("t", strip_tool_blocks=True)


def test_pump_strips_complete_block_from_stream():
    pump = _pump_armed()
    shown = pump._filter_piece('Answer.\n<tool_call>\nterminal\n</tool_call>\nDone.')
    # the trailing ≤10 chars ride the partial-tag holdback until flush
    shown += pump.flush_tail()
    assert shown == "Answer.\n\nDone."


def test_pump_strips_block_split_across_token_boundaries():
    pump = _pump_armed()
    chunks = ["Let me ", "check.<tool_", "call>terminal<arg_key>comm", "and</arg_key>"
              "<arg_value>ls</arg_value></tool", "_call>ok done"]
    shown = "".join(pump._filter_piece(c) for c in chunks)
    shown += pump.flush_tail()
    assert shown == "Let me check.ok done"


def test_pump_holds_partial_tag_tail_then_flushes():
    pump = _pump_armed()
    shown = pump._filter_piece("hello <tool")
    assert shown == "h"  # last 10 chars held back as a possible open tag
    tail = pump.flush_tail()
    # the held "<tool" was never completed — it displays as text
    assert shown + tail == "hello <tool"


def test_pump_unterminated_block_valve_flushes_as_text():
    pump = _pump_armed()
    shown = pump._filter_piece("<tool_call>" + "x" * 70_000)
    shown += pump.flush_tail()
    # far past the 64KB swallow limit: not a tool call — display it,
    # open tag included
    assert "x" * 1000 in shown


def test_pump_disarmed_forwards_markup_verbatim():
    """Grace/ask calls keep the model's prose — hermes shows unparseable
    text as text. The filter is armed per-call, only when tools bound."""
    pump = _AgentTokenPump("t", strip_tool_blocks=False)
    assert pump.strip_tool_blocks is False
    armed = _pump_armed()
    assert armed.strip_tool_blocks is True


def test_pump_flush_tail_releases_only_the_holdback():
    pump = _pump_armed()
    shown = pump._filter_piece("a<tool_call>x</tool_call>b")
    assert shown == "a"
    tail = pump.flush_tail()
    assert tail == "b"  # the held partial-tag candidate
    assert pump.flush_tail() == ""  # nothing held after the flush


# ── 3. Field 2026-09-10: the run ended "Ended unverified" with three
#      terminal calls lying in the transcript as RAW TEXT ───────────────────


OWNER_FIELD_TEXT = """Let me proceed with browser testing and proof screenshot.
<tool_call>terminal
<arg_key>command</arg_key>
<arg_value>cd /d/TestCrusorAI/test5 && curl -s -o /dev/null -w "%{http_code}" http://localhost:3000</arg_value>
</tool_call>
<tool_call>terminal
<arg_key>command</arg_key>
<arg_value>cd /d/TestCrusorAI/test5 && ls -la components/ui/ | head -30</arg_value>
</tool_call>
<tool_call>terminal
<arg_key>command</arg_key>
<arg_value>which npx && node --version</arg_value>
</tool_call>"""


def test_owner_field_shape_parses_to_three_calls():
    out = repair_text_tool_calls(AIMessage(content=OWNER_FIELD_TEXT), allow=True)
    assert len(out.tool_calls) == 3
    assert all(tc["name"] == "terminal" for tc in out.tool_calls)
    assert out.tool_calls[0]["args"]["command"].startswith("cd /d/TestCrusorAI/test5 && curl")
    assert "<tool_call>" not in out.content
    assert "Let me proceed with browser testing" in out.content


def test_hermes_json_body_dialect_parses():
    """hermes acp_openai_bridge TOOL_CALL_BLOCK_RE: <tool_call>{json}</tool_call>."""
    text = ('Before.\n<tool_call>{"name": "terminal", "arguments": '
            '{"command": "ls", "timeout": 10}}</tool_call>\nAfter.')
    out = repair_text_tool_calls(AIMessage(content=text), allow=True)
    assert out.tool_calls[0]["name"] == "terminal"
    assert out.tool_calls[0]["args"] == {"command": "ls", "timeout": 10}
    assert "Before." in out.content and "After." in out.content


def test_hermes_openai_envelope_dialect_keeps_provided_id():
    text = ('<tool_call>\n{"id": "call_abc", "type": "function", '
            '"function": {"name": "read_file", "arguments": "{\\"path\\": \\"a.ts\\"}"}}\n</tool_call>')
    out = repair_text_tool_calls(AIMessage(content=text), allow=True)
    assert out.tool_calls[0]["name"] == "read_file"
    assert out.tool_calls[0]["id"] == "call_abc"
    assert out.tool_calls[0]["args"] == {"path": "a.ts"}


def test_mixed_emission_appends_leftovers_and_dedupes():
    """Field 2026-09-10 loss channel: structured calls AND text blocks in ONE
    message — the text blocks used to stay prose and their actions never
    ran. hermes' bridge extracts from text regardless; parsed blocks dedupe
    against the structured set and leftovers append."""
    mixed = AIMessage(
        content=("Running checks.\n"
                 "<tool_call>terminal\n<arg_key>command</arg_key>\n"
                 "<arg_value>ls -la</arg_value>\n</tool_call>\n"
                 "<tool_call>terminal\n<arg_key>command</arg_key>\n"
                 "<arg_value>cat package.json</arg_value>\n</tool_call>"),
        tool_calls=[{"name": "terminal", "args": {"command": "ls -la"}, "id": "native1"}],
    )
    out = repair_text_tool_calls(mixed, allow=True)
    assert len(out.tool_calls) == 2                      # dupe dropped, leftover appended
    assert out.tool_calls[0]["id"] == "native1"
    assert out.tool_calls[1]["args"] == {"command": "cat package.json"}
    assert "<tool_call>" not in out.content
    assert "Running checks." in out.content


def test_mixed_all_duplicates_still_strips_blocks():
    mixed = AIMessage(
        content="note\n<tool_call>terminal\n<arg_key>command</arg_key>\n<arg_value>ls</arg_value>\n</tool_call>",
        tool_calls=[{"name": "terminal", "args": {"command": "ls"}, "id": "n1"}],
    )
    out = repair_text_tool_calls(mixed, allow=True)
    assert [tc["id"] for tc in out.tool_calls] == ["n1"]  # nothing appended
    assert "<tool_call>" not in out.content


def test_grace_law_untouched_for_all_dialects():
    for text in (OWNER_FIELD_TEXT,
                 '<tool_call>{"name": "terminal", "arguments": {"command": "ls"}}</tool_call>'):
        msg = AIMessage(content=text)
        assert repair_text_tool_calls(msg, allow=False) is msg


def test_garbage_block_stays_prose():
    text = "<tool_call>not a dialect just words</tool_call>"
    msg = AIMessage(content=text)
    assert repair_text_tool_calls(msg, allow=True) is msg
