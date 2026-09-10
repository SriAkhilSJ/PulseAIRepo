"""Pipe exit-code masking: `npm run build 2>&1 | tail -40` on a BROKEN build
reports tail's exit 0, and pulse read that as a verified pass.

Field 2026-09-10 (test5, owner screenshot): the terminal card showed the
compiler's error lines and then "Passed · exit 0". Root cause is POSIX shell
semantics — a pipeline's status is its LAST member's status — so the receipt
told the truth about the shell and a lie about the build. hermes answers this
in TWO layers, both ported here verbatim:

  1. tools/terminal_tool_result.py::_failure_hint ->
     tools/terminal_hints.py::annotate_masked_success — rc=0 + a masking pipe
     shape + strong failure indicators in the output => the result carries a
     hint that says to treat the run as FAILED; the exit code is never
     rewritten.
  2. agent/verification_evidence.py::_exit_status_is_attributable — a matched
     segment's status must be provable from the shell's exit code before the
     ledger records ANY evidence; pipes, `||`, and backgrounding hide it.
"""
from __future__ import annotations

import os
import stat

from src.context.verification_evidence import (
    VerificationLedger,
    _exit_status_is_attributable,
    _split_shell_segments,
)
from src.tools.terminal_hints import (
    _FAILURE_SHAPES,
    annotate_failure,
    annotate_masked_success,
)

FIELD_COMMAND = "cd /d/TestPulseAI/test5 && npm run build 2>&1 | tail -40"
FIELD_OUTPUT = (
    "STDOUT:\n> test5@0.1.0 build\n> next build\n"
    "  ▲ Next.js 15\n   Linting and checking validity of types ...\n"
    "Failed to compile.\n\n./app/demo/page.tsx\nType error: Property 'x' does not exist.\n"
    "npm ERR! code ELIFECYCLE\nnpm ERR! Exit status 1\nExit code: 0"
)


# ── Layer 1: the terminal receipt's masked-success hint (hermes verbatim) ──


def test_masked_success_hint_fires_for_the_field_command():
    note = annotate_masked_success(FIELD_COMMAND, FIELD_OUTPUT)
    assert note is not None
    assert "Treat this run as FAILED" in note
    assert "NOT of the command before the pipe" in note
    assert "WITHOUT the pipe" in note


def test_masked_success_requires_a_failure_shape():
    clean = "STDOUT:\n> next build\nCompiled successfully.\nExit code: 0"
    assert annotate_masked_success(FIELD_COMMAND, clean) is None


def test_readonly_head_is_suppressed():
    # `grep ... | head` output legitimately contains error text — hermes
    # excludes read-only heads so log inspection never warns.
    assert annotate_masked_success("grep npm build.log | head -20", FIELD_OUTPUT) is None
    assert annotate_masked_success("cat build.log | tail -20", FIELD_OUTPUT) is None


def test_or_fallback_shape_fires():
    cmd = "npm run build || echo build-failed-continuing"
    assert "||` fallback" in annotate_masked_success(cmd, FIELD_OUTPUT)


def test_failed_command_gets_a_recovery_hint():
    hint = annotate_failure("totally-missing-cmd --flag", 127,
                            "bash: totally-missing-cmd: command not found")
    assert hint is not None and "PATH" in hint
    assert "SIGKILL" in annotate_failure("big-job", 137, "")
    assert annotate_failure("whatever", 0, "") is None


def test_failure_shapes_pin_hermes_table():
    for shape in ("npm ERR!", "error: could not compile", "Traceback (most recent call last)",
                  "compilation terminated.", "BUILD FAILED"):
        assert _FAILURE_SHAPES.search(shape), shape


# ── Layer 2: the evidence ledger refuses unattributable exit codes ────────


def _ledger(tmp_path):
    return VerificationLedger(tmp_path / "verification.db")


def test_field_command_records_no_evidence(tmp_path):
    ledger = _ledger(tmp_path)
    assert ledger.record_command(
        session_id="s", workspace=str(tmp_path), command=FIELD_COMMAND,
        exit_code=0, output=FIELD_OUTPUT,
    ) is None
    assert ledger.status(session_id="s", workspace=str(tmp_path))["status"] == "unverified"


def test_bare_and_andchain_still_record(tmp_path):
    ledger = _ledger(tmp_path)
    ev = ledger.record_command(
        session_id="s", workspace=str(tmp_path),
        command="npm run build", exit_code=0, output="ok",
    )
    assert ev is not None and ev["status"] == "passed"
    ev = ledger.record_command(
        session_id="s", workspace=str(tmp_path),
        command="npm run build && echo done", exit_code=0, output="ok",
    )
    assert ev is not None and ev["status"] == "passed"  # && proves members on success
    ev = ledger.record_command(
        session_id="s", workspace=str(tmp_path),
        command="pytest -q", exit_code=1, output="1 failed",
    )
    assert ev is not None and ev["status"] == "failed"


def test_backgrounded_and_unparseable_record_nothing(tmp_path):
    ledger = _ledger(tmp_path)
    for command in (
        "npm run build &",                      # backgrounding hides the status
        'npm run build " && echo oops',         # unbalanced quote -> fail closed
        "npm run build |",                      # trailing operator -> fail closed
    ):
        assert ledger.record_command(
            session_id="s", workspace=str(tmp_path), command=command,
            exit_code=0, output="ok",
        ) is None, command


def test_attributable_matches_hermes_semantics():
    segments = _split_shell_segments("cd x && npm run build 2>&1 | tail -40")
    assert [(s.tokens, s.following_operator) for s in segments] == [
        (["cd", "x"], "&&"),
        (["npm", "run", "build", "2>&1"], "|"),
        (["tail", "-40"], None),
    ]
    assert _exit_status_is_attributable(segments, 1, 0) is False
    bare = _split_shell_segments("npm run build")
    assert _exit_status_is_attributable(bare, 0, 1) is True   # bare owns its status
    chain = _split_shell_segments("npm run build && echo done")
    assert _exit_status_is_attributable(chain, 0, 0) is True
    assert _exit_status_is_attributable(chain, 0, 1) is False  # && proves only on success


# ── End-to-end: pulse's real terminal tool, a real broken build ────────────


def test_terminal_receipt_carries_the_masked_success_hint(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_npm = bin_dir / "npm"
    fake_npm.write_text("#!/usr/bin/env bash\necho 'npm ERR! Missing script: build'\nexit 2\n")
    fake_npm.chmod(fake_npm.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ.get('PATH', '')}")

    from src.tools.terminal_tools import terminal

    out = terminal.invoke(
        {"command": "npm run build 2>&1 | tail -40"},
        {"configurable": {"workspace": str(tmp_path)}},
    )
    assert "Exit code: 0" in out          # the shell's truth — never rewritten
    assert "npm ERR!" in out              # the build's truth
    assert "hint:" in out
    assert "Treat this run as FAILED" in out


def test_terminal_receipt_clean_build_stays_unhinted(tmp_path):
    from src.tools.terminal_tools import terminal

    out = terminal.invoke(
        {"command": "echo build-ok"},
        {"configurable": {"workspace": str(tmp_path)}},
    )
    assert "Exit code: 0" in out
    assert "hint:" not in out


# ── Pins: the ports stay hermes-verbatim and stay wired ────────────────────


def test_pins_hermes_module_and_wiring():
    hints = open("src/tools/terminal_hints.py", encoding="utf-8").read()
    assert "_SCAN_CHARS = 4000" in hints
    assert '_PASSTHROUGH_CONSUMERS = r"(?:tail|head|cat|tee|less|more|wc|sort|uniq)"' in hints
    assert "def annotate_masked_success" in hints
    assert "Advisory only" in hints or "advisory only" in hints

    terminal_src = open("src/tools/terminal_tools.py", encoding="utf-8").read()
    assert 'hint = _failure_hint(command, process.returncode, final_output, None)' in terminal_src
    assert 'final_output = f"{final_output}\\n\\nhint: {hint}"' in terminal_src
    assert "never pipe through tail/head to shorten" in terminal_src

    ledger_src = open("src/context/verification_evidence.py", encoding="utf-8").read()
    assert "_exit_status_is_attributable(segments, match_index, int(exit_code))" in ledger_src
