"""Pins for execute_code (D18, programmatic tool calling).

Every test asserts a BEHAVIOR the design doc claims:
- only print() output returns, chained tools run in-process
- caps: 50KB stdout, 50 tool calls, wall-clock deadline (in worker threads)
- AST allowlist rejects imports/builtins bypasses BEFORE any execution
- SafetyGuard checkpoints are re-enforced INSIDE scripts (overwrite,
  destructive shell) -- auto-deny + guidance, operations never execute
- tool failures inside scripts degrade to strings, not script death
- registry/guard wiring matches the documented design
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.tools import code_exec_tool
from src.tools.code_exec_tool import execute_code


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "a.py").write_text("def login():\n    return 1\n" * 100)
    (tmp_path / "b.py").write_text("def logout():\n    return 2\n" * 80)
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "precious.txt").write_text("do not delete")
    return tmp_path


@pytest.fixture()
def cfg(ws):
    return {"configurable": {"workspace": str(ws), "thread_id": "ptc-test"}}


def run(code: str, cfg) -> str:
    return execute_code.invoke({"code": code}, config=cfg)


# ---------------------------------------------------------------- pipeline
def test_chained_pipeline_returns_only_print_output(ws, cfg):
    script = (
        'a = read_file("a.py")\n'
        'b = read_file("b.py")\n'
        'hits = search_code("def login", ".")\n'
        'print(f"a={len(a)}ch b={len(b)}ch | {hits.splitlines()[0]}")'
    )
    result = run(script, cfg)
    assert "a=2600ch b=2160ch" in result
    assert "a.py:1" in result
    # The whole point: raw tool payloads never enter the window.
    assert "return 1" not in result
    assert len(result) < 200


def test_no_print_gets_friendly_hint(cfg):
    result = run("x = 1 + 1", cfg)
    assert "printed nothing" in result
    assert "print()" in result


def test_runner_output_collapses_to_tail_lines(cfg, ws):
    # `seq` is a Unix binary that only exists on PATH inside Git Bash, not
    # plain PowerShell/cmd (Windows portability — same class as the `which`
    # collection bugs). Generate the 500 lines with the venv python instead;
    # forward slashes are accepted by both cmd.exe and /bin/sh.
    (ws / "gen.py").write_text("for i in range(1, 501):\n    print(i)\n")
    py = Path(sys.executable).as_posix()
    script = (
        f'out = run_terminal("{py} gen.py")\n'
        "nums = [l for l in out.splitlines() if l.isdigit()]\n"
        "print(len(nums))\n"
        "print(nums[-1])"
    )
    result = run(script, cfg)
    lines = result.strip().splitlines()
    assert lines[0] == "500"       # line count computed IN the script
    assert lines[1] == "500"       # 500 lines of output never returned
    assert len(result) < 80

# ------------------------------------------------------------------ caps
def test_stdout_capped_at_50k(cfg):
    result = run("print('x' * 120000)", cfg)
    assert "truncated at 50000" in result
    assert len(result) < 50_100


def test_tool_call_budget_enforced(cfg):
    script = (
        "for i in range(60):\n"
        '    list_files(".")\n'
        'print("should never see this")'
    )
    result = run(script, cfg)
    assert "50" in result and "budget" in result
    assert "should never see this" not in result


def test_deadline_kills_infinite_loop_inside_worker_thread(cfg, monkeypatch):
    monkeypatch.setattr(code_exec_tool, "_PTC_TIMEOUT_S", 0.5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run, "while True:\n    pass", cfg)
        result = future.result(timeout=15)   # must come back, not hang
    assert "time budget" in result


def test_oversized_script_rejected(cfg):
    result = run("print(1)\n" + "# pad\n" * 4000, cfg)
    assert "exceeds the" in result and "16000" in result

# -------------------------------------------------------- AST allowlist
REJECTED_SNIPPETS = [
    "import subprocess",
    "from subprocess import run",
    "open('a.py')",
    "x = (1).__class__",
    "getattr([], 'append')",
    "exec('print(1)')",
    "eval('1+1')",
    "__import__('os')",
    "async def f():\n    pass",
]


@pytest.mark.parametrize("snippet", REJECTED_SNIPPETS)
def test_banned_constructs_rejected(snippet, cfg):
    assert "rejected" in run(snippet, cfg).lower()


def test_rejection_happens_before_any_execution(ws, cfg):
    script = 'write_file("evil.txt", "x")\nimport subprocess'
    result = run(script, cfg)
    assert "rejected" in result.lower()
    assert not (ws / "evil.txt").exists(), "rejected script must have zero side effects"


def test_preloaded_modules_include_hardened_os(cfg):
    """D8: os is now preloaded (hardened — pure path/dir helpers only) so
    the agent's batch scripts (`import os; os.makedirs(...)`) run instead
    of being rejected and falling back to one write_file per round trip."""
    good = run("print(json.dumps({'r': len(re.findall('a', 'banana')), 's': math.sqrt(16)}))", cfg)
    assert '"r": 3' in good and '"s": 4.0' in good
    ok = run("print(os.path.basename('x/y.py'))", cfg)
    assert "y.py" in ok
    # hardened: no process-escape surface
    assert "Script error" in run("print(os.system('echo hi'))", cfg)
    assert "Script error" in run("print(os.popen('echo hi'))", cfg)

# --------------------------------------------- safety inside the script
def test_destructive_command_denied_and_never_runs(ws, cfg):
    script = (
        'r = run_terminal("rm -rf keep")\n'
        "print(r.splitlines()[0])"
    )
    result = run(script, cfg)
    assert "⛔" in result and "Safety guard" in result
    # Real proof nothing executed: the target survived.
    assert (ws / "keep" / "precious.txt").read_text() == "do not delete"


def test_overwrite_checkpoint_enforced_inside_scripts(ws, cfg):
    script = (
        'deny = write_file("a.py", "overwritten!")\n'
        'ok = write_file("fresh.txt", "brand new")\n'
        "print(deny.splitlines()[0])\n"
        "print(ok)"
    )
    result = run(script, cfg)
    assert "⛔" in result                       # existing file: denied
    assert "File written: fresh.txt" in result # new file: allowed, script CONTINUED
    assert ws.joinpath("a.py").read_text().startswith("def login")
    assert (ws / "fresh.txt").read_text() == "brand new"


def test_tool_failures_degrade_to_strings_not_script_death(cfg):
    script = (
        'r = read_file("missing.txt")\n'
        "print(r[:5])\n"
        'print("still alive")'
    )
    result = run(script, cfg)
    assert "Error" in result
    assert "still alive" in result

# ------------------------------------------------------------- wiring
def test_registry_contains_execute_code_once():
    from src.graphs.chat_graph import tools
    names = [t.name for t in tools]
    assert names.count("execute_code") == 1
    assert names.count("session_search") == 1
    # 30 since Test-2: typecheck_workspace (tsc --noEmit verify tool)
    # joined after D33's 21 (delegate_to_subagent_batch); the UI
    # verification pass added 8 browser_* tools.
    assert len(names) == 30


def test_graph_guard_is_name_based_inner_guard_is_the_control(cfg):
    """Pins the documented two-layer policy: SafeToolNode's SafetyGuard only
    inspects tool args by NAME, so execute_code is 'safe' at graph level no
    matter the script text -- the per-inner-call re-check (proven above) is
    the real control. If someone later 'fixes' the graph guard to string-scan
    script code, this pin forces a conscious revisit of that policy."""
    from src.context.safety_guard import SafetyGuard
    is_safe, _ = SafetyGuard(".").check_tool_call(
        "execute_code", {"code": 'run_terminal("rm -rf /")'}
    )
    assert is_safe is True
    # ...and the inner guard still catches the SAME command (defense in depth):
    assert "⛔" in run('print(run_terminal("rm -rf /"))', cfg)


def test_no_recursion_no_delegation_inside_scripts(cfg):
    assert "Script error" in run("execute_code('print(1)')", cfg)
    assert "Script error" in run('delegate_to_subagent("code", "x")', cfg)


def test_workspace_paths_resolve_to_session_workspace(ws, cfg):
    run('write_file("nested/rel.txt", "here")', cfg)
    assert (ws / "nested" / "rel.txt").read_text() == "here"
    assert not os.path.exists(os.path.join(os.getcwd(), "nested", "rel.txt"))


# --------------------------------------------------------- allowlisted imports
def test_allowlisted_import_stripped_os_is_preloaded(cfg):
    """D8 regression: the agent's batch script `import os; os.makedirs(...)`
    was rejected (imports banned, os not preloaded) and it fell back to 19
    single write_file round trips. `import X` of a preloaded module must be
    a no-op (the name is already in the namespace)."""
    result = run("import os\nprint(os.path.dirname('a/b/c'))", cfg)
    assert "a/b" in result
    assert "rejected" not in result


def test_allowlisted_import_asname_and_from_bind(cfg):
    result = run(
        "import os as o\n"
        "from collections import Counter\n"
        "print(o.path.basename('x/y'), Counter('aab')['a'])",
        cfg,
    )
    assert "y 2" in result


def test_disallowed_import_still_rejected(cfg):
    result = run("import subprocess\nprint('nope')", cfg)
    assert "rejected" in result and "subprocess" in result
    assert "nope" not in result


def test_os_makedirs_batch_script_pattern(cfg, ws):
    """The exact D8 script shape (parent-dir creation for file batches)
    now runs inside the sandbox."""
    sub = ws / "batch_sub"
    script = (
        "import os\n"
        f"os.makedirs({str(sub)!r}, exist_ok=True)\n"
        "print('made')"
    )
    result = run(script, cfg)
    assert "made" in result
    assert sub.is_dir()
