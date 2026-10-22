"""Test suite for StepTracker and Diagnostic Engine."""
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

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

    def test_cost_estimation_uses_live_rate_card_and_reported_cache_rate(self):
        card = {
            "deepseek-v3": {
                "input_per_1m": 0.27,
                "output_per_1m": 1.10,
                "cached_input_per_1m": 0.07,
                "currency": "USD",
            }
        }
        with patch("src.telemetry.call_ledger.load_rate_card", return_value=card):
            cost = estimate_cost("deepseek-v3", input_tokens=1_000_000, output_tokens=0)
            cached_cost = estimate_cost(
                "deepseek-v3", input_tokens=1_000_000, output_tokens=0,
                cached_tokens=1_000_000, cache_reported=True,
            )
        self.assertAlmostEqual(cost, 0.27, places=4)
        self.assertAlmostEqual(cached_cost, 0.07, places=4)

    def test_unknown_model_cost_is_not_filled_with_a_generic_price(self):
        with patch("src.telemetry.call_ledger.load_rate_card", return_value={}):
            self.assertIsNone(estimate_cost("z-ai/glm-5.3-flash", 12_000, 100))

    def test_velona_report_uses_dynamic_usd_rate_and_ignores_unreported_cache(self):
        card = {
            "z-ai/glm-5.3-flash": {
                "input_per_1m": 0.018,
                "output_per_1m": 0.121,
                "currency": "USD",
            }
        }
        with patch("src.telemetry.call_ledger.load_rate_card", return_value=card):
            self.tracker.start_step("ai")
            self.tracker.record_llm_metrics(
                model="z-ai/glm-5.3-flash",
                provider="velona",
                input_tokens=12_000,
                output_tokens=100,
                cached_tokens=9_000,
                cache_reported=False,
                duration_s=2.0,
            )
            finished = self.tracker.finish_step()
        expected = (12_000 * 0.018 + 100 * 0.121) / 1_000_000
        self.assertAlmostEqual(finished.estimated_cost_usd, expected, places=10)
        report = (Path(self.tmpdir.name) / "diagnostics" / "LATEST_PERFORMANCE_AUDIT.md").read_text(encoding="utf-8")
        self.assertIn(f"${expected:.4f} USD", report)
        self.assertNotIn("$1.00/$3.00", report)

    def test_unpriced_step_report_says_unknown_not_zero_dollars(self):
        with patch("src.telemetry.call_ledger.load_rate_card", return_value={}):
            self.tracker.start_step("ai")
            self.tracker.record_llm_metrics(
                model="some/unpriced-model", provider="custom",
                input_tokens=2_000, output_tokens=50,
            )
            finished = self.tracker.finish_step()
        self.assertIsNone(finished.estimated_cost_usd)
        report = (Path(self.tmpdir.name) / "diagnostics" / "LATEST_PERFORMANCE_AUDIT.md").read_text(encoding="utf-8")
        self.assertIn("**Unknown** (0/1 token-bearing calls priced in USD)", report)

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
        lines = self.tracker.system_trace_file.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        data = json.loads(lines[0])
        self.assertEqual(data["node_name"], "ai")
        self.assertEqual(data["cached_tokens"], 8000)

        # Verify Markdown report in workspace diagnostics/
        report_file = Path(self.tmpdir.name) / "diagnostics" / "LATEST_PERFORMANCE_AUDIT.md"
        self.assertTrue(report_file.exists())
        self.assertIn("Agent Performance & Diagnostics Audit", report_file.read_text(encoding="utf-8"))

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

    def test_velona_unreported_cache_telemetry_no_penalty(self):
        """When using Velona or an endpoint omitting input_token_details,
        do NOT penalize the agent health score or output false cache warnings."""
        # Step 1: AI run through Velona (cached_tokens is 0 because input_token_details is empty)
        self.tracker.start_step("ai")
        self.tracker.record_llm_metrics(
            model="z-ai/glm-5.3-flash",
            provider="velona",
            input_tokens=25000,
            output_tokens=300,
            cached_tokens=0,
            duration_s=1.0,
        )
        self.tracker.record_tool_call(name="write_file", args={"path": "a.txt"}, status="success")
        self.tracker.record_tool_call(name="write_file", args={"path": "b.txt"}, status="success")
        self.tracker.finish_step()

        perf = self.tracker.compute_performance_score()
        self.assertFalse(perf["metrics"]["telemetry_available"])
        self.assertEqual(perf["breakdown"]["cache_score"], 25.0)
        self.assertGreaterEqual(perf["score"], 85.0)
        # Ensure false cache warning is not present in actionable ideas
        self.assertFalse(any("Enable Prompt Caching" in idea for idea in perf["actionable_ideas"]))
        self.assertTrue(any("Provider Telemetry Notice" in idea for idea in perf["actionable_ideas"]))


if __name__ == "__main__":
    import unittest
    unittest.main()
