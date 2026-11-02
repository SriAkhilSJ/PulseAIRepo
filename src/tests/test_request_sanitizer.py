"""D36 pre-send sanitizer: lossless dedup of the outgoing message list.

Mirrors hermes' pre-call sanitizer (agent_runtime_helpers.py:3436) and the
byte-identical tool-result dedup (context_compressor.py:3390):
  - collapse duplicate tool_calls within an assistant message (DeepSeek 400)
  - drop later tool results reusing an already-seen tool_call_id
  - preserve distinct call/result IDs and bodies even when bodies match
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


def test_byte_identical_results_preserve_call_pairs_and_contents():
    content = "SAME BYTES " * 100
    msgs = [
        _aim([{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
        ToolMessage(content=content, name="read_file", tool_call_id="c1", id="r1"),
        _aim([{"id": "c2", "name": "read_file", "args": {"path": "b.py"}}]),
        ToolMessage(content=content, name="read_file", tool_call_id="c2", id="r2"),
    ]
    out = sanitize_request_messages(msgs)
    assert len(out) == 4
    assert out[0].tool_calls[0]["id"] == out[1].tool_call_id == "c1"
    assert out[2].tool_calls[0]["id"] == out[3].tool_call_id == "c2"
    assert out[1].content == content
    assert out[3].content == content
    assert out[3].id == "r2"
    assert msgs[3].content == content  # do not mutate checkpoint history


def test_duplicate_results_are_not_mixed_across_tools_status_or_short_outputs():
    content = "same output " * 100
    msgs = [
        _aim([{"id": "a", "name": "read_file", "args": {}}]),
        ToolMessage(content=content, name="read_file", tool_call_id="a"),
        _aim([{"id": "b", "name": "search_files", "args": {}}]),
        ToolMessage(content=content, name="search_files", tool_call_id="b"),
        _aim([{"id": "c", "name": "read_file", "args": {}}]),
        ToolMessage(content=content, name="read_file", tool_call_id="c", status="error"),
        _aim([{"id": "d", "name": "read_file", "args": {}}]),
        ToolMessage(content="ok", name="read_file", tool_call_id="d"),
        _aim([{"id": "e", "name": "read_file", "args": {}}]),
        ToolMessage(content="ok", name="read_file", tool_call_id="e"),
    ]
    out = sanitize_request_messages(msgs)
    assert [m.content for m in out if isinstance(m, ToolMessage)] == [
        content, content, content, "ok", "ok"
    ]


def test_duplicate_results_in_parallel_batch_keep_each_id():
    content = "repeated output " * 100
    msgs = [
        _aim([
            {"id": "a", "name": "read_file", "args": {"path": "a"}},
            {"id": "b", "name": "read_file", "args": {"path": "b"}},
        ]),
        ToolMessage(content=content, name="read_file", tool_call_id="a"),
        ToolMessage(content=content, name="read_file", tool_call_id="b"),
    ]
    out = sanitize_request_messages(msgs)
    assert [c["id"] for c in out[0].tool_calls] == ["a", "b"]
    assert [m.tool_call_id for m in out[1:]] == ["a", "b"]
    assert out[2].content == content


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
    def __init__(self, model="gpt-4o", with_tools=True):
        self.model = model
        self.sent = None
        # Simulate bound tools so has_tools detection returns True — otherwise
        # the new has_tools=False safety net would correctly strip tool traffic
        # for no-tools requests (Sarvam 400 fix), which would make this test
        # expect the old pre-fix behavior.
        if with_tools:
            self.kwargs = {"tools": [{"type": "function", "function": {"name": "read_file"}}]}
        else:
            self.kwargs = {}

    def invoke(self, *args, **kwargs):
        self.sent = args[0] if args else kwargs.get("messages")
        return "ok"


def test_proxy_invoke_sanitizes_before_underlying_llm(monkeypatch):
    from src.config import settings
    from src.llm import factory as factory_mod
    monkeypatch.setattr(settings, "PROVIDER_SAFE_LIMIT", 1_000_000)
    llm = _StubLLM(with_tools=True)
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


def test_proxy_strips_tool_messages_when_no_tools_bound(monkeypatch):
    """New: when has_tools=False (grace/ask path), tool traffic must be stripped
    to avoid Sarvam/DeepSeek 400 'Tool messages found but no tools provided'."""
    from src.config import settings
    monkeypatch.setattr(settings, "PROVIDER_SAFE_LIMIT", 1_000_000)
    llm = _StubLLM(with_tools=False)
    proxy = RetryLLMProxy(llm)
    msgs = [
        _aim([{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
        _tool("c1", "UNIQUE CONTENT"),
        HumanMessage(content="hi"),
    ]
    assert proxy.invoke(msgs) == "ok"
    # Tool messages stripped, human preserved
    assert len([m for m in llm.sent if isinstance(m, ToolMessage)]) == 0
    assert any(getattr(m, "content", "") == "hi" for m in llm.sent)

def test_proxy_keeps_distinct_pairs_for_identical_results(monkeypatch):
    from src.config import settings
    monkeypatch.setattr(settings, "PROVIDER_SAFE_LIMIT", 1_000_000)
    llm = _StubLLM(with_tools=True)
    proxy = RetryLLMProxy(llm)
    content = "identical output " * 100
    msgs = [
        _aim([{"id": "a", "name": "read_file", "args": {"path": "a"}}]),
        ToolMessage(content=content, name="read_file", tool_call_id="a"),
        _aim([{"id": "b", "name": "read_file", "args": {"path": "b"}}]),
        ToolMessage(content=content, name="read_file", tool_call_id="b"),
    ]
    assert proxy.invoke(msgs) == "ok"
    assert [m.tool_calls[0]["id"] for m in llm.sent if isinstance(m, AIMessage)] == ["a", "b"]
    assert [m.tool_call_id for m in llm.sent if isinstance(m, ToolMessage)] == ["a", "b"]
