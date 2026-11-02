"""Tests for modular Python extractor (src.context.extraction.python_extractor)."""

from pathlib import Path

import pytest

from src.context.extraction.python_extractor import (
    _extract_py_import_edges,
    _sha256_id,
    _truncate_for_embedding,
    extract_chunks,
    extract_chunks_python,
    extract_py_import_edges,
)


def test_extract_python_chunks_module_func_class(tmp_path):
    code = '''"""Module docstring."""

def regular_func(a, b):
    """Adds numbers."""
    return a + b

async def async_func():
    """Async operation."""
    pass

class Calculator:
    """Class docstring."""
    def add(self, a, b):
        return a + b

    async def compute(self):
        pass
'''
    f = tmp_path / "calc.py"
    f.write_text(code)

    chunks = extract_chunks_python(f, tmp_path)
    symbols = {c["symbol_name"]: c for c in chunks}

    assert "(module)" in symbols
    assert symbols["(module)"]["symbol_type"] == "module"
    assert symbols["(module)"]["docstring"] == "Module docstring."

    assert "regular_func" in symbols
    assert symbols["regular_func"]["symbol_type"] == "function"
    assert symbols["regular_func"]["docstring"] == "Adds numbers."

    assert "async_func" in symbols
    assert symbols["async_func"]["symbol_type"] == "function"

    assert "Calculator" in symbols
    assert symbols["Calculator"]["symbol_type"] == "class"
    assert "def add(...)" in symbols["Calculator"]["content"]
    assert "def compute(...)" in symbols["Calculator"]["content"]


def test_extract_python_syntax_error(tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def broken_syntax( -:")
    assert extract_chunks_python(f, tmp_path) == []


def test_extract_python_truncation(tmp_path):
    # Over 50 lines should get truncated marker
    lines = ["def huge():"] + [f"    x = {i}" for i in range(70)]
    f = tmp_path / "huge.py"
    f.write_text("\n".join(lines))

    chunks = extract_chunks_python(f, tmp_path)
    func_chunk = next(c for c in chunks if c["symbol_name"] == "huge")
    assert "# (truncated) ..." in func_chunk["body"]


def test_extract_py_import_edges(tmp_path):
    ws = tmp_path
    (ws / "pkg").mkdir()
    (ws / "pkg" / "__init__.py").write_text("")
    (ws / "pkg" / "mod_a.py").write_text("def a(): pass\n")
    (ws / "pkg" / "mod_b.py").write_text(
        "import os\n"
        "from . import mod_a\n"
        "from pkg.mod_a import a\n"
    )

    importer = Path("pkg/mod_b.py")
    source = (ws / importer).read_text()
    edges = extract_py_import_edges(source, importer, ws)

    # os is stdlib, so dropped; mod_a is in workspace
    assert "pkg/mod_a.py" in edges
    # Does not link to self
    assert "pkg/mod_b.py" not in edges
