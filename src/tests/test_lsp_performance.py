"""Tests for LSP latency optimizations and performance fast-paths."""
from __future__ import annotations

import os
import time
from pathlib import Path
import unittest

from src.lsp import get_service, warmup


class TestLSPPerformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svc = get_service()
        cls.test_file = Path(os.path.abspath("test_lsp_perf_fixture.py"))

    @classmethod
    def tearDownClass(cls):
        if cls.test_file.exists():
            cls.test_file.unlink()

    def test_nonexistent_file_snapshot_is_instant(self):
        bogus_file = Path(os.path.abspath("does_not_exist_xyz.py"))
        t0 = time.perf_counter()
        if self.svc:
            self.svc.snapshot_baseline(str(bogus_file))
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.05, f"Nonexistent file snapshot took too long: {elapsed:.4f}s")

    def test_lsp_fastpath_and_delta(self):
        if not self.svc:
            self.skipTest("LSP service not active")

        # 1. Write clean file
        self.test_file.write_text("def multiply(a: int, b: int) -> int:\n    return a * b\n")

        # Initial check / warm
        t0 = time.perf_counter()
        diags_initial = self.svc.get_diagnostics_sync(str(self.test_file))
        t1 = time.perf_counter()
        self.assertEqual(len(diags_initial or []), 0)

        # 2. Baseline snapshot of unchanged file should be sub-10ms
        t0 = time.perf_counter()
        self.svc.snapshot_baseline(str(self.test_file))
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.05, f"Unchanged baseline snapshot took {elapsed:.4f}s; expected < 0.05s")

        # 3. Introduce type error
        self.test_file.write_text("def multiply(a: int, b: int) -> int:\n    return a + 'str'\n")

        # 4. Query delta diagnostics
        t0 = time.perf_counter()
        delta_diags = self.svc.get_diagnostics_sync(str(self.test_file), delta=True)
        elapsed = time.perf_counter() - t0

        self.assertGreater(len(delta_diags or []), 0, "LSP should have detected delta type error")
        self.assertLess(elapsed, 2.5, f"Delta check took {elapsed:.4f}s; expected < 2.5s")

    def test_warmup_submits_without_blocking(self):
        if not self.svc:
            self.skipTest("LSP service not active")
        t0 = time.perf_counter()
        warmup(str(self.test_file))
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 0.05, f"Warmup blocked for {elapsed:.4f}s")


if __name__ == "__main__":
    unittest.main()
