"""Pytest plugin: emit the real collected node IDs as JSON.

`--collect-only -q` prints a tree in pytest 9, so parsing console text is not a
stable identity source. `session.items` is the authoritative list; this plugin
writes it once collection finishes.

Used by scripts/run_test_groups.py:

    CRUSOR_TEST_MANIFEST=<path> pytest -p scripts.collect_manifest -q --collect-only ...
"""
from __future__ import annotations

import json
import os


def pytest_collection_finish(session) -> None:  # noqa: ANN001 - pytest hook signature
    target = os.environ.get("CRUSOR_TEST_MANIFEST", "").strip()
    if not target:
        return
    items = []
    for item in session.items:
        nodeid = getattr(item, "nodeid", "")
        if not nodeid:
            continue
        items.append({
            "nodeid": nodeid,
            "module": nodeid.split("::", 1)[0].replace("\\", "/"),
        })
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(items, fh)
