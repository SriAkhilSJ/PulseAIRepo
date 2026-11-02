"""
Tree-sitter Source Extractor
============================

Concrete syntax tree chunk extraction and import edge analysis for
non-Python source files (JS/TS family, Go, Rust, Java).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Optional

from src.context.extraction.language_registry import (
    _EXT_JS_FAMILY,
    _GENERIC_LANGS,
    _kind_for,
    _load_grammar,
)
from src.context.extraction.python_extractor import (
    _sha256_id,
    _truncate_for_embedding,
)

# Cutting safety valves: mega generated bundles shouldn't O(n) us to death.
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_NODES_WALKED = 50_000

# JS/TS-family walk sets (specialized: export unwrap + variable declarators)
_FUNC_TYPES = frozenset({"function_declaration", "generator_function_declaration"})
_CLASS_TYPES = frozenset({"class_declaration", "abstract_class_declaration"})
_VAR_STMT_TYPES = frozenset({"lexical_declaration", "variable_declaration"})
_VALUE_FUNC_TYPES = frozenset({"arrow_function", "function_expression"})
_METHOD_TYPES = frozenset({"method_definition", "method_signature"})
_JS_COMMENT_TYPES = frozenset({"comment"})


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
    nodes; JSDoc `/** */` are block_comment; go `//` are comment).
    """
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
    rust declaration_list, java class/interface_body).
    """
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


def extract_chunks_treesitter(
    file_path: Path, root: Path, source: str | None = None
) -> list[dict[str, Any]]:
    """Parse any supported non-Python source file into chunks shaped exactly
    like the Python extractor's output (same schema, same truncation rules,
    same id scheme). Error-tolerant by construction: tree-sitter yields
    ERROR nodes on broken source instead of raising.
    """
    kind = _kind_for(file_path.suffix.lower())
    if kind is None:
        return []
    loaded = _load_grammar(kind)
    if loaded is None:
        return []
    tree_sitter, lang = loaded

    try:
        if source is None:
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
                _add_chunk(chunks, child, name, "class", child, src, lines,
                           rel_path, comment_types, methods, "    // (truncated) ...")


# ---------------------------------------------------------------------
# Import edges for non-Python source files
# ---------------------------------------------------------------------

_JS_RESOLVE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs")


def extract_js_import_edges(source: str, importer_rel: Path, workspace: Path) -> set[str]:
    """JS/TS: import/export-from, require(), dynamic import(), side-effect
    imports. Only RELATIVE specifiers resolve.
    """
    specs: set[str] = set()
    for m in re.finditer(r"""(?:import|export)\s[^;'"]*?from\s*['"]([^'"]+)['"]""", source):
        specs.add(m.group(1))
    for m in re.finditer(r"""import\s*['"]([^'"]+)['"]""", source):
        specs.add(m.group(1))
    for m in re.finditer(r"""require\(\s*['"]([^'"]+)['"]\s*\)""", source):
        specs.add(m.group(1))
    for m in re.finditer(r"""import\(\s*['"]([^'"]+)['"]\s*\)""", source):
        specs.add(m.group(1))

    targets: set[str] = set()
    for spec in specs:
        if not spec.startswith("."):
            continue
        base = importer_rel.parent / spec
        candidates: list[Path] = []
        if base.suffix.lower() in _EXT_JS_FAMILY:
            candidates.append(base)
        else:
            candidates.extend(Path(str(base) + e) for e in _JS_RESOLVE_EXTS)
            candidates.extend(base / f"index{e}" for e in _JS_RESOLVE_EXTS)
        for cand in candidates:
            try:
                if (workspace / cand).is_file():
                    targets.add(str(cand))
                    break
            except OSError:
                continue
    targets.discard(str(importer_rel))
    return targets


def extract_go_import_edges(source: str, importer_rel: Path, workspace: Path) -> set[str]:
    """Go: single + grouped (+ aliased/dot) imports."""
    specs: set[str] = set()
    for m in re.finditer(r"import\s*\(([^)]*)\)", source, re.DOTALL):
        for q in re.finditer(r'"([^"]+)"', m.group(1)):
            specs.add(q.group(1))
    for m in re.finditer(r'import\s+(?:[\w.]+\s+)?"([^"]+)"', source):
        specs.add(m.group(1))

    targets: set[str] = set()
    for spec in specs:
        parts = spec.split("/")
        for trim in range(0, min(4, len(parts))):
            cand_dir = Path(*parts[trim:])
            try:
                if (workspace / cand_dir).is_dir():
                    for f in sorted((workspace / cand_dir).glob("*.go"))[:5]:
                        rel = f.relative_to(workspace)
                        if str(rel) != str(importer_rel):
                            targets.add(str(rel))
                    break
            except OSError:
                continue
    return targets


def _rust_file_candidates(base: Path) -> list[Path]:
    return [base.with_suffix(".rs"), base / "mod.rs"]


def extract_rust_import_edges(source: str, importer_rel: Path, workspace: Path) -> set[str]:
    """Rust: mod declarations and use crate::/self::/super:: paths."""
    targets: set[str] = set()
    importer_str = str(importer_rel)

    def _add(base: Path) -> None:
        bases = [base]
        if base.name:
            bases.append(base.parent)
        for b in bases:
            for cand in _rust_file_candidates(b):
                try:
                    if (workspace / cand).is_file():
                        targets.add(str(cand))
                        return
                except OSError:
                    continue

    for m in re.finditer(r"(?m)^\s*(?:pub\s+)?mod\s+([A-Za-z_]\w*)\s*;", source):
        name = m.group(1)
        if name not in {"self", "super", "crate"}:
            _add(importer_rel.parent / name)

    for m in re.finditer(r"(?m)^\s*(?:pub\s+)?use\s+([^;]+);", source):
        body = m.group(1).split("{")[0]
        body = re.sub(r"\s+as\s+\w+", "", body)
        segs = [s for s in body.strip().strip(":").split("::") if s]
        if not segs:
            continue
        head, rest = segs[0], segs[1:]
        if head == "crate":
            base = Path("")
        elif head == "self":
            base = importer_rel.parent
        elif head == "super":
            climbs = 1
            while rest and rest[0] == "super":
                climbs += 1
                rest = rest[1:]
            base = importer_rel.parent
            for _ in range(climbs):
                base = base.parent
        else:
            continue
        base = base / Path(*rest) if rest else base
        _add(base)

    targets.discard(importer_str)
    return targets


def extract_java_import_edges(source: str, importer_rel: Path, workspace: Path) -> set[str]:
    """Java: import (including static) dotted paths."""
    targets: set[str] = set()
    importer_str = str(importer_rel)
    prefixes = [Path(""), Path("src/main/java"), Path("src")]

    for m in re.finditer(r"(?m)^\s*import\s+(?:static\s+)?([\w.]+)(\.\*)?\s*;", source):
        parts = m.group(1).split(".")
        wildcard = bool(m.group(2))
        if wildcard:
            continue
        rel_path = Path(*parts).with_suffix(".java")
        hit = None
        for pre in prefixes:
            cand = pre / rel_path
            try:
                if (workspace / cand).is_file():
                    hit = cand
                    break
            except OSError:
                continue
        if hit is None:
            tail = Path(*parts[-1:]).with_suffix(".java")
            cand = importer_rel.parent / tail
            try:
                if (workspace / cand).is_file():
                    hit = cand
            except OSError:
                pass
        if hit is not None:
            targets.add(str(hit))

    targets.discard(importer_str)
    return targets


__all__ = [
    "extract_chunks_treesitter",
    "extract_js_import_edges",
    "extract_go_import_edges",
    "extract_rust_import_edges",
    "extract_java_import_edges",
    "_MAX_FILE_BYTES",
    "_MAX_NODES_WALKED",
    "_node_text",
    "_name_of",
    "_leading_doc",
    "_method_names_from",
    "_js_class_method_names",
    "_generic_class_name",
    "_add_chunk",
    "_walk_js_family",
    "_walk_generic",
    "_JS_RESOLVE_EXTS",
    "_rust_file_candidates",
]
