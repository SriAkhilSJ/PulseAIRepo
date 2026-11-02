"""
Python Source Extractor
=======================

AST-based code chunk and import extraction for Python source files.
Uses standard library ast module for complete, zero-dependency parsing.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any, Optional

EMBED_HARD_CAP_CHARS = 800  # ~200 tokens at ~4 chars/token (embed window)


def _sha256_id(*parts: str) -> str:
    """Generate deterministic 16-char hex ID from component parts."""
    return hashlib.sha256(":".join(parts).encode()).hexdigest()[:16]


def _truncate_for_embedding(
    file_path: str,
    symbol_type: str,
    symbol_name: str,
    signature: str,
    docstring: Optional[str],
    body_lines: list[str],
) -> str:
    """Text that gets embedded. Hard-capped for the embedding model's
    training window (~256 tokens); structure first, body sample last.
    """
    doc = (docstring or "")[:150]
    body_head = "\n".join(body_lines[:8])
    content = (
        f"FILE: {file_path} | TYPE: {symbol_type} | NAME: {symbol_name}\n"
        f"SIG: {signature}\n"
        f"DOC: {doc}\n"
        f"BODY:\n{body_head}"
    )
    if len(content) > EMBED_HARD_CAP_CHARS:
        content = content[:EMBED_HARD_CAP_CHARS]
    return content


def extract_chunks_python(
    file_path: Path, root: Path, source: str | None = None
) -> list[dict[str, Any]]:
    """Parse a Python file into semantic chunks (plain dicts for storage).

    ``source`` (P1): the file's decoded text when the caller already read it
    once for the physical-read ledger — avoids a second physical read.
    """
    try:
        if source is None:
            source = file_path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except Exception:
        return []

    lines = source.splitlines()
    rel_path = str(file_path.relative_to(root))
    chunks: list[dict[str, Any]] = []

    # --- module header chunk ---
    header_lines = lines[: min(20, len(lines))]
    header_body = "\n".join(header_lines)
    chunks.append({
        "id": _sha256_id(rel_path, "module"),
        "file_path": rel_path,
        "symbol_name": "(module)",
        "symbol_type": "module",
        "start_line": 1,
        "end_line": len(header_lines),
        "signature": "",
        "docstring": ast.get_docstring(tree),
        "body": header_body,
        "content": _truncate_for_embedding(
            rel_path, "module", "(module)", "", ast.get_docstring(tree), header_lines
        ),
        "content_hash": hashlib.sha256(header_body.encode()).hexdigest()[:16],
    })

    # --- top-level functions / classes ---
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno - 1
        end = node.end_lineno or start + 1
        chunk_lines = lines[start:end]

        if len(chunk_lines) > 50:
            display_body = "\n".join(
                chunk_lines[:40] + ["    ...", "    # (truncated) ..."] + chunk_lines[-5:]
            )
        else:
            display_body = "\n".join(chunk_lines)

        sig = chunk_lines[0].strip() if chunk_lines else ""
        doc = ast.get_docstring(node)
        symbol_type = "class" if isinstance(node, ast.ClassDef) else "function"

        if isinstance(node, ast.ClassDef):
            methods = [
                f"  def {c.name}(...)"
                for c in ast.iter_child_nodes(node)
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            body_for_emb = [sig] + methods[:5]
        else:
            body_for_emb = chunk_lines

        chunks.append({
            "id": _sha256_id(rel_path, node.name, str(start)),
            "file_path": rel_path,
            "symbol_name": node.name,
            "symbol_type": symbol_type,
            "start_line": start + 1,
            "end_line": end,
            "signature": sig,
            "docstring": doc,
            "body": display_body,
            "content": _truncate_for_embedding(
                rel_path, symbol_type, node.name, sig, doc, body_for_emb
            ),
            "content_hash": hashlib.sha256(display_body.encode()).hexdigest()[:16],
        })

    return chunks


extract_chunks = extract_chunks_python


def extract_py_import_edges(source: str, importer_rel: Path, workspace: Path) -> set[str]:
    """Resolve a Python file's imports to in-workspace file targets.

    Full dotted-path resolution (repo_map's first-segment module names
    cannot produce file->file edges — verified). `import a.b.c` resolves
    the exact module path; `from a.b import c` resolves both the module
    file (`a/b.py`, `a/b/__init__.py`) and submodule targets (`a/b/c.py`);
    relative `from .x import y` climbs from the importer's package dir.
    stdlib/third-party imports resolve to nothing and are dropped: edges
    exist only between workspace files. Never raises — missing edges are
    a retrieval bonus, not a failure mode.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return set()

    targets: set[str] = set()
    importer_str = importer_rel.as_posix()  # forward slashes everywhere (Windows durability)
    importer_dir = importer_rel.parent

    def _resolve(module: str, names: list[str], level: int) -> None:
        if level >= 1:
            base = importer_dir
            for _ in range(level - 1):
                base = base.parent  # Path('.').parent == '.': cannot escape root
        else:
            base = Path("")
        mod_path = Path(*module.split(".")) if module else Path("")
        full = base / mod_path
        candidates = [full.with_suffix(".py"), full / "__init__.py"]
        for name in names:  # from X import n -> X/n.py may be the real target
            candidates.append(full / f"{name}.py")
            candidates.append(full / name / "__init__.py")
        for cand in candidates:
            rel_str = cand.as_posix()
            if rel_str == importer_str:
                continue
            try:
                if (workspace / cand).is_file():
                    targets.add(rel_str)
            except OSError:
                continue

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _resolve(alias.name, [], 0)
        elif isinstance(node, ast.ImportFrom):
            _resolve(node.module or "", [a.name for a in node.names], node.level or 0)
    return targets


_extract_py_import_edges = extract_py_import_edges

__all__ = [
    "EMBED_HARD_CAP_CHARS",
    "_sha256_id",
    "_truncate_for_embedding",
    "extract_chunks_python",
    "extract_chunks",
    "extract_py_import_edges",
    "_extract_py_import_edges",
]
