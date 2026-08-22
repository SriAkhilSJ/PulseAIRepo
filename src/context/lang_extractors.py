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
import re
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


def extract_chunks_treesitter(
    file_path: Path, root: Path, source: str | None = None
) -> list[dict[str, Any]]:
    """Parse any supported non-Python source file into chunks shaped exactly
    like the Python extractor's output (same schema, same truncation rules,
    same id scheme). Error-tolerant by construction: tree-sitter yields
    ERROR nodes on broken source instead of raising.

    ``source`` (P1): the file's decoded text when the caller already read it
    once for the physical-read ledger — avoids a second physical read.
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
                # Rust trait/impl/java interfaces embed callable members only;
                # go structs have none to embed (methods are top-level).
                _add_chunk(chunks, child, name, "class", child, src, lines,
                           rel_path, comment_types, methods, "    // (truncated) ...")


# ---------------------------------------------------------------------
# IMPORT EDGES (D15-remainder, §41): JS/TS, Go, Rust, Java
# ---------------------------------------------------------------------
# The Python resolver (verified in the D15 Python slice) lives in
# chunk_index.py; these are its siblings for the D5 languages. Same
# doctrine: bounded candidate checks against the filesystem (no repo
# walks, no DB reads — determinism independent of indexing order), edges
# only between workspace files, never raises — edges are a retrieval
# bonus, not a failure mode. Extraction is regex/line based on purpose
# (fast, dependency-free); a false edge from a comment is harmless
# metadata compared to the cost of full AST parses per sync.

_EXT_JS_FAMILY = frozenset(set(_EXT_JS) | set(_EXT_TS) | set(_EXT_TSX))
_JS_RESOLVE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs")


def extract_js_import_edges(source: str, importer_rel: Path, workspace: Path) -> set[str]:
    """JS/TS: import/export-from, require(), dynamic import(), side-effect
    imports. Only RELATIVE specifiers resolve (bare 'react' etc. dropped —
    monorepo alias mapping is a future bonus, not correctness)."""
    specs: set[str] = set()
    for m in re.finditer(r"""(?:import|export)\s[^;'"]*?from\s*['"]([^'"]+)['"]""", source):
        specs.add(m.group(1))
    for m in re.finditer(r"""import\s*['"]([^'"]+)['"]""", source):  # side-effect
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
            candidates.append(base)                       # explicit ext
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
    """Go: single + grouped (+ aliased/dot) imports. A Go import names a
    PACKAGE directory, not a file — resolve the module-path tail to a
    workspace directory (longest match wins, stdlib like "fmt" has no
    workspace dir so drops for free), then edge to up to 5 .go files in it."""
    specs: set[str] = set()
    for m in re.finditer(r"import\s*\(([^)]*)\)", source, re.DOTALL):
        for q in re.finditer(r'"([^"]+)"', m.group(1)):
            specs.add(q.group(1))
    for m in re.finditer(r'import\s+(?:[\w.]+\s+)?"([^"]+)"', source):
        specs.add(m.group(1))

    targets: set[str] = set()
    for spec in specs:
        parts = spec.split("/")
        # progressively trim module-prefix segments; longest dir match wins
        # (trim may go down to the last segment: module "mod" + pkg tail
        # resolves "mod/pkg" -> "pkg" when ./mod/pkg doesn't exist).
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
    """Rust: `mod name;` declarations and `use crate::/self::/super::` paths
    (external crates like serde:: dropped). Leaf resolves to .rs or mod.rs.
    `use a::b::{c, d}` resolves the PATH part (a/b) — item-level edges are
    not needed for file->file."""
    targets: set[str] = set()
    importer_str = str(importer_rel)

    def _add(base: Path) -> None:
        # The LAST ::segment of a use-path is usually an ITEM inside the
        # parent module's file (use crate::auth::Session -> src/auth.rs),
        # so check the parent path as well as the full path. Full path wins
        # (module-file over item ambiguity).
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
        body = m.group(1).split("{")[0]           # drop item lists
        body = re.sub(r"\s+as\s+\w+", "", body)   # drop renames
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
            continue                                # external crate: dropped
        base = base / Path(*rest) if rest else base
        _add(base)

    targets.discard(importer_str)
    return targets


def extract_java_import_edges(source: str, importer_rel: Path, workspace: Path) -> set[str]:
    """Java: import (incl. static) dotted paths. Bounded candidates:
    layout prefixes ["", src/main/java, src] + dotted path, then the
    importer's own package dir (same-package files need no import, but
    nested test projects often import their siblings). Wildcard imports
    resolve the PACKAGE only when it maps to a single obvious sibling dir —
    skipped otherwise (bounded-check doctrine)."""
    targets: set[str] = set()
    importer_str = str(importer_rel)
    prefixes = [Path(""), Path("src/main/java"), Path("src")]

    for m in re.finditer(r"(?m)^\s*import\s+(?:static\s+)?([\w.]+)(\.\*)?\s*;", source):
        parts = m.group(1).split(".")
        wildcard = bool(m.group(2))
        if wildcard:
            continue  # package-level: no single bounded candidate
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
