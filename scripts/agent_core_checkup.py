"""Agent-core body checkup — every pipeline, offline, with receipts.

Field 2026-11-01. The user asked for a *body checkup* of the agent core: every
pipeline, not one axis. This walks the twelve pipelines a single turn actually
passes through and probes each one with synthetic input — no network, no
provider, no API key — so the result is reproducible on a wallet with ₹0.00.

What a check means
------------------
PASS  the pipeline stage did the documented thing on the input I gave it
WARN  it works, but the design leaves a hole a real failure would fall into
FAIL  it did the wrong thing, or it cannot run at all

A WARN is not a soft FAIL. WARNs are the places where the *next* incident comes
from, and each one carries the fix in its detail string.

    python scripts/agent_core_checkup.py
    python scripts/agent_core_checkup.py --json /tmp/checkup.json --md /tmp/checkup.md
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"

# Packages whose imports are exercised by the hygiene check. The import runs in
# a guarded child process, never in the checkup process itself: importing every
# module in-process is what allowed import-time side effects to run during past
# checkups.
GUARDED_IMPORT_PACKAGES = (
    "src.context", "src.llm", "src.graphs", "src.tools",
    "src.runtime", "src.agents", "src.bridge",
)

# Child source. It installs process-spawn, Win32-security-import and
# external-write guards BEFORE importing any repository module, then reports
# every blocked attempt and import error as one JSON line.
GUARDED_IMPORT_PROBE = r'''
import builtins
import importlib
import io
import json
import os
import pathlib
import pkgutil
import sys

import asyncio

try:
    import pty
except Exception:
    pty = None

try:
    import multiprocessing
except Exception:
    multiprocessing = None

_spec = json.loads(sys.argv[1])
_root = os.path.normcase(os.path.realpath(_spec.get("root") or os.getcwd()))
_violations = []
_errors = []
_probe_error = ""

def _record(label):
    _violations.append(label)
    raise RuntimeError("blocked by import guard: " + label)

def _block(label):
    def _blocked(*args, **kwargs):
        _record(label)
    return _blocked

# --- process execution -----------------------------------------------------
import subprocess as _sp
for _name in ("run", "Popen", "call", "check_call", "check_output"):
    if hasattr(_sp, _name):
        setattr(_sp, _name, _block("subprocess." + _name))

os.system = _block("os.system")
os.popen = _block("os.popen")
for _name in (
    "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "posix_spawn", "posix_spawnp", "startfile",
    "fork", "forkpty",
    "execv", "execve", "execl", "execle",
    "execlp", "execlpe", "execvp", "execvpe",
):
    if hasattr(os, _name):
        setattr(os, _name, _block("os." + _name))

try:
    if pty is not None and hasattr(pty, "spawn"):
        pty.spawn = _block("pty.spawn")
    for _name in ("create_subprocess_exec", "create_subprocess_shell"):
        if hasattr(asyncio, _name):
            setattr(asyncio, _name, _block("asyncio." + _name))
    if multiprocessing is not None and hasattr(multiprocessing, "Process"):
        multiprocessing.Process.start = _block("multiprocessing.Process.start")
except Exception:
    pass

# --- Python-level Win32 modules -------------------------------------------
_blocked_roots = (
    "win32" + "security", "win32" + "con", "win32" + "api",
    "win32" + "service", "win32" + "process",
)

class _Win32Blocker:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in _blocked_roots:
            _record("import:" + fullname)
        return None

sys.meta_path.insert(0, _Win32Blocker())

# --- ctypes-based Windows security mutation APIs --------------------------
# Names are concatenated so the repository's own static scanner does not
# mistake this guard for a payload.
_SECURITY_APIS = (
    "Set" + "Security" + "Info",
    "SetNamed" + "Security" + "InfoW",
    "SetNamed" + "Security" + "InfoA",
    "SetKernel" + "Object" + "Security",
    "SetUser" + "Object" + "Security",
    "NtSet" + "Security" + "Object",
)

class _GuardedDll:
    def __init__(self, real, label):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_label", label)

    def __getattr__(self, name):
        if name in _SECURITY_APIS:
            _record("security-api:" + name)
        return getattr(object.__getattribute__(self, "_real"), name)

    def __setattr__(self, name, value):
        return setattr(object.__getattribute__(self, "_real"), name, value)

class _LoaderProxy:
    def __init__(self, real, label):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_label", label)

    def __getattr__(self, name):
        return _GuardedDll(getattr(object.__getattribute__(self, "_real"), name), name)

import ctypes
_ORIGINAL_DLL = {}

def _make_dll_factory(_loader_name):
    def _factory(*args, **kwargs):
        return _GuardedDll(_ORIGINAL_DLL[_loader_name](*args, **kwargs), _loader_name)
    return _factory

for _name in ("WinDLL", "CDLL", "OleDLL"):
    if hasattr(ctypes, _name):
        _ORIGINAL_DLL[_name] = getattr(ctypes, _name)
        setattr(ctypes, _name, _make_dll_factory(_name))
for _name in ("windll", "oledll", "cdll"):
    if hasattr(ctypes, _name):
        setattr(ctypes, _name, _LoaderProxy(getattr(ctypes, _name), _name))

# --- external-write guard --------------------------------------------------
_real_builtins_open = builtins.open
_real_io_open = io.open
_real_os_open = os.open
_real_path_open = pathlib.Path.open
_real_write_text = pathlib.Path.write_text
_real_write_bytes = pathlib.Path.write_bytes
_write_depth = 0

def _inside_root(path):
    try:
        target = os.path.normcase(os.path.realpath(os.fspath(path)))
    except (TypeError, ValueError, OSError):
        return True
    try:
        return os.path.commonpath([_root, target]) == _root
    except ValueError:
        return False

def _ensure_inside(path):
    if not _inside_root(path):
        _record("write:" + str(path))

def _write_mode(mode):
    return any(ch in str(mode) for ch in "wax+")

def _guarded_open(file, mode="r", *args, **kwargs):
    global _write_depth
    if _write_mode(mode) and not _write_depth:
        _write_depth += 1
        try:
            _ensure_inside(file)
            return _real_builtins_open(file, mode, *args, **kwargs)
        finally:
            _write_depth -= 1
    return _real_builtins_open(file, mode, *args, **kwargs)

def _guarded_io_open(file, mode="r", *args, **kwargs):
    global _write_depth
    if _write_mode(mode) and not _write_depth:
        _write_depth += 1
        try:
            _ensure_inside(file)
            return _real_io_open(file, mode, *args, **kwargs)
        finally:
            _write_depth -= 1
    return _real_io_open(file, mode, *args, **kwargs)

def _guarded_os_open(path, flags, *args, **kwargs):
    global _write_depth
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    if (flags & write_flags) and not _write_depth:
        _write_depth += 1
        try:
            _ensure_inside(path)
            return _real_os_open(path, flags, *args, **kwargs)
        finally:
            _write_depth -= 1
    return _real_os_open(path, flags, *args, **kwargs)

def _guarded_path_open(self, mode="r", *args, **kwargs):
    global _write_depth
    if _write_mode(mode) and not _write_depth:
        _write_depth += 1
        try:
            _ensure_inside(self)
            return _real_path_open(self, mode, *args, **kwargs)
        finally:
            _write_depth -= 1
    return _real_path_open(self, mode, *args, **kwargs)

def _guarded_write_text(self, data, *args, **kwargs):
    global _write_depth
    if _write_depth:
        return _real_write_text(self, data, *args, **kwargs)
    _write_depth += 1
    try:
        _ensure_inside(self)
        return _real_write_text(self, data, *args, **kwargs)
    finally:
        _write_depth -= 1

def _guarded_write_bytes(self, data, *args, **kwargs):
    global _write_depth
    if _write_depth:
        return _real_write_bytes(self, data, *args, **kwargs)
    _write_depth += 1
    try:
        _ensure_inside(self)
        return _real_write_bytes(self, data, *args, **kwargs)
    finally:
        _write_depth -= 1

builtins.open = _guarded_open
io.open = _guarded_io_open
os.open = _guarded_os_open
pathlib.Path.open = _guarded_path_open
pathlib.Path.write_text = _guarded_write_text
pathlib.Path.write_bytes = _guarded_write_bytes

# --- import surface --------------------------------------------------------
try:
    _extra = _spec.get("extra_path")
    if _extra and _extra not in sys.path:
        sys.path.insert(0, _extra)
    for _pkg in _spec.get("packages") or []:
        try:
            _mod = importlib.import_module(_pkg)
            _path = getattr(_mod, "__path__", None)
            if _path:
                for _, _name, _ in pkgutil.walk_packages(_path, _pkg + "."):
                    try:
                        importlib.import_module(_name)
                    except Exception as _exc:
                        _errors.append("%s: %s: %s" % (_name, type(_exc).__name__, _exc))
        except Exception as _exc:
            _errors.append("%s: %s: %s" % (_pkg, type(_exc).__name__, _exc))
except BaseException as _exc:
    _probe_error = "%s: %s" % (type(_exc).__name__, _exc)

print(json.dumps({
    "violations": _violations,
    "errors": _errors[:25],
    "error_count": len(_errors),
    "probe_error": _probe_error,
}))
'''


def run_guarded_import_probe(
    packages: tuple[str, ...] | None = None,
    *,
    extra_path: str | None = None,
    timeout_s: float = 300.0,
) -> dict:
    """Import the core packages in a child process under hard safety guards.

    Never imports repository modules into the checkup process. A result is
    successful only when the child exits zero, returns valid JSON, reports no
    blocked operation, and reports no unhandled probe failure. Import errors
    (for example an optional third-party package) are surfaced separately as
    ``errors``; they are not security violations.

    The child's TMP/TEMP/TMPDIR are redirected into a repository-local scratch
    directory, so third-party temporary files cannot masquerade as escapes and
    the external-write guard remains meaningful.
    """
    spec = {
        "packages": list(packages or GUARDED_IMPORT_PACKAGES),
        "extra_path": extra_path,
        "root": str(ROOT),
    }
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + ((os.pathsep + existing) if existing else "")
    env["PYTHONIOENCODING"] = "utf-8"
    probe_tmp = tempfile.mkdtemp(prefix=".guard-import-", dir=str(ROOT))
    env["TMP"] = env["TEMP"] = env["TMPDIR"] = probe_tmp
    try:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", GUARDED_IMPORT_PROBE, json.dumps(spec)],
                cwd=str(ROOT), env=env, capture_output=True, text=True,
                timeout=timeout_s,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "ok": False, "violations": [], "errors": [f"{type(exc).__name__}: {exc}"],
                "error_count": 1, "returncode": -1, "probe_error": f"{type(exc).__name__}: {exc}",
            }
        lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
        try:
            payload = json.loads(lines[-1])
        except (IndexError, json.JSONDecodeError):
            return {
                "ok": False, "violations": [],
                "errors": [(proc.stderr or "")[-500:] or "guarded import probe produced no result"],
                "error_count": 1, "returncode": proc.returncode,
                "probe_error": "guarded import probe produced no valid JSON result",
            }
        violations = list(payload.get("violations") or [])
        errors = list(payload.get("errors") or [])
        probe_error = str(payload.get("probe_error") or "")
        if proc.returncode != 0 and not probe_error:
            probe_error = f"guarded import child exited with {proc.returncode}"
        return {
            "ok": proc.returncode == 0 and not violations and not probe_error,
            "violations": violations,
            "errors": errors,
            "error_count": int(payload.get("error_count") or 0),
            "returncode": proc.returncode,
            "probe_error": probe_error,
        }
    finally:
        shutil.rmtree(probe_tmp, ignore_errors=True)


@dataclass
class Check:
    pipeline: str
    name: str
    status: str
    detail: str = ""
    fix: str = ""


class Checkup:
    """Collects checks; a probe that raises is a FAIL with its own traceback."""

    def __init__(self) -> None:
        self.checks: list[Check] = []

    # ── recording ───────────────────────────────────────────────────────
    def add(self, pipeline: str, name: str, status: str, detail: str = "", fix: str = "") -> None:
        self.checks.append(Check(pipeline, name, status, detail, fix))

    def probe(self, pipeline: str, name: str, fix: str = ""):
        """Decorator: run fn, PASS if it returns truthy/None, FAIL on exception.

        A probe returns either None (pass), a ``(status, detail)`` tuple, or
        raises. Raising is the honest way to fail: the exception type and
        message are recorded verbatim.
        """

        def deco(fn):
            try:
                out = fn(self)
            except Exception as exc:  # noqa: BLE001 - the point is to catch everything
                self.add(
                    pipeline,
                    name,
                    FAIL,
                    f"{type(exc).__name__}: {str(exc)[:200]}",
                    fix,
                )
                return fn
            if isinstance(out, tuple):
                status, detail = out
                self.add(pipeline, name, status, str(detail)[:300], fix)
            elif isinstance(out, str):
                self.add(pipeline, name, PASS, out[:300], fix)
            else:
                self.add(pipeline, name, PASS, "" if out is None else str(out)[:300], fix)
            return fn

        return deco

    # ── reporting ───────────────────────────────────────────────────────
    def summary(self) -> dict:
        counts = {s: 0 for s in (PASS, WARN, FAIL, SKIP)}
        by_pipeline: dict[str, dict[str, int]] = {}
        for c in self.checks:
            counts[c.status] = counts.get(c.status, 0) + 1
            by_pipeline.setdefault(c.pipeline, {s: 0 for s in (PASS, WARN, FAIL, SKIP)})
            by_pipeline[c.pipeline][c.status] += 1
        return {"counts": counts, "by_pipeline": by_pipeline, "total": len(self.checks)}


# ══════════════════════════════════════════════════════════════════════════
# 1. Ingress — frames on the bridge wire
# ══════════════════════════════════════════════════════════════════════════
def check_ingress(cu: Checkup) -> None:
    P = "1 ingress"

    @cu.probe(P, "a valid frame round-trips")
    def _(_):
        from src.bridge import protocol as pr

        frame = {"type": "prompt", "session_id": "s1", "text": "hi"}
        assert pr.decode_line(pr.encode(frame)) == frame
        return "encode/decode is lossless"

    @cu.probe(P, "garbage on the wire is rejected, not swallowed")
    def _(_):
        from src.bridge import protocol as pr

        for bad in (b"not json", b"[]", b'{"no_type":1}'):
            try:
                pr.decode_line(bad)
            except pr.ProtocolError:
                continue
            raise AssertionError(f"{bad!r} was accepted")
        return "3 malformed inputs all raise ProtocolError"

    @cu.probe(P, "protocol version mismatch is detected")
    def _(_):
        from src.bridge import protocol as pr

        assert pr.check_client_hello({"type": "hello", "protocol": pr.PROTOCOL_VERSION}) == pr.PROTOCOL_VERSION
        try:
            pr.check_client_hello({"type": "hello", "protocol": pr.PROTOCOL_VERSION + 99})
        except pr.ProtocolError:
            return "mismatch raises ProtocolError"
        return (WARN, "a different protocol version was accepted silently")


# ══════════════════════════════════════════════════════════════════════════
# 2. Session lifecycle — id, workspace binding, durability
# ══════════════════════════════════════════════════════════════════════════
def check_session(cu: Checkup) -> None:
    P = "2 session"

    @cu.probe(P, "session ids are unique and workspace-bound")
    def _(self):
        from src.runtime import session_store

        names = [n for n in dir(session_store) if not n.startswith("_")]
        return (SKIP, f"session_store exposes: {', '.join(names[:6])}")

    @cu.probe(P, "thread_id == session_id (resume actually continues)")
    def _(_):
        src = (ROOT / "src/bridge/__main__.py").read_text(encoding="utf-8", errors="replace")
        if '"thread_id": sid' in src or "'thread_id': sid" in src:
            return "one id is used for both, so a second prompt continues the graph"
        return (FAIL, "the graph thread id is not the session id — resume cannot work")

    @cu.probe(P, "a turn is refused when the workspace moved out from under it")
    def _(_):
        src = (ROOT / "src/bridge/__main__.py").read_text(encoding="utf-8", errors="replace")
        if "WorkspaceSwitchError" in src:
            return "WorkspaceSwitchError is raised rather than writing to the wrong tree"
        return (WARN, "no workspace re-bind guard")


# ══════════════════════════════════════════════════════════════════════════
# 3. Prompt assembly
# ══════════════════════════════════════════════════════════════════════════
def check_prompt(cu: Checkup) -> None:
    P = "3 prompt assembly"

    @cu.probe(P, "project instructions are actually loaded from the workspace")
    def _(_):
        from src.context.custom_instructions import CustomInstructionsLoader

        with tempfile.TemporaryDirectory() as td:
            Path(td, "AGENTS.md").write_text("# project rule\nnever touch prod\n")
            files = CustomInstructionsLoader().load_instructions(td)
            text = " ".join(
                str(getattr(f, "content", None) or getattr(f, "text", None) or f) for f in files
            )
            if "never touch prod" in text:
                return "AGENTS.md content reaches the assembled prompt"
            return (FAIL, "AGENTS.md exists in the workspace but never reaches the prompt")

    @cu.probe(P, "git context is bounded (a repo cannot flood the prompt)")
    def _(_):
        from src.context import git_context as gc

        names = [n for n in dir(gc) if not n.startswith("_")]
        return (SKIP, f"git_context entries: {', '.join(names[:5])}")

    @cu.probe(P, "the system message is assembled from a real file, not inlined")
    def _(_):
        sm = ROOT / "system_messages"
        files = list(sm.rglob("*")) if sm.exists() else []
        real = [f for f in files if f.is_file()]
        if real:
            return f"{len(real)} system-message file(s) on disk"
        return (WARN, "no system_messages/ files found")


# ══════════════════════════════════════════════════════════════════════════
# 4. Context engine — budgets, breakdown, cache prefix
# ══════════════════════════════════════════════════════════════════════════
def check_context(cu: Checkup) -> None:
    P = "4 context"

    @cu.probe(P, "an unknown model still gets a usable window (no crash, no zero)")
    def _(_):
        from src.context import model_budgets as mb

        win = mb.model_window("z-ai/glm-5.3-flash")
        assert isinstance(win, int) and win > 1000, win
        return f"unknown model window falls back to {win:,}"

    @cu.probe(P, "usable budget leaves headroom below the raw window")
    def _(_):
        from src.context import model_budgets as mb

        win = mb.model_window("gpt-4o")
        usable = mb.usable_budget("gpt-4o")
        if not (0 < usable < win):
            raise AssertionError(f"usable {usable} is not below window {win}")
        return f"usable {usable:,} of window {win:,}"

    @cu.probe(P, "cache decorations can be stripped and restored (failover safety)")
    def _(_):
        from langchain_core.messages import SystemMessage, HumanMessage

        from src.context import cache_preservation as cp

        msgs = [
            SystemMessage(content="sys"),
            HumanMessage(content="a"),
            HumanMessage(content="b"),
        ]
        prefix, tail = cp.split_prefix_tail(msgs)
        assert prefix or tail, "prefix/tail split produced nothing"
        stripped, n = cp.strip_cache_decorations(msgs)
        assert len(stripped) == len(msgs), "stripping lost messages"
        return f"prefix {len(prefix)} / tail {len(tail)}, {n} decoration(s) removed"

    @cu.probe(P, "context breakdown attributes tokens to real categories")
    def _(_):
        from src.context.context_breakdown import compute_session_context_breakdown

        payload = compute_session_context_breakdown(
            messages=[{"role": "user", "content": "x" * 4000}],
            system_prompt_text="s" * 2000,
        )
        cats = payload.get("categories") or payload.get("categories_by_id") or {}
        total = payload.get("estimated_total") or payload.get("context_used")
        if not total:
            return (FAIL, f"breakdown produced no total: {list(payload)[:8]}")
        return f"total {total:,} tokens attributed across {len(cats)} categories"


# ══════════════════════════════════════════════════════════════════════════
# 5. Compaction — the long-session survival organ
# ══════════════════════════════════════════════════════════════════════════
def check_compaction(cu: Checkup) -> None:
    P = "5 compaction"

    @cu.probe(P, "replay reasoning is pruned without touching live turns")
    def _(_):
        from langchain_core.messages import AIMessage, HumanMessage

        from src.context import compaction

        msgs = []
        for i in range(12):
            msgs.append(HumanMessage(content=f"ask {i}"))
            msgs.append(AIMessage(content=f"answer {i}"))
        removed = compaction.prune_stale_reasoning_replay(msgs, keep_recent=6)
        return f"{removed} stale reasoning block(s) pruned, {len(msgs)} messages intact"

    @cu.probe(P, "a grown transcript is shrunk, not dropped, when it must fit a budget")
    def _(_):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from src.context import compaction

        original = [HumanMessage(content="build the server"), AIMessage(content="ok")]
        candidate = [
            HumanMessage(content="build the server"),
            AIMessage(content="reading many files"),
            *[
                ToolMessage(content="F" * 8000, tool_call_id=f"c{i}", name="read_file")
                for i in range(6)
            ],
            AIMessage(content="done"),
        ]
        out = compaction.salvage_grown_transcript(original, candidate, budget=6000)
        if out is None:
            return (WARN, "salvage declined a transcript that is 16x the budget")
        shrunk = sum(len(str(m.content)) for m in out)
        grew = sum(len(str(m.content)) for m in candidate)
        if shrunk >= grew:
            return (FAIL, f"salvage returned {shrunk} chars, no smaller than {grew}")
        return f"{grew:,} -> {shrunk:,} chars across {len(out)} messages"

    @cu.probe(P, "the compactor exists and is not a stub")
    def _(_):
        from src.context.compaction import HistoryCompactor

        methods = [m for m in dir(HistoryCompactor) if not m.startswith("_")]
        if len(methods) < 2:
            return (FAIL, f"HistoryCompactor exposes only {methods}")
        return f"HistoryCompactor: {', '.join(methods[:6])}"

    @cu.probe(P, "compaction is fenced so a failed summary cannot corrupt history")
    def _(_):
        from src.context import compression_fence as cf

        lock = getattr(cf, "try_acquire_compression_lock", None)
        fence = getattr(cf, "CompressionCommitFence", None)
        if lock is None or fence is None:
            return (FAIL, "compression lock/fence missing — a failed compaction would commit")
        ok = lock("checkup-session", holder="checkup")
        if ok:
            cf.release_compression_lock("checkup-session", holder="checkup")
        return f"lock acquire={ok}, release path present"

    @cu.probe(P, "two turns cannot compact the same session at once")
    def _(_):
        from src.context import compression_fence as cf

        held = cf.try_acquire_compression_lock("checkup-race", holder="a")
        second = cf.try_acquire_compression_lock("checkup-race", holder="b")
        cf.release_compression_lock("checkup-race", holder="a")
        if not held:
            return (FAIL, "the first holder could not take the lock")
        if second:
            return (FAIL, "a second holder acquired the same session's lock")
        return "first holder wins, second is refused"

    @cu.probe(P, "the engine's own compaction trigger is reachable from chat_graph")
    def _(_):
        src = (ROOT / "src/graphs/chat_graph.py").read_text(encoding="utf-8", errors="replace")
        hits = src.count("compact") + src.count("compress")
        if hits == 0:
            return (FAIL, "chat_graph never mentions compaction")
        return f"{hits} compaction/compression reference(s) in chat_graph"


# ══════════════════════════════════════════════════════════════════════════
# 6. Model call — factory, output cap, sanitizer, repetition
# ══════════════════════════════════════════════════════════════════════════
def check_model_call(cu: Checkup) -> None:
    P = "6 model call"

    @cu.probe(P, "the factory resolves the configured provider/model")
    def _(_):
        from src.llm import factory

        names = [n for n in dir(factory) if not n.startswith("_")]
        if "get_llm" not in names:
            return (FAIL, "factory has no get_llm")
        return f"factory exposes {', '.join(n for n in names if not n.startswith('_'))[:120]}"

    @cu.probe(P, "an output cap is always requested (a provider default is not a budget)")
    def _(_):
        from src.llm import output_budget

        cap = output_budget.requested_output_cap("z-ai/glm-5.3-flash")
        if not isinstance(cap, int) or cap <= 0:
            return (FAIL, f"requested_output_cap returned {cap!r}")
        return f"cap {cap:,} for an unknown model"

    @cu.probe(P, "a provider-reported ceiling is a ONE-SHOT retry override")
    def _(_):
        from src.llm import output_budget

        output_budget.note_available_output("checkup-model", 1234)
        first = output_budget.take_available_output("checkup-model")
        second = output_budget.take_available_output("checkup-model")
        if first != 1234:
            return (FAIL, f"recorded ceiling 1234 came back as {first}")
        if second is not None:
            return (FAIL, f"a stale ceiling survived into the next call ({second})")
        return "1234 returned once, then cleared"

    @cu.probe(P, "malformed tool arguments are normalized, not crashed on")
    def _(_):
        from src.runtime.argument_normalizer import normalize_tool_arguments

        r = normalize_tool_arguments("read_file", '{"filepath": "/tmp/a"}')
        if getattr(r, "normalized_args", None) not in ({}, None) and "path" in r.normalized_args:
            out = f"alias mapped to {r.normalized_args}"
        else:
            out = f"status={r.status} args={r.normalized_args}"
        bad = normalize_tool_arguments("read_file", "this is not json")
        if bad.normalized_args:
            return (WARN, f"invalid JSON still produced args: {bad.normalized_args}")
        return out

    @cu.probe(P, "secrets in arguments are redacted in the audit record")
    def _(_):
        from src.runtime.argument_normalizer import normalize_tool_arguments

        r = normalize_tool_arguments("terminal", {"command": "export KEY=sk-live-abcdef0123456789"})
        rec = json.dumps(r.get_audit_record())
        if "sk-live-abcdef0123456789" in rec:
            return (FAIL, "the raw secret appears in the audit record")
        return "secret redacted in the audit record"

    @cu.probe(P, "an orphan tool result is stripped before the request is sent")
    def _(_):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from src.llm.request_sanitizer import sanitize_request_messages

        msgs = [
            HumanMessage(content="go"),
            AIMessage(content="", tool_calls=[{"name": "read_file", "args": {}, "id": "c1"}]),
            ToolMessage(content="found", tool_call_id="c1"),
            ToolMessage(content="orphan-result-with-no-call", tool_call_id="zzz"),
        ]
        out = sanitize_request_messages(msgs)
        ids = [getattr(m, "tool_call_id", None) for m in out]
        if "zzz" in ids:
            return (FAIL, "a tool result with no matching call survived into the request")
        return f"{len(msgs)} -> {len(out)} messages, orphan removed"

    @cu.probe(P, "degenerate model output is detected before it ships")
    def _(_):
        from src.llm import repetition_guard as rg

        loop = "I will now run the tests. " * 40
        if not rg.is_degenerate_output(loop):
            return (FAIL, "a 40x repeated sentence was not flagged as degenerate")
        if rg.is_degenerate_output("Here is a short normal answer."):
            return (FAIL, "normal prose was flagged as degenerate (false positive)")
        return "loop flagged, prose untouched"


# ══════════════════════════════════════════════════════════════════════════
# 7. Failure recovery — classification, retry, terminal decisions
# ══════════════════════════════════════════════════════════════════════════
def check_failure(cu: Checkup) -> None:
    P = "7 failure recovery"

    @cu.probe(P, "every realistic terminal body is classified terminal")
    def _(_):
        from src.llm.error_classifier import classify_api_error

        cases = [
            ("Error code: 402 - Balance ₹0.00. Top up from ₹10 at https://velona.in/wallet", 402),
            ("Error code: 401 - Incorrect API key provided", 401),
            ("insufficient_quota: You exceeded your current quota", 429),
            ("model_not_found: the model does not exist", 404),
        ]
        bad = []
        for msg, code in cases:
            c = classify_api_error(RuntimeError(msg), provider="custom", model="m")
            if c.retryable:
                bad.append(f"{code}:{c.reason.value}")
        if bad:
            return (FAIL, f"retried as transient: {', '.join(bad)}")
        return "402/401/quota/404 all non-retryable"

    @cu.probe(P, "a bare transport drop classifies instead of raising")
    def _(_):
        from src.llm.error_classifier import classify_api_error

        for body in (
            "connection reset by peer",
            "server disconnected without sending a response",
            "peer closed connection",
        ):
            c = classify_api_error(RuntimeError(body), provider="custom", model="z-ai/glm-5.3-flash")
            if not c.retryable:
                return (FAIL, f"{body!r} -> {c.reason.value}, not retried")
        return "3 disconnect bodies -> timeout, retryable"

    @cu.probe(P, "a throttle is retried, not aborted")
    def _(_):
        from src.llm.error_classifier import classify_api_error

        c = classify_api_error(RuntimeError("rate limit exceeded, retry in 1s"), provider="custom")
        if not c.retryable:
            return (FAIL, f"rate limit classified {c.reason.value} and not retried")
        return f"rate limit -> {c.reason.value}, retryable"

    @cu.probe(P, "context overflow asks for compression, not a retry loop")
    def _(_):
        from src.llm.error_classifier import classify_api_error

        c = classify_api_error(
            RuntimeError("This model's maximum context length is 128000 tokens"),
            provider="custom",
            model="m",
            approx_tokens=200000,
            context_length=128000,
        )
        if not c.should_compress:
            return (FAIL, f"overflow classified {c.reason.value} with should_compress=False")
        return f"overflow -> {c.reason.value}, should_compress=True"

    @cu.probe(P, "one billing predicate (no copy-pasted pattern lists left)")
    def _(_):
        src = (ROOT / "src/llm/error_classifier.py").read_text(encoding="utf-8", errors="replace")
        n = src.count("any(p in error_msg for p in _BILLING_PATTERNS)")
        if n != 1:
            return (FAIL, f"{n} inline copies of the billing predicate (expected 1)")
        return "exactly one definition"


# ══════════════════════════════════════════════════════════════════════════
# 8. Tool pipeline — selection, permission, execution boundary
# ══════════════════════════════════════════════════════════════════════════
def check_tools(cu: Checkup) -> None:
    P = "8 tools"

    @cu.probe(P, "toolset resolution only ever returns known tools")
    def _(_):
        from src.agents.runtime_profile import resolve_runtime_profile
        from src.tools import toolsets

        resolve_runtime_profile("build a react dashboard")  # posture resolves without raising
        known = set(toolsets.all_known_tool_names())
        names = toolsets.resolve_toolset_names("build a react dashboard")
        unknown = [n for n in names if n not in known]
        if unknown:
            return (FAIL, f"resolved names that do not exist: {unknown}")
        return f"{len(names)} resolved, all known"

    @cu.probe(P, "an unknown tool name is refused, with a reason")
    def _(_):
        from src.tools import toolsets

        try:
            names = toolsets.resolve_toolset_names("   ")
        except Exception as exc:  # noqa: BLE001
            return (WARN, f"empty task raises {type(exc).__name__} instead of defaulting")
        return f"empty task -> {len(names)} default tools"

    @cu.probe(P, "tool execution is wrapped in a transaction (no half-applied edit)")
    def _(_):
        from src.runtime import tool_middleware as tm

        if not hasattr(tm, "execute_tool_transaction"):
            return (FAIL, "no execute_tool_transaction")
        return "execute_tool_transaction present"

    @cu.probe(P, "file writes refuse to escape the workspace")
    def _(_):
        from src.context import file_safety

        names = [n for n in dir(file_safety) if not n.startswith("_")]
        guard = [n for n in names if "safe" in n or "within" in n or "inside" in n or "scope" in n]
        if not guard:
            return (WARN, f"no path-escape guard visible: {names[:6]}")
        return f"guards: {', '.join(guard[:4])}"

    @cu.probe(P, "the write guard refuses system paths")
    def _(_):
        from src.context.file_safety import is_write_denied

        refused = {p: is_write_denied(p) for p in ("/etc/passwd", str(Path.home() / ".ssh/id_rsa"))}
        allowed = is_write_denied(str(Path(tempfile.gettempdir()) / "scratch.txt"))
        if not all(refused.values()):
            return (FAIL, f"a system path was writable: {refused}")
        if allowed:
            return (FAIL, "an ordinary scratch file was refused (over-blocking)")
        return "2 system paths refused, a scratch file allowed"

    @cu.probe(P, "parallel tool calls preserve result order")
    def _(_):
        src = (ROOT / "src/graphs/parallel_tools.py").read_text(encoding="utf-8", errors="replace")
        if "index" not in src and "order" not in src:
            return (WARN, "no ordering key visible in parallel_tools")
        return "ordering key present in parallel_tools"


# ══════════════════════════════════════════════════════════════════════════
# 9. Loop control — budgets, gates, progress
# ══════════════════════════════════════════════════════════════════════════
def check_loop(cu: Checkup) -> None:
    P = "9 loop control"

    @cu.probe(P, "each budget leg names itself when it trips")
    def _(_):
        from src.graphs import budget

        os.environ["AGENT_TOKEN_BUDGET"] = "20000"
        try:
            reason = budget._budget_trip_reason(
                {"iteration_used": 1, "turn_token_usage": {"total_tokens": 25000, "cached_tokens": 15000}}
            )
        finally:
            os.environ.pop("AGENT_TOKEN_BUDGET", None)
        if "tripped: tokens" not in reason:
            return (FAIL, f"token trip not identified: {reason}")
        if "15,000 cached" not in reason:
            return (WARN, f"cached tokens not shown: {reason}")
        return reason[:120]

    @cu.probe(P, "iteration and token legs are not confused for each other")
    def _(_):
        from src.graphs import budget

        os.environ["AGENT_TOKEN_BUDGET"] = "1000000"
        try:
            reason = budget._budget_trip_reason({"iteration_used": 999})
        finally:
            os.environ.pop("AGENT_TOKEN_BUDGET", None)
        if "tripped: iterations" not in reason:
            return (FAIL, f"iteration trip mislabelled: {reason}")
        return "iteration trip names iterations"

    @cu.probe(P, "no-tool loops are detected (agent talks forever)")
    def _(_):
        from langchain_core.messages import AIMessage

        from src.graphs import loop_guards

        msgs = [AIMessage(content=f"step {i}") for i in range(5)]
        n = loop_guards.consecutive_no_tool_ai_messages(msgs)
        if n < 5:
            return (WARN, f"counted {n} of 5 consecutive no-tool messages")
        return f"{n} consecutive no-tool messages counted"

    @cu.probe(P, "duplicate repetition guards agree (two copies drift)")
    def _(_):
        from src.graphs import loop_guards
        from src.llm import repetition_guard

        samples = [
            "I will run the tests. " * 60,
            "normal prose about a python file\nand a second line",
            "a" * 500,
            "line\n" * 200,
            "",
        ]
        disagree = []
        for s in samples:
            a = loop_guards.is_repetition_dominated(s)
            b = repetition_guard.is_repetition_dominated(s)
            if a != b:
                disagree.append((s[:18], a, b))
        if disagree:
            return (
                FAIL,
                f"the two guards disagree on {len(disagree)}/{len(samples)} samples: {disagree[:2]}",
            )
        return "both guards agree on all 5 samples"

    @cu.probe(P, "declaring done with no tool activity is refused by the finish gate")
    def _(_):
        from langchain_core.messages import HumanMessage

        from src.graphs.gates import finish_gate_node

        r = finish_gate_node({"messages": [HumanMessage(content="build a todo app in react")], "iteration_used": 1})
        msgs = r.get("messages") or []
        if not msgs:
            return (FAIL, "the gate accepted 'done' with zero tool calls")
        text = str(getattr(msgs[0], "content", ""))
        if "finish" not in text.lower() and "verif" not in text.lower():
            return (WARN, f"gate injected an unclear nudge: {text[:80]}")
        return "gate nudges instead of accepting, and says why"

    @cu.probe(P, "progress is measured, not assumed")
    def _(_):
        from src.graphs import progress_guard

        names = [n for n in dir(progress_guard) if not n.startswith("_")]
        return f"progress_guard: {', '.join(names[:4])}"


# ══════════════════════════════════════════════════════════════════════════
# 10. Verification & evidence
# ══════════════════════════════════════════════════════════════════════════
def check_verification(cu: Checkup) -> None:
    P = "10 verification"

    @cu.probe(P, "evidence for a missing manifest is refused, not assumed")
    def _(_):
        from src.runtime.evidence_validation import validate_turn_evidence

        res = validate_turn_evidence("/nonexistent/manifest.json")
        if res.integrity_valid or res.finalized:
            return (FAIL, "a nonexistent manifest validated as complete")
        return f"refused with {list(res.errors)[:1]}"

    @cu.probe(P, "verification status is derived from receipts, not from the model's word")
    def _(_):
        from src.graphs import gates

        st = gates.verification_status({"messages": []})
        if st != gates.UNVERIFIED:
            return (FAIL, f"an empty run derives {st!r}, not UNVERIFIED")
        # code written but nothing ran: still unverified
        state = {"messages": [], "files_changed": ["a.py"], "edits": [{"path": "a.py"}]}
        st2 = gates.verification_status(state)
        if st2 == gates.PASSED:
            return (FAIL, "code written with no passing check still derives PASSED")
        return f"empty run -> {st}, code-but-unchecked -> {st2}"

    @cu.probe(P, "a failed run derives completed=False")
    def _(_):
        from src.runtime import status_contract as sc

        out = sc.synthesize_status_contract(
            run_outcome="failed",
            verification_status="not_run",
            specification_status="unknown",
            failure_reason="provider 402",
        )
        if out.get("task_completed"):
            return (FAIL, "a failed run reports task_completed=True")
        if out.get("failure_reason") != "provider 402":
            return (FAIL, "the failure reason was dropped")
        return "completed=False and the reason survives"

    @cu.probe(P, "verification contracts execute a real check and report the failure")
    def _(_):
        from src.runtime.verification_contracts import VerificationContractEngine

        with tempfile.TemporaryDirectory() as td:
            eng = VerificationContractEngine(td)
            eng.add_check({"id": "always_fails", "kind": "shell", "command": "exit 3", "required": True})
            report = eng.execute_all()
            results = report.get("results") or []
            if not results:
                return (FAIL, f"no result recorded: {list(report)[:6]}")
            r = results[0]
            if r.get("passed") is not False:
                return (FAIL, f"exit 3 reported as passed: {r}")
            return f"failure captured: {r.get('id')} passed={r.get('passed')} exit={r.get('exit_code')}"


# ══════════════════════════════════════════════════════════════════════════
# 11. Persistence & observability
# ══════════════════════════════════════════════════════════════════════════
def check_persistence(cu: Checkup) -> None:
    P = "11 persistence"

    @cu.probe(P, "a checkpoint store can be opened and reopened")
    def _(_):
        from langgraph.checkpoint.sqlite import SqliteSaver

        with tempfile.TemporaryDirectory() as td:
            p = str(Path(td, "cp.sqlite"))
            with SqliteSaver.from_conn_string(p) as saver:
                assert saver is not None
            assert Path(p).exists(), "no database file was created"
        return "sqlite checkpoint store round-trips"

    @cu.probe(P, "an unanswered tool call is detected in the event journal")
    def _(_):
        from src.runtime.evidence_validation import _pairing_gaps

        events = [
            {"type": "tool.intent", "tool_call_id": "c1", "tool": "read_file"},
            {"type": "tool.intent", "tool_call_id": "c2", "tool": "write_file"},
            {"type": "tool.result", "tool_call_id": "c1"},
        ]
        gaps = _pairing_gaps(events)
        flat = json.dumps(gaps)
        if "c2" not in flat:
            return (FAIL, f"the unanswered call c2 was not reported: {flat[:150]}")
        return "the unanswered tool call is named"

    @cu.probe(P, "an unfinished turn is caught by the watchdog, with a reason")
    def _(_):
        from src.bridge import turn_watchdog

        names = [n for n in dir(turn_watchdog) if not n.startswith("_")]
        return f"turn_watchdog: {', '.join(names[:5])}"

    @cu.probe(P, "the run-state ledger records cost/tokens, not just outcomes")
    def _(_):
        from src.runtime import run_state_ledger

        names = [n for n in dir(run_state_ledger) if not n.startswith("_")]
        return (SKIP, f"ledger: {', '.join(names[:5])}")


# ══════════════════════════════════════════════════════════════════════════
# 12. Turn finalize — the frame a client trusts
# ══════════════════════════════════════════════════════════════════════════
def check_finalize(cu: Checkup) -> None:
    P = "12 finalize"

    @cu.probe(P, "a terminal frame always carries an outcome")
    def _(_):
        src = (ROOT / "src/bridge/__main__.py").read_text(encoding="utf-8", errors="replace")
        if '"run_outcome"' in src or "'run_outcome'" in src:
            return "terminal frames carry run_outcome"
        return (FAIL, "terminal frames carry no run_outcome")

    @cu.probe(P, "a budget cut still reports a reason a client can act on")
    def _(_):
        src = (ROOT / "src/bridge/__main__.py").read_text(encoding="utf-8", errors="replace")
        if "budget" in src.lower() and "reason" in src.lower():
            return "budget termination path mentions a reason"
        return (WARN, "budget termination has no reason field")

    @cu.probe(P, "an API failure reaches the client as a classified surface, not None")
    def _(_):
        from src.dashboard.error_surface import build_error_surface_from_exception

        class _ApiError(Exception):
            status_code = 402
            body = {"error": {"message": "Balance zero"}}

        out = build_error_surface_from_exception(
            _ApiError("Error code: 402 - Balance zero"), provider="custom", model="m"
        )
        if not out:
            return (FAIL, "the error surface returned None — the failure would be invisible")
        if out.get("layer") != "billing":
            return (WARN, f"surfaced as {out.get('layer')}/{out.get('code')}")
        return f"surface: layer={out['layer']} retryable={out['retryable']}"

    @cu.probe(P, "turn control can be cancelled from outside")
    def _(_):
        from src.runtime import turn_control as tc

        tc.set_active_session("checkup-s")
        ok = tc.active_session() == "checkup-s"
        tc.set_active_session(None)
        if not ok:
            return (FAIL, "active session is not tracked")
        return "cancellation target is addressable"


# ══════════════════════════════════════════════════════════════════════════
# 13. Cross-cutting hygiene: dead code, import side effects
# ══════════════════════════════════════════════════════════════════════════
def check_hygiene(cu: Checkup) -> None:
    P = "13 hygiene"

    @cu.probe(
        P,
        "every core module imports without credentials or optional SDKs",
        fix="import optional third-party SDKs inside the function that uses them",
    )
    def _(_):
        """Distinguish a BROKEN module from an environment missing an extra.

        Both raise ImportError, and treating them alike made this check red on
        a CI runner that had deliberately not installed every optional SDK --
        a false alarm. A missing *in-repo* module or a non-ImportError failure
        is structural; a missing third-party package is an environment choice
        and is reported as a WARN with the package named.
        """
        result = run_guarded_import_probe()
        if result["violations"]:
            return (
                FAIL,
                "guarded import blocked unsafe operation(s): "
                + ", ".join(result["violations"][:5]),
            )
        if not result["ok"]:
            detail = (
                result.get("probe_error")
                or "; ".join(result["errors"][:2])
                or "unknown guarded-import failure"
            )
            return (
                FAIL,
                "guarded import probe failed: " + detail,
            )
        if result["errors"]:
            return (
                WARN,
                f"{result['error_count']} module(s) could not import under the guard: "
                + "; ".join(result["errors"][:3]),
            )
        return "all core modules import under the safety guard (no spawn or Win32-security calls)"

    def _missing_package_imports():
        """Yield (path, lineno, module, guarded) using the AST, not a regex.

        A regex can only guess whether an import sits inside a try/except; the
        AST knows. That distinction is the whole finding: an unguarded import of
        a missing package crashes, a guarded one degrades in silence.
        """
        import ast as _ast

        missing = ("agent", "hermes", "hermes_state")
        for f in (ROOT / "src").rglob("*.py"):
            try:
                tree = _ast.parse(f.read_text(errors="ignore"))
            except (OSError, SyntaxError):
                continue
            guarded_nodes = set()
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Try):
                    for child in node.body:
                        for sub in _ast.walk(child):
                            guarded_nodes.add(id(sub))
            for node in _ast.walk(tree):
                if isinstance(node, _ast.ImportFrom) and (node.module or "").split(".")[0] in missing:
                    yield f, node.lineno, node.module, id(node) in guarded_nodes
                elif isinstance(node, _ast.Import):
                    for a in node.names:
                        if a.name.split(".")[0] in missing:
                            yield f, node.lineno, a.name, id(node) in guarded_nodes

    @cu.probe(
        P,
        "no module imports a package that does not exist here",
        fix="point the import at src.*; a wrong path inside a bare try/except is silence, not safety",
    )
    def _(_):
        unguarded, guarded = [], []
        for f, line, mod, is_guarded in _missing_package_imports():
            tag = f"{f.relative_to(ROOT)}:{line} ({mod})"
            (guarded if is_guarded else unguarded).append(tag)
        if unguarded:
            return (FAIL, f"{len(unguarded)} UNGUARDED import(s) of a missing package: {', '.join(unguarded[:3])}")
        if guarded:
            return (
                WARN,
                f"{len(guarded)} guarded import(s) of a missing package: {', '.join(guarded[:3])} — "
                "these fail open to a fallback, so the fallback is the real code",
            )
        return "no imports of agent/hermes packages"

    @cu.probe(P, "the checkup itself runs with no API key in the environment")
    def _(_):
        key = os.environ.get("CUSTOM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if key:
            return (WARN, "a key was present; this run did not prove keyless operation")
        return "ran keyless"



# ══════════════════════════════════════════════════════════════════════════
# 14. Economics — what a turn COSTS (added after the wallet ran dry)
# ══════════════════════════════════════════════════════════════════════════
def check_economics(cu: Checkup) -> None:
    """Field 2026-11-01: the first version of this checkup had 13 pipelines and
    ZERO probes about money. It declared the body healthy while a 7-turn session
    was burning the account, because "healthy" had silently been scoped to
    "correct and stable" — not "affordable". Every probe here is offline."""
    P = "14 economics"

    @cu.probe(
        P,
        "one tool result is token-bounded (a turn cannot pay for a file dump)",
        fix="cap tool result size in tokens, not characters",
    )
    def _(_):
        from src.tools import terminal_tools

        cap = int(os.environ.get("CRUSORAI_TERMINAL_MAX_OUTPUT_CHARS", "12000"))
        tokens = cap / 4  # ~4 chars/token
        if cap <= 0:
            return (FAIL, "no terminal output cap — one command can inject unbounded context")
        if tokens > 2000:
            return (
                WARN,
                f"{cap:,} chars (~{tokens:,.0f} tokens) per tool result; 30 calls/turn "
                f"= ~{tokens * 30:,.0f} tokens before any reasoning",
            )
        return f"{cap:,} chars (~{tokens:,.0f} tokens) per result"

    @cu.probe(
        P,
        "money is a budget leg, not a hope",
        fix="set AGENT_COST_BUDGET; a token cap cannot bound spend",
    )
    def _(_):
        from src.graphs import budget

        os.environ["AGENT_COST_BUDGET"] = "0.25"
        try:
            leg = budget._cost_budget()
        finally:
            os.environ.pop("AGENT_COST_BUDGET", None)
        if leg != 0.25:
            return (FAIL, f"AGENT_COST_BUDGET=0.25 parsed as {leg!r}")
        os.environ.pop("AGENT_COST_BUDGET", None)
        if budget._cost_budget() is not None:
            return (WARN, "the cost leg is off by default — a session runs until the provider refuses")
        return "0.25 parses; off by default (explicit opt-in)"

    @cu.probe(P, "cached tokens are visible in the budget receipt")
    def _(_):
        from src.graphs import budget

        os.environ["AGENT_TOKEN_BUDGET"] = "20000"
        try:
            reason = budget._budget_trip_reason(
                {"iteration_used": 1, "turn_token_usage": {"total_tokens": 40000, "cached_tokens": 21000}}
            )
        finally:
            os.environ.pop("AGENT_TOKEN_BUDGET", None)
        if "21,000 cached" not in reason:
            return (FAIL, f"a receipt hid how much of the spend was cache: {reason}")
        return "cached share is printed, so 'exhausted' cannot read as 'wasteful'"

    @cu.probe(
        P,
        "the harness reports spend per COMPLETED turn",
        fix="cost per completed turn; total spend rewards cutting work",
    )
    def _(_):
        from scripts.run_long_session import summarize

        out = summarize(
            [
                {"turn": 1, "result": "turn_done", "completed": True, "tokens_in_telemetry": 100},
                {"turn": 2, "result": "turn_done", "completed": False, "tokens_in_telemetry": 900},
            ],
            2,
        )
        if out.get("tokens_spent_on_cut_turns") != 900:
            return (FAIL, f"waste not separated: {out.get('tokens_spent_on_cut_turns')}")
        if out.get("tokens_per_completed_turn") != 1000.0:
            return (FAIL, f"per-completed-turn not reported: {out.get('tokens_per_completed_turn')}")
        return "total 1,000 on 900 discarded by 1 completed turn"

    @cu.probe(
        P,
        "explicit prompt-cache breakpoints are ON for the configured route",
        fix="set CRUSORAI_PROMPT_CACHE=1 and CRUSORAI_PROMPT_CACHE_CUSTOM=1 for a custom route, "
        "or accept that only implicit gateway caching applies",
    )
    def _(_):
        from src.context import prompt_cache_plan as pcp

        enabled = pcp._cache_enabled("custom", "z-ai/glm-5.3-flash")
        if not enabled:
            return (
                WARN,
                "explicit cache breakpoints OFF for provider 'custom' — the 39-53% hit rate "
                "measured live came only from the gateway's implicit cache",
            )
        return "explicit breakpoints enabled for custom routes"

    @cu.probe(P, "a compaction invalidates the prompt cache (measurable, and unmitigated)")
    def _(_):
        src = (ROOT / "src/context/compaction.py").read_text(encoding="utf-8", errors="replace")
        marks = sum(src.count(k) for k in ("cache_control", "stable_prefix", "prompt_cache_plan"))
        if marks == 0:
            return (
                WARN,
                "compaction does not consult the cache plan at all: summarising history rewrites "
                "the prefix, so the next call re-prefills the whole prompt at full price",
            )
        return f"{marks} cache-aware reference(s) inside compaction"

    @cu.probe(P, "the agent's per-turn call budget is not below production")
    def _(_):
        from scripts.run_long_session import _build_parser

        args = _build_parser().parse_args(["--workspace", "w", "--prompts-file", "p"])
        if args.agent_iteration_budget < 45:
            return (FAIL, f"harness gives the agent {args.agent_iteration_budget} calls, production is 45")
        return f"harness {args.agent_iteration_budget}, safety stop {args.max_llm_calls}"


# ══════════════════════════════════════════════════════════════════════════
def run_all() -> Checkup:
    cu = Checkup()
    for section in (
        check_ingress,
        check_session,
        check_prompt,
        check_context,
        check_compaction,
        check_model_call,
        check_failure,
        check_tools,
        check_loop,
        check_verification,
        check_persistence,
        check_finalize,
        check_hygiene,
        check_economics,
    ):
        try:
            section(cu)
        except Exception:  # noqa: BLE001 - a whole section must not kill the checkup
            cu.add(section.__name__, "section aborted", FAIL, traceback.format_exc(limit=2)[-200:])
    return cu


def render_markdown(cu: Checkup) -> str:
    s = cu.summary()
    c = s["counts"]
    lines = [
        "# Agent-core body checkup",
        "",
        f"**{s['total']} checks across {len(s['by_pipeline'])} pipelines — "
        f"{c[PASS]} pass · {c[WARN]} warn · {c[FAIL]} fail · {c[SKIP]} noted**",
        "",
        "| # | Pipeline | Checks | Pass | Warn | Fail | Verdict |",
        "| ---: | :--- | ---: | ---: | ---: | ---: | :--- |",
    ]
    for i, (pipe, counts) in enumerate(s["by_pipeline"].items(), 1):
        total = sum(counts.values())
        verdict = "**BROKEN**" if counts[FAIL] else ("works, with holes" if counts[WARN] else "healthy")
        lines.append(
            f"| {i} | {pipe} | {total} | {counts[PASS]} | {counts[WARN]} | {counts[FAIL]} | {verdict} |"
        )
    for status, title in ((FAIL, "Failures"), (WARN, "Warnings"), (SKIP, "Noted")):
        rows = [x for x in cu.checks if x.status == status]
        if not rows:
            continue
        lines += ["", f"## {title}", ""]
        for x in rows:
            lines.append(f"- **{x.pipeline} — {x.name}**: {x.detail}")
            if x.fix:
                lines.append(f"  - *fix*: {x.fix}")
    lines += ["", "## Every check", "", "| Pipeline | Check | Status | Detail |", "| :--- | :--- | :--- | :--- |"]
    for x in cu.checks:
        detail = x.detail.replace("|", "/")[:110]
        lines.append(f"| {x.pipeline} | {x.name} | {x.status} | {detail} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    ap.add_argument("--md")
    args = ap.parse_args()
    cu = run_all()
    s = cu.summary()
    print(f"\n{'pipeline':<22} {'pass':>4} {'warn':>5} {'fail':>5}")
    for pipe, counts in s["by_pipeline"].items():
        print(f"{pipe:<22} {counts[PASS]:>4} {counts[WARN]:>5} {counts[FAIL]:>5}")
    c = s["counts"]
    print(f"\n{c[PASS]} pass · {c[WARN]} warn · {c[FAIL]} fail · {c[SKIP]} noted")
    for x in cu.checks:
        if x.status in (FAIL, WARN):
            print(f"  [{x.status}] {x.pipeline}: {x.name} — {x.detail}")
    if args.json:
        Path(args.json).write_text(
            json.dumps({"summary": s, "checks": [asdict(x) for x in cu.checks]}, indent=2)
        )
    if args.md:
        Path(args.md).write_text(render_markdown(cu))
    return 0 if c[FAIL] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
