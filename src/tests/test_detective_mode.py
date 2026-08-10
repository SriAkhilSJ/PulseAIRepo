"""Detective mode — import-linked retrieval expansion (ARCHITECTURE_REVIEW.md §26).

Covers: edge resolution (dotted/from/relative imports), dual-direction
relations in the context layer, hard caps, edit-sync of edges, v2
migration (PRAGMA user_version), and JS tolerance (no edges, no crash).
No network; fake embedder; sqlite-vec optional.
"""

import hashlib
import math
import re
from pathlib import Path

import pytest

import src.context.chunk_index as ci_mod
from src.context.chunk_index import (
    ChunkIndex,
    _extract_py_import_edges,
    _related_files_lines,
    build_relevant_chunks_layer,
)


class _Embeds(list):
    def tolist(self):
        return list(self)


class FakeEmbedder:
    DIM = 384

    def encode(self, texts, normalize_embeddings=True):
        out = _Embeds()
        for text in texts:
            vec = [0.0] * self.DIM
            for word in re.findall(r"\w+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vec[h % self.DIM] += 1.0 if (h >> 8) % 2 == 0 else -1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


BASE_PY = {
    "repo.py": '"""Accounts storage."""\n\n\ndef fetch_user(user_id):\n    """Load one user row from the accounts table."""\n    return {"id": user_id}\n',
    "service.py": '"""Session services."""\nimport repo\n\n\ndef validate_session_token(token):\n    """Check a session token expiry and load the matching user row."""\n    return repo.fetch_user(token["uid"])\n',
    "app.py": '"""Entry point."""\nimport service\n\n\ndef main_entry():\n    """Run the session validator."""\n    service.validate_session_token({})\n',
    "lonely.py": "def untouched_helper():\n    return 42\n",
}


def _write(ws: Path, files: dict[str, str]) -> None:
    for rel, src in files.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src)


@pytest.fixture()
def ws_and_index(tmp_path, monkeypatch):
    ws = tmp_path / "proj"
    ws.mkdir()
    _write(ws, BASE_PY)
    monkeypatch.setattr(ci_mod.ChunkIndex, "start_watcher", lambda self: None)
    idx = ChunkIndex(str(ws), db_path=str(tmp_path / "ci.db"), watch=False,
                     embedder=FakeEmbedder())
    idx.sync_workspace()
    key = str(ws.resolve())
    monkeypatch.setitem(ci_mod._INDEX_CACHE, key, idx)
    yield ws, idx
    idx.conn.close()


def _edges(idx, importer):
    with idx._write_lock:
        return {r[0] for r in idx.conn.execute(
            "SELECT imported FROM import_edges WHERE importer = ?", (importer,))}


# ---------------------------------------------------------------------
# Edge resolution (unit level)
# ---------------------------------------------------------------------

def test_dotted_from_and_relative_import_resolution(tmp_path):
    ws = tmp_path / "proj"
    (ws / "src" / "pkg").mkdir(parents=True)
    (ws / "src" / "pkg" / "__init__.py").write_text("")
    (ws / "src" / "pkg" / "base.py").write_text("class Base:\n    pass\n")
    (ws / "src" / "pkg" / "impl.py").write_text("from .base import Base\n")
    (ws / "user.py").write_text("from src.pkg import impl\n")

    impl_edges = _extract_py_import_edges(
        "from .base import Base\n", Path("src/pkg/impl.py"), ws)
    assert impl_edges == {"src/pkg/base.py"}

    user_edges = _extract_py_import_edges(
        "from src.pkg import impl\n", Path("user.py"), ws)
    # both the package __init__ and the submodule are legit targets
    assert "src/pkg/impl.py" in user_edges
    assert "src/pkg/__init__.py" in user_edges


def test_stdlib_self_and_missing_targets_are_dropped(tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    (ws / "a.py").write_text("import os\nimport a\nimport ghosts.mod\n")
    edges = _extract_py_import_edges(
        "import os\nimport a\nimport ghosts.mod\n", Path("a.py"), ws)
    assert edges == set()  # os = stdlib, a = self, ghosts = not in repo


# ---------------------------------------------------------------------
# Relations in the layer
# ---------------------------------------------------------------------

def test_related_files_both_directions(ws_and_index):
    _ws, idx = ws_and_index
    # direct call pins both directions deterministically (no search ranking)
    lines = _related_files_lines(idx, {"service.py"})
    text = "\n".join(lines)
    assert "app.py imports service.py" in text
    assert "may BREAK this file" in text
    assert "repo.py imported by service.py" in text
    assert "relies on it" in text
    assert "lonely.py" not in text


def test_related_files_end_to_end_in_layer(ws_and_index):
    ws, _idx = ws_and_index
    # Lexically unique to repo.py ("accounts/storage/table" appear nowhere
    # else in the fixture), so the matched set is exactly {repo.py}.
    layer = build_relevant_chunks_layer(
        {"workspace": str(ws), "current_task": "accounts storage table"})
    content = layer.content
    assert "=== RELEVANT CODE CHUNKS ===" in content
    assert "repo.py" in content
    assert "=== RELATED FILES (import links) ===" in content
    assert "service.py imports repo.py" in content
    assert "may BREAK this file" in content


def test_related_files_hard_cap_at_four(tmp_path, monkeypatch):
    ws = tmp_path / "proj"
    ws.mkdir()
    files = {"repo.py": BASE_PY["repo.py"]}
    for i in range(10):
        files[f"imp{i:02d}.py"] = f"import repo\n\ndef user_{i}():\n    return repo.fetch_user({i})\n"
    _write(ws, files)
    monkeypatch.setattr(ci_mod.ChunkIndex, "start_watcher", lambda self: None)
    idx = ChunkIndex(str(ws), db_path=str(tmp_path / "ci.db"), watch=False,
                     embedder=FakeEmbedder())
    idx.sync_workspace()
    lines = _related_files_lines(idx, {"repo.py"})
    bullets = [l for l in lines if l.startswith("- ")]
    assert len(bullets) == 4, f"cap breached: {bullets}"
    assert "imp00.py imports repo.py" in bullets[0]  # sorted order, dependents first
    idx.conn.close()


def test_no_edges_no_section(ws_and_index):
    _ws, idx = ws_and_index
    lines = _related_files_lines(idx, {"lonely.py"})
    assert lines == []


# ---------------------------------------------------------------------
# Edge lifecycle
# ---------------------------------------------------------------------

def test_edges_follow_edits(ws_and_index):
    ws, idx = ws_and_index
    assert _edges(idx, "service.py") == {"repo.py"}

    service = ws / "service.py"
    service.write_text(
        '"""Session services."""\n\n\ndef validate_session_token(token):\n'
        '    """Check a session token expiry without storage."""\n'
        "    return True\n"
    )
    idx.sync_workspace()
    assert _edges(idx, "service.py") == set()
    assert _edges(idx, "app.py") == {"service.py"}  # untouched files keep edges
    text = "\n".join(_related_files_lines(idx, {"service.py"}))
    assert "repo.py imported by service.py" not in text


def test_remove_file_drops_its_edges(ws_and_index):
    ws, idx = ws_and_index
    (ws / "service.py").unlink()
    idx.sync_workspace()  # ghost prune path must clear importer edges too
    assert _edges(idx, "service.py") == set()


def test_v2_migration_forces_one_resync(ws_and_index, tmp_path):
    _ws, idx = ws_and_index
    # Simulate a pre-v2 database: chunks exist, edge table/schema absent.
    idx.conn.execute("DROP TABLE import_edges")
    idx.conn.execute("PRAGMA user_version = 1")
    idx.conn.commit()

    idx2 = ChunkIndex(str(_ws), db_path=str(tmp_path / "ci.db"), watch=False,
                      embedder=FakeEmbedder())
    assert idx2._needs_edge_resync is True
    assert _edges(idx2, "service.py") == set()  # not yet rebuilt

    idx2.sync_workspace()
    assert idx2._needs_edge_resync is False
    assert _edges(idx2, "service.py") == {"repo.py"}
    assert _edges(idx2, "app.py") == {"service.py"}
    assert idx2.sync_workspace() == 0  # mtime-clean afterwards, no loop
    idx2.conn.close()


# ---------------------------------------------------------------------
# Non-Python tolerance
# ---------------------------------------------------------------------

def test_js_files_index_with_edges_and_related_files(tmp_path, monkeypatch):
    # §41 CONTRACT CHANGE: this pin used to be
    # "test_js_files_index_without_edges_no_crash" and asserted n_edges == 0
    # ("v1 edges are Python-only by design"). D15-remainder fixed exactly
    # that debt: JS/TS (and Go/Rust/Java) now produce import edges. The
    # assertion inversion is deliberate, not a regression.
    pytest.importorskip("tree_sitter_javascript")
    ws = tmp_path / "proj"
    ws.mkdir()
    _write(ws, {
        "util.js": "export function helperCalc(x) { return x * 2; }\n",
        "app.js": "import { helperCalc } from './util.js';\n"
                  "export function mainRun() { return helperCalc(21); }\n",
    })
    monkeypatch.setattr(ci_mod.ChunkIndex, "start_watcher", lambda self: None)
    idx = ChunkIndex(str(ws), db_path=str(tmp_path / "ci.db"), watch=False,
                     embedder=FakeEmbedder())
    idx.sync_workspace()
    with idx._write_lock:
        rows = idx.conn.execute(
            "SELECT importer, imported FROM import_edges").fetchall()
    assert (Path("app.js").as_posix(), Path("util.js").as_posix()) in {
        (Path(a).as_posix(), Path(b).as_posix()) for a, b in rows
    }
    related = _related_files_lines(idx, {"app.js"})
    assert any("util.js" in ln for ln in related)
    idx.conn.close()
