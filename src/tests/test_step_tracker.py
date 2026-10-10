"""Test suite for StepTracker and Diagnostic Engine."""
import json
import tempfile
from pathlib import Path
from unittest import TestCase

from src.runtime.step_tracker import (
    StepRecord,
    StepTracker,
    ToolExecutionRecord,
    estimate_cost,
)


class TestStepTracker(TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tracker = StepTracker("test_session_unit", workspace_root=self.tmpdir.name)
        self.tracker.system_trace_dir = Path(self.tmpdir.name) / "system_traces"
        self.tracker.system_trace_dir.mkdir(parents=True, exist_ok=True)
        self.tracker.system_trace_file = self.tracker.system_trace_dir / "test_session_unit.jsonl"
        self.tracker.latest_symlink = self.tracker.system_trace_dir / "latest.jsonl"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_cost_estimation(self):
        cost = estimate_cost("deepseek-v3", input_tokens=1000000, output_tokens=0, cached_tokens=0)
        self.assertAlmostEqual(cost, 0.27, places=4)

        cached_cost = estimate_cost("deepseek-v3", input_tokens=1000000, output_tokens=0, cached_tokens=1000000)
        self.assertAlmostEqual(cached_cost, 0.07, places=4)

    def test_start_and_finish_step(self):
        step = self.tracker.start_step("ai", state={"verification_status": "passed"})
        self.assertEqual(step.step_index, 1)
        self.assertEqual(step.node_name, "ai")
        self.assertEqual(step.verification_status, "passed")

        self.tracker.record_llm_metrics(
            model="claude-3-5-sonnet",
            provider="anthropic",
            input_tokens=10000,
            output_tokens=500,
            cached_tokens=8000,
            duration_s=1.2,
        )

        self.tracker.record_tool_call(
            name="read_file",
            args={"path": "src/main.py"},
            status="success",
            duration_ms=15.0,
            output="file content here",
        )

        finished = self.tracker.finish_step()
        self.assertEqual(finished.input_tokens, 10000)
        self.assertEqual(finished.cached_tokens, 8000)
        self.assertEqual(finished.cache_hit_ratio, 0.8)
        self.assertEqual(len(finished.tool_calls), 1)

        # Verify persistence to JSONL
        self.assertTrue(self.tracker.system_trace_file.exists())
        lines = self.tracker.system_trace_file.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual(data["node_name"], "ai")
        self.assertEqual(data["cached_tokens"], 8000)

        # Verify Markdown report in workspace diagnostics/
        report_file = Path(self.tmpdir.name) / "diagnostics" / "LATEST_PERFORMANCE_AUDIT.md"
        self.assertTrue(report_file.exists())
        self.assertIn("Agent Performance & Diagnostics Audit", report_file.read_text())

    def test_performance_score_computation(self):
        # Step 1: AI with high cache hit and 2 batched tools
        self.tracker.start_step("ai")
        self.tracker.record_llm_metrics(
            model="deepseek-v3",
            provider="deepseek",
            input_tokens=10000,
            output_tokens=100,
            cached_tokens=9000,
            duration_s=0.8,
        )
        self.tracker.record_tool_call(name="read_file", args={"path": "a.txt"}, status="success")
        self.tracker.record_tool_call(name="read_file", args={"path": "b.txt"}, status="success")
        self.tracker.finish_step()

        # Step 2: Tool execution
        self.tracker.start_step("tools")
        self.tracker.record_tool_call(name="write_file", args={"path": "c.txt"}, status="success")
        self.tracker.finish_step()

        score = self.tracker.compute_performance_score()
        self.assertGreaterEqual(score["score"], 80)
        self.assertIn("A", score["grade"])


if __name__ == "__main__":
    import unittest
    unittest.main()
