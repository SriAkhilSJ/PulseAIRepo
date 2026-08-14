"""Adjudication measurements for the external "6.5/10 teardown" review (Aug 7).

Verdicts must be earned with numbers, not argued. This script measures:

  CLAIM 1  differential layer cache "never hit in normal operation"
           -> real ContextEngine.build_ai_messages over a simulated 10-turn
              active session (token_usage merges EVERY turn, execution_trace
              grows on tool turns — exactly what chat_graph writes).
              Counts layer-cache hits/misses + per-turn rebuild wall time,
              current hash vs. whitelist-hash (only keys layers read).
  CLAIM 2  repo-map staleness check = "full os.walk every turn"
           -> RepoMap._get_latest_mtime wall time at 1k / 10k / 30k files.
  CLAIM 6  ambiguity detector "embeds constants every turn"
           -> backend encode-text count across 5 turns, cold vs warm cache.
  CLAIM 2b git_context runs every turn (volatile by design) -> wall time.

Run:  python scripts/review6_adjudicate.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.context.context_engine import ContextEngine


# ------------------------------------------------------------------ helpers

def _git_ws(n_files: int = 40) -> str:
    ws = tempfile.mkdtemp(prefix="adj-ws-")
    for i in range(n_files):
        p = Path(ws) / f"mod_{i:03d}.py"
        p.write_text(f"def f{i}(x):\n    return x + {i}\n" * 5)
    subprocess.run(["git", "init", "-q"], cwd=ws, check=True)
    subprocess.run(["git", "add", "."], cwd=ws, check=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=ws, check=True,
    )
    return ws


def _engine(ws: str) -> ContextEngine:
    eng = ContextEngine(max_tokens=12_000, model="gpt-4o-mini", probe_window=False)
    tmp = tempfile.mkdtemp(prefix="adj-fb-")
    eng._feedback_path = os.path.join(tmp, "f.jsonl")
    eng._feedback_history = []
    return eng


def _turn_state(ws: str, turn: int, msgs: list) -> dict:
    """Mimic what chat_graph ACTUALLY writes each turn:
    - token_usage merges on every AI turn (call counts always grow)
    - execution_trace appends on tool turns
    - steps_completed grows only when a step finishes (turns 4, 8)
    """
    trace = [{"tool": f"tool_{i}", "ok": True} for i in range(max(0, turn - 1))]
    return {
        "messages": msgs,
        "current_task": "fix the crash in mod_001.py",
        "latest_instruction": "fix the crash in mod_001.py",
        "workspace": ws,
        "plan": [{"id": 1, "description": "reproduce", "status": "completed"},
                 {"id": 2, "description": "fix", "status": "pending"}],
        "plan_goal": "fix crash",
        "steps_completed": (["reproduce"] if turn >= 4 else [])
                           + (["fix"] if turn >= 8 else []),
        "failed_steps": [],
        # ---- the per-turn noise keys (NO layer reads these) ----
        "token_usage": {"calls": turn, "prompt_tokens": 4000 + 137 * turn,
                        "completion_tokens": 200 + 31 * turn},
        "execution_trace": trace,
    }


LAYER_KEYS = [
    "current_task", "latest_instruction", "workspace", "plan", "plan_goal",
    "steps_completed", "failed_steps", "recovery_mode", "recovery_attempts",
    "recovery_command", "replan_count", "prior_attempts",
]


def measure_claim1():
    print("\n=== CLAIM 1: differential layer-cache hit rate, active session ===")
    ws = _git_ws()

    def run_session(engine: ContextEngine, label: str) -> dict:
        sys_msg = SystemMessage(content="system prompt")
        msgs: list = [HumanMessage(content="fix the crash in mod_001.py")]
        hits = misses = 0
        times = []
        orig_builders = dict(engine._build_context_layers.__wrapped__.__defaults__ or {})  # noqa - not used; see below
        for turn in range(1, 11):
            state = _turn_state(ws, turn, list(msgs))
            # count rebuilds: wrap each builder
            rebuilt = []
            builders_t0 = time.perf_counter()
            t0 = time.perf_counter()
            out = engine.build_ai_messages(state, sys_msg)
            dt = (time.perf_counter() - t0) * 1000
            times.append(dt)
            # hit = layer served from cache this build; count via cache diff:
            # simpler: hash compare tells us rebuild_all or not
            cur = engine._last_state_hash
            msgs.append(AIMessage(content=f"turn {turn} working..."))
            msgs.append(HumanMessage(content=f"ok continue {turn}"))
        return {"times": times}

    # --- current hash (everything except messages) ---
    eng = _engine(ws)
    hashes = []
    hit_turns = 0
    t_rebuilds = []
    for turn in range(1, 11):
        state = _turn_state(ws, turn, [HumanMessage(content="fix it")])
        h = eng._hash_state(state)
        hit = (h == eng._last_state_hash)
        hit_turns += int(hit)
        t0 = time.perf_counter()
        eng.build_ai_messages(state, SystemMessage(content="sys"))
        t_rebuilds.append((time.perf_counter() - t0) * 1000)
        hashes.append(h)
    print(f"  CURRENT hash: layer-cache hits {hit_turns}/10 turns "
          f"({100*hit_turns/10:.0f}% hit rate)")
    print(f"  CURRENT hash: unique hashes over 10 turns = {len(set(hashes))} "
          f"(token_usage/execution_trace churn flips it)")
    print(f"  per-turn build_ai_messages wall time: "
          f"median {sorted(t_rebuilds)[len(t_rebuilds)//2]:.1f}ms, "
          f"max {max(t_rebuilds):.1f}ms (small 40-file ws, warm 2nd-level caches)")

    # --- proposed fix: hash ONLY the keys any layer builder reads ---
    import hashlib, json
    def whitelist_hash(self, state):
        payload = json.dumps({k: str(state.get(k)) for k in LAYER_KEYS},
                             sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    eng2 = _engine(ws)
    ContextEngine._hash_state = whitelist_hash
    try:
        hit_turns2 = 0
        for turn in range(1, 11):
            state = _turn_state(ws, turn, [HumanMessage(content="fix it")])
            h = eng2._hash_state(state)
            hit_turns2 += int(h == eng2._last_state_hash)
            eng2.build_ai_messages(state, SystemMessage(content="sys"))
    finally:
        del ContextEngine._hash_state  # restore class original
    print(f"  WHITELIST hash (12 layer-read keys): hits {hit_turns2}/10 turns "
          f"({100*hit_turns2/10:.0f}% hit rate) — token/execution churn ignored")
    return ws


def measure_claim2():
    print("\n=== CLAIM 2: repo-map staleness os.walk cost per turn ===")
    from src.context.repo_map import RepoMap
    for n in (1_000, 10_000, 30_000):
        root = tempfile.mkdtemp(prefix=f"adj-tree{n}-")
        wide = 100
        for d in range(n // wide):
            dp = Path(root) / f"pkg_{d:04d}"
            dp.mkdir()
            for f in range(wide):
                (dp / f"f{f:03d}.py").write_text("x = 1\n")
        rm = RepoMap(root)
        rm._get_latest_mtime()  # warm fs cache
        ts = []
        for _ in range(5):
            t0 = time.perf_counter()
            rm._get_latest_mtime()
            ts.append((time.perf_counter() - t0) * 1000)
        print(f"  {n:>6,} files: _get_latest_mtime median "
              f"{sorted(ts)[len(ts)//2]:.1f}ms (runs on EVERY staleness check, "
              f"i.e. every turn that builds the repo_map layer)")


def measure_claim6():
    print("\n=== CLAIM 6: ambiguity detector embedding cost per turn ===")
    from src.context.embedding_cache import EmbeddingCache

    class CountingEmbedder:
        model = "counting-fake"

        def __init__(self):
            self.texts_encoded = 0

        def encode(self, texts, normalize_embeddings=True):
            import hashlib
            import numpy as np
            self.texts_encoded += len(texts)
            out = []
            for t in texts:
                h = hashlib.sha256(t.encode()).digest()
                v = [b / 255.0 for b in h[:16]]
                out.append(v)
            return np.array(out)

    emb = CountingEmbedder()
    cache = EmbeddingCache(max_entries=4096)
    ambiguous = ["fix it", "make it better", "improve", "update", "refactor",
                 "optimize", "clean up", "debug", "solve", "handle this"]
    specific = ["file", "function", "class", "method", "module",
                "create", "add", "delete", "rename", "move",
                "test", "bug", "error", "line", "import", "path"]
    for turn in range(1, 6):
        task = f"user task phrasing #{turn}"  # new task text each turn
        cache.encode(emb, [task] + ambiguous + specific)
        print(f"  turn {turn}: backend texts encoded total = {emb.texts_encoded}")
    print("  (first turn pays 1+26 constants ONCE per process; every later "
          "turn pays exactly 1 — the new task text)")


def measure_git_cost(ws: str):
    print("\n=== CLAIM 2b: volatile git_context per-turn cost ===")
    from src.context.git_context import build_git_context_layer
    state = {"workspace": ws, "current_task": "fix the crash in mod_001.py"}
    build_git_context_layer(state)  # warm
    ts = []
    for _ in range(7):
        t0 = time.perf_counter()
        build_git_context_layer(state)
        ts.append((time.perf_counter() - t0) * 1000)
    print(f"  build_git_context_layer median {sorted(ts)[len(ts)//2]:.1f}ms, "
          f"max {max(ts):.1f}ms per turn (volatility is by design; "
          f"D23 tails it so churn busts no cache prefix)")


if __name__ == "__main__":
    ws = measure_claim1()
    measure_claim2()
    measure_claim6()
    measure_git_cost(ws)
