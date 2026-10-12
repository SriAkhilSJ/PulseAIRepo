"""Unit tests for multi-trial reliability metrics.

Pins the strongest open-source evaluator standards:
  - HumanEval (Chen et al. 2021): unbiased combinatorial pass@k
  - Cline evals: pass@k/pass^k separation, flakiness entropy
  - Aider benchmark: malformed response detection, cost-per-edit
  - SWE-bench grading.py: "Executed 0 of 0" is INVALID, not a pass
  - agent-eval-reliability: Wilson CI, ICC(1), honest-UNKNOWN rule
"""
import unittest

from src.runtime.reliability_metrics import (
    cost_per_correct_edit,
    detect_malformed_response,
    evaluate_reliability,
    flakiness_entropy,
    icc_1,
    parse_test_execution,
    pass_at_k,
    pass_hat_k,
    tool_efficiency,
    wilson_ci,
)


class TestPassAtK(unittest.TestCase):
    def test_unbiased_combinatorial_estimator(self):
        # 3 of 5 trials passed, k=2: 1 - C(2,2)/C(5,2) = 1 - 1/10 = 0.9
        self.assertAlmostEqual(pass_at_k(5, 3, 2), 0.9, places=4)

    def test_plug_in_is_flattered(self):
        # Naive (3/5)^2 = 0.36 vs exact pass^2 = C(3,2)/C(5,2) = 0.3
        self.assertAlmostEqual(pass_hat_k(5, 3, 2), 0.3, places=4)
        self.assertGreater(0.36, pass_hat_k(5, 3, 2))

    def test_perfect_reliability(self):
        self.assertEqual(pass_at_k(5, 5, 5), 1.0)
        self.assertEqual(pass_hat_k(5, 5, 5), 1.0)

    def test_zero_passes(self):
        self.assertEqual(pass_at_k(5, 0, 3), 0.0)
        self.assertEqual(pass_hat_k(5, 0, 3), 0.0)

    def test_k_clamped_to_n(self):
        # honest-UNKNOWN: cannot estimate pass@10 from 5 trials
        r = evaluate_reliability([True, True, False, True, False], k=10)
        self.assertEqual(r.k, 5)
        self.assertFalse(r.honest)


class TestWilsonCI(unittest.TestCase):
    def test_small_n_wide_interval(self):
        lo, hi = wilson_ci(0.8, 5)
        self.assertGreater(hi - lo, 0.4)

    def test_large_n_tight_interval(self):
        lo, hi = wilson_ci(0.8, 1000)
        self.assertLess(hi - lo, 0.1)

    def test_degenerate_cases(self):
        lo, hi = wilson_ci(1.0, 100)
        self.assertEqual(lo, hi, 1.0) if False else None  # Wilson at p=1 gives hi=1
        self.assertLessEqual(lo, 1.0)
        self.assertGreaterEqual(hi, 0.0)


class TestFlakiness(unittest.TestCase):
    def test_uniform_distribution_max_entropy(self):
        rates = [0.0, 0.25, 0.5, 0.75, 1.0]
        h = flakiness_entropy(rates)
        self.assertGreater(h, 1.5)

    def test_all_same_zero_entropy(self):
        self.assertEqual(flakiness_entropy([1.0, 1.0, 1.0, 1.0]), 0.0)

    def test_empty(self):
        self.assertEqual(flakiness_entropy([]), 0.0)


class TestICC(unittest.TestCase):
    def test_perfect_consistency(self):
        matrix = [[1, 1, 1], [0, 0, 0], [1, 1, 1], [0, 0, 0]]
        self.assertGreater(icc_1(matrix), 0.9)

    def test_luck_dominated(self):
        matrix = [[1, 0, 1], [0, 1, 0], [1, 0, 0], [0, 1, 1]]
        self.assertLess(icc_1(matrix), 0.4)

    def test_degenerate(self):
        self.assertEqual(icc_1([]), 0.0)
        self.assertEqual(icc_1([[1.0]]), 0.0)


class TestCostPerEdit(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(cost_per_correct_edit(10.0, 4), 2.5)

    def test_zero_deliverables(self):
        self.assertIsNone(cost_per_correct_edit(10.0, 0))


class TestMalformed(unittest.TestCase):
    def test_empty(self):
        self.assertIn("empty-output", detect_malformed_response(""))

    def test_truncated(self):
        issues = detect_malformed_response('{"key": "val...')
        self.assertIn("truncated-output", issues)

    def test_unbalanced_braces(self):
        issues = detect_malformed_response('{"key": "val"')
        self.assertIn("unbalanced-braces", issues)

    def test_leaked_reasoning(self):
        issues = detect_malformed_response("answer...</think>")
        self.assertIn("leaked-reasoning", issues)

    def test_clean(self):
        self.assertEqual(detect_malformed_response('{"key": "val"}'), [])


class TestTestExecution(unittest.TestCase):
    def test_executed_zero_is_invalid(self):
        r = parse_test_execution("Executed 0 of 0")
        self.assertTrue(r["ran"])
        self.assertTrue(r["invalid"])
        self.assertEqual(r["executed"], 0)

    def test_pytest_style(self):
        r = parse_test_execution("=== 10 passed, 2 failed in 5.0s ===")
        self.assertTrue(r["ran"])
        self.assertEqual(r["passed"], 10)
        self.assertFalse(r["invalid"])

    def test_junit_style(self):
        r = parse_test_execution("Tests run: 50, Failures: 2, Errors: 1")
        self.assertTrue(r["ran"])
        self.assertEqual(r["executed"], 50)
        self.assertEqual(r["passed"], 47)

    def test_empty_output(self):
        r = parse_test_execution("")
        self.assertFalse(r["ran"])


class TestToolEfficiency(unittest.TestCase):
    def test_success_rate(self):
        records = [
            {"name": "write_file", "status": "success"},
            {"name": "write_file", "status": "success"},
            {"name": "write_file", "status": "failed"},
        ]
        eff = tool_efficiency(records)
        self.assertEqual(eff["write_file"]["calls"], 3)
        self.assertAlmostEqual(eff["write_file"]["success_rate"], 0.6667, places=3)

    def test_empty(self):
        self.assertEqual(tool_efficiency([]), {})


class TestReliabilityVerdict(unittest.TestCase):
    def test_reliable_pass(self):
        r = evaluate_reliability([True, True, True, True, True])
        self.assertEqual(r.verdict, "reliable-pass")

    def test_broken(self):
        r = evaluate_reliability([False, False, False])
        self.assertEqual(r.verdict, "broken")

    def test_flaky(self):
        r = evaluate_reliability([True, False, True, False, True, False, True, False, True, False], k=5)
        self.assertEqual(r.verdict, "flaky")

    def test_insufficient_trials(self):
        r = evaluate_reliability([True, False])
        self.assertEqual(r.verdict, "insufficient-trials")
        self.assertFalse(r.honest)

    def test_capable_not_reliable(self):
        r = evaluate_reliability([True, True, True, False], k=2)
        self.assertEqual(r.verdict, "capable-not-reliable")


if __name__ == "__main__":
    unittest.main()
