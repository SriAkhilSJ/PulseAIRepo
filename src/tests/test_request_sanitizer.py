"""D36 pre-send sanitizer: hermes outstanding-call semantics.

Ported from hermes' ``_dedupe_tool_call_ids`` (agent/agent_runtime_helpers.py:
2690):
  - collapse duplicate tool_calls within an assistant message (DeepSeek 400)
  - OUTSTANDING-CALL tracking: a result answers a PENDING call or is dropped;
    an id answered once may be re-armed by a genuine new call (llama.cpp
    constant-id sessions) — hermes: "a seen-once-drop-forever rule ... deletes
    [the second legitimate result], so from the second tool call onward the
    model never sees any result — it announces its next action and the turn
    dies with the work unfinished."
  - empty tool content becomes a placeholder (Sarvam 400)

There is deliberately NO content-based dedup: hermes never re-points one
assistant tool_call at another call's result. Pulse field proof (2026-09-06):
the old byte-identical dedup hid repeated `terminal ls -la` results and the
model re-ran the same command four times in one turn.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.llm.factory import RetryLLMProxy
from src.llm.request_sanitizer import sanitize_request_messages


def _aim(calls, content="", id="a1"):
    return AIMessage(
        content=content,
        tool_calls=calls,
        additional_kwargs={},
        id=id,
    )


def _tool(cid, content="ok", id=None):
    return ToolMessage(content=content, tool_call_id=cid, id=id or f"t-{cid}")


def test_inline_duplicate_tool_calls_collapsed():
    msgs = [
        _aim([
            {"id": "c1", "name": "read_file", "args": {"path": "a.py"}},
            {"id": "c1", "name": "read_file", "args": {"path": "a.py"}},
            {"id": "c2", "name": "list_files", "args": {}},
        ]),
    ]
    out = sanitize_request_messages(msgs)
    assert out is not msgs
    assert len(out[0].tool_calls) == 2
    ids = [tc["id"] for tc in out[0].tool_calls]
    assert ids == ["c1", "c2"]


def test_reused_tool_call_id_result_dropped():
    msgs = [
        _aim([{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
        _tool("c1", "content one", "r1"),
        _tool("c1", "content two", "r2"),  # re-uses c1 -> must be dropped
    ]
    out = sanitize_request_messages(msgs)
    tool_msgs = [m for m in out if isinstance(m, ToolMessage)]
    assert out is not msgs
    assert len(tool_msgs) == 1
    assert tool_msgs[0].content == "content one"


def test_byte_identical_results_both_survive():
    """Hermes has NO content dedup: two identical results answering two live
    calls are both legitimate history. The old keep-newest-and-repoint rule
    manufactured pairings the model read as amnesia (field flail)."""
    msgs = [
        _aim([{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
        _tool("c1", "SAME BYTES", "r1"),
        _aim([{"id": "c2", "name": "read_file", "args": {"path": "a.py"}}]),
        _tool("c2", "SAME BYTES", "r2"),  # byte-identical to r1, own live call
    ]
    out = sanitize_request_messages(msgs)
    tool_msgs = [m for m in out if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 2, "each result answers its own outstanding call"
    assert [t.tool_call_id for t in tool_msgs] == ["c1", "c2"]
    ai_msgs = [m for m in out if isinstance(m, AIMessage)]
    assert ai_msgs[0].tool_calls[0]["id"] == "c1", "no re-pointing, ever"
    assert ai_msgs[1].tool_calls[0]["id"] == "c2"


def test_answered_id_rearms_for_a_genuine_new_call():
    """llama.cpp constant-id discipline (hermes #58327 note): the same id
    answering a NEW call must keep the new result — the seen-once rule
    deleted it and the turn died with the work unfinished."""
    msgs = [
        _aim([{"id": "c1", "name": "terminal", "args": {"command": "ls"}}]),
        _tool("c1", "listing one", "r1"),
        _aim([{"id": "c1", "name": "terminal", "args": {"command": "ls"}}]),
        _tool("c1", "listing two", "r2"),
    ]
    out = sanitize_request_messages(msgs)
    tool_msgs = [m for m in out if isinstance(m, ToolMessage)]
    assert [t.content for t in tool_msgs] == ["listing one", "listing two"]


def test_unanswered_duplicate_call_dropped_result_kept():
    """An assistant tool_call repeating an id that is STILL outstanding is a
    retry/crash glitch: hermes drops the LATER CALL so the live result has
    one unambiguous owner."""
    msgs = [
        _aim([{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
        _aim([{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
        _tool("c1", "the one result", "r1"),
    ]
    out = sanitize_request_messages(msgs)
    ai_msgs = [m for m in out if isinstance(m, AIMessage)]
    assert len(ai_msgs[0].tool_calls) == 1
    assert ai_msgs[1].tool_calls == [], "duplicate unanswered call removed"
    tool_msgs = [m for m in out if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1 and tool_msgs[0].content == "the one result"


def test_same_gap_result_not_deduped():
    msgs = [
        _aim([{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
        _tool("c1", "ONE"),
        _aim([{"id": "c2", "name": "read_file", "args": {"path": "b.py"}}]),
        _tool("c2", "TWO"),  # different bytes -> both kept
    ]
    out = sanitize_request_messages(msgs)
    tool_msgs = [m for m in out if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 2


def test_noop_returns_input_object():
    msgs = [
        HumanMessage(content="hi"),
        _aim([{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
        _tool("c1", "UNIQUE CONTENT"),
    ]
    out = sanitize_request_messages(msgs)
    assert out is msgs, "callers gate on identity"


def test_never_raises_on_adversarial_inputs():
    assert sanitize_request_messages([]) == []
    assert sanitize_request_messages(None) is None
    assert sanitize_request_messages("nope") == "nope"
    # A ToolMessage with garbage/empty ids must not crash the pass.
    msgs = [_tool(""), AIMessage(content="x", tool_calls=[]) ]
    out = sanitize_request_messages(msgs)
    assert len(out) == 2


class _StubLLM:
    def __init__(self, model="gpt-4o"):
        self.model = model
        self.sent = None

    def invoke(self, *args, **kwargs):
        self.sent = args[0] if args else kwargs.get("messages")
        return "ok"


def test_proxy_invoke_sanitizes_before_underlying_llm(monkeypatch):
    from src.config import settings
    from src.llm import factory as factory_mod
    monkeypatch.setattr(settings, "PROVIDER_SAFE_LIMIT", 1_000_000)
    llm = _StubLLM()
    proxy = RetryLLMProxy(llm)
    # Real, already-sanitized messages: proxy must send them untouched.
    msgs = [
        _aim([{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
        _tool("c1", "UNIQUE CONTENT"),
    ]
    assert proxy.invoke(msgs) == "ok"
    assert len([m for m in llm.sent if isinstance(m, ToolMessage)]) == 1

    # Dirty messages: the duplicate result must never reach the underlying llm.
    dirty = msgs + [_tool("c1", "DUPLICATE"), ]
    proxy.invoke(dirty)
    tool_msgs = [m for m in llm.sent if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].content == "UNIQUE CONTENT"