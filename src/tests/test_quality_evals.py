"""Unit & Benchmark tests for Task Quality & User Ask Fulfillment Evaluator."""
import tempfile
from pathlib import Path
import pytest

from src.runtime.quality_evaluator import UserAskQualityEvaluator, STUB_PATTERNS
from src.runtime.step_tracker import StepTracker


def test_quality_evaluator_all_deliverables_created_and_clean():
    """Evaluates when the agent creates all requested files without stubs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text("<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width'></head><body><h1>Timer</h1></body></html>")
        (ws / "styles.css").write_text("body { background: #000; color: #fff; display: flex; }")
        (ws / "app.js").write_text("console.log('Timer loaded'); function start() { return true; }")

        evaluator = UserAskQualityEvaluator(str(ws))
        report = evaluator.evaluate(
            user_ask="Create a modern timer in index.html with styles.css and app.js",
            marked_edits=["index.html", "styles.css", "app.js"],
            verification_status="passed",
            final_assistant_message="I have built the timer app. You can open index.html in your browser or run python -m http.server to view it.",
        )

        assert report.quality_score >= 90.0
        assert report.pillars["deliverables"].score >= 32.0
        assert report.pillars["constraints"].score == 25.0
        assert report.pillars["soundness"].score == 25.0
        assert report.pillars["presentation"].score >= 13.0
        assert len(report.identified_gaps) == 0


def test_quality_evaluator_detects_missing_file_and_stubs():
    """Evaluates when the agent misses a file and leaves unresolved TODO stubs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        # index.html created with a lazy TODO comment
        (ws / "index.html").write_text("<html><body>// TODO: implement countdown logic here</body></html>")
        # app.py created with NotImplementedError
        (ws / "app.py").write_text("def run():\n    raise NotImplementedError('finish later')")
        # Missing styles.css and README.md

        evaluator = UserAskQualityEvaluator(str(ws))
        report = evaluator.evaluate(
            user_ask="Build web app with index.html, styles.css, and README.md",
            marked_edits=["index.html", "app.py"],
            verification_status="stale",
            final_assistant_message="",
        )

        assert report.quality_score < 75.0
        assert report.pillars["deliverables"].score < 25.0
        assert report.stub_audit["total_stubs"] >= 2
        assert any("TODO" in gap or "stub" in gap.lower() for gap in report.identified_gaps)
        assert any("Missing" in gap for gap in report.identified_gaps)


def test_quality_evaluator_negative_constraint_violation():
    """Evaluates when the user explicitly said 'no jQuery' or 'do not use external libraries' and agent violated it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "app.js").write_text("$(document).ready(function() { $('#btn').click(); });")

        evaluator = UserAskQualityEvaluator(str(ws))
        report = evaluator.evaluate(
            user_ask="Write app.js without jquery. Do not use jQuery.",
            marked_edits=["app.js"],
            verification_status="passed",
            final_assistant_message="Created app.js",
        )

        assert report.pillars["constraints"].score < 25.0
        assert any("negative constraint" in gap.lower() or "jquery" in gap.lower() for gap in report.identified_gaps)


def test_step_tracker_unified_champion_score():
    """Evaluates StepTracker computing unified benchmark scorecard (Quality + Runtime)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text("<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width'></head><body><h1>App</h1></body></html>")

        tracker = StepTracker("session-unit-test-champ", workspace_root=str(ws))
        tracker.set_user_ask("Build index.html for dashboard")
        tracker.set_final_message("Created index.html. Run with preview.")

        tracker.start_step("ai")
        tracker.record_llm_metrics(model="claude-3-5-sonnet", provider="anthropic", input_tokens=2000, output_tokens=100, cached_tokens=1600)
        tracker.finish_step()

        tracker.start_step("tools")
        tracker.record_tool_call("write_file", "saved index.html", "success", exit_code=0)
        tracker.finish_step()

        unified = tracker.compute_unified_agent_score()
        assert "unified_score" in unified
        assert unified["unified_score"] >= 80.0
        assert "quality" in unified
        assert "runtime" in unified
