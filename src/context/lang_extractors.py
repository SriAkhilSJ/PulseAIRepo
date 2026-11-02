# src/context/lang_extractors.py
"""Multi-language source chunk extraction.

Delegates to modular extraction subsystem:
- src.context.extraction.language_registry
- src.context.extraction.treesitter_extractor
- src.context.extraction.python_extractor

Kept for 100% backward compatibility with existing tests and callers.
"""

from __future__ import annotations

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
    _sha256_id,
    _truncate_for_embedding,
)
from src.context.extraction.treesitter_extractor import (
    _CLASS_TYPES,
    _FUNC_TYPES,
    _JS_COMMENT_TYPES,
    _JS_RESOLVE_EXTS,
    _MAX_FILE_BYTES,
    _MAX_NODES_WALKED,
    _METHOD_TYPES,
    _VALUE_FUNC_TYPES,
    _VAR_STMT_TYPES,
    _add_chunk,
    _generic_class_name,
    _js_class_method_names,
    _leading_doc,
    _method_names_from,
    _name_of,
    _node_text,
    _rust_file_candidates,
    _walk_generic,
    _walk_js_family,
    extract_chunks_treesitter,
    extract_go_import_edges,
    extract_java_import_edges,
    extract_js_import_edges,
    extract_rust_import_edges,
)

__all__ = [
    "EMBED_HARD_CAP_CHARS",
    "_MAX_FILE_BYTES",
    "_MAX_NODES_WALKED",
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
    "_FUNC_TYPES",
    "_CLASS_TYPES",
    "_VAR_STMT_TYPES",
    "_VALUE_FUNC_TYPES",
    "_METHOD_TYPES",
    "_JS_COMMENT_TYPES",
    "_load_grammar",
    "source_extensions",
    "_kind_for",
    "_sha256_id",
    "_truncate_for_embedding",
    "_node_text",
    "_name_of",
    "_leading_doc",
    "_method_names_from",
    "_js_class_method_names",
    "_generic_class_name",
    "_add_chunk",
    "extract_chunks_treesitter",
    "_walk_js_family",
    "_walk_generic",
    "_JS_RESOLVE_EXTS",
    "extract_js_import_edges",
    "extract_go_import_edges",
    "_rust_file_candidates",
    "extract_rust_import_edges",
    "extract_java_import_edges",
    "extract_source_chunks",
    "is_supported_source_file",
]
