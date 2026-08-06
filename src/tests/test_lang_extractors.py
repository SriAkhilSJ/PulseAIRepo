"""D5: multi-language chunk extraction (tree-sitter, milestone 1: JS/TS).

Pure CI tests: real tree-sitter grammars (declared deps), no embedder, no
network, temp workspaces only.
"""

import sys

import pytest

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
    monkeypatch.setitem(sys.modules, "tree_sitter_javascript", None)  # import fails
    monkeypatch.setitem(sys.modules, "tree_sitter_typescript", None)

    assert le._load_grammar("javascript") is None
    assert le._load_grammar("typescript") is None
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
