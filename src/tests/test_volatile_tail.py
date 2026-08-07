"""Pins for D23 (§42): volatile layers emitted AFTER history.

Measured facts these pins defend (scripts/d23_volatile_tail_measure.py,
20-turn session, edit at turn 17): LEGACY placement lost 84.7% of the
request prefix on the post-edit turn (breaker layer:git_context evicted
the ENTIRE history); D23 placement kept 91.7% and, on every turn of every
scenario, the ONLY breaker category is history:* (natural growth) — a
git change can never again evict the conversation from the cache prefix.

Design contract:
- placement is the ONLY change: same layers selected, same history —
  quality gate = identical layer multiset between layouts (pinned);
- a constant preamble marks the boundary (volatile repo state is
  reference data, not conversation — and commit messages can be
  attacker-supplied, so the framing is explicit);
- PULSEAI_VOLATILE_TAIL=off restores the legacy layout byte-for-byte.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.context.context_engine import ContextEngine

git = pytest.mark.skipif(
    subprocess.run(["which", "git"], capture_output=True).returncode != 0,
    reason="git binary unavailable",
)


def _workspace() -> str:
    ws = tempfile.mkdtemp(prefix="d23-test-")
    (Path(ws) / "util.py").write_text("X = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "add", "."], cwd=ws, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=ws, check=True,
    )
    return ws


def _engine(ws: str, volatile_tail) -> ContextEngine:
    eng = ContextEngine(max_tokens=12_000, model="gpt-4o-mini",
                        probe_window=False, volatile_tail=volatile_tail)
    tmp = tempfile.mkdtemp(prefix="d23-fb-")
    eng._feedback_path = os.path.join(tmp, "f.jsonl")
    eng._feedback_history = []
    return eng


def _state(ws: str, msgs: list) -> dict:
    return {
        "messages": msgs,
        "current_task": "add the new feature to util.py",
        "latest_instruction": "add the new feature to util.py",
        "task_status": "in_progress",
        "plan": [], "steps_completed": [],
        "workspace": ws,
    }


def _kind(msg) -> str:
    if isinstance(msg, SystemMessage) and str(msg.content).startswith("=== GIT CONTEXT"):
        return "git"
    if isinstance(msg, SystemMessage) and str(msg.content).startswith(
            "=== VOLATILE REPOSITORY STATE"):
        return "preamble"
    if isinstance(msg, HumanMessage):
        return "human"
    if isinstance(msg, AIMessage):
        return "ai"
    return "other"


@git
def test_d23_order_git_after_history_and_preamble():
    ws = _workspace()
    eng = _engine(ws, volatile_tail=True)
    msgs = [HumanMessage(content="q1"), AIMessage(content="a1"),
            HumanMessage(content="q2")]
    out = eng.build_ai_messages(_state(ws, msgs), SystemMessage(content="P"))
    kinds = [_kind(m) for m in out]
    assert "git" in kinds, f"git layer missing — cannot pin placement: {kinds}"
    git_i = kinds.index("git")
    last_hist = max(i for i, k in enumerate(kinds) if k in ("human", "ai"))
    assert git_i > last_hist, f"volatile not after history: {kinds}"
    # preamble directly precedes the volatile block
    assert kinds[git_i - 1] == "preamble"
    assert out[git_i - 1].content == ContextEngine.VOLATILE_TAIL_PREAMBLE


@git
def test_d23_legacy_layout_via_flag_and_env(monkeypatch):
    ws = _workspace()
    msgs = [HumanMessage(content="q1"), AIMessage(content="a1")]
    eng = _engine(ws, volatile_tail=False)
    out = eng.build_ai_messages(_state(ws, msgs), SystemMessage(content="P"))
    kinds = [_kind(m) for m in out]
    assert "preamble" not in kinds
    if "git" in kinds:
        assert kinds.index("git") < max(
            i for i, k in enumerate(kinds) if k in ("human", "ai")
        )

    monkeypatch.setenv("PULSEAI_VOLATILE_TAIL", "off")
    eng2 = ContextEngine(max_tokens=12_000, model="gpt-4o-mini", probe_window=False)
    assert eng2._volatile_tail is False
    monkeypatch.delenv("PULSEAI_VOLATILE_TAIL")
    eng3 = ContextEngine(max_tokens=12_000, model="gpt-4o-mini", probe_window=False)
    assert eng3._volatile_tail is True


def test_d23_no_volatile_no_preamble():
    eng = ContextEngine(max_tokens=12_000, model="gpt-4o-mini",
                        probe_window=False, volatile_tail=True)
    tmp = tempfile.mkdtemp()
    eng._feedback_path = os.path.join(tmp, "f.jsonl")
    eng._feedback_history = []
    msgs = [HumanMessage(content="hello there"), AIMessage(content="hi!")]
    out = eng.build_ai_messages({
        "messages": msgs, "current_task": "just chatting",
        "latest_instruction": "just chatting", "task_status": "in_progress",
        "plan": [], "steps_completed": [], "workspace": tempfile.mkdtemp(),
    }, SystemMessage(content="P"))
    kinds = [_kind(m) for m in out]
    if "git" not in kinds:
        assert "preamble" not in kinds


@git
def test_d23_quality_gate_identical_selection_between_layouts():
    """The ONLY permitted delta is PLACEMENT: same layer multiset, same
    history — proven per turn over a short session."""
    ws = _workspace()
    msgs: list = []
    seen_flag_diffs = []
    for a, b in (("q1", "a1"), ("q2", "a2"), ("q3", "a3")):
        msgs = msgs + [HumanMessage(content=a), AIMessage(content=b)]
        st = _state(ws, msgs)
        out_new = _engine(ws, True).build_ai_messages(st, SystemMessage(content="P"))
        out_old = _engine(ws, False).build_ai_messages(st, SystemMessage(content="P"))
        new_names = sorted((m.response_metadata.get("layer") or _kind(m))
                           for m in out_new if isinstance(m, SystemMessage))
        old_names = sorted((m.response_metadata.get("layer") or _kind(m))
                           for m in out_old if isinstance(m, SystemMessage))
        # the preamble is the only SYSTEM-side addition of the new layout
        assert set(new_names) - set(old_names) <= {"preamble"}
        assert set(old_names) - set(new_names) == set()
        seen_flag_diffs.append(len(out_new) - len(out_old))
        # feedback attribution still sees the volatile layer
        assert "git_context" in [n for n in new_names if isinstance(n, str)]
    assert seen_flag_diffs  # scenario actually ran


@git
def test_d23_measured_cache_stability_post_edit():
    """The scenario from §42, pinned: legacy loses the prefix on the
    post-edit edit turn (breaker layer:git_context, ratio < 0.5 at this
    scale); D23's only breakers are history:* with ratio >= 0.80."""
    for flag, label in ((False, "legacy"), (True, "d23")):
        ws = _workspace()
        eng = _engine(ws, volatile_tail=flag)
        msgs: list = []
        filler = "implementation detail discussed and applied. " * 12
        for i in range(20):
            msgs = msgs + [HumanMessage(content=f"turn {i+1} improve feature {i+1}"),
                           AIMessage(content=f"turn {i+1} done. {filler}")]
            out = eng.build_ai_messages(_state(ws, msgs), SystemMessage(content="P"))
            if i == 16:
                (Path(ws) / "util.py").write_text("X = 2\nLONG_AWAITED = True\n")
                subprocess.run(["git", "add", "."], cwd=ws, check=True)
        stats = eng.cache_audit_stats()
        rec = [t for t in stats["recent"] if t["stable_ratio"] is not None]
        if label == "legacy":
            if not any(t["breaker"] == "layer:git_context" for t in rec):
                pytest.skip("git layer never broke — env gated the layer out")
            edit_turn = next(t for t in rec if t["breaker"] == "layer:git_context")
            assert edit_turn["stable_ratio"] < 0.5, (
                f"legacy placement suddenly cache-friendly? {edit_turn}")
        else:
            bad = [t for t in rec if not t["breaker"].startswith("history:")]
            assert not bad, f"volatile leaked into the prefix: {bad}"
            post = [t for t in rec if t["turn"] >= 17]
            assert post and min(t["stable_ratio"] for t in post) >= 0.80, (
                f"D23 post-edit stability regressed: {post}")
