from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.ci_report_pytest import main


def test_reporter_emits_failure_annotation_and_step_summary(tmp_path, monkeypatch, capsys):
    junit = tmp_path / "pytest.xml"
    junit.write_text(
        '<testsuites><testsuite><testcase classname="sample.Test" name="test_failure">'
        '<failure message="assertion failed">expected true</failure>'
        '</testcase></testsuite></testsuites>',
        encoding="utf-8",
    )
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    assert main([str(junit)]) == 0
    assert "::error::sample.Test.test_failure" in capsys.readouterr().out
    assert "expected true" in summary.read_text(encoding="utf-8")


def test_reporter_cli_reconfigures_legacy_console_to_utf8(tmp_path):
    junit = tmp_path / "pytest.xml"
    junit.write_text(
        '<testsuites><testsuite><testcase classname="sample.Test" name="test_unicode">'
        '<failure message="failure ❌">traceback</failure>'
        '</testcase></testsuite></testsuites>',
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[2] / "scripts" / "ci_report_pytest.py"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"
    env["GITHUB_STEP_SUMMARY"] = str(tmp_path / "summary.md")

    result = subprocess.run(
        [sys.executable, str(script), str(junit)], env=env, capture_output=True
    )

    assert result.returncode == 0
    assert "❌".encode("utf-8") in result.stdout


def test_reporter_does_not_mask_missing_pytest_report(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert main([str(tmp_path / "missing.xml")]) == 0
    assert "No pytest JUnit report" in capsys.readouterr().err
