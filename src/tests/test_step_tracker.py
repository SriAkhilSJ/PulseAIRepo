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
    _step_record_from_dict,
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
        self.assertIn("**N/A** (Provider Velona/Gateway omits", report)
        perf = self.tracker.compute_performance_score()
        self.assertFalse(perf["metrics"]["telemetry_available"])
        self.assertEqual(perf["metrics"]["reported_cached_tokens"], 0)

    def test_positive_gateway_cache_tokens_are_reported_not_n_a(self):
        self.tracker.start_step("ai")
        self.tracker.record_llm_metrics(
            model="z-ai/glm-5.3-flash",
            provider="velona",
            input_tokens=12_000,
            output_tokens=100,
            cached_tokens=9_000,
            duration_s=2.0,
        )
        finished = self.tracker.finish_step()

        self.assertTrue(finished.cache_reported)
        perf = self.tracker.compute_performance_score()
        self.assertTrue(perf["metrics"]["telemetry_available"])
        self.assertEqual(perf["metrics"]["reported_cached_tokens"], 9_000)
        self.assertEqual(perf["metrics"]["cache_hit_rate_pct"], 75.0)
        report = (
            Path(self.tmpdir.name) / "diagnostics" / "LATEST_PERFORMANCE_AUDIT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("**75.0%** (9,000 cached)", report)
        self.assertIn("| 75% |", report)

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
        self.tracker.record_tool_call(name="write_file", args={"path": "a.txt"}, status="proposed")
        self.tracker.record_tool_call(name="write_file", args={"path": "b.txt"}, status="proposed")
        self.tracker.finish_step()

        perf = self.tracker.compute_performance_score()
        self.assertFalse(perf["metrics"]["telemetry_available"])
        self.assertIsNone(perf["breakdown"]["cache_score"])
        self.assertEqual(perf["metrics"]["scored_runtime_dimensions"], 2)
        self.assertGreaterEqual(perf["score"], 85.0)
        # Ensure false cache warning is not present in actionable ideas
        self.assertFalse(any("Enable Prompt Caching" in idea for idea in perf["actionable_ideas"]))
        self.assertTrue(any("Provider Telemetry Notice" in idea for idea in perf["actionable_ideas"]))

    def test_measured_llm_duration_is_not_overwritten_by_wrapper_time(self):
        self.tracker.start_step("ai")
        self.tracker.record_llm_metrics(
            model="test-model",
            provider="custom",
            input_tokens=100,
            output_tokens=10,
            duration_s=12.5,
        )
        finished = self.tracker.finish_step()

        self.assertEqual(finished.duration_s, 12.5)
        perf = self.tracker.compute_performance_score()
        self.assertTrue(perf["metrics"]["duration_telemetry_available"])
        self.assertEqual(perf["metrics"]["total_measured_duration_s"], 12.5)

    def test_legacy_ai_success_rows_hydrate_as_proposals(self):
        restored = _step_record_from_dict({
            "session_id": "legacy",
            "step_index": 1,
            "node_name": "ai",
            "started_at": 1.0,
            "tool_calls": [{
                "name": "write_file",
                "args_summary": '{"path": "app.py"}',
                "status": "success",
            }],
        })

        self.assertEqual(restored.tool_calls[0].status, "proposed")

    def test_proposals_do_not_count_as_executed_successes(self):
        self.tracker.start_step("ai")
        self.tracker.record_tool_call(
            "write_file", {"path": "app.py", "content": "print('x')"},
            status="proposed",
        )
        self.tracker.finish_step()

        self.tracker.start_step("tools")
        self.tracker.record_tool_call(
            "write_file", {"path": "app.py", "content": "print('x')"},
            status="failed", error="disk failed",
        )
        self.tracker.finish_step()

        perf = self.tracker.compute_performance_score()
        self.assertEqual(perf["metrics"]["tool_failure_rate_pct"], 100.0)
        self.assertNotIn("app.py", self.tracker.marked_edits)

    def test_trace_omits_tool_body_redacts_output_and_tracks_safe_path(self):
        synthetic = "sk-test-secret-1234567890"
        self.tracker.start_step("tools")
        self.tracker.record_tool_call(
            "write_file",
            {"path": "scratch/probe.py", "content": synthetic},
            status="success",
            output=f"File written; token={synthetic}",
        )
        finished = self.tracker.finish_step()

        record = finished.tool_calls[0]
        stored_args = json.loads(record.args_summary)
        self.assertEqual(stored_args["path"], "scratch/probe.py")
        self.assertTrue(stored_args["content"]["__omitted__"])
        self.assertNotIn(synthetic, record.args_summary)
        self.assertNotIn(synthetic, record.output_preview)
        self.assertIn("scratch/probe.py", self.tracker.marked_edits)

    def test_current_interest_replaces_stale_greeting_in_report_state(self):
        self.tracker.set_user_ask("hello")
        state = {
            "current_task": "Build the analytics app.",
            "latest_instruction": "Only change the backend.",
            "user_interest": {
                "schema_version": 1,
                "objective": "Build the analytics app.",
                "latest_instruction": "Only change the backend.",
                "latest_substantive_instruction": "Only change the backend.",
                "mode": "act",
                "change_policy": "changes_requested",
                "relationship": "corrects",
            },
        }
        self.tracker.start_step("ai", state=state)
        self.tracker.finish_step()

        self.assertIn("Build the analytics app", self.tracker.user_ask)
        self.assertIn("Only change the backend", self.tracker.user_ask)
        self.assertNotEqual(self.tracker.user_ask, "hello")

    def test_restarted_tracker_hydrates_full_workspace_trace(self):
        self.tracker.start_step("ai")
        self.tracker.record_llm_metrics(
            model="test-model", provider="custom", input_tokens=10,
            output_tokens=1, duration_s=1.0,
        )
        self.tracker.finish_step()
        self.tracker.start_step("tools")
        self.tracker.record_tool_call(
            "write_file",
            {"path": "restored.py", "content": "print('restored')"},
            status="success",
        )
        self.tracker.finish_step()

        resumed = StepTracker("test_session_unit", workspace_root=self.tmpdir.name)
        self.assertEqual(len(resumed.steps), 2)
        self.assertEqual(resumed.marked_edits, ["restored.py"])
        next_step = resumed.start_step("ai")
        self.assertEqual(next_step.step_index, 3)

    def test_report_marks_unknown_telemetry_na_and_never_claims_optimal(self):
        self.tracker.set_user_ask("Build app.py")
        self.tracker.start_step("ai")
        self.tracker.record_tool_call(
            "write_file", {"path": "app.py", "content": "print('x')"},
            status="proposed",
        )
        self.tracker.finish_step()

        perf = self.tracker.compute_performance_score()
        self.assertEqual(perf["metrics"]["scored_runtime_dimensions"], 1)
        self.assertEqual(perf["score"], 60.0)

        report = (
            Path(self.tmpdir.name) / "diagnostics" / "LATEST_PERFORMANCE_AUDIT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Runtime Health Score", report)
        self.assertIn("1/4 dimensions scored", report)
        self.assertIn("/ 100", report)
        self.assertIn("N/A (duration telemetry unavailable)", report)
        self.assertNotIn("Optimal Performance", report)

    def test_finalize_report_refreshes_authoritative_verdict_evidence(self):
        self.tracker.set_user_ask("hello")
        self.tracker.start_step("ai")
        self.tracker.finish_step()
        self.tracker.start_step("tools")
        self.tracker.record_tool_call(
            "write_file", {"path": "analytics.py", "content": "print('ok')"},
            status="success",
        )
        self.tracker.finish_step()
        self.tracker.finalize_report(
            user_ask="Build analytics.py",
            final_message="The file was created but tests failed.",
            verification_status="failed",
            receipts={"task_status": "unverified"},
        )

        report = (
            Path(self.tmpdir.name) / "diagnostics" / "LATEST_PERFORMANCE_AUDIT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Build analytics.py", report)
        self.assertNotIn('User Ask:** *"hello"', report)
        self.assertIn("Verification status is FAILED", report)
        self.assertIn("| **Task verdict** | `unverified` |", report)
        self.assertIn("| **Verification status** | `failed` |", report)
        self.assertEqual(self.tracker.steps[-1].node_name, "finalize")
        self.assertEqual(self.tracker.steps[-1].verification_status, "failed")
        self.assertIn("FINAL_VERDICT: unverified", self.tracker.steps[-1].diagnostics)

    def test_begin_turn_invalidates_the_prior_terminal_receipt(self):
        self.tracker.finalize_report(
            user_ask="Run the failure probe.",
            final_message="Exit code 3.",
            verification_status="unverified",
            receipts={
                "task_status": "failed",
                "tool_execution_count": 1,
                "failed_step_count": 1,
            },
        )
        before = (
            Path(self.tmpdir.name) / "diagnostics" / "LATEST_PERFORMANCE_AUDIT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("| **Task verdict** | `failed` |", before)

        self.tracker.begin_turn(
            user_ask="Create, run, remove, and confirm cleanup_probe.py is absent."
        )
        after = (
            Path(self.tmpdir.name) / "diagnostics" / "LATEST_PERFORMANCE_AUDIT.md"
        ).read_text(encoding="utf-8")
        self.assertIn("cleanup_probe.py", after)
        self.assertIn("| **Task verdict** | `in_progress` |", after)
        self.assertIn("| **Verification status** | `pending` |", after)
        self.assertIn("| **Current-turn executed tool records** | N/A |", after)
        self.assertIn("| **Current-task failed steps** | N/A |", after)
        self.assertNotIn("| **Task verdict** | `failed` |", after)

    def test_exit_code_parser_uses_final_authoritative_receipt(self):
        from src.graphs.chat_graph import _extract_exit_code

        self.assertEqual(
            _extract_exit_code("Expected exit code 1.\nExit code: 0"),
            0,
        )
        self.assertEqual(_extract_exit_code("process exited with -1"), -1)
        self.assertIsNone(_extract_exit_code("completed without a code receipt"))


if __name__ == "__main__":
    import unittest
    unittest.main()
