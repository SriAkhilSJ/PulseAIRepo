"""Pins for the Aug-7 review-autopsy fix pack (§44):

  D25  repo-map staleness TTL + own-mutation invalidation (the Turn Tax)
  D26  layer-cache whitelist hash (the Self-Poisoning Cache)
  D27  zombie-layer signature pin + loud-build smoke
  D28  Python syntax receipt on edit_file / write_file-overwrite
  D29  dashboard per-thread turn lock

All pure: temp workspaces, no LLM, no provider keys.
"""

from __future__ import annotations

import ast
import inspect
import os
import threading
import time
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

import src.context.repo_map as repo_map_mod
from src.context.repo_map import (
    RepoMap, get_repo_map, invalidate_repo_map, stale_check_ttl,
)
from src.context.context_engine import ContextEngine, TaskType
from src.tools.file_tools import edit_file, write_file
from src.dashboard.turn_locks import turn_lock, reset_for_tests

EDIT = edit_file.func
WRITE = write_file.func


def _ws(tmp_path, n: int = 6) -> str:
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    for i in range(n):
        (ws / f"mod_{i}.py").write_text(f"def f{i}(x):\n    return x + {i}\n")
    return str(ws)


def _engine(ws: str) -> ContextEngine:
    eng = ContextEngine(max_tokens=12_000, model="gpt-4o-mini", probe_window=False)
    tmp = ws  # feedback goes to a throwaway path under the tmp ws
    eng._feedback_path = os.path.join(tmp, "fb.jsonl")
    eng._feedback_history = []
    return eng


def _state(ws: str, **noise) -> dict:
    st = {
        "messages": [HumanMessage(content="add the feature")],
        "current_task": "add the feature to mod_0.py",
        "latest_instruction": "add the feature to mod_0.py",
        "workspace": ws,
        "plan": [], "steps_completed": [], "failed_steps": [],
    }
    st.update(noise)
    return st


# ---------------------------------------------------------------------------
# D25 — staleness TTL
# ---------------------------------------------------------------------------

def test_d25_second_get_map_within_ttl_skips_the_walk(tmp_path, monkeypatch):
    monkeypatch.delenv("PULSEAI_REPO_MAP_STALE_TTL", raising=False)
    ws = _ws(tmp_path)
    rm = RepoMap(ws)
    rm.get_map()  # build: walks at least once

    calls = {"n": 0}
    orig = RepoMap._get_latest_mtime
    def counting(self):
        calls["n"] += 1
        return orig(self)
    monkeypatch.setattr(RepoMap, "_get_latest_mtime", counting)

    rm.get_map()
    rm.get_map()
    assert calls["n"] == 0, "within TTL the staleness walk must not run"


def test_d25_ttl_zero_restores_legacy_always_walk(tmp_path, monkeypatch):
    monkeypatch.setenv("PULSEAI_REPO_MAP_STALE_TTL", "0")
    ws = _ws(tmp_path)
    rm = RepoMap(ws)
    rm.get_map()

    calls = {"n": 0}
    orig = RepoMap._get_latest_mtime
    def counting(self):
        calls["n"] += 1
        return orig(self)
    monkeypatch.setattr(RepoMap, "_get_latest_mtime", counting)

    rm.get_map()
    assert calls["n"] == 1, "TTL=0 must behave exactly like legacy"
    assert stale_check_ttl() == 0.0


def test_d25_external_change_appears_after_ttl_expiry(tmp_path, monkeypatch):
    monkeypatch.delenv("PULSEAI_REPO_MAP_STALE_TTL", raising=False)
    ws = _ws(tmp_path)
    rm = RepoMap(ws)
    assert "brand_new.py" not in rm.get_map()

    new_file = Path(ws) / "brand_new.py"
    new_file.write_text("def shiny():\n    return 1\n")
    # Strictly-newer mtime: no filesystem granularity edge against the
    # cache's recorded "latest mtime" (the whole point is change detection).
    future = time.time() + 5
    os.utime(new_file, (future, future))
    rm._last_stale_check = 0.0  # simulate TTL window expired (no sleeping)
    assert "brand_new.py" in rm.get_map()


def test_d25_write_hook_invalidates_own_changes_immediately(tmp_path, monkeypatch):
    monkeypatch.delenv("PULSEAI_REPO_MAP_STALE_TTL", raising=False)
    ws = _ws(tmp_path)
    assert "hook_added.py" not in get_repo_map(ws)

    WRITE(path="hook_added.py", content="def via_tool():\n    return 7\n",
          config={"configurable": {"workspace": ws}})
    # Same instant, TTL fully armed — our own mutation must NOT wait.
    assert "hook_added.py" in get_repo_map(ws)


def test_d25_invalidate_helper_tolerates_unknown_workspace(tmp_path):
    invalidate_repo_map(tmp_path / "never-built")  # no exception, no build


# ---------------------------------------------------------------------------
# D26 — whitelist hash
# ---------------------------------------------------------------------------

def test_d26_token_and_trace_churn_no_longer_busts_layer_cache(tmp_path):
    ws = _ws(tmp_path)
    eng = _engine(ws)
    sys_msg = SystemMessage(content="sys")

    eng.build_ai_messages(_state(
        ws, token_usage={"calls": 1, "prompt_tokens": 100},
        execution_trace=[],
    ), sys_msg)
    cache_before = dict(eng._layer_cache)
    assert cache_before, "first build must populate the differential cache"

    # chat_graph's per-turn noise, verbatim shape: token_usage merges,
    # execution_trace appends (chat_graph.py:373-375, :871).
    eng.build_ai_messages(_state(
        ws, token_usage={"calls": 2, "prompt_tokens": 250, "completion_tokens": 42},
        execution_trace=[{"tool": "edit_file", "ok": True}],
    ), sys_msg)

    assert set(eng._layer_cache) == set(cache_before), \
        "noise-key churn must not clear the layer cache"
    for name, msg in cache_before.items():
        assert eng._layer_cache[name] is msg, \
            f"layer {name!r} rebuilt on pure noise (object identity lost)"

    # ...while a real change still rebuilds:
    st = _state(ws, token_usage={"calls": 3})
    st["steps_completed"] = ["step one done"]
    eng.build_ai_messages(st, sys_msg)
    assert eng._layer_cache["progress"] is not cache_before.get("progress")


def test_d26_hashed_keys_match_builder_usage_ast():
    """Drift guard: every state key read by ANY ContextEngine method that
    takes `state` must be in _HASHED_STATE_KEYS (or be 'messages'). A
    future layer reading a new key fails HERE, loudly — never silently
    stale in production."""
    src = (Path(__file__).parent.parent / "context" / "context_engine.py").read_text()
    tree = ast.parse(src)

    engine_cls = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.ClassDef) and n.name == "ContextEngine")
    used: set[str] = set()
    for node in engine_cls.body:
        if not (isinstance(node, ast.FunctionDef)
                and any(a.arg == "state" for a in node.args.args)):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "get"
                    and isinstance(sub.func.value, ast.Name)
                    and sub.func.value.id == "state"
                    and sub.args and isinstance(sub.args[0], ast.Constant)
                    and isinstance(sub.args[0].value, str)):
                used.add(sub.args[0].value)
            if (isinstance(sub, ast.Subscript)
                    and isinstance(sub.value, ast.Name)
                    and sub.value.id == "state"
                    and isinstance(sub.slice, ast.Constant)
                    and isinstance(sub.slice.value, str)):
                used.add(sub.slice.value)

    leftovers = used - ContextEngine._HASHED_STATE_KEYS - {"messages"}
    assert leftovers == set(), (
        f"builders read state keys outside the D26 whitelist: {leftovers}. "
        f"Add them to _HASHED_STATE_KEYS or the differential cache will "
        f"serve stale layers."
    )


# ---------------------------------------------------------------------------
# D27 — no zombie layer can ever ship again
# ---------------------------------------------------------------------------

def test_d27_every_registered_builder_takes_exactly_state():
    src = (Path(__file__).parent.parent / "context" / "context_engine.py").read_text()
    tree = ast.parse(src)

    engine_cls = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.ClassDef) and n.name == "ContextEngine")
    build_fn = next(n for n in engine_cls.body
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "_build_context_layers")

    layer_methods: list[str] = []
    for sub in ast.walk(build_fn):
        # builders = {"name": self._x_layer, ...} — collect the attributes
        if (isinstance(sub, ast.Dict)):
            for v in sub.values:
                if (isinstance(v, ast.Attribute)
                        and isinstance(v.value, ast.Name) and v.value.id == "self"):
                    layer_methods.append(v.attr)
    assert len(layer_methods) >= 15, \
        f"expected the full layer registry, found {len(layer_methods)}"

    for name in layer_methods:
        method = getattr(ContextEngine, name, None)
        assert method is not None, f"registry references missing method {name}"
        params = list(inspect.signature(method).parameters)
        assert params == ["self", "state"], (
            f"{name} has signature {params} — the builder loop calls "
            f"builder(state); anything else dies silently for MONTHS "
            f"(that bug class deadened the quality layer)."
        )


def test_d27_full_build_smoke_is_loud_free(tmp_path, capsys):
    ws = _ws(tmp_path)
    eng = _engine(ws)
    layers = eng._build_context_layers(
        _state(ws), TaskType.CREATE
    )
    out = capsys.readouterr().out
    assert "builder failed" not in out, \
        "a layer builder threw during a healthy build — zombie risk"
    assert layers, "healthy CREATE build must produce layers"


# ---------------------------------------------------------------------------
# D28 — syntax receipt
# ---------------------------------------------------------------------------

def test_d28_edit_file_refuses_broken_python(tmp_path):
    ws = _ws(tmp_path)
    target = Path(ws) / "mod_0.py"
    before = target.read_text()
    out = EDIT(path="mod_0.py", old_text="    return x + 0",
               new_text="    return x + 0  # coffee\n    def broken(:",
               config={"configurable": {"workspace": ws}})
    assert "rejected" in out.lower() and "line" in out.lower()
    assert target.read_text() == before  # untouched


def test_d28_edit_file_can_repair_already_broken_file(tmp_path):
    ws = _ws(tmp_path)
    target = Path(ws) / "mod_0.py"
    target.write_text("def f0(x):\n    return x + 0  # coffee\n    def broken(:\n")
    out = EDIT(path="mod_0.py", old_text="    def broken(:",
               new_text="    return x",
               config={"configurable": {"workspace": ws}})
    assert out.startswith("✅"), out
    import ast
    ast.parse(target.read_text())  # repaired, parses now


def test_d28_write_file_protects_existing_python_only(tmp_path):
    ws = _ws(tmp_path)
    target = Path(ws) / "mod_0.py"
    before = target.read_text()
    out = WRITE(path="mod_0.py", content="def nope(:\n",
                config={"configurable": {"workspace": ws}})
    assert "rejected" in out.lower()
    assert target.read_text() == before

    # Brand-new .py with placeholders: allowed (skeletons/templates).
    out2 = WRITE(path="skeleton.py", content="def todo(...) -> ...:\n    ...\n",
                 config={"configurable": {"workspace": ws}})
    assert out2.startswith("File written")

    # Non-Python files: receipt never applies.
    out3 = WRITE(path="notes.txt", content="def nope(:\n",
                 config={"configurable": {"workspace": ws}})
    assert out3.startswith("File written")


# ---------------------------------------------------------------------------
# D29 — per-thread turn lock
# ---------------------------------------------------------------------------

def test_d29_same_thread_same_lock_distinct_threads_distinct():
    reset_for_tests()
    assert turn_lock("t1") is turn_lock("t1")
    assert turn_lock("t1") is not turn_lock("t2")


def test_d29_mutual_exclusion_under_contention():
    reset_for_tests()
    lock = turn_lock("race")
    active = {"now": 0, "max": 0}
    guard = threading.Lock()

    def worker():
        for _ in range(5):
            with lock:
                with guard:
                    active["now"] += 1
                    active["max"] = max(active["max"], active["now"])
                time.sleep(0.001)
                with guard:
                    active["now"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert active["max"] == 1, "two turns entered the same thread at once"
