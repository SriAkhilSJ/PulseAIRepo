# src/context/lang_extractors.py
"""Multi-language source chunk extraction (debt D5, milestone 1: JS/TS family).

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

Scope discipline (milestone 1): the JS/TS family — .js/.jsx/.mjs/.cjs and
.ts/.tsx/.cts/.mts. That covers the web stack AND this repo's own
dashboard/desktop languages. Python keeps its richer stdlib-ast extractor
in chunk_index.py (handles async/decorators; verified). More grammars
(go/rust/java) are a config-level follow-up once this pattern is proven.

Degradation contract (same pattern as the watchdog dep): grammars are
declared dependencies, but a slim/broken environment must never take down
PYTHON indexing — any load failure degrades to Python-only with exactly
one loud notice per process.
"""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any, Optional

EMBED_HARD_CAP_CHARS = 800  # ~200 tokens at ~4 chars/token (embed window)

_EXT_JS = frozenset({".js", ".jsx", ".mjs", ".cjs"})
_EXT_TS = frozenset({".ts", ".cts", ".mts"})
_EXT_TSX = frozenset({".tsx"})

_LOAD_LOCK = threading.Lock()
_GRAMMARS: dict[str, tuple[Any, Any]] = {}   # kind -> (tree_sitter module, Language)
_FAILED: set[str] = set()
_NOTICED = False

_FUNC_TYPES = frozenset({"function_declaration", "generator_function_declaration"})
_CLASS_TYPES = frozenset({"class_declaration", "abstract_class_declaration"})
_VAR_STMT_TYPES = frozenset({"lexical_declaration", "variable_declaration"})
_VALUE_FUNC_TYPES = frozenset({"arrow_function", "function_expression"})
_METHOD_TYPES = frozenset({"method_definition", "method_signature"})

# Cutting safety valves: mega generated bundles shouldn't O(n) us to death.
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_NODES_WALKED = 50_000


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

            if kind == "javascript":
                import tree_sitter_javascript as mod

                lang = tree_sitter.Language(mod.language())
            elif kind == "typescript":
                import tree_sitter_typescript as mod

                lang = tree_sitter.Language(mod.language_typescript())
            elif kind == "tsx":
                import tree_sitter_typescript as mod

                lang = tree_sitter.Language(mod.language_tsx())
            else:  # pragma: no cover - internal dispatch only
                return None
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
    return frozenset(exts)


def _kind_for(ext: str) -> Optional[str]:
    if ext in _EXT_JS:
        return "javascript"
    if ext in _EXT_TS:
        return "typescript"
    if ext in _EXT_TSX:
        return "tsx"
    return None


def _node_text(node: Any, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _name_of(node: Any, src: bytes) -> Optional[str]:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    return _node_text(name_node, src)


def _leading_doc(node: Any, src: bytes) -> Optional[str]:
    """Nearest contiguous block of comments directly above a declaration —
    the JS/TS stand-in for a docstring."""
    docs: list[str] = []
    sib = node.prev_named_sibling
    while sib is not None and sib.type == "comment" and len(docs) < 6:
        # Contiguous lines only: a detached comment block belongs to itself.
        if docs and sib.end_point[0] < docs[-1][0] - 1:
            break
        docs.append((sib.start_point[0], _node_text(sib, src)))
        sib = sib.prev_named_sibling
    if not docs:
        return None
    docs.reverse()
    return "\n".join(text for _, text in docs)[:400]


def _class_method_names(class_node: Any, src: bytes) -> list[str]:
    body = class_node.child_by_field_name("body")
    names: list[str] = []
    if body is not None:
        for child in body.named_children:
            if child.type in _METHOD_TYPES:
                name = _name_of(child, src)
                if name:
                    names.append(f"  {name}(...)")
    return names[:5]


def extract_chunks_ts_js(file_path: Path, root: Path) -> list[dict[str, Any]]:
    """Parse a JS/TS-family file into chunks shaped exactly like the Python
    extractor's output (same schema, same truncation rules, same ids)."""
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

    def add_chunk(
        node: Any,
        name: str,
        symbol_type: str,
        doc_anchor: Any = None,
    ) -> None:
        start = node.start_point[0]
        end = node.end_point[0] + 1
        chunk_lines = lines[start:end]
        if not chunk_lines:
            return
        if len(chunk_lines) > 50:
            display_body = "\n".join(
                chunk_lines[:40] + ["    ...", "    // (truncated) ..."] + chunk_lines[-5:]
            )
        else:
            display_body = "\n".join(chunk_lines)
        sig = chunk_lines[0].strip()
        # docs attach above the OUTER statement (export ...) when present —
        # a JSDoc block is a sibling of the export, not of the decl within.
        doc = _leading_doc(doc_anchor if doc_anchor is not None else node, src)
        if symbol_type == "class":
            body_for_emb = [sig] + _class_method_names(node, src)
        else:
            body_for_emb = chunk_lines
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

    # --- top-level declarations (error-tolerant walk; tree-sitter never
    # throws on broken source, it yields ERROR nodes we simply skip) ---
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
                add_chunk(node, name, "function", doc_anchor)
        elif node.type in _CLASS_TYPES:
            name = _name_of(node, src)
            if name:
                add_chunk(node, name, "class", doc_anchor)
        elif node.type in _VAR_STMT_TYPES:
            for decl in node.named_children:
                if decl.type != "variable_declarator":
                    continue
                value = decl.child_by_field_name("value")
                if value is not None and value.type in _VALUE_FUNC_TYPES:
                    name = _name_of(decl, src)
                    if name:
                        add_chunk(node, name, "function", doc_anchor)

    return chunks
