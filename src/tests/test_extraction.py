"""Tests for modular code extraction subsystem (src.context.extraction)."""

from pathlib import Path

import pytest

from src.context.extraction.language_registry import (
    extract_source_chunks,
    is_supported_source_file,
    source_extensions,
)
from src.context.extraction.python_extractor import (
    extract_chunks_python,
    extract_py_import_edges,
)
from src.context.extraction.treesitter_extractor import (
    extract_chunks_treesitter,
    extract_go_import_edges,
    extract_java_import_edges,
    extract_js_import_edges,
    extract_rust_import_edges,
)


def test_source_extensions_includes_python_and_treesitter():
    exts = source_extensions()
    assert ".py" in exts
    assert ".js" in exts
    assert ".ts" in exts
    assert ".go" in exts
    assert ".rs" in exts
    assert ".java" in exts

    assert is_supported_source_file("src/main.py")
    assert is_supported_source_file("app.ts")
    assert not is_supported_source_file("style.css")
    assert not is_supported_source_file("README.md")


def test_extract_source_chunks_dispatch(tmp_path):
    py_file = tmp_path / "service.py"
    py_file.write_text("def serve(): pass\n")

    js_file = tmp_path / "client.js"
    js_file.write_text("export function request() { return 1; }\n")

    chunks_py = extract_source_chunks(py_file, tmp_path)
    assert any(c["symbol_name"] == "serve" for c in chunks_py)

    chunks_js = extract_source_chunks(js_file, tmp_path)
    assert any(c["symbol_name"] == "request" for c in chunks_js)


def test_treesitter_js_class_and_methods(tmp_path):
    js_code = """
    export class AuthController {
        login() { return true; }
        logout() { return false; }
    }
    """
    f = tmp_path / "auth.js"
    f.write_text(js_code)

    chunks = extract_chunks_treesitter(f, tmp_path)
    symbols = {c["symbol_name"]: c for c in chunks}

    assert "AuthController" in symbols
    class_chunk = symbols["AuthController"]
    assert class_chunk["symbol_type"] == "class"
    assert "login(...)" in class_chunk["content"]


def test_import_edges_js(tmp_path):
    ws = tmp_path
    (ws / "store.js").write_text("export const s = 1;\n")
    importer = ws / "index.js"
    importer.write_text("import { s } from './store';\n")

    edges = extract_js_import_edges(importer.read_text(), Path("index.js"), ws)
    assert "store.js" in edges


def test_import_edges_go(tmp_path):
    ws = tmp_path
    pkg_dir = ws / "pkg" / "auth"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "token.go").write_text("package auth\n")

    importer = ws / "main.go"
    importer.write_text('package main\nimport "pkg/auth"\n')

    edges = extract_go_import_edges(importer.read_text(), Path("main.go"), ws)
    assert any("token.go" in e for e in edges)


def test_import_edges_rust(tmp_path):
    ws = tmp_path
    (ws / "auth.rs").write_text("pub struct Session;\n")
    importer = ws / "main.rs"
    importer.write_text("mod auth;\nuse crate::auth::Session;\n")

    edges = extract_rust_import_edges(importer.read_text(), Path("main.rs"), ws)
    assert "auth.rs" in edges
