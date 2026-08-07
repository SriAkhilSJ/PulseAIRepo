"""D31 measurement: what does a shadow snapshot COST per turn? (§43)

Numbers the ledger cites:
  - first-ever snapshot (store init + full first commit)
  - steady-state mutation turn (one file changed since last snapshot)
  - no-change turn (must be ~free: dedup + diff-index --quiet)
  - file-level restore wall time
  - 500-file workspace variant (bigger repo shape)

Run:  python scripts/d31_checkpoint_measure.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tools.shadow_checkpoints import ShadowCheckpoints


def _ws(n_files: int) -> str:
    ws = tempfile.mkdtemp(prefix=f"d31-ws{n_files}-")
    for i in range(n_files):
        (Path(ws) / f"mod_{i:03d}.py").write_text(f"V_{i} = {i}\n" * 10)
    return ws


def run(n_files: int) -> None:
    base = Path(tempfile.mkdtemp(prefix="d31-store-"))
    mgr = ShadowCheckpoints(enabled=True, base=base)
    ws = _ws(n_files)
    target = Path(ws) / "mod_000.py"

    # 1. first snapshot (cold store)
    t0 = time.perf_counter()
    assert mgr.ensure_checkpoint(ws, "baseline") is True
    first_ms = (time.perf_counter() - t0) * 1000
    cp = mgr.list_checkpoints(ws)[0]["hash"]

    # 2. steady-state mutation turns (x5)
    steady = []
    for i in range(5):
        target.write_text(f"V_0 = {100 + i}\n")
        mgr.new_turn()
        t0 = time.perf_counter()
        mgr.ensure_checkpoint(ws, f"turn {i}")
        steady.append((time.perf_counter() - t0) * 1000)

    # 3. no-change turn (x5)
    noop = []
    for _ in range(5):
        mgr.new_turn()
        t0 = time.perf_counter()
        assert mgr.ensure_checkpoint(ws, "no change") is False
        noop.append((time.perf_counter() - t0) * 1000)

    # 4. restore wall time
    t0 = time.perf_counter()
    res = mgr.restore(ws, cp, "mod_000.py")
    restore_ms = (time.perf_counter() - t0) * 1000
    assert res["success"] is True

    store_mb = sum(f.stat().st_size for f in base.rglob("*") if f.is_file()) / 1e6
    print(f"[{n_files:>4} files] first snapshot {first_ms:7.1f}ms | "
          f"mutation turn median {sorted(steady)[len(steady)//2]:6.1f}ms | "
          f"no-change turn median {sorted(noop)[len(noop)//2]:6.1f}ms | "
          f"restore {restore_ms:6.1f}ms | store {store_mb:.2f}MB "
          f"({len(mgr.list_checkpoints(ws))} snapshots kept)")


if __name__ == "__main__":
    for n in (50, 500):
        run(n)
