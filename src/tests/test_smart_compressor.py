"""Turn-atomic SmartCompressor tests.

The old per-message scoring could keep a ToolMessage while dropping its
answering AIMessage (or the HumanMessage that started the turn) — not just
incoherent, but *protocol-invalid* for providers (tool results without a
tool_call = HTTP 400). Selection is now atomic per turn.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.context.smart_compressor import SmartCompressor


def _counter(msgs, model):
    return max(1, sum(len(str(m.content)) // 4 for m in msgs))


def _compressor():
    return SmartCompressor(model="fake-model")


def _assert_protocol_valid(out):
    """Every ToolMessage must have its call's AIMessage before it, and every
    AIMessage with tool_calls must be followed by its ToolMessages."""
    seen_call_ids = set()
    for m in out:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for c in m.tool_calls:
                cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
                seen_call_ids.add(cid)
        elif isinstance(m, ToolMessage):
            assert m.tool_call_id in seen_call_ids, (
                f"orphan ToolMessage (call {m.tool_call_id}) without its AIMessage"
            )
    answered = {
        m.tool_call_id for m in out if isinstance(m, ToolMessage)
    }
    for m in out:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for c in m.tool_calls:
                cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
                assert cid in answered, f"unanswered tool_call {cid}"
    assert not (out and isinstance(out[0], ToolMessage)), "output starts with a tool result"


def _history():
    return [
        # Turn A (old, weak): short, generic
        HumanMessage(content="help", id="h1"),
        AIMessage(content="ok", id="a1"),
        # Turn B (recent, strong): task words + error signals in tool output
        HumanMessage(content="debug the auth bug", id="h2"),
        AIMessage(
            content="let me try the login command",
            tool_calls=[{"name": "run_terminal", "args": {"command": "login"}, "id": "c1"}],
            id="a2",
        ),
        ToolMessage(content="error traceback auth failure exception in login", tool_call_id="c1", name="run_terminal", id="t1"),
        AIMessage(content="found the root cause in the auth parser", id="a3"),
    ]


def test_turn_atomicity_all_or_nothing():
    comp = _compressor()
    hist = _history()
    full_tokens = _counter(hist, "fake-model")
    turn_a_tokens = _counter(hist[:2], "fake-model")
    # Budget: fits turn B exactly, not A+B
    budget = full_tokens - turn_a_tokens
    out = comp.compress(hist, budget=budget, token_counter=_counter, task="auth bug")
    texts = [str(m.content) for m in out]
    assert not any(t == "help" for t in texts), "weak old turn leaked in"
    assert "debug the auth bug" in texts, "strong user's own turn dropped!"
    assert any(m.tool_call_id == "c1" for m in out if isinstance(m, ToolMessage))
    assert any(getattr(m, "tool_calls", None) for m in out), "AI tool-call half of turn missing"
    _assert_protocol_valid(out)


def test_budget_respected_and_order_preserved():
    comp = _compressor()
    hist = _history()
    budget = _counter(hist, "fake-model") - 1
    out = comp.compress(hist, budget=budget, token_counter=_counter, task="auth")
    assert _counter(out, "fake-model") <= budget
    pos = {m.id: i for i, m in enumerate(hist)}
    idx = [pos[m.id] for m in out]
    assert idx == sorted(idx), "chronological order broken"


def test_full_fit_returns_everything():
    comp = _compressor()
    hist = _history()
    out = comp.compress(hist, budget=10**6, token_counter=_counter, task="")
    assert [m.id for m in out] == [m.id for m in hist]


def test_leading_orphan_tool_message_dropped():
    comp = _compressor()
    hist = [
        ToolMessage(content="stale answer", tool_call_id="c9", name="x", id="t9"),
        HumanMessage(content="hi", id="h1"),
        AIMessage(content="hello", id="a1"),
    ]
    out = comp.compress(hist, budget=10**6, token_counter=_counter, task="")
    assert not any(isinstance(m, ToolMessage) for m in out), "orphan tool message kept"
    _assert_protocol_valid(out)


def test_unanswered_tool_call_sanitized():
    comp = _compressor()
    hist = [
        HumanMessage(content="try it", id="h1"),
        AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c2"}], id="a1"),
        HumanMessage(content="never mind", id="h2"),
        AIMessage(content="done", id="a2"),
    ]
    out = comp.compress(hist, budget=10**6, token_counter=_counter, task="")
    for m in out:
        if isinstance(m, AIMessage):
            assert not getattr(m, "tool_calls", None) or any(
                isinstance(x, ToolMessage) and x.tool_call_id == "c2" for x in out
            )
    _assert_protocol_valid(out)


def test_empty_history():
    assert _compressor().compress([], budget=100, token_counter=_counter) == []
