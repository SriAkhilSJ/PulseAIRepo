"""Current scaffold ownership contract.

The dedicated scaffold tools were intentionally deleted: the terminal creates a
framework project and ordinary verification/repair tools fix generated output.
Keep this pin so an orphaned test cannot silently reintroduce that retired tool
family.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def test_retired_scaffold_layout_normalizer_stays_deleted():
    root = Path(__file__).resolve().parents[2]
    assert importlib.util.find_spec("src.tools.scaffold_tools") is None
    assert not (root / "src" / "tools" / "scaffold_tools.py").exists()

    graph = (root / "src" / "graphs" / "chat_graph.py").read_text(encoding="utf-8")
    assert "scaffold_tools" not in graph
    assert "_normalize_generated_layout" not in graph
