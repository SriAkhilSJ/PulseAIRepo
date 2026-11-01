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
