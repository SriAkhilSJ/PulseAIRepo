"""D19 measurement harness -- runs realistic turn sequences through the
REAL ContextEngine and reports prompt-cache prefix stability per scenario.

Usage:  python3 scripts/cache_audit_measure.py

Scenarios:
  A  dashboard double-fire (identical state, two builds)
  B  normal continuation, no feedback recorded      (expected: healthy)
  C  continuation WITH record_feedback each turn    (the suspect)
  C2 C + noisy embedding scores (float jitter)      (compound suspect)
  D  task switch mid-session                        (legit break)
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.context.context_engine import ContextEngine


def _make_workspace() -> str:
    import subprocess

    ws = tempfile.mkdtemp(prefix="cache-audit-")
    with open(os.path.join(ws, "app.py"), "w") as f:
        f.write("def main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()\n")
    with open(os.path.join(ws, "util.py"), "w") as f:
        f.write("def helper(x):\n    return x * 2\n")
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "add", "."], cwd=ws, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=audit", "commit", "-qm", "init"],
        cwd=ws, check=True,
    )
    return ws


def _engine(ws: str) -> ContextEngine:
    eng = ContextEngine(max_tokens=12_000, model="gpt-4o-mini", probe_window=False)
    # Isolate the learning loop from the founder's real feedback store.
    engine_tmp = tempfile.mkdtemp(prefix="cache-audit-fb-")
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


def _run(label, ws, turns: list[dict], feedback: list[bool] | None = None,
         patch_noise: bool = False) -> None:
    restore = None
    if patch_noise:
        import random
        import src.llm.factory as factory
        import src.context.context_engine as ce

        rng = random.Random(7)

        def _det_vec(text: str) -> list[float]:
            base = [((hash(text + str(i)) % 1000) / 1000.0) - 0.5 for i in range(16)]
            return base

        class _FakeCache:
            def encode(self, embedder, texts):
                return [[v + rng.uniform(-0.02, 0.02) for v in _det_vec(t)] for t in texts]

        restore = (factory.get_embedder, ce.get_embedding_cache)
        factory.get_embedder = lambda: object()
        ce.get_embedding_cache = lambda: _FakeCache()

    eng = _engine(ws)
    msgs: list = []
    try:
        for i, turn_cfg in enumerate(turns):
            msgs = msgs + turn_cfg.get("append", [])
            task = turn_cfg.get("task", turns[0]["task"])
            eng.build_ai_messages(_state(ws, msgs, task), SystemMessage(content="PERSONA"))
            if feedback is not None and turn_cfg.get("feedback", True):
                eng.record_feedback(feedback[i % len(feedback)], task)
    finally:
        if restore is not None:
            import src.llm.factory as factory
            import src.context.context_engine as ce
            factory.get_embedder, ce.get_embedding_cache = restore

    stats = eng.cache_audit_stats()
    print(f"\n=== {label} ===")
    for t in stats["recent"]:
        if t["stable_ratio"] is None:
            print(f"  turn {t['turn']}: first build ({t['total_chars']} chars)")
        else:
            print(
                f"  turn {t['turn']}: stable {t['stable_chars']}/{t['total_chars']} "
                f"({t['stable_ratio']:.1%}) -- broke at {t['breaker']}"
            )
    print(
        f"  >> mean {stats['mean_stable_ratio']}, min {stats['min_stable_ratio']}, "
        f"prefix-reached-history {stats['prefix_reached_history_pct']}, "
        f"breakers {stats['breaker_histogram']}"
    )


def main() -> None:
    ws = _make_workspace()
    task = "fix the login timeout bug"
    pair = lambda u, a: [HumanMessage(content=u), AIMessage(content=a)]
    convo = [pair(f"question {i} about the login fix", f"answer {i} with details") for i in range(6)]
    turns = [{"append": msgs, "task": task} for msgs in convo]

    # A: dashboard double-fire -- identical state twice
    _run("A double-fire (identical state x2)", ws,
         [{"append": convo[0], "task": task}, {"append": [], "task": task}])

    # B: healthy continuation, no feedback
    _run("B continuation, NO feedback", ws, turns)

    # C: production shape -- feedback recorded per turn
    _run("C continuation + feedback each turn", ws, turns, feedback=[True, False])

    # C2: + embedding noise (float jitter in semantic scores)
    _run("C2 feedback + embedding noise", ws, turns, feedback=[True, False], patch_noise=True)

    # D: task switch (legitimate break)
    _run("D task switch", ws,
         [{"append": convo[0], "task": task}, {"append": convo[1], "task": "add a dashboard chart"}])

    # E: the agent edits files mid-session -> git status changes -> the
    # VOLATILE git_context layer rebuilds with different bytes. Where does
    # the prefix break, and how much does it cost?
    import subprocess

    eng = _engine(ws)
    msgs = []
    for i, add in enumerate(convo + [pair("commit that", "committed as abc123")]):
        msgs = msgs + add
        eng.build_ai_messages(
            _state(ws, msgs, task), SystemMessage(content="PERSONA")
        )
        if i == 2:  # after turn 3: simulate an agent edit cycle
            with open(os.path.join(ws, "app.py"), "a") as f:
                f.write("\ndef new_feature():\n    return 42\n")
            subprocess.run(["git", "add", "."], cwd=ws, check=True)
    stats = eng.cache_audit_stats()
    print("\n=== E file edit + git add between turns (volatile git_context) ===")
    for t in stats["recent"]:
        if t["stable_ratio"] is not None:
            print(
                f"  turn {t['turn']}: stable {t['stable_chars']}/{t['total_chars']} "
                f"({t['stable_ratio']:.1%}) -- broke at {t['breaker']}"
            )
    print(f"  >> prefix-reached-history {stats['prefix_reached_history_pct']}, "
          f"breakers {stats['breaker_histogram']}")

    # G: long feedback horizon -- 20 turns, alternated outcomes. Does the
    # learned-weight drift EVER flip the emitted layer order?
    _run("G 20-turn feedback drift horizon", ws,
         [{"append": msgs_i, "task": task} for msgs_i in
          (pair(f"q{i}", f"a{i}") for i in range(20))],
         feedback=[True, False])


if __name__ == "__main__":
    main()
