"""Pins for the D19 prompt-cache prefix audit + canonical emission order.

The MEASURED facts these pins defend (scripts/cache_audit_measure.py, §32):
pre-fix, a git-state change mid-session held only 22.2% of the request
prefix because volatile git_context sat mid-block in score order; post-fix
(same scenario) 70.3%, with git_context emitting dead last. Learned-weight
feedback never flipped emission order at 20-turn horizons (pre- or
post-fix) -- selection stays score-driven, placement is now boring.
"""

from __future__ import annotations

import os
import subprocess

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.context.prompt_cache_audit import CachePrefixAudit, _first_diff


def _layer(name: str, text: str) -> SystemMessage:
    msg = SystemMessage(content=text)
    msg.response_metadata["layer"] = name
    return msg


# ------------------------------------------------------------------ unit
def test_first_diff_equal_prefix_and_midpoint():
    assert _first_diff("abc", "abc") == 3
    assert _first_diff("abc", "abcdef") == 3
    assert _first_diff("abXdef", "abYdef") == 2
    assert _first_diff("", "abc") == 0
    big_a = "x" * 100_000 + "A"
    big_b = "x" * 100_000 + "B"
    assert _first_diff(big_a, big_b) == 100_000  # chunk-skip path correct


def test_first_turn_has_no_ratio():
    audit = CachePrefixAudit()
    rec = audit.record([SystemMessage(content="persona")])
    assert rec["stable_ratio"] is None and rec["breaker"] == "first_turn"


def test_identical_second_turn_is_fully_stable():
    msgs = [SystemMessage(content="persona"), _layer("task", "T"), HumanMessage(content="hi")]
    audit = CachePrefixAudit()
    audit.record(msgs)
    rec = audit.record([SystemMessage(content="persona"), _layer("task", "T"), HumanMessage(content="hi")])
    assert rec["stable_ratio"] == 1.0 and rec["breaker"] == "identical"


def test_appended_history_breaks_at_history_boundary():
    base = [SystemMessage(content="persona"), _layer("task", "TASK"), HumanMessage(content="q1")]
    audit = CachePrefixAudit()
    audit.record(base)
    rec = audit.record(base + [AIMessage(content="a1"), HumanMessage(content="q2")])
    # stable prefix = the ENTIRE previous request; the first appended
    # message owns the break point.
    assert rec["breaker"] == "history:assistant"
    assert rec["break_msg_idx"] == 3


def test_layer_byte_change_blamed_to_named_layer():
    audit = CachePrefixAudit()
    audit.record([SystemMessage(content="persona"), _layer("task", "one"), _layer("plan", "p")])
    rec = audit.record([SystemMessage(content="persona"), _layer("task", "TWO"), _layer("plan", "p")])
    assert rec["breaker"] == "layer:task" and rec["break_msg_idx"] == 1


def test_stats_shape_histogram_and_ring_buffer():
    audit = CachePrefixAudit(keep=5)
    audit.record([HumanMessage(content="a")])
    for i in range(8):
        audit.record([HumanMessage(content="a" * (i + 2))])
    stats = audit.stats()
    assert stats["turns"] == 5  # ring buffer honored
    assert stats["comparable_turns"] == 5  # ring kept only post-first turns
    assert "breaker_histogram" in stats and "prefix_reached_history_pct" in stats


def test_jsonl_sink_only_when_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("PULSEAI_CACHE_AUDIT_JSONL", raising=False)
    quiet = CachePrefixAudit()
    assert quiet._jsonl_path is None
    loud = CachePrefixAudit(jsonl_path=str(tmp_path / "audit.jsonl"))
    loud.record([HumanMessage(content="x")])
    loud.record([HumanMessage(content="xy")])
    lines = (tmp_path / "audit.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2 and '"stable_ratio"' in lines[1]


# -------------------------------------------------- engine integration
def _git_workspace(tmp_path) -> str:
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "app.py").write_text("def main():\n    return 1\n")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "add", "."], cwd=ws, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=ws, check=True,
    )
    return str(ws)


@pytest.fixture()
def engine(tmp_path):
    from src.context.context_engine import ContextEngine
    eng = ContextEngine(max_tokens=12_000, model="gpt-4o-mini", probe_window=False)
    eng._feedback_path = str(tmp_path / "fb.jsonl")
    eng._feedback_history = []
    return eng


def _state(ws, msgs):
    return {
        "messages": msgs,
        "current_task": "fix the login timeout bug",
        "latest_instruction": "fix the login timeout bug",
        "task_status": "in_progress",
        "plan": [{"step": 1, "description": "inspect", "status": "active"}],
        "workspace": ws,
    }


def test_engine_audits_and_git_context_emits_last(engine, tmp_path):
    ws = _git_workspace(tmp_path)
    persona = SystemMessage(content="PERSONA")
    msgs = [HumanMessage(content="q1"), AIMessage(content="a1")]

    first = engine.build_ai_messages(_state(ws, msgs), persona)
    # git_context must be the LAST layer-tagged message, even though it is
    # built early and scores mid-pack (the D19 placement invariant).
    tagged = [m for m in first
              if isinstance(m, SystemMessage) and m.response_metadata.get("layer")]
    assert tagged, "expected context layers in the request"
    assert tagged[-1].response_metadata["layer"] == "git_context"

    # Simulate the agent's edit cycle between turns.
    (tmp_path / "repo" / "app.py").write_text("def main():\n    return 2\n")
    subprocess.run(["git", "add", "."], cwd=ws, check=True)

    msgs2 = msgs + [HumanMessage(content="q2"), AIMessage(content="a2")]
    engine.build_ai_messages(_state(ws, msgs2), persona)
    stats = engine.cache_audit_stats()
    rec = stats["recent"][-1]
    # §42 CONTRACT CHANGE: D19 asserted breaker == "layer:git_context" with
    # stable_ratio >= 0.55 (its measured 70.3%). D23 moved volatile layers
    # AFTER history, so a git change can no longer evict the conversation
    # from the prefix — the only breakers are natural history growth (the
    # measured long-session cross-over: 15.3% -> 91.7% on the post-edit
    # turn). The engine fixture defaults to the NEW layout; the legacy
    # assertion is superseded deliberately, not regressed.
    assert rec["breaker"].startswith("history:"), (
        f"volatile layer leaked back into the cache prefix: {rec}")
    assert rec["stable_ratio"] >= 0.55
    # ...and the placement guarantee itself: git sits after all history.
    seen = []
    for m in engine.build_ai_messages(_state(ws, msgs2), persona):
        if isinstance(m, SystemMessage) and str(m.content).startswith("=== GIT CONTEXT"):
            seen.append("git")
        elif isinstance(m, (HumanMessage, AIMessage)):
            seen.append("hist")
    assert "git" in seen, "git layer missing — placement cannot be verified"
    assert seen.index("git") > max(i for i, k in enumerate(seen) if k == "hist")


def test_selection_score_driven_placement_canonical(engine):
    """Over budget, the FIT walk still prefers high scores; only the
    emitted ORDER is canonical (never score order)."""
    from src.context.token_budget import count_tokens

    def triple(score, name, text):
        msg = _layer(name, text)
        return (score, msg, count_tokens([msg], engine.model))

    layers = [
        triple(0.99, "skills", "S"),      # scores highest, emits late
        triple(0.50, "task", "T"),        # scores lowest, emits early
        triple(0.75, "repo_map", "R"),
    ]
    big_budget = 10_000
    emitted = engine._assemble_hierarchical(layers, big_budget)
    order = [m.content for m in emitted]
    assert order == ["R", "T", "S"]  # _BUILDER_ORDER, not score order

    # Budget pressure path: walk is score-ordered, so the LOW scorer is
    # first dropped/compressed — selection semantics preserved.
    budget = min(t for _, _, t in layers)  # room for ~1 layer
    emitted = engine._assemble_hierarchical(layers, budget)
    kept = [m.content for m in emitted]
    assert len(kept) <= 2                  # compression may rescue one
    assert kept and kept[0] in {"S", "R"}  # a HIGH scorer survives
    if len(kept) == 1:
        assert kept[0] == "S"              # highest scorer wins outright
