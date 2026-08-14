"""
execute_code -- Programmatic Tool Calling (PTC)
================================================

Lets the LLM write ONE Python script that calls PulseAI's in-process tools
directly, collapsing multi-step tool chains into a single tool call. Only
the script's ``print()`` output re-enters the conversation window.

Pattern lifted from NousResearch hermes-agent
(``tools/code_execution_tool.py``, ledger §29 -> debt D18). Design deltas
from their version, all verified before writing:

* **No RPC.** Their tools can live on remote machines (Docker/SSH) so they
  shuttle calls over a Unix socket / request files. Ours are in-process
  Python functions -- the "transport" is a function call. The whole UDS
  layer is skipped.
* **Custom print, not redirect_stdout.** This process is a server: the
  dashboard, event bus and other threads share sys.stdout. A script-scoped
  capped buffer replaces ``print`` instead of hijacking the global stream.
* **Deadline via per-thread sys.settrace.** ToolNode runs tool calls on
  worker threads; ``signal.alarm`` is main-thread-only. A line-level trace
  hook enforces the wall-clock budget in ANY thread. Honest limit: a single
  pathological C-level expression (``10**10**9``) runs no Python lines and
  can overshoot until it finishes; ``run_terminal`` is additionally
  time-boxed by running it on a bounded daemon thread.
* **SafetyGuard is re-checked per inner call.** The graph-level guard only
  inspects top-level tool args by tool NAME (SafetyGuard.check_tool_call),
  so script text sails past it. Every inner call of write_file (overwrite),
  edit_file (critical path) and run_terminal/start_terminal (dangerous
  command) is re-validated; unsafe ops are DENIED with guidance (auto-deny,
  hermes delegate_tool.py worker-thread policy) because a script cannot
  surface the human approval prompt.
* **Iteration budget.** Hermes refunds PTC iterations from their budget.
  Our analog is structural: LangGraph budgets node executions, and an
  execute_code turn is exactly ONE tool call no matter how many inner calls
  it makes -- the refund is built in.

This is a set of guardrails for cooperative model-written scripts on the
user's own machine, NOT a security boundary against malicious code: the
real boundaries remain workspace path resolution inside every tool and the
SafetyGuard approval checkpoints.
"""

import ast
import builtins
import collections
import datetime
import functools
import itertools
import json
import math
import os
import random
import re
import statistics
import string
import sys
import textwrap
import threading
import time
import types
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.context.safety_guard import SafetyGuard
from src.tools.file_tools import (
    read_file,
    list_files,
    search_code,
    write_file,
    edit_file,
)
from src.tools.terminal_tools import (
    run_terminal,
    start_terminal,
    check_terminal,
    stop_terminal,
    list_terminal_processes,
    cleanup_terminal_processes,
    read_terminal_output,
)
from src.tools.web_tools import web_search, web_fetch

# ---------------------------------------------------------------------------
# Budgets (hermes: 300s / 50 calls / 50KB stdout -- verified §29)
# ---------------------------------------------------------------------------
_PTC_TIMEOUT_S = 120.0
_PTC_MAX_TOOL_CALLS = 50
_PTC_MAX_STDOUT_CHARS = 50_000
_PTC_MAX_SCRIPT_CHARS = 16_000

def _safe_os_namespace() -> types.SimpleNamespace:
    """A hardened `os` for scripts: pure path/dir helpers only.

    D-series finding: the agent's batch scripts use the natural Python
    idiom `import os; os.makedirs(os.path.dirname(path))` — which was
    rejected (no os) and pushed it back to one write_file per round trip.
    Expose ONLY inert helpers: no system/popen/spawn/startfile (process
    escape), no environ (secrets), no remove/unlink/rename (destructive
    outside the sanctioned write_file path). os.path is its own
    SimpleNamespace of pure string ops.
    """
    path = types.SimpleNamespace(
        join=os.path.join, dirname=os.path.dirname, basename=os.path.basename,
        splitext=os.path.splitext, exists=os.path.exists, isfile=os.path.isfile,
        isdir=os.path.isdir, abspath=os.path.abspath, normpath=os.path.normpath,
        sep=os.path.sep,
    )
    return types.SimpleNamespace(
        makedirs=os.makedirs, mkdir=os.mkdir, getcwd=os.getcwd,
        listdir=os.listdir, walk=os.walk, sep=os.sep, linesep=os.linesep,
        path=path,
    )


# Pure-stdlib helper modules preloaded into the script namespace. Import
# statements for allowlisted names are stripped (see
# _strip_allowlisted_imports), so this allowlist IS the module menu.
_PRELOADED_MODULES: dict[str, Any] = {
    "re": re,
    "json": json,
    "math": math,
    "datetime": datetime,
    "collections": collections,
    "itertools": itertools,
    "functools": functools,
    "textwrap": textwrap,
    "statistics": statistics,
    "string": string,
    "random": random,
    "os": _safe_os_namespace(),
}

# Names a script may not load. getattr/setattr/delattr are banned because
# they'd defeat the dunder-attribute ban with string-built names
# (getattr(x, "__" + "class__")); open/eval/exec/compile are obvious.
_BANNED_NAMES = frozenset({
    "exec", "eval", "compile", "open", "input", "globals", "locals",
    "vars", "dir", "getattr", "setattr", "delattr", "help", "exit",
    "quit", "breakpoint", "super", "memoryview", "__import__",
    "__builtins__",
})

# Builtin callables kept available, plus exception types for try/except.
_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bin", "bool", "bytearray", "bytes", "chr",
    "complex", "dict", "divmod", "enumerate", "filter", "float",
    "format", "frozenset", "hash", "hex", "int", "isinstance",
    "issubclass", "iter", "len", "list", "map", "max", "min", "next",
    "oct", "ord", "pow", "range", "repr", "reversed", "round", "set",
    "slice", "sorted", "str", "sum", "tuple", "type", "zip",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "RuntimeError", "StopIteration", "ZeroDivisionError",
    "AttributeError", "NameError", "NotImplementedError", "OSError",
)
_SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES
}
_SAFE_BUILTINS.update({"True": True, "False": False, "None": None})


class _DeadlineExceeded(Exception):
    """Raised by the trace hook when the wall-clock budget is spent."""


class _CallBudgetExceeded(Exception):
    """Raised by a tool stub past _PTC_MAX_TOOL_CALLS inner calls."""


class _CappedStdout:
    """Script-private stdout: appends up to the cap, then drops and flags.

    Deliberately NOT sys.stdout redirection -- other threads (dashboard,
    event bus) share the process stream.
    """

    def __init__(self, cap: int = _PTC_MAX_STDOUT_CHARS):
        self._cap = cap
        self._chunks: list[str] = []
        self._len = 0
        self.truncated = False

    def write(self, text: str) -> None:
        if self._len >= self._cap:
            self.truncated = True
            return
        remaining = self._cap - self._len
        if len(text) > remaining:
            self._chunks.append(text[:remaining])
            self._len = self._cap
            self.truncated = True
        else:
            self._chunks.append(text)
            self._len += len(text)

    def getvalue(self) -> str:
        return "".join(self._chunks)


def _strip_allowlisted_imports(tree: ast.AST) -> None:
    """Rewrite imports of PRELOADED modules into name bindings.

    Keeps the model's natural Python idiom working inside the sandbox:
    `import os` -> nothing (os is already in the namespace, so the name
    is bound by identity); `import os as o` -> `o = os`;
    `from collections import Counter` -> `Counter = collections.Counter`.
    Imports of anything NOT in the allowlist are left untouched so
    _validate_script rejects them with a clear reason.
    """
    allowed_modules = set(_PRELOADED_MODULES)
    drops: set[int] = set()
    replacements: dict[int, list[ast.stmt]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            remaining: list[ast.alias] = []
            binds: list[ast.stmt] = []
            for alias in node.names:
                mod = alias.name.split(".", 1)[0]
                if mod in allowed_modules:
                    if alias.asname:
                        binds.append(ast.Assign(
                            targets=[ast.Name(id=alias.asname, ctx=ast.Store())],
                            value=ast.Name(id=mod, ctx=ast.Load()),
                        ))
                else:
                    remaining.append(alias)
            if remaining:
                node.names = remaining
            else:
                drops.add(id(node))
            if binds:
                replacements[id(node)] = binds
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".", 1)[0]
            if mod in allowed_modules and node.level == 0:
                binds = [
                    ast.Assign(
                        targets=[ast.Name(id=alias.name, ctx=ast.Store())],
                        value=ast.Attribute(
                            value=ast.Name(id=mod, ctx=ast.Load()),
                            attr=alias.name,
                            ctx=ast.Load(),
                        ),
                    )
                    for alias in node.names
                    if alias.name != "*"
                ]
                drops.add(id(node))
                if binds:
                    replacements[id(node)] = binds

    for parent in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            seq = getattr(parent, field, None)
            if not isinstance(seq, list):
                continue
            new_seq: list[ast.stmt] = []
            for child in seq:
                if id(child) in drops:
                    new_seq.extend(replacements.get(id(child), []))
                else:
                    new_seq.append(child)
            setattr(parent, field, new_seq)
    ast.fix_missing_locations(tree)


def _validate_script(tree: ast.AST) -> str | None:
    """Reject scripts outside the cooperative-script allowlist.

    Returns a human/model-readable reason, or None if the script is OK.
    Checked BEFORE anything executes: a rejected script has zero effects.
    """
    _strip_allowlisted_imports(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = (
                (node.names[0].name if node.names else "")
                if isinstance(node, ast.Import)
                else (node.module or "")
            )
            return (
                f"line {node.lineno}: `import {mod}` is disabled. "
                f"Preloaded (use WITHOUT import): "
                f"{', '.join(sorted(_PRELOADED_MODULES))}. "
                f"To write files call the preloaded `write_file(path, "
                f"content)` function (it creates parent dirs); to read, "
                f"`read_file(path)`."
            )
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return (
                f"line {node.lineno}: private/dunder attribute access "
                f"(.{node.attr}) is disabled."
            )
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in _BANNED_NAMES
        ):
            return (
                f"line {node.lineno}: '{node.id}' is not available "
                f"inside execute_code."
            )
        if isinstance(node, (ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith, ast.Await)):
            return f"line {node.lineno}: async constructs are not supported in scripts."
    return None


class _InnerCallDispatcher:
    """Builds the script-visible tool functions over the real tool objects.

    Every stub: (1) counts against the call budget, (2) re-runs the
    SafetyGuard for checkpointed operations and auto-denies, (3) converts
    tool exceptions into error strings so one bad call in a loop doesn't
    kill the script. Budget/deadline exception types always re-raise.
    """

    # Inner ops that must pass SafetyGuard before dispatch, mirroring the
    # graph-level checkpoints the script text bypasses (see module docstring).
    # Values map the stub's args dict -> the args shape the guard inspects.
    _GUARDED_KEY = {
        "write_file": "path",
        "edit_file": "path",
        "run_terminal": "command",
        "start_terminal": "command",
    }

    # Guards are stateless apart from their workspace, so keep one per
    # distinct workspace (SafeToolNode's caching pattern, same reasoning).
    _guards: dict[str, SafetyGuard] = {}
    _guards_lock = threading.Lock()

    def __init__(self, config: RunnableConfig):
        self._config = config
        workspace = (config or {}).get("configurable", {}).get("workspace", ".")
        self._workspace = str(Path(workspace).resolve())
        self._calls = 0
        self._deadline = 0.0

    def set_deadline(self, deadline: float) -> None:
        self._deadline = deadline

    def _guard(self) -> SafetyGuard:
        with self._guards_lock:
            guard = self._guards.get(self._workspace)
            if guard is None:
                guard = SafetyGuard(self._workspace)
                self._guards[self._workspace] = guard
            return guard

    def _deny(self, name: str, warning: str) -> str:
        first_line = warning.strip().splitlines()[0] if warning else "unsafe operation"
        return (
            f"⛔ Safety guard blocked {name}() inside the script: {first_line}\n"
            "A script cannot ask the human for approval. Ask the user first, "
            f"then run {name} as a normal tool call so they can confirm."
        )

    def _count_call(self) -> None:
        self._calls += 1
        if self._calls > _PTC_MAX_TOOL_CALLS:
            raise _CallBudgetExceeded(
                f"script made more than {_PTC_MAX_TOOL_CALLS} tool calls "
                f"({_PTC_MAX_TOOL_CALLS} is the budget per script)"
            )

    def _remaining(self) -> float:
        return max(1.0, self._deadline - time.monotonic())

    def _dispatch(self, name: str, tool_obj, args: dict[str, Any], needs_config: bool) -> str:
        self._count_call()

        guard_key = self._GUARDED_KEY.get(name)
        if guard_key is not None:
            is_safe, warning = self._guard().check_tool_call(name, {guard_key: args.get(guard_key, "")})
            if not is_safe:
                return self._deny(name, warning)

        def _invoke_raw() -> Any:
            if needs_config:
                return tool_obj.invoke(args, config=self._config)
            return tool_obj.invoke(args)

        def _invoke() -> Any:
            # Inner PTC calls cross the same durable middleware as direct and
            # parallel calls; execute_code is not an audit/approval bypass.
            from src.runtime.tool_middleware import execute_tool_transaction
            outcome = execute_tool_transaction(
                name=name, args=args,
                tool_call_id=f"ptc-{threading.get_ident()}-{self._calls}",
                config=self._config, invoke=_invoke_raw,
            )
            return outcome.content

        try:
            # run_terminal is the one unbounded inner call (subprocess.run
            # with no timeout). Give it only the script's remaining budget
            # on a daemon thread so a hung command cannot outlive the script.
            if name == "run_terminal":
                box: dict[str, Any] = {}

                def _run() -> None:
                    try:
                        box["result"] = _invoke()
                    except Exception as error:  # converted to string below
                        box["error"] = error

                worker = threading.Thread(target=_run, daemon=True)
                worker.start()
                worker.join(self._remaining())
                if worker.is_alive():
                    return (
                        f"⏱️ Error: run_terminal({args.get('command', '')!r}) did not "
                        "finish within the script's time budget. For long commands "
                        "use start_terminal + check_terminal instead."
                    )
                if "error" in box:
                    raise box["error"]
                result = box.get("result")
            else:
                result = _invoke()
        except (_DeadlineExceeded, _CallBudgetExceeded):
            raise
        except Exception as error:
            return f"Error: {name}() failed: {type(error).__name__}: {error}"

        return result if isinstance(result, str) else str(result)

    def namespace(self) -> dict[str, Any]:
        """Script-visible tool functions with friendly signatures."""
        return {
            # File tools
            "read_file": lambda path: self._dispatch(
                "read_file", read_file, {"path": path}, True),
            "list_files": lambda path=".": self._dispatch(
                "list_files", list_files, {"path": path}, True),
            "search_code": lambda query, path=".": self._dispatch(
                "search_code", search_code, {"query": query, "path": path}, True),
            "write_file": lambda path, content: self._dispatch(
                "write_file", write_file, {"path": path, "content": content}, True),
            "edit_file": lambda path, old_text, new_text: self._dispatch(
                "edit_file", edit_file,
                {"path": path, "old_text": old_text, "new_text": new_text}, True),
            # Terminal tools
            "run_terminal": lambda command: self._dispatch(
                "run_terminal", run_terminal, {"command": command}, True),
            "start_terminal": lambda command: self._dispatch(
                "start_terminal", start_terminal, {"command": command}, True),
            "check_terminal": lambda process_id, wait_seconds=0: self._dispatch(
                "check_terminal", check_terminal,
                {"process_id": process_id, "wait_seconds": wait_seconds}, False),
            "stop_terminal": lambda process_id: self._dispatch(
                "stop_terminal", stop_terminal, {"process_id": process_id}, False),
            "list_terminal_processes": lambda: self._dispatch(
                "list_terminal_processes", list_terminal_processes, {}, False),
            "cleanup_terminal_processes": lambda: self._dispatch(
                "cleanup_terminal_processes", cleanup_terminal_processes, {}, False),
            "read_terminal_output": lambda process_id, start_line=1, end_line=200: self._dispatch(
                "read_terminal_output", read_terminal_output,
                {"process_id": process_id, "start_line": start_line, "end_line": end_line}, False),
            # Web tools
            "web_search": lambda query, max_results=5: self._dispatch(
                "web_search", web_search, {"query": query, "max_results": max_results}, False),
            "web_fetch": lambda url, max_chars=12_000: self._dispatch(
                "web_fetch", web_fetch, {"url": url, "max_chars": max_chars}, False),
        }


def _run_script(code: str, config: RunnableConfig) -> str:
    """Validate, sandbox-execute, and return ONLY what the script prints."""
    if len(code) > _PTC_MAX_SCRIPT_CHARS:
        return (
            f"⛔ Script rejected: {len(code)} chars exceeds the "
            f"{_PTC_MAX_SCRIPT_CHARS}-char limit. Split the work into smaller scripts."
        )

    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return f"⛔ Script has a Python syntax error (line {error.lineno}): {error.msg}"

    rejection = _validate_script(tree)
    if rejection is not None:
        return f"⛔ Script rejected: {rejection}"

    out = _CappedStdout()

    def _ptc_print(*args: Any, sep: str = " ", end: str = "\n", file: Any = None, flush: bool = False) -> None:
        # `file` is accepted for signature familiarity and deliberately
        # ignored: everything the script "prints" goes to its private buffer.
        out.write(sep.join(str(a) for a in args) + end)

    dispatcher = _InnerCallDispatcher(config)
    dispatcher.set_deadline(time.monotonic() + _PTC_TIMEOUT_S)

    namespace: dict[str, Any] = {"__builtins__": dict(_SAFE_BUILTINS), "print": _ptc_print}
    namespace.update(_PRELOADED_MODULES)
    namespace.update(dispatcher.namespace())

    previous_trace = sys.gettrace()

    def _tracer(frame, event, arg):  # noqa: ANN001, ANN202 - CPython trace API
        if event in ("line", "call"):
            if time.monotonic() > dispatcher._deadline:
                raise _DeadlineExceeded(
                    f"script exceeded its {_PTC_TIMEOUT_S:.0f}s time budget"
                )
        return _tracer

    # D31: one shadow snapshot for the WHOLE script — a PTC script can run
    # write_file/edit_file many times; per-turn dedup makes this cheap.
    from src.tools.shadow_checkpoints import checkpoint_before_mutation
    _ws = (config or {}).get("configurable", {}).get("workspace", ".")
    checkpoint_before_mutation(str(_ws), "execute_code script")

    error_report: str | None = None
    sys.settrace(_tracer)
    try:
        exec(compile(tree, "<execute_code>", "exec"), namespace)  # noqa: S102 - guarded sandbox
    except _DeadlineExceeded as error:
        error_report = f"⏱️ {error}"
    except _CallBudgetExceeded as error:
        error_report = f"⛔ {error}"
    except Exception as error:
        line = "?"
        tb = sys.exc_info()[2]
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == "<execute_code>":
                line = str(tb.tb_lineno)
                break
            tb = tb.tb_next
        error_report = (
            f"⛔ Script error (line {line}): "
            f"{type(error).__name__}: {error}"
        )
    finally:
        sys.settrace(previous_trace)

    stdout = out.getvalue()
    if out.truncated:
        stdout += f"\n... [stdout truncated at {_PTC_MAX_STDOUT_CHARS} chars]"

    if error_report is not None:
        if stdout.strip():
            return f"{error_report}\n--- partial output before the failure ---\n{stdout}"
        return error_report

    if not stdout.strip():
        return (
            "✅ Script finished but printed nothing. "
            "Only print() output is returned -- print the result you want back."
        )
    return stdout


@tool
def execute_code(code: str, config: RunnableConfig) -> str:
    """
    Run ONE Python script that can call the file/terminal/web tools as
    functions, then return ONLY what the script prints.

    WHEN TO USE: 3+ chained tool steps (read, search, then check) in ONE
    call; or raw tool output that would be huge - filter it and print only
    the lines that matter.
    WHEN NOT TO USE: a single simple action (call the tool directly); or
    anything needing human approval (overwrite/edit existing files,
    secrets, destructive shell commands) - those are DENIED inside scripts.

    Callable inside the script (same behavior as the tools):
    read_file, list_files, search_code, write_file (blocked if the file
    exists), edit_file, run_terminal, start_terminal, check_terminal,
    stop_terminal, list_terminal_processes, cleanup_terminal_processes,
    read_terminal_output, web_search, web_fetch.

    RULES: no imports (preloaded: re, json, math, datetime, collections,
    itertools, functools, textwrap, statistics, string, random); no
    open/eval/exec/getattr or dunder attributes; budgets: 120s wall clock,
    50 tool calls, 50KB printed output; errors return as strings - inspect
    and adapt; ALWAYS print() your final result (only printed text is
    returned). Example: read_file, search_code, run_terminal, then print a
    filtered summary.
    """
    return _run_script(code, config)
