"""Code extraction subsystem for Context Engine."""

from src.context.extraction.language_registry import (
    _EXT_JS,
    _EXT_JS_FAMILY,
    _EXT_TS,
    _EXT_TSX,
    _FAILED,
    _GENERIC_LANGS,
    _GRAMMAR_IMPORTS,
    _GRAMMARS,
    _LOAD_LOCK,
    _NOTICED,
    _kind_for,
    _load_grammar,
    extract_source_chunks,
    is_supported_source_file,
    source_extensions,
)
from src.context.extraction.python_extractor import (
    EMBED_HARD_CAP_CHARS,
    _extract_py_import_edges,
    _sha256_id,
    _truncate_for_embedding,
    extract_chunks,
    extract_chunks_python,
    extract_py_import_edges,
)
from src.context.extraction.treesitter_extractor import (
    _MAX_FILE_BYTES,
    _MAX_NODES_WALKED,
    extract_chunks_treesitter,
    extract_go_import_edges,
    extract_java_import_edges,
    extract_js_import_edges,
    extract_rust_import_edges,
)

__all__ = [
    # Python AST extraction
    "EMBED_HARD_CAP_CHARS",
    "_sha256_id",
    "_truncate_for_embedding",
    "extract_chunks_python",
    "extract_chunks",
    "extract_py_import_edges",
    "_extract_py_import_edges",
    # Tree-sitter extraction
    "_MAX_FILE_BYTES",
    "_MAX_NODES_WALKED",
    "extract_chunks_treesitter",
    "extract_js_import_edges",
    "extract_go_import_edges",
    "extract_rust_import_edges",
    "extract_java_import_edges",
    # Language registry & dispatch
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
