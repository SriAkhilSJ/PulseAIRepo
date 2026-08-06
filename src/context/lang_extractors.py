# src/context/lang_extractors.py
"""Multi-language source chunk extraction (debt D5: JS/TS family + Go/Rust/Java).

Why tree-sitter, and why NOT the VS Code fork's APIs (founder asked): the
fork's language smarts are (a) TextMate grammars — regex tokenizers with no
AST — and (b) LSP servers — out-of-process daemons behind an extension-host
IPC bridge, in TypeScript, inside the editor process. A Python backend can
import neither; spawning Electron/node just to parse files is the wrong
shape for an index-time task measured in µs per file. tree-sitter is the
in-process standard for exactly this job (error-tolerant concrete syntax
trees, per-language grammars, Python wheels) — the same class of tech
Cursor/Aider-style indexers use. Fork/extension APIs pay off at P2 for
*integration* (file-watch feeds → index freshness, diagnostics → context),
not for parsing.

Languages (all node types verified empirically against the installed
grammar wheels, not from docs):

- **JS family** (.js/.jsx/.mjs/.cjs) + **TS family** (.ts/.tsx/.cts/.mts):
  specialized walk — export-unwrapping, arrow/function-expression consts,
  class methods embedded.
- **Go** (.go): function_declaration + method_declaration chunks;
  type_declaration (structs) as searchable "class" chunks. Methods are
  top-level in Go, so nothing is embedded.
- **Rust** (.rs): function_item chunks; struct_item/trait_item as "class"
  chunks; impl_item as a "class" chunk named `impl <Type>` with its
  methods embedded from declaration_list.
- **Java** (.java): class_declaration/interface_declaration as "class"
  chunks with method_declaration/constructor_declaration names embedded;
  no standalone method chunks (Python-parity granularity).

Degradation contract (same pattern as the watchdog dep): grammars are
declared dependencies, but a slim/broken environment must never take down
Python indexing — any load failure degrades that language out of the
extension allowlist with exactly one loud notice per process.
"""

from __future__ import annotations

import hashlib
import importlib
import threading
from pathlib import Path
from typing import Any, Callable, Optional

EMBED_HARD_CAP_CHARS = 800  # ~200 tokens at ~4 chars/token (embed window)

# Cutting safety valves: mega generated bundles shouldn't O(n) us to death.
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_NODES_WALKED = 50_000

# ------------------------------------------------------------- grammars

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

# JS/TS-family walk sets (specialized: export unwrap + variable declarators)
_FUNC_TYPES = frozenset({"function_declaration", "generator_function_declaration"})
_CLASS_TYPES = frozenset({"class_declaration", "abstract_class_declaration"})
_VAR_STMT_TYPES = frozenset({"lexical_declaration", "variable_declaration"})
_VALUE_FUNC_TYPES = frozenset({"arrow_function", "function_expression"})
_METHOD_TYPES = frozenset({"method_definition", "method_signature"})
_JS_COMMENT_TYPES = frozenset({"comment"})


def _load_grammar(kind: str) -> Optional[tuple[Any, Any]]:
    """Lazy, cached grammar load. Degrades loud-once, never raises."""
    global _NOTICED
    with _LOAD_LOCK:
        if kind in _GRAMMARS:
            return _GRAMMARS[kind]
        if kind in _FAILED:
            return None
        try:
            import tree_sitter

            module_name, attr = _GRAMMAR_IMPORTS[kind]
            mod = importlib.import_module(module_name)
            lang = tree_sitter.Language(getattr(mod, attr)())
        except Exception as exc:
            _FAILED.add(kind)
            if not _NOTICED:
                _NOTICED = True
                print(
                    f"[ChunkIndex] tree-sitter grammar '{kind}' unavailable "
                    f"({exc}); indexing Python sources only"
                )
            return None
        _GRAMMARS[kind] = (tree_sitter, lang)
        return _GRAMMARS[kind]


def source_extensions() -> frozenset[str]:
    """Extensions the index may consume RIGHT NOW (grammar availability is
    dynamic). `.py` is always indexed via the stdlib-ast extractor."""
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


# ------------------------------------------------------------- helpers


def _sha256_id(*parts: str) -> str:
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
    training window (~256 tokens); structure first, body sample last."""
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


def _node_text(node: Any, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _name_of(node: Any, src: bytes) -> Optional[str]:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _node_text(name_node, src)


def _leading_doc(node: Any, src: bytes, comment_types: frozenset) -> Optional[str]:
    """Nearest contiguous block of comments directly above a declaration —
    the universal stand-in for a docstring (rust `///` are line_comment
    nodes; JSDoc `/** */` are block_comment; go `//` are comment)."""
    docs: list[tuple[int, str]] = []
    sib = node.prev_named_sibling
    while sib is not None and sib.type in comment_types and len(docs) < 6:
        # Contiguous lines only: a detached comment block belongs to itself.
        if docs and sib.end_point[0] < docs[-1][0] - 1:
            break
        docs.append((sib.start_point[0], _node_text(sib, src)))
        sib = sib.prev_named_sibling
    if not docs:
        return None
    docs.reverse()
    return "\n".join(text for _, text in docs)[:400]


def _method_names_from(node: Any, src: bytes, container_types: frozenset) -> list[str]:
    """Embedded "name(...)" listing for class-like chunks (JS class_body,
    rust declaration_list, java class/interface_body)."""
    for child in node.named_children:
        if child.type in container_types:
            names = []
            for member in child.named_children:
                name = member.child_by_field_name("name")
                if name is not None:
                    names.append(f"  {_node_text(name, src)}(...)")
            return names[:5]
    return []


def _js_class_method_names(class_node: Any, src: bytes) -> list[str]:
    body = class_node.child_by_field_name("body")
    names: list[str] = []
    if body is not None:
        for child in body.named_children:
            if child.type in _METHOD_TYPES:
                name = _name_of(child, src)
                if name:
                    names.append(f"  {name}(...)")
    return names[:5]


# Per-language class-name resolution (rust impl has no name field; go
# type_declaration nests the name inside type_spec).
def _generic_class_name(kind: str, node: Any, src: bytes) -> Optional[str]:
    if node.type == "impl_item":  # rust: impl <Type> { ... }
        for child in node.named_children:
            if child.type in ("type_identifier", "generic_type"):
                return f"impl {_node_text(child, src)}"
        return None
    if kind == "go" and node.type == "type_declaration":
        for child in node.named_children:
            if child.type == "type_spec":
                return _name_of(child, src)
        return None
    return _name_of(node, src)


def _add_chunk(
    chunks: list[dict[str, Any]],
    node: Any,
    name: str,
    symbol_type: str,
    doc_anchor: Any,
    src: bytes,
    lines: list[str],
    rel_path: str,
    comment_types: frozenset,
    method_names: list[str],
    trunc_marker: str,
) -> None:
    start = node.start_point[0]
    end = node.end_point[0] + 1
    chunk_lines = lines[start:end]
    if not chunk_lines:
        return
    if len(chunk_lines) > 50:
        display_body = "\n".join(
            chunk_lines[:40] + ["    ...", trunc_marker] + chunk_lines[-5:]
        )
    else:
        display_body = "\n".join(chunk_lines)
    sig = chunk_lines[0].strip()
    # docs attach above the OUTER statement (e.g. export ...) when present —
    # a JSDoc block is a sibling of the export, not of the decl within.
    doc = _leading_doc(doc_anchor if doc_anchor is not None else node, src, comment_types)
    body_for_emb = [sig] + method_names if symbol_type == "class" else chunk_lines
    chunks.append(
        {
            "id": _sha256_id(rel_path, name, str(start)),
            "file_path": rel_path,
            "symbol_name": name,
            "symbol_type": symbol_type,
            "start_line": start + 1,
            "end_line": end,
            "signature": sig,
            "docstring": doc,
            "body": display_body,
            "content": _truncate_for_embedding(
                rel_path, symbol_type, name, sig, doc, body_for_emb
            ),
            "content_hash": hashlib.sha256(display_body.encode()).hexdigest()[:16],
        }
    )


# ------------------------------------------------------------- extraction


def extract_chunks_treesitter(file_path: Path, root: Path) -> list[dict[str, Any]]:
    """Parse any supported non-Python source file into chunks shaped exactly
    like the Python extractor's output (same schema, same truncation rules,
    same id scheme). Error-tolerant by construction: tree-sitter yields
    ERROR nodes on broken source instead of raising."""
    kind = _kind_for(file_path.suffix.lower())
    if kind is None:
        return []
    loaded = _load_grammar(kind)
    if loaded is None:
        return []
    tree_sitter, lang = loaded

    try:
        if file_path.stat().st_size > _MAX_FILE_BYTES:
            return []  # generated bundle / minified: skip, don't choke
        source = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    src = source.encode("utf-8", "replace")
    try:
        parser = tree_sitter.Parser(lang)
        tree = parser.parse(src)
    except Exception:
        return []

    lines = source.splitlines()
    rel_path = str(file_path.relative_to(root))
    chunks: list[dict[str, Any]] = []

    # --- module header chunk (same shape as the Python one) ---
    header_lines = lines[: min(20, len(lines))]
    header_body = "\n".join(header_lines)
    chunks.append(
        {
            "id": _sha256_id(rel_path, "module"),
            "file_path": rel_path,
            "symbol_name": "(module)",
            "symbol_type": "module",
            "start_line": 1,
            "end_line": len(header_lines),
            "signature": "",
            "docstring": None,
            "body": header_body,
            "content": _truncate_for_embedding(
                rel_path, "module", "(module)", "", None, header_lines
            ),
            "content_hash": hashlib.sha256(header_body.encode()).hexdigest()[:16],
        }
    )

    if kind in ("javascript", "typescript", "tsx"):
        _walk_js_family(tree, src, lines, rel_path, chunks)
    else:
        cfg = _GENERIC_LANGS[kind]
        _walk_generic(tree, src, lines, rel_path, chunks, kind, cfg)

    return chunks


def _walk_js_family(
    tree: Any, src: bytes, lines: list[str], rel_path: str, chunks: list[dict[str, Any]]
) -> None:
    walked = 0
    for child in tree.root_node.named_children:
        walked += 1
        if walked > _MAX_NODES_WALKED:
            break
        node = child
        doc_anchor = child
        if node.type == "export_statement":
            decl = next((c for c in node.named_children if c.is_named), None)
            if decl is not None and decl.type in (
                _FUNC_TYPES | _CLASS_TYPES | _VAR_STMT_TYPES
            ):
                node = decl
            else:
                continue

        if node.type in _FUNC_TYPES:
            name = _name_of(node, src)
            if name:
                _add_chunk(chunks, node, name, "function", doc_anchor, src, lines,
                           rel_path, _JS_COMMENT_TYPES, [], "    // (truncated) ...")
        elif node.type in _CLASS_TYPES:
            name = _name_of(node, src)
            if name:
                _add_chunk(chunks, node, name, "class", doc_anchor, src, lines,
                           rel_path, _JS_COMMENT_TYPES, _js_class_method_names(node, src),
                           "    // (truncated) ...")
        elif node.type in _VAR_STMT_TYPES:
            for decl in node.named_children:
                if decl.type != "variable_declarator":
                    continue
                value = decl.child_by_field_name("value")
                if value is not None and value.type in _VALUE_FUNC_TYPES:
                    name = _name_of(decl, src)
                    if name:
                        _add_chunk(chunks, node, name, "function", doc_anchor, src,
                                   lines, rel_path, _JS_COMMENT_TYPES, [],
                                   "    // (truncated) ...")


def _walk_generic(
    tree: Any,
    src: bytes,
    lines: list[str],
    rel_path: str,
    chunks: list[dict[str, Any]],
    kind: str,
    cfg: dict[str, Any],
) -> None:
    comment_types = cfg["comment_types"]
    walked = 0
    for child in tree.root_node.named_children:
        walked += 1
        if walked > _MAX_NODES_WALKED:
            break
        if child.type in cfg["func_types"]:
            name = _name_of(child, src)
            if name:
                _add_chunk(chunks, child, name, "function", child, src, lines,
                           rel_path, comment_types, [], "    // (truncated) ...")
        elif child.type in cfg["class_types"]:
            name = _generic_class_name(kind, child, src)
            if name:
                methods = (
                    _method_names_from(child, src, cfg["method_containers"])
                    if cfg["method_containers"]
                    else []
                )
                # Rust trait/impl/java interfaces embed callable members only;
                # go structs have none to embed (methods are top-level).
                _add_chunk(chunks, child, name, "class", child, src, lines,
                           rel_path, comment_types, methods, "    // (truncated) ...")
