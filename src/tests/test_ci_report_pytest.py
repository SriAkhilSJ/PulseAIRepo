from __future__ import annotations

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


def test_reporter_does_not_mask_missing_pytest_report(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert main([str(tmp_path / "missing.xml")]) == 0
    assert "No pytest JUnit report" in capsys.readouterr().err
