"""D36 pre-send sanitizer: lossless dedup of the outgoing message list.

Mirrors hermes' pre-call sanitizer (agent_runtime_helpers.py:3436) and the
byte-identical tool-result dedup (context_compressor.py:3390):
  - collapse duplicate tool_calls within an assistant message (DeepSeek 400)
  - drop later tool results reusing an already-seen tool_call_id
  - keep the newest byte-identical result, re-point older copies at it
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


def test_byte_identical_results_keep_newest_and_rewire():
    msgs = [
        _aim([{"id": "c1", "name": "read_file", "args": {"path": "a.py"}}]),
        _tool("c1", "SAME BYTES", "r1"),
        _aim([{"id": "c2", "name": "read_file", "args": {"path": "a.py"}}]),
        _tool("c2", "SAME BYTES", "r2"),  # byte-identical to r1
    ]
    out = sanitize_request_messages(msgs)
    tool_msgs = [m for m in out if isinstance(m, ToolMessage)]
    assert out is not msgs
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "c2", "newest copy survives"
    # The older assistant tool_call must be re-pointed at the surviving id so
    # no tool_call is left without a matching result.
    ai_msgs = [m for m in out if isinstance(m, AIMessage)]
    assert ai_msgs[0].tool_calls[0]["id"] == "c2"


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