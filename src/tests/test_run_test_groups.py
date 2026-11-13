"""Process-tree safety for the grouped runner (scripts/run_test_groups.py).

A group timeout must kill the whole tree. Killing only the direct child leaves the
cold interpreters and sandbox helpers a test spawned, which is how one process
accumulated work for hours (run 43410282051 / the 33,455 CPU-second orphan).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from scripts.run_test_groups import terminate_tree

pytestmark = pytest.mark.skipif(
    os.name == "nt", reason="process groups are POSIX-only; Windows uses taskkill /T"
)


def test_terminate_tree_kills_grandchildren(tmp_path):
    pidfile = tmp_path / "grandchild.pid"
    parent_code = (
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        "open(sys.argv[1], 'w').write(str(p.pid))\n"
        "time.sleep(120)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", parent_code, str(pidfile)],
        start_new_session=True,
    )
    try:
        for _ in range(200):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            time.sleep(0.05)
        assert pidfile.exists(), "grandchild never started"
        grandchild = int(pidfile.read_text().strip())

        terminate_tree(proc)

        assert proc.poll() is not None, "parent survived terminate_tree"
        for _ in range(40):
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("grandchild survived terminate_tree (process group not killed)")
    finally:
        if proc.poll() is None:
            terminate_tree(proc)


def test_terminate_tree_is_idempotent_for_a_finished_process():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=30)
    terminate_tree(proc)  # must not raise
    assert proc.poll() == 0
