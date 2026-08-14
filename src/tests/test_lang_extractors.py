"""D5: multi-language chunk extraction (tree-sitter, milestone 1: JS/TS).

Pure CI tests: real tree-sitter grammars (declared deps), no embedder, no
network, temp workspaces only.
"""

import sys

import pytest

from pathlib import Path

from src.context.chunk_index import ChunkIndex, extract_chunks, extract_source_chunks
from src.context import lang_extractors as le

JS = """// Session management module
import { store } from './store.js';

/** Creates a session for the user. */
export function login(user) {
  return store.auth(user);
}

const helper = (x) => {
  return x * 2;
};

export class Session {
  start() { /* begin */ }
  stop() {}
}

const answer = 42;
"""

TS = """interface Config { port: number }

type ID = string;

// Fetch a user by id.
async function fetchUser(id: ID): Promise<void> {}

export class Api {
  private url = "";
  async get() {}
}
"""

TSX = """/** Main app component */
export const App = () => {
  return <div className="app">Hello</div>;
};

function useData() {
  return { data: [] };
}
"""


def _names(chunks):
    return {c["symbol_name"]: c for c in chunks}


# ---------------------------------------------------------- extraction


def test_js_functions_classes_and_ignores(tmp_path):
    src = tmp_path / "app.js"
    src.write_text(JS)
    chunks = extract_source_chunks(src, tmp_path)
    by = _names(chunks)

    assert by["login"]["symbol_type"] == "function"
    assert by["login"]["start_line"] == 5  # export unwrapped to the decl
    assert by["helper"]["symbol_type"] == "function"  # arrow const
    assert by["Session"]["symbol_type"] == "class"
    assert "  start(...)" in by["Session"]["content"]  # methods embedded
    assert "answer" not in by  # non-function const is not a chunk
    assert by["(module)"]["symbol_type"] == "module"


def test_ts_types_ignored_functions_kept(tmp_path):
    src = tmp_path / "api.ts"
    src.write_text(TS)
    by = _names(extract_source_chunks(src, tmp_path))

    assert "fetchUser" in by
    assert "Api" in by and by["Api"]["symbol_type"] == "class"
    assert "Config" not in by  # interface: type-level, not callable code
    assert "ID" not in by      # type alias: same
    assert by["fetchUser"]["docstring"] == "// Fetch a user by id."


def test_tsx_component_and_hook(tmp_path):
    src = tmp_path / "App.tsx"
    src.write_text(TSX)
    by = _names(extract_source_chunks(src, tmp_path))
    assert "App" in by and "useData" in by


def test_jsdoc_above_export_attaches(tmp_path):
    src = tmp_path / "app.js"
    src.write_text(JS)
    by = _names(extract_source_chunks(src, tmp_path))
    assert by["login"]["docstring"] == "/** Creates a session for the user. */"
    src2 = tmp_path / "App.tsx"
    src2.write_text(TSX)
    by2 = _names(extract_source_chunks(src2, tmp_path))
    assert by2["App"]["docstring"] == "/** Main app component */"


def test_broken_source_never_crashes(tmp_path):
    src = tmp_path / "broken.js"
    src.write_text("const x = {] broken; function f(")
    chunks = extract_source_chunks(src, tmp_path)  # tree-sitter is error-tolerant
    assert chunks and chunks[0]["symbol_type"] == "module"


def test_unsupported_suffix_extracts_nothing(tmp_path):
    src = tmp_path / "style.css"
    src.write_text("body { color: red; }")
    assert extract_source_chunks(src, tmp_path) == []


def test_schema_parity_with_python(tmp_path):
    py = tmp_path / "mod.py"
    py.write_text('"""module doc."""\n\ndef f():\n    return 1\n')
    js = tmp_path / "mod.js"
    js.write_text(JS)
    py_keys = set(extract_chunks(py, tmp_path)[0].keys())
    js_keys = set(extract_source_chunks(js, tmp_path)[0].keys())
    assert py_keys == js_keys


# ---------------------------------------------------------- degradation


def test_python_only_degradation_is_loud_once(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(le, "_GRAMMARS", {})
    monkeypatch.setattr(le, "_FAILED", set())
    monkeypatch.setattr(le, "_NOTICED", False)
    for mod_name in ("tree_sitter_javascript", "tree_sitter_typescript",
                     "tree_sitter_go", "tree_sitter_rust", "tree_sitter_java"):
        monkeypatch.setitem(sys.modules, mod_name, None)  # imports fail

    assert le._load_grammar("javascript") is None
    assert le._load_grammar("typescript") is None
    assert le._load_grammar("go") is None
    assert le.source_extensions() == frozenset({".py"})

    src = tmp_path / "app.js"
    src.write_text(JS)
    assert extract_source_chunks(src, tmp_path) == []

    out = capsys.readouterr().out
    assert out.count("tree-sitter grammar") == 1  # loud exactly ONCE


# ---------------------------------------------------------- index e2e


def test_index_mixed_workspace_search_and_sync(tmp_path):
    (tmp_path / "auth.py").write_text(
        'def validate_password(pw):\n    """Check pw rules."""\n    return len(pw) > 7\n'
    )
    (tmp_path / "app.js").write_text(JS)
    (tmp_path / "api.ts").write_text(TS)

    idx = ChunkIndex(tmp_path, db_path=str(tmp_path / "idx.db"), embedder=None, watch=False)
    idx.index_workspace()

    files = {
        r.file_path
        for r in idx.search("login session", top_k=10)
    }
    assert "app.js" in files  # the JS login/Session chunks are retrievable

    hits = {r.symbol_name for r in idx.search("fetchUser", top_k=10)}
    assert "fetchUser" in hits  # BM25 finds the TS function by name

    py_hits = {r.symbol_name for r in idx.search("validate_password", top_k=10)}
    assert "validate_password" in py_hits  # Python path unchanged

    # incremental sync on a JS edit: new symbol becomes searchable
    (tmp_path / "app.js").write_text(JS + "\nexport function logout(u) { store.bye(u); }\n")
    idx.sync_workspace()
    assert any(r.symbol_name == "logout" for r in idx.search("logout", top_k=10))

    # remove_file cleans JS ghosts, too
    removed = idx.remove_file(tmp_path / "app.js")
    assert removed > 0
    assert not [r for r in idx.search("logout", top_k=10) if r.file_path == "app.js"]


def test_edited_file_reembeds_only_changed_chunks(tmp_path, monkeypatch):
    """D2×D5 synergy: syncing a small edit must not re-embed every chunk."""
    import hashlib
    import math

    class _Vec:
        def __init__(self, rows):
            self._rows = rows

        def tolist(self):
            return [list(r) for r in self._rows]

    class _CountingEmbedder:
        def __init__(self, dim=4):
            self.dim = dim
            self.encoded = 0

        def encode(self, texts, normalize_embeddings=True):
            self.encoded += len(texts)
            rows = []
            for t in texts:
                h = hashlib.sha256(t.encode()).digest()
                row = [((h[i] % 32) - 16) / 16.0 for i in range(self.dim)]
                n = math.sqrt(sum(x * x for x in row))
                rows.append([x / (n or 1) for x in row] + [0.0] * (384 - self.dim))
            return _Vec(rows)

    from src.context.embedding_cache import EmbeddingCache

    embedder = _CountingEmbedder()
    cache = EmbeddingCache()
    # _embed_batch imports get_embedding_cache lazily from the module at call
    # time, so patching the module attribute routes it to this fresh cache.
    monkeypatch.setattr(
        "src.context.embedding_cache.get_embedding_cache", lambda: cache
    )

    (tmp_path / "app.js").write_text(JS)
    idx = ChunkIndex(tmp_path, db_path=str(tmp_path / "idx.db"), embedder=embedder, watch=False)
    idx.index_workspace()
    first = embedder.encoded  # module + 3 decls = 4 chunks
    assert first == 4

    # tiny edit: append one function -> only it (and any header churn) re-embeds
    (tmp_path / "app.js").write_text(JS + "\nexport function logout(u) { store.bye(u); }\n")
    idx.sync_workspace()
    delta = embedder.encoded - first
    assert delta <= 2, f"re-sync embedded {delta} chunks instead of ~1"


# ---------------------------------------------------------- D5-2: go/rust/java


GO = """// Package main entry.
package main

import "fmt"

// Login authenticates a user.
func Login(u string) error { return nil }

type Session struct { ttl int }

// Start begins the session.
func (s *Session) Start() { fmt.Println(s.ttl) }
"""

RUST = """/// Authenticate a user.
pub fn login(u: &str) -> bool { true }

struct Session { ttl: u32 }

impl Session {
    /// Begin the session.
    pub fn start(&self) {}
    fn stop(&mut self) {}
}

trait Stoppable { fn halt(&self); }
"""

JAVA = """package com.pulse;

/** User service. */
class UserService {
    private int ttl;
    UserService(int t) { this.ttl = t; }
    public User login(String u) { return new User(u); }
}

interface Repo { User get(String id); }
"""


def test_go_functions_methods_struct(tmp_path):
    src = tmp_path / "main.go"
    src.write_text(GO)
    by = _names(extract_source_chunks(src, tmp_path))
    assert by["Login"]["symbol_type"] == "function"
    assert by["Login"]["docstring"] == "// Login authenticates a user."
    assert by["Session"]["symbol_type"] == "class"          # struct, via type_spec
    assert by["Start"]["symbol_type"] == "function"          # receiver method: top-level chunk
    assert by["Start"]["docstring"] == "// Start begins the session."


def test_rust_fn_struct_impl_trait(tmp_path):
    src = tmp_path / "lib.rs"
    src.write_text(RUST)
    by = _names(extract_source_chunks(src, tmp_path))
    assert by["login"]["symbol_type"] == "function"
    assert by["login"]["docstring"].startswith("/// Authenticate")
    assert by["Session"]["symbol_type"] == "class"
    assert by["impl Session"]["symbol_type"] == "class"      # name resolved from type_identifier
    assert "  start(...)" in by["impl Session"]["content"]   # methods embedded
    assert by["Stoppable"]["symbol_type"] == "class"         # trait


def test_java_class_interface_javadoc(tmp_path):
    src = tmp_path / "UserService.java"
    src.write_text(JAVA)
    by = _names(extract_source_chunks(src, tmp_path))
    assert by["UserService"]["docstring"] == "/** User service. */"
    assert "  UserService(...)" in by["UserService"]["content"]  # constructor listed
    assert "  login(...)" in by["UserService"]["content"]
    assert by["Repo"]["symbol_type"] == "class"              # interface
    assert "login" not in by                                 # no standalone method chunks


def test_new_languages_tolerant_of_broken_source(tmp_path):
    for name, text in [("bad.rs", "fn broken( { {{{"), ("bad.go", "func ((( oops")]:
        src = tmp_path / name
        src.write_text(text)
        chunks = extract_source_chunks(src, tmp_path)
        assert chunks and chunks[0]["symbol_type"] == "module"


def test_source_extensions_cover_d5_2(tmp_path):
    exts = le.source_extensions()
    assert {".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java"} <= exts


def test_index_e2e_go_rust_java(tmp_path):
    (tmp_path / "main.go").write_text(GO)
    (tmp_path / "lib.rs").write_text(RUST)
    (tmp_path / "UserService.java").write_text(JAVA)
    (tmp_path / "auth.py").write_text("def validate_token(t):\n    return True\n")

    idx = ChunkIndex(tmp_path, db_path=str(tmp_path / "idx.db"), embedder=None, watch=False)
    idx.index_workspace()

    assert any(r.symbol_name == "Login" and r.file_path == "main.go"
               for r in idx.search("Login authenticates", top_k=10))
    assert any(r.symbol_name == "impl Session"
               for r in idx.search("Session", top_k=10))
    assert any(r.symbol_name == "UserService"
               for r in idx.search("user service login", top_k=10))
    assert any(r.symbol_name == "validate_token"
               for r in idx.search("validate_token", top_k=10))  # python unchanged

    (tmp_path / "lib.rs").write_text(RUST + "\npub fn logout(u: &str) {}\n")
    idx.sync_workspace()
    assert any(r.symbol_name == "logout" for r in idx.search("logout", top_k=10))

    removed = idx.remove_file(tmp_path / "main.go")
    assert removed > 0
    assert not [r for r in idx.search("Login", top_k=10) if r.file_path == "main.go"]


def test_iter_source_files_yields_all_supported(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.js").write_text(JS)
    sub = tmp_path / "web"
    sub.mkdir()
    (sub / "c.tsx").write_text(TSX)
    (tmp_path / "d.css").write_text("body{}\n")
    hidden = tmp_path / "node_modules"
    hidden.mkdir()
    (hidden / "e.js").write_text("function skipped() {}\n")

    idx = ChunkIndex(tmp_path, db_path=str(tmp_path / "idx.db"), embedder=None, watch=False)
    found = {f.name for f in idx._iter_source_files()}
    assert {"a.py", "b.js", "c.tsx"} <= found
    assert "d.css" not in found
    assert "e.js" not in found  # skip-dirs still apply


# ---------------------------------------------------------------------
# D15-remainder pins (§41): import edges for JS/TS, Go, Rust, Java
# ---------------------------------------------------------------------

from src.context.lang_extractors import (
    extract_js_import_edges,
    extract_go_import_edges,
    extract_rust_import_edges,
    extract_java_import_edges,
)


def _mk(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp_path


def test_d15_js_ts_edges(tmp_path):
    ws = _mk(tmp_path, {
        "src/util.ts": "export const u = 1;\n",
        "src/lib/api.ts": "export const a = 1;\n",
        "src/lib/index.ts": "export * from './api';\n",
        "node_modules_skip.ts": "",
    })
    src = (
        "import { u } from './util';\n"
        "export { a } from './lib/api';\n"
        "const dyn = import('./util');\n"
        "const rq = require('./lib');\n"
        "import './util';\n"
        "import React from 'react';\n"
    )
    edges = extract_js_import_edges(src, Path("src/app.ts"), ws)
    assert str(Path("src/util.ts")) in edges
    assert str(Path("src/lib/api.ts")) in edges          # export-from + ./lib -> index.ts
    assert str(Path("src/lib/index.ts")) in edges
    assert all("react" not in e for e in edges)          # bare specifier dropped


def test_d15_go_edges_package_dirs(tmp_path):
    ws = _mk(tmp_path, {
        "go.mod": "module github.com/me/proj\n",
        "cmd/server/main.go": "package main\n",
        "internal/auth/session.go": "package auth\n",
        "internal/auth/helpers.go": "package auth\n",
    })
    src = (
        "package main\n\n"
        "import (\n"
        '    "fmt"\n'
        '    "github.com/me/proj/internal/auth"\n'
        ")\n\n"
        'import alias "github.com/me/proj/internal/auth"\n'
    )
    edges = extract_go_import_edges(src, Path("cmd/server/main.go"), ws)
    assert str(Path("internal/auth/session.go")) in edges
    assert str(Path("internal/auth/helpers.go")) in edges
    assert all("fmt" not in e for e in edges)


def test_d15_rust_edges(tmp_path):
    ws = _mk(tmp_path, {
        "src/main.rs": "fn main() {}\n",
        "src/auth.rs": "pub fn s() {}\n",
        "src/store/mod.rs": "pub mod mem;\n",
        "src/store/mem.rs": "pub fn m() {}\n",
    })
    src_main = (
        "mod auth;\n"
        "mod store;\n"
        "use crate::auth::s;\n"
        "use serde::Serialize;\n"
    )
    edges = extract_rust_import_edges(src_main, Path("src/main.rs"), ws)
    assert str(Path("src/auth.rs")) in edges
    assert str(Path("src/store/mod.rs")) in edges        # mod declaration
    assert all("serde" not in e for e in edges)          # external crate dropped

    # use self:: / super:: from a nested module
    edges2 = extract_rust_import_edges(
        "use super::auth::s;\n", Path("src/store/mem.rs"), ws)
    assert str(Path("src/auth.rs")) in edges2


def test_d15_java_edges(tmp_path):
    ws = _mk(tmp_path, {
        "src/main/java/com/example/app/Main.java": "class Main {}\n",
        "src/main/java/com/example/auth/Session.java": "class Session {}\n",
        "src/main/java/com/example/auth/Tokens.java": "class Tokens {}\n",
    })
    src = (
        "package com.example.app;\n\n"
        "import com.example.auth.Session;\n"
        "import static com.example.auth.Tokens;\n"
        "import java.util.List;\n"
        "import com.external.lib.*;\n"
    )
    edges = extract_java_import_edges(
        src, Path("src/main/java/com/example/app/Main.java"), ws)
    assert str(Path("src/main/java/com/example/auth/Session.java")) in edges
    assert str(Path("src/main/java/com/example/auth/Tokens.java")) in edges
    assert not any("java/util" in e or "external" in e for e in edges)


def test_d15_edges_flow_into_index(tmp_path):
    """Integration: a mixed workspace indexes edges for ALL languages into
    the SAME import_edges table, in the chunk-row transactions."""
    from src.context.chunk_index import ChunkIndex

    ws = _mk(tmp_path, {
        "core.py": "import util\n",
        "util.py": "X = 1\n",
        "app.ts": "import { u } from './helper';\n",
        "helper.ts": "export const u = 1;\n",
        "main.go": 'package main\n\nimport "mod/pkg"\n',
        "pkg/p.go": "package pkg\n",
    })
    (ws / "go.mod").write_text("module mod\n")
    # embedder=None: edges are storage-level metadata, embedding-independent
    idx = ChunkIndex(ws, db_path=str(tmp_path / "idx.db"), embedder=None, watch=False)
    idx.index_workspace()
    rows = set(idx.conn.execute(
        "SELECT importer, imported FROM import_edges").fetchall())
    assert (str(Path("core.py")), str(Path("util.py"))) in rows
    assert (str(Path("app.ts")), str(Path("helper.ts"))) in rows
    assert (str(Path("main.go")), str(Path("pkg/p.go"))) in rows


def test_d15_edges_never_raise_on_garbage(tmp_path):
    ws = _mk(tmp_path, {"a.ts": "x\n"})
    for fn, rel in (
        (extract_js_import_edges, "a.ts"),
        (extract_go_import_edges, "a.go"),
        (extract_rust_import_edges, "a.rs"),
        (extract_java_import_edges, "A.java"),
    ):
        assert fn("!!!!(((({{{{", Path(rel), ws) == set()
        assert fn("", Path(rel), ws) == set()
