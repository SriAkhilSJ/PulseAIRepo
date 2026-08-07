"""
D13+D14 ranking measurement harness — planted scenarios, judged results
=======================================================================

Debt items (ARCHITECTURE_REVIEW.md §36 debt board):
- D13: fused retrieval orders by RRF position only; it never considers WHAT
  matched. Exact symbol-name hits, path affinity, test-file demotion and
  recency are invisible to it. (External reviewers' 8.0 gate.)
- D14: repo_map lists files alphabetically and, when over budget, truncates
  from the END OF THE ALPHABET — the most important file can vanish while
  junk survives. Import graph also emitted alphabetically.

This harness does not assume the failures — it manufactures them and prints
measured ranks. Run before the fix (record), after the fix (report).

Run:  python scripts/d13_d14_rank_measure.py
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.context.chunk_index import ChunkIndex
from src.context.repo_map import RepoMap


# ---------------------------------------------------------------------
# Deterministic fake embedder (same word-bucket class as the test suite)
# ---------------------------------------------------------------------

class _Embeds(list):
    def tolist(self):
        return list(self)


class FakeEmbedder:
    DIM = 384
    calls = 0

    def encode(self, texts, normalize_embeddings=True):
        type(self).calls += 1
        out = _Embeds()
        for text in texts:
            vec = [0.0] * self.DIM
            for word in re.findall(r"\w+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vec[h % self.DIM] += 1.0 if (h >> 8) % 2 == 0 else -1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


TWIN_VOCAB = (
    '"""Helper that raises TypeError on malformed header data.\n\n'
    "    Reused across the suite: raises TypeError, malformed input,\n"
    '    header checks, assertion plumbing.\n    """\n'
)


def _twin_module(n: int) -> str:
    """Vocabulary-twin distractors: docstrings stuffed with every content
    word of the scenario query — they rank well in BOTH retrievers while
    being the wrong answer."""
    funcs = []
    for i in range(3):
        funcs.append(
            f"def twin_{n}_{i}(raw_header, malformed, assertion):\n"
            f"    {TWIN_VOCAB}"
            f"    return raw_header or malformed or assertion\n\n"
        )
    return f'"""Twin module {n}: raises TypeError malformed header assertion."""\n' + "".join(funcs)


GOLD_AUTH = '''"""Authentication module."""
import os
import hashlib


def parse_auth_token(raw_header):
    """Parse a Bearer token from an Authorization header."""
    parts = raw_header.split(" ")
    assert len(parts) == 2, "malformed header"
    return parts[1]
'''


def _mk_ws(files: dict[str, str], mtimes: dict[str, float] | None = None) -> Path:
    ws = Path(tempfile.mkdtemp(prefix="d13_d14_ws_"))
    for rel, text in files.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    if mtimes:
        for rel, m in mtimes.items():
            os.utime(ws / rel, (m, m))
    return ws


def _mk_index(ws: Path, embedder=None) -> ChunkIndex:
    idx = ChunkIndex(
        ws, db_path=tempfile.mktemp(prefix="d13_d14_idx_", suffix=".db"),
        embedder=embedder or FakeEmbedder(),
    )
    idx.index_workspace()
    return idx


def _gold_rank(results, symbol: str, file_path: str | None = None) -> int:
    for i, r in enumerate(results, 1):
        if r.symbol_name == symbol and (file_path is None or r.file_path == file_path):
            return i
    return len(results) + 1  # not found


# ---------------------------------------------------------------------
# D13 scenarios (chunk re-rank)
# ---------------------------------------------------------------------

def scenario_s1_exact_name() -> None:
    """Query names the exact symbol; vocabulary twins out-fuse it today."""
    files = {"core/auth.py": GOLD_AUTH}
    for n in range(6):
        files[f"noise/distractor_{n}.py"] = _twin_module(n)
    ws = _mk_ws(files)
    idx = _mk_index(ws)
    q = "parse_auth_token raises TypeError: malformed header assertion"
    FakeEmbedder.calls = 0
    res = idx.search(q, top_k=3)
    rank = _gold_rank(res, "parse_auth_token", "core/auth.py")
    top3 = [(r.symbol_name, r.file_path) for r in res[:3]]
    print(f"S1 exact-name rescue ..... gold 'parse_auth_token' rank={rank}"
          f"  P@3={'HIT' if rank <= 3 else 'MISS'}  top3={top3}"
          f"  encodes={FakeEmbedder.calls}")


def scenario_s2_test_flood() -> None:
    """Non-test query; test-file twins must not occupy the top slots."""
    impl = (
        '"""Cache layer with eviction and TTL policy."""\n\n'
        "def cache_put(key, value, ttl):\n"
        '    """Store value under key with ttl eviction policy."""\n'
        "    return (key, value, ttl)\n\n"
        "def cache_get(key):\n"
        '    """Fetch a cached value by key."""\n'
        "    return key\n"
    )
    twin = (
        '"""Cache layer with eviction and TTL policy."""\n\n'
        "def cache_put_checked(key, value, ttl):\n"
        '    """Store value under key with ttl eviction policy, verified."""\n'
        "    assert key and (key, value, ttl)\n\n"
        "def cache_get_checked(key):\n"
        '    """Fetch a cached value by key, verified."""\n'
        "    assert key and key\n"
    )
    ws = _mk_ws({"src/cache.py": impl, "tests/test_cache.py": twin})
    idx = _mk_index(ws)
    q = "cache layer eviction ttl policy"
    res = idx.search(q, top_k=3)
    n_tests = sum(1 for r in res[:3] if "test_" in r.file_path)
    top3 = [(r.symbol_name, r.file_path) for r in res[:3]]
    print(f"S2 test-flood demote ..... test files in top3={n_tests}  top3={top3}")


def scenario_s3_path_affinity() -> None:
    """Query mentions the subsystem by name only via the file path."""
    auth_mod = (
        '"""Session lifecycle manager."""\n\n'
        "def open_session(user):\n"
        '    """Begin a user session and store its cookie."""\n'
        "    return user\n"
    )
    garden_mod = (
        '"""Session lifecycle manager."""\n\n'
        "def open_session(user):\n"
        '    """Begin a user session and store its cookie."""\n'
        "    return user\n"
    )
    ws = _mk_ws({"auth_flow.py": auth_mod, "garden.py": garden_mod})
    idx = _mk_index(ws)
    q = "auth session manager"
    res = idx.search(q, top_k=2)
    top1 = (res[0].symbol_name, res[0].file_path) if res else None
    print(f"S3 path affinity ......... top1={top1}  want file auth_flow.py")


def scenario_s4_no_regress() -> None:
    """Pure semantic query, no name hints: the right FILE must keep the top
    slot after the fix. (Within-file module-vs-function order may swap when
    the file stem is a query word — both chunks come from the same file and
    the layer emits both, so the information set is unchanged.)"""
    shade = (
        '"""Shade structures."""\n\n'
        "def build_pergola(beams):\n"
        '    """Assemble the roof beams."""\n'
        "    return beams\n"
    )
    water = (
        '"""Irrigation."""\n\n'
        "def water_plants(plants, litres):\n"
        '    """Water each plant with the given amount."""\n'
        "    return {p: litres for p in plants}\n"
    )
    ws = _mk_ws({"shade.py": shade, "water.py": water})
    idx = _mk_index(ws)
    q = "give every plant some water"
    res = idx.search(q, top_k=2)
    top1_file = res[0].file_path if res else None
    in_top2 = any(r.symbol_name == "water_plants" for r in res[:2])
    print(f"S4 no-regress (file lvl) . top1_file={top1_file} want water.py"
          f"  water_plants in top2={in_top2}")


def scenario_s4b_strict_zero_feature() -> None:
    """STRICT invariant: when NO re-rank feature fires, search() must equal
    raw RRF fusion byte-for-byte."""
    alpha = (
        '"""Hydration scheduling."""\n\n'
        "def schedule_irrigation(zones):\n"
        '    """Compute watering windows per zone."""\n'
        "    return zones\n"
    )
    beta = (
        '"""Pergola assembly notes."""\n\n'
        "def assemble_beams(beams):\n"
        '    """Bolt the cross beams together."""\n'
        "    return beams\n"
    )
    ws = _mk_ws({"hydra.py": alpha, "beams.py": beta})
    idx = _mk_index(ws)
    # query words intersect no symbol/stem: 'compute','watering','windows'
    # appear only inside BODIES/docstrings, not in names or stems here... to
    # be strict we compare against the raw fuse of the same inputs.
    q = "compute watering windows per zone"
    vec = idx._search_vector(q, 9)
    bm25 = idx._search_bm25(q, 9)
    raw = idx._rrf_fuse(vec, bm25)[:3]
    got = idx.search(q, top_k=3)
    same = [r.id for r in got] == [r.id for r in raw]
    print(f"S4b strict zero-feature .. search == raw RRF order: {same}")


def scenario_s5_hot_file() -> None:
    """Two equal-vocabulary candidates; the recently edited file wins."""
    old = (
        '"""Rate limiting."""\n\n'
        "def throttle_request(req):\n"
        '    """Apply the sliding window to this request."""\n'
        "    return req\n"
    )
    new = (
        '"""Rate limiting."""\n\n'
        "def throttle_request(req):\n"
        '    """Apply the sliding window to this request."""\n'
        "    return req\n"
    )
    ws = _mk_ws(
        {"legacy_limiter.py": old, "limiter.py": new},
        mtimes={"legacy_limiter.py": time.time() - 30 * 86400,
                "limiter.py": time.time()},
    )
    idx = _mk_index(ws)
    q = "throttle request sliding window"
    res = idx.search(q, top_k=2)
    top1 = (res[0].symbol_name, res[0].file_path) if res else None
    print(f"S5 hot-file preference ... top1={top1}  want file limiter.py (fresh)")


# ---------------------------------------------------------------------
# D14 scenarios (repo map ranking)
# ---------------------------------------------------------------------

def _junk_file(i: int) -> str:
    return f'"""Junk constants block {i}."""\n' + "\n".join(
        f"CONST_{i}_{j} = {j}" for j in range(40)
    ) + "\n"


def _r1_files() -> dict[str, str]:
    files: dict[str, str] = {}
    for i in range(12):
        files[f"a_junk_{i:02d}.py"] = _junk_file(i)
    # IMPORTANT file, deliberately LATE in the alphabet, imported by every
    # consumer, freshest mtime.
    files["z_core_engine.py"] = (
        '"""The core orchestration engine everything depends on."""\n\n'
        "class Engine:\n    pass\n\n"
        "def run_pipeline():\n    return Engine()\n\n"
        "def plan_tasks():\n    return []\n"
    )
    for c in range(4):
        files[f"m_consumer_{c}.py"] = (
            f"from z_core_engine import Engine\n\n\ndef consume_{c}():\n"
            f"    return Engine()\n"
        )
    return files


def scenario_r1_compress_keeps_important(RepoMapImpl=RepoMap, tag: str = "new") -> None:
    """Over-budget map, two budgets:
      roomy (620 tok): graduated detail — symbols kept ONLY where they matter
      tight (240 tok): files must be DROPPED — junk first, gold survives.
    Deterministic importance: junk files aged 30 days, consumers+core now."""
    stale = time.time() - 30 * 86400
    mtimes = {f"a_junk_{i:02d}.py": stale for i in range(12)}
    ws = _mk_ws(_r1_files(), mtimes=mtimes)
    rm = RepoMapImpl(ws)

    roomy = rm.get_map(max_tokens=620)
    r_symbols = "run_pipeline" in roomy or "plan_tasks" in roomy
    r_junk_symbols = "rebuild_matrix" in roomy  # junk has no symbols, marker word
    print(f"R1a roomy [{tag}] .......... core={('z_core_engine.py' in roomy)}"
          f"  core symbols kept={r_symbols}")

    tight = rm.get_map(max_tokens=240)
    present = "z_core_engine.py" in tight
    junk_present = sum(1 for i in range(12) if f"a_junk_{i:02d}.py" in tight)
    print(f"R1b tight [{tag}] .......... z_core_engine shown={present}"
          f"  junk files still shown={junk_present}/12")


def scenario_r2_import_graph_centrality(RepoMapImpl=RepoMap, tag: str = "new") -> None:
    """Import graph emission: the most-depended-upon file must surface."""
    files = {
        "libbase.py": '"""Base library everyone uses."""\nX = 1\n',
        "a_leaf.py": "import libbase\n\n\nleaf = 1\n",
        "b_leaf.py": "import libbase\n\n\nleaf = 2\n",
        "c_leaf.py": "import libbase\n\n\nleaf = 3\n",
    }
    ws = _mk_ws(files)
    rm = RepoMapImpl(ws)
    text = rm.get_map(max_tokens=100_000)
    graph = ""
    if "=== IMPORT GRAPH ===" in text:
        graph = text.split("=== IMPORT GRAPH ===", 1)[1]
    hub_line = next((ln for ln in graph.splitlines() if "depended" in ln), "")
    hub_named = "libbase.py" in graph
    print(f"R2 import graph [{tag}] .... hub line='{hub_line.strip()}'"
          f"  libbase.py named in graph={hub_named}")


if __name__ == "__main__":
    print("D13 — chunk re-rank scenarios (gold = the chunk the user means)")
    scenario_s1_exact_name()
    scenario_s2_test_flood()
    scenario_s3_path_affinity()
    scenario_s4_no_regress()
    scenario_s4b_strict_zero_feature()
    scenario_s5_hot_file()
    print()
    print("D14 — repo map ranking scenarios")
    # Honest before/after: the PRE-FIX repo_map recovered from git HEAD if
    # available the same day the fix was written — after the commit lands,
    # HEAD IS the fix, so only run 'old' when a snapshot file exists.
    import importlib.util
    old_path = "/tmp/old_repo_map.py"
    if os.path.exists(old_path):
        spec = importlib.util.spec_from_file_location("old_repo_map", old_path)
        old_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old_mod)
        scenario_r1_compress_keeps_important(old_mod.RepoMap, tag="OLD")
        scenario_r2_import_graph_centrality(old_mod.RepoMap, tag="OLD")
    scenario_r1_compress_keeps_important(RepoMap, tag="NEW")
    scenario_r2_import_graph_centrality(RepoMap, tag="NEW")
