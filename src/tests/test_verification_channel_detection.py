"""The gate must read the verification channel the USER named.

Field 2026-11-01, live GLM 5.3 MVP run (session t5-da9b3e8719):

  prompt:  "mvp/test_server.py — a `unittest` file that ..."
           "Then run `python mvp/test_server.py` with the terminal tool and
            confirm it passes. If it fails, fix it and re-run until it passes."
  reality: mvp/server.py, index.html, styles.css, test_server.py all written,
           and mvp/__pycache__/server.cpython-311.pyc existed — bytecode is
           only emitted when the module is imported, so the test really ran.
  verdict: finalize entered with `unverified=True`, turn came back
           completed=False, and the E2E report scored I5 FAIL.

Three independent reasons, all in this file's blast radius:

  1. the token list knew " test" (leading space) but the command is
     `python mvp/test_server.py` — slash before "test", so no receipt at all;
  2. the prompt's word "page" made _looks_like_ui_task true, so the gate
     additionally demanded browser navigate + rendered proof, which a
     stdlib ThreadingHTTPServer task never asks for and the runner cannot give;
  3. test_suite_ask only knew "automated test"/"run the tests", so the
     explicitly named test channel never downgraded (2).

A gate that ignores the user's own stated check is not being honest, it is
being unhelpfully strict — and it fails the run while the artifact is green.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.graphs import gates

PROMPT = (
    "Build a minimal, COMPLETE \"PulseAir Status\" MVP. It must run with no "
    "third-party dependencies.\n"
    "1. `mvp/server.py` — a Python standard-library HTTP server on port 8137.\n"
    "2. `mvp/index.html` — a single page that fetches `/api/health` on load.\n"
    "4. `mvp/test_server.py` — a `unittest` file that starts the server on an "
    "ephemeral port in a background thread and asserts the health route.\n"
    "Then run `python mvp/test_server.py` with the terminal tool and confirm "
    "it passes. If it fails, fix it and re-run until it passes."
)

PASSING_TEST_OUTPUT = (
    "Ran 2 tests in 0.031s\n"
    "\n"
    "OK\n"
    "Exit code: 0"
)


# ---------------------------------------------------------------- unit level


@pytest.mark.parametrize(
    "command",
    [
        "python mvp/test_server.py",
        "python3 test_server.py",
        "python -m unittest discover -s mvp",
        "python -m pytest -q",
        "npm test",
        "pytest -q mvp/",
        "./run_tests.sh",
        "bash scripts/test_all.py",
    ],
)
def test_named_test_file_is_a_verification_command(command):
    assert gates._is_verification_command(command) is True


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "git status",
        "python mvp/server.py",
        "cat mvp/server.py",
    ],
)
def test_plain_commands_are_not_verification(command):
    """No false positives: running the app is not the same as checking it."""
    assert gates._is_verification_command(command) is False


def test_prompt_naming_a_unittest_file_counts_as_a_test_suite_ask():
    """The user named the channel, so browser domains are not owed."""
    import re

    assert re.search(
        r"(?i)(?:automated test|run (?:the )?(?:automated )?tests?"
        r"|\bunittest\b|\bpytest\b|\btest_[\w.-]*\.py\b|\b[\w.-]*_tests?\.py\b"
        r"|\bpython[\d.]*\s+-m\s+(?:unittest|pytest)\b"
        r"|\btest suite\b|\btests? pass(?:es)?\b)",
        PROMPT,
    )


# ------------------------------------------------------- end-to-end gate state


def _state(tmp_path: Path):
    (tmp_path / "mvp").mkdir()
    (tmp_path / "mvp" / "server.py").write_text(
        "from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer\n"
    )
    (tmp_path / "mvp" / "index.html").write_text("<html><body><div id=health></div></body></html>")
    (tmp_path / "mvp" / "styles.css").write_text("body{background:#111}")
    (tmp_path / "mvp" / "test_server.py").write_text(
        "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
    )
    messages = [
        HumanMessage(content=PROMPT),
        AIMessage(
            content="",
            tool_calls=[{
                "id": "call-check",
                "name": "run_terminal",
                "args": {"command": "python mvp/test_server.py"},
            }],
        ),
        ToolMessage(
            content=PASSING_TEST_OUTPUT,
            tool_call_id="call-check",
            name="run_terminal",
        ),
        AIMessage(content="Ran python mvp/test_server.py — 2 tests, OK."),
    ]
    return {
        "messages": messages,
        "workspace": str(tmp_path),
        "steps_completed": ["write", "run test"],
        "failed_steps": [],
        "current_task": PROMPT,
        "latest_instruction": PROMPT,
    }


def test_named_test_run_satisfies_the_verification_gate(tmp_path):
    """The exact field shape: code written + the named test file run green."""
    state = _state(tmp_path)
    receipt = gates._verification_receipt_status(state)

    assert receipt["ran_any"] is True
    assert receipt["static"] is True, receipt
    # The user named the test channel, so no browser proof is owed.
    assert "navigate" not in receipt["required"], receipt
    assert "rendered" not in receipt["required"], receipt
    assert receipt["passed"] is True, receipt
    assert gates._verification_ran_and_passed(state) is True


def test_unnamed_ui_task_still_owes_browser_proof(tmp_path):
    """Regression guard: the fix must not delete the UI gate.

    A UI task that never names a test suite still owes navigate + render
    evidence — a 500 page is unverified UI regardless of how clean it looks.
    """
    state = _state(tmp_path)
    ui_prompt = (
        "Build a web app dashboard in the current workspace with a dark theme. "
        "Write it to mvp/index.html and mvp/server.py."
    )
    state["messages"][0] = HumanMessage(content=ui_prompt)
    state["current_task"] = ui_prompt
    state["latest_instruction"] = ui_prompt

    receipt = gates._verification_receipt_status(state)
    assert receipt["ui_task"] is True
    assert "navigate" in receipt["required"], receipt
    assert receipt["passed"] is False, receipt


# ------------------------------------------------- report-level visibility


def test_report_lists_the_commands_the_agent_ran(tmp_path, monkeypatch):
    """The verdict must show what the agent DID, not only what it spent.

    Two 2026-11-01 runs cost a full diagnosis each because the report showed
    tokens and node counts and nothing about which commands were executed —
    "never ran the test the prompt named" and "ran it and was ignored" looked
    identical.
    """
    import json
    import os
    import subprocess
    import sys

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    frames = [
        {"type": "turn_started", "session_id": f"s-cmd"},
        {"type": "tool_call_start", "tool_id": "t1", "name": "terminal",
         "arguments": {"command": "cd mvp && python mvp/test_server.py"}},
        {"type": "tool_call_end", "tool_id": "t1", "status": "ok",
         "result": "Ran 3 tests\n\nOK\nExit code: 0"},
        {"type": "tool_call_start", "tool_id": "t2", "name": "terminal",
         "arguments": {"command": "ls mvp"}},
        {"type": "tool_call_end", "tool_id": "t2", "status": "ok", "result": "server.py"},
        {"type": "turn_done", "session_id": "s-cmd", "completed": True,
         "run_outcome": "completed"},
    ]
    (run_dir / "frames.jsonl").write_text("\n".join(json.dumps(f) for f in frames) + "\n")
    (run_dir / "outcome.json").write_text(json.dumps({"session_id": "s-cmd"}))

    repo_root = Path(__file__).resolve().parents[2]
    out = run_dir / "report.md"
    subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "e2e_core_report.py"),
         "--run-dir", str(run_dir), "--out", str(out)],
        capture_output=True, text=True, env=dict(os.environ), cwd=str(repo_root),
    )
    report = out.read_text()

    assert "## Commands the agent ran" in report
    assert "python mvp/test_server.py" in report
    assert "ls mvp" in report
    # `ls` is not a check; the test file is.
    assert "| ok | yes |" in report
    assert "| ok | no |" in report
    assert "1 verification command(s) run, 1 green" in report


# --------------------------------------------------- unclosable-debt guard


def test_transient_probe_failure_does_not_create_permanent_debt():
    """Field 2026-11-01 run 41279653910, the exact sequence.

    The agent ran its real test file green, probed the not-yet-finished API with
    an inline `python -c` (which errored), then ran the test file green again.
    The probe counted as a "check" because the string "health" appeared in it,
    so it minted a debt whose only cure is re-running THAT command identity —
    nobody re-runs a throwaway one-liner, so the turn was unclosable.
    """
    from src.graphs.gates import _unresolved_failed_verification_checks

    probe = (
        'cd ws && python -c " import threading, urllib.request, json, sys\n'
        "sys.path.insert(0, 'mvp')\nfrom server import create_server\n"
        "srv = create_server()\nurllib.request.urlopen('http://127.0.0.1:8137/api/health') \""
    )
    state = {
        "execution_trace": [
            {"tool": "terminal", "args": {"command": "python mvp/test_server.py -v"},
             "status": "success", "result": "Ran 3 tests\n\nOK\nExit code: 0"},
            {"tool": "terminal", "args": {"command": probe},
             "status": "failed", "result": "ImportError: cannot import name 'create_server'\nExit code: 1"},
            {"tool": "terminal", "args": {"command": "python mvp/test_server.py -v"},
             "status": "success", "result": "Ran 3 tests\n\nOK\nExit code: 0"},
        ],
    }
    assert _unresolved_failed_verification_checks(state) == []


def test_real_failing_test_file_still_owes_a_rerun():
    """The narrowing must not disarm the nudge for a genuine failing suite."""
    from src.graphs.gates import _unresolved_failed_verification_checks

    state = {
        "execution_trace": [
            {"tool": "terminal", "args": {"command": "python mvp/test_server.py -v"},
             "status": "failed", "result": "FAILED (failures=1)\nExit code: 1"},
        ],
    }
    debts = _unresolved_failed_verification_checks(state)
    assert len(debts) == 1
    assert debts[0]["repair_landed"] is False


# ------------------------------------------- integrity: document-root scope


def _mvp_workspace(tmp_path: Path, stylesheet_href: str) -> Path:
    mvp = tmp_path / "mvp"
    mvp.mkdir()
    (mvp / "server.py").write_text("from http.server import ThreadingHTTPServer\n")
    (mvp / "styles.css").write_text("body{background:#111}")
    (mvp / "test_server.py").write_text("import unittest\n")
    (mvp / "index.html").write_text(
        f'<html><head><link rel="stylesheet" href="{stylesheet_href}"></head>'
        '<body><div id="health"></div></body></html>'
    )
    return tmp_path


def test_root_absolute_reference_resolves_from_the_served_directory(tmp_path):
    """`/styles.css` served out of `mvp/` is correct, not missing.

    Field 2026-11-01: the prompt specified `mvp/styles.css` served at
    `/styles.css`. The agent did exactly that, and the integrity audit called it
    a missing dependency because it resolved root-absolute paths against the
    workspace root only — the one domain still missing at finalize
    (`missing=['integrity']`) on a turn whose test was green and whose live
    endpoint returned 200 {"status":"ok"}.
    """
    from src.context.workspace_integrity import audit_workspace

    workspace = _mvp_workspace(tmp_path, "/styles.css")
    assert audit_workspace(workspace) == []


def test_genuinely_missing_root_absolute_reference_is_still_reported(tmp_path):
    """Widening the document root must not silence the audit."""
    from src.context.workspace_integrity import audit_workspace

    workspace = _mvp_workspace(tmp_path, "/does-not-exist.css")
    findings = {(i.kind, i.path, i.reference) for i in audit_workspace(workspace)}
    assert findings == {("missing-html-reference", "mvp/index.html", "/does-not-exist.css")}
