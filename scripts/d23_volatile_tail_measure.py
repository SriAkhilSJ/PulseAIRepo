"""
D23 measurement — legacy volatile placement vs volatile-after-history
=====================================================================

Debt D23 (filed §32): D19 moved volatile git_context to the END of the
layer block, lifting edit-turn cache stability 22.2% -> 70.3%. The last
break: volatile STILL sits before history, so a git change evicts the
whole history from the prefix. D23 emits volatile AFTER history (with a
constant preamble marking the boundary).

Same scenario as §32's scenario E: identical conversation, an agent edit
+ `git add` between turns 3 and 4. Two engines, flags pinned explicitly
so both layouts measure in one process, one workspace.

Run:  python scripts/d23_volatile_tail_measure.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.context.context_engine import ContextEngine


def _make_workspace() -> str:
    ws = tempfile.mkdtemp(prefix="d23-ws-")
    (Path(ws) / "app.py").write_text("def main():\n    return 1\n")
    (Path(ws) / "util.py").write_text("X = 1\n")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "add", "."], cwd=ws, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=audit", "commit", "-qm", "init"],
        cwd=ws, check=True,
    )
    return ws


def _engine(ws: str, volatile_tail: bool) -> ContextEngine:
    eng = ContextEngine(max_tokens=12_000, model="gpt-4o-mini",
                        probe_window=False, volatile_tail=volatile_tail)
    engine_tmp = tempfile.mkdtemp(prefix="d23-fb-")
    eng._feedback_path = os.path.join(engine_tmp, "feedback.jsonl")
    eng._feedback_history = []
    return eng


def _state(ws: str, msgs, task: str):
    return {
        "messages": msgs,
        "current_task": task,
        "latest_instruction": task,
        "task_status": "in_progress",
        "plan": [{"step": 1, "description": "inspect", "status": "done"},
                 {"step": 2, "description": "patch", "status": "active"}],
        "steps_completed": ["inspect"],
        "workspace": ws,
    }


def _pair(i: int):
    return [HumanMessage(content=f"turn {i}: update the feature"),
            AIMessage(content=f"turn {i}: I'll update the feature now.")]


def run(label: str, ws: str, volatile_tail: bool) -> None:
    eng = _engine(ws, volatile_tail)
    msgs: list = []
    task = "add the new feature to app.py"
    for i in range(5):
        msgs = msgs + _pair(i + 1)
        eng.build_ai_messages(_state(ws, msgs, task), SystemMessage(content="PERSONA"))
        if i in (1, 3):  # two mid-session edit cycles (git churn points)
            with open(os.path.join(ws, "app.py"), "a") as f:
                f.write(f"\ndef feature_{i}():\n    return {i}\n")
            subprocess.run(["git", "add", "."], cwd=ws, check=True)

    stats = eng.cache_audit_stats()
    print(f"\n=== {label} ===")
    ratios = []
    for t in stats["recent"]:
        if t["stable_ratio"] is None:
            print(f"  turn {t['turn']}: first build ({t['total_chars']} chars)")
        else:
            ratios.append(t["stable_ratio"])
            print(f"  turn {t['turn']}: stable {t['stable_chars']}/{t['total_chars']}"
                  f" ({t['stable_ratio']:.1%}) -- broke at {t['breaker']}")
    print(f"  >> history-break turns: {[t['stable_ratio'] for t in stats['recent'] if t['stable_ratio'] is not None]}")
    print(f"  >> prefix-reached-history {stats['prefix_reached_history_pct']},"
          f" breakers {stats['breaker_histogram']}")
    if ratios:
        print(f"  >> mean stability {sum(ratios)/len(ratios):.1%},"
              f" min {min(ratios):.1%}")


def run_long(label: str, ws: str, volatile_tail: bool) -> None:
    """20 turns with realistic-size replies; ONE edit cycle at turn 17 —
    the long-session regime where the placement guarantee pays for real."""
    eng = _engine(ws, volatile_tail)
    msgs: list = []
    task = "add the new feature to util.py"  # coding-classified: git layer relevant
    filler = "implementation detail discussed and applied. " * 12
    for i in range(20):
        msgs = msgs + [HumanMessage(content=f"turn {i+1}: improve feature {i+1}"),
                       AIMessage(content=f"turn {i+1}: done. {filler}")]
        eng.build_ai_messages(_state(ws, msgs, task), SystemMessage(content="PERSONA"))
        if i == 16:
            with open(os.path.join(ws, "util.py"), "a") as f:
                f.write("\nLONG_AWAITED = True\n")
            subprocess.run(["git", "add", "."], cwd=ws, check=True)
    stats = eng.cache_audit_stats()
    post = [t for t in stats["recent"] if t["stable_ratio"] is not None
            and t["turn"] >= 17]
    print(f"\n=== {label} (long: 20 turns, edit at 17) ===")
    for t in post:
        print(f"  turn {t['turn']}: stable {t['stable_chars']}/{t['total_chars']}"
              f" ({t['stable_ratio']:.1%}) -- broke at {t['breaker']}")
    breakers = {t["breaker"] for t in stats["recent"] if t["breaker"]}
    print(f"  >> all breakers: {breakers}")


if __name__ == "__main__":
    # separate workspaces per layout: identical content until each run's
    # own edits (a shared ws contaminated D23's baseline with legacy's
    # edit cycle — harness bug caught on first run).
    run("LEGACY (volatile before history)", _make_workspace(), volatile_tail=False)
    run("D23    (volatile AFTER history)", _make_workspace(), volatile_tail=True)
    run_long("LEGACY", _make_workspace(), volatile_tail=False)
    run_long("D23   ", _make_workspace(), volatile_tail=True)
