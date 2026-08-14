"""D37 prompt-cache preservation across provider failover.

PulseAI emits no cache_control blocks, so the port is the hermes invariant:
the static prefix is byte-preserved across a provider transition, and any
provider cache decoration is stripped defensively.
"""

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.context import cache_preservation as cp

_SENTINEL = cp._VOLATILE_SENTINEL


def _sys(content, layer=None, kw=None):
    return SystemMessage(content=content,
                         response_metadata={"layer": layer} if layer else {},
                         additional_kwargs=kw or {})


def _engine_like_messages():
    return [
        _sys("persona"),
        _sys("REPO MAP", layer="repo_map"),
        _sys("TASK", layer="task"),
        HumanMessage(content="user hi"),
        AIMessage(content="hi", id="a1"),
        ToolMessage(content="ok", tool_call_id="c1", id="t1"),
        _sys(_SENTINEL),
        _sys("git: clean", layer="git_context"),
    ]


def test_split_at_engine_sentinel():
    msgs = _engine_like_messages()
    prefix, tail = cp.split_prefix_tail(msgs)
    assert len(prefix) == 6
    assert len(tail) == 2
    assert tail[0].content == _SENTINEL
    assert prefix == msgs[:6]
    assert tail == msgs[6:]


def test_split_no_sentinel_is_all_prefix():
    msgs = [_sys("persona"), _sys("TASK", layer="task"), HumanMessage(content="hi")]
    prefix, tail = cp.split_prefix_tail(msgs)
    assert prefix == msgs
    assert tail == []


def test_stable_prefix_is_leading_run_of_system_messages():
    msgs = _engine_like_messages()
    stable = cp.stable_prefix(msgs)
    assert [m.content for m in stable] == ["persona", "REPO MAP", "TASK"]
    assert all(type(m).__name__ == "SystemMessage" for m in stable)


def test_strip_cache_decorations_removes_and_reuses_without_them():
    msgs = [
        _sys("persona", kw={"cache_control": {"type": "ephemeral"}}),
        _sys("TASK", layer="task"),
    ]
    out, stripped = cp.strip_cache_decorations(msgs)
    assert stripped == 1
    assert "cache_control" not in (out[0].additional_kwargs or {})
    # Untouched messages keep object identity (prefix stays stable at rest).
    assert out[1] is msgs[1]


def test_strip_noop_returns_input_identity():
    msgs = [_sys("persona"), _sys("TASK", layer="task")]
    out, stripped = cp.strip_cache_decorations(msgs)
    assert stripped == 0
    assert out is msgs


def test_redecorate_preserves_static_prefix_bytes():
    msgs = _engine_like_messages()
    prefix_before = [m.content for m in cp.stable_prefix(msgs)]
    out, info = cp.redecorate_for_failover(msgs)
    assert info["prefix_len"] == 6
    assert info["tail_len"] == 2
    assert info["changed"] is False  # no decorations to strip -> reuse input
    assert out is msgs
    prefix_after = [m.content for m in cp.stable_prefix(out)]
    assert prefix_after == prefix_before


def test_redecorate_strips_decorations_but_keeps_prefix():
    msgs = [
        _sys("persona", kw={"cache_control": {"type": "ephemeral"}}),
        _sys("TASK", layer="task"),
        _sys(_SENTINEL),
        _sys("git: clean", layer="git_context"),
    ]
    out, info = cp.redecorate_for_failover(msgs)
    assert info["decorations_stripped"] == 1
    assert info["changed"] is True
    assert "cache_control" not in (out[0].additional_kwargs or {})
    assert out[0].content == "persona"
    assert out[2].content == _SENTINEL


def test_redecorate_never_raises_on_garbage():
    assert cp.redecorate_for_failover(None)[1].get("error")
    assert cp.redecorate_for_failover("nope")[0] == "nope"


def test_failover_cache_report_identifies_prefix_match_and_break():
    base = _engine_like_messages()
    routed = base  # failover reuse: identical payload
    rep = cp.failover_cache_report(base, routed)
    assert rep["prefix_identical"] is True
    assert rep["base_chars"] == rep["routed_chars"]

    broken = list(base)
    broken[1] = _sys("REPO MAP CHANGED", layer="repo_map")  # mid-prefix break
    rep2 = cp.failover_cache_report(base, broken)
    assert rep2["prefix_identical"] is False