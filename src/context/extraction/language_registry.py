"""
Language Registry & Parser Dispatcher
======================================

Maintains language-to-parser mappings, grammar availability, and dynamic
source extension allowlists for Crusor AI Context Engine.
"""

from __future__ import annotations

import importlib
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass

# ------------------------------------------------------------- grammars config

# kind -> (module, language-function attribute)
_GRAMMAR_IMPORTS: dict[str, tuple[str, str]] = {
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "java": ("tree_sitter_java", "language"),
}

_EXT_JS = frozenset({".js", ".jsx", ".mjs", ".cjs"})
_EXT_TS = frozenset({".ts", ".cts", ".mts"})
_EXT_TSX = frozenset({".tsx"})
_EXT_JS_FAMILY = frozenset(set(_EXT_JS) | set(_EXT_TS) | set(_EXT_TSX))

# Generic-walk languages: node-type config per grammar (spike-verified).
_GENERIC_LANGS: dict[str, dict[str, Any]] = {
    "go": {
        "extensions": frozenset({".go"}),
        "func_types": frozenset({"function_declaration", "method_declaration"}),
        "class_types": frozenset({"type_declaration"}),
        "comment_types": frozenset({"comment"}),
        "method_containers": frozenset(),  # Go methods are top-level chunks
    },
    "rust": {
        "extensions": frozenset({".rs"}),
        "func_types": frozenset({"function_item"}),
        "class_types": frozenset({"struct_item", "trait_item", "impl_item"}),
        "comment_types": frozenset({"line_comment", "block_comment"}),
        "method_containers": frozenset({"declaration_list"}),
    },
    "java": {
        "extensions": frozenset({".java"}),
        "func_types": frozenset(),
        "class_types": frozenset({"class_declaration", "interface_declaration"}),
        "comment_types": frozenset({"line_comment", "block_comment"}),
        "method_containers": frozenset({"class_body", "interface_body"}),
    },
}

_LOAD_LOCK = threading.Lock()
_GRAMMARS: dict[str, tuple[Any, Any]] = {}   # kind -> (tree_sitter module, Language)
_FAILED: set[str] = set()
_NOTICED = False


def _load_grammar(kind: str) -> Optional[tuple[Any, Any]]:
    """Lazy, cached grammar load. Degrades loud-once, never raises."""
    global _NOTICED
    le = sys.modules.get("src.context.lang_extractors")

    lock = getattr(le, "_LOAD_LOCK", _LOAD_LOCK)
    grammars = getattr(le, "_GRAMMARS", _GRAMMARS)
    failed = getattr(le, "_FAILED", _FAILED)

    with lock:
        if kind in grammars:
            return grammars[kind]
        if kind in failed:
            return None
        try:
            import tree_sitter

            module_name, attr = _GRAMMAR_IMPORTS[kind]
            mod = importlib.import_module(module_name)
            lang = tree_sitter.Language(getattr(mod, attr)())
        except Exception as exc:
            failed.add(kind)
            noticed = getattr(le, "_NOTICED", _NOTICED)
            if not noticed:
                if le is not None:
                    try:
                        le._NOTICED = True
                    except Exception:
                        pass
                _NOTICED = True
                print(
                    f"[ChunkIndex] tree-sitter grammar '{kind}' unavailable "
                    f"({exc}); indexing Python sources only"
                )
            return None
        grammars[kind] = (tree_sitter, lang)
        return grammars[kind]


def source_extensions() -> frozenset[str]:
    """Extensions the index may consume RIGHT NOW (grammar availability is
    dynamic). `.py` is always indexed via the stdlib-ast extractor.
    """
    exts = {".py"}
    if _load_grammar("javascript"):
        exts |= set(_EXT_JS)
    if _load_grammar("typescript"):
        exts |= set(_EXT_TS)
    if _load_grammar("tsx"):
        exts |= set(_EXT_TSX)
    for kind, cfg in _GENERIC_LANGS.items():
        if _load_grammar(kind):
            exts |= set(cfg["extensions"])
    return frozenset(exts)


def _kind_for(ext: str) -> Optional[str]:
    """Return the grammar kind string for a given file extension."""
    if ext in _EXT_JS:
        return "javascript"
    if ext in _EXT_TS:
        return "typescript"
    if ext in _EXT_TSX:
        return "tsx"
    for kind, cfg in _GENERIC_LANGS.items():
        if ext in cfg["extensions"]:
            return kind
    return None


def is_supported_source_file(file_path: Path | str) -> bool:
    """Return True if file_path has a currently supported source extension."""
    suffix = Path(file_path).suffix.lower()
    return suffix in source_extensions()


def extract_source_chunks(
    file_path: Path, root: Path, source: str | None = None
) -> list[dict[str, Any]]:
    """Extension dispatch (D5): stdlib AST for Python — the richest path,
    already verified for async/decorators — tree-sitter for the JS/TS
    family and generic languages (Go, Rust, Java). Unsupported suffixes
    extract to nothing. ``source`` (P1): decoded text when caller already
    read the file once.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".py":
        from src.context.extraction.python_extractor import extract_chunks_python
        return extract_chunks_python(file_path, root, source)

    from src.context.extraction.treesitter_extractor import extract_chunks_treesitter
    return extract_chunks_treesitter(file_path, root, source)


__all__ = [
    "_GRAMMAR_IMPORTS",
    "_EXT_JS",
    "_EXT_TS",
    "_EXT_TSX",
    "_EXT_JS_FAMILY",
    "_GENERIC_LANGS",
    "_LOAD_LOCK",
    "_GRAMMARS",
    "_FAILED",
    "_NOTICED",
    "_load_grammar",
    "source_extensions",
    "_kind_for",
    "is_supported_source_file",
    "extract_source_chunks",
]
