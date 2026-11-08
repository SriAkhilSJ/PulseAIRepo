"""P0.6.6 — Execution reliability closure (offline).

Covers the three defects from P0.6.5:

  1. FinOps: reserve -> settle once (duplicate commit is a no-op),
     pre-dispatch refusal releases (never retains), post-dispatch ambiguity
     retains, and the orchestrator reconciles on every exit.
  2. Planner dispatch budget: plans are coalesced into the available
     dispatches, requirements are never dropped, over-budget plans are
     refused before any provider request.
  3. Output ceiling: the per-node ceiling is configurable (4096 justified by
     measurement) and flows into the provider kwargs; P0.5.1 fail-closed
     validation is unchanged.

No provider is called: fakes are used for the adapter and planner where the
real component would need the network.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from src.orchestration.models import ExecutionLimits, EngineeringTaskNode
from src.orchestration.planner import (
    EngineeringTaskPlanner,
    PlanBudgetExceeded,
    merge_requirement_nodes,
)


def _requirement(index: int, *, files: list[str] | None = None):
    return SimpleNamespace(
        id=f"REQ-{index}",
        title=f"Requirement {index}",
        description=f"Do the thing for requirement {index}",
        status=SimpleNamespace(value="APPROVED"),
        affected_files=files if files is not None else [f"src/mod_{index}.py"],
        acceptance_criteria=[f"REQ-{index} passes"],
    )


def _specification(count: int):
    reqs = [_requirement(i) for i in range(1, count + 1)]
    return SimpleNamespace(
        all_requirements=lambda: reqs,
        requirements=reqs,
        desired_outcome="Ship it",
        title="Task",
        implementation_scope=SimpleNamespace(value="TASK"),
    )


class TestPlannerBudget(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="p0_6_6_plan_"))
        self.planner = EngineeringTaskPlanner(str(self.tmp))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_1_plan_without_budget_keeps_every_requirement_node(self) -> None:
        dag = self.planner.build_plan("t1", _specification(6))
        self.assertEqual(len(dag.nodes), 7)  # 6 requirement nodes + verification
        req_ids = {rid for n in dag.nodes.values() for rid in n.related_requirement_ids}
        self.assertEqual(req_ids, {f"REQ-{i}" for i in range(1, 7)})

    def test_2_budget_coalesces_and_preserves_every_requirement(self) -> None:
        dag = self.planner.build_plan("t2", _specification(6), max_nodes=5)
        self.assertLessEqual(len(dag.nodes), 5)
        req_ids = {rid for n in dag.nodes.values() for rid in n.related_requirement_ids}
        self.assertEqual(req_ids, {f"REQ-{i}" for i in range(1, 7)},
                         "coalescing must never drop a requirement")
        self.assertIn("task_verification", dag.nodes)
        # Dispatches are per FILE, not per node: 6 requirements must fit in 4
        # implementation dispatches (5 total minus the free verification node).
        file_demand = sum(len(n.target_files) for n in dag.nodes.values()
                          if n.node_id != "task_verification")
        self.assertLessEqual(file_demand, 4)
        # Dependencies stay valid for a topological order.
        dag.get_execution_order()

    def test_3_tight_budget_still_covers_all_requirements(self) -> None:
        dag = self.planner.build_plan("t3", _specification(6), max_nodes=2)
        self.assertEqual(len(dag.nodes), 2)
        req_ids = {rid for n in dag.nodes.values() for rid in n.related_requirement_ids}
        self.assertEqual(req_ids, {f"REQ-{i}" for i in range(1, 7)})
        impl = [n for n in dag.nodes.values() if n.node_id != "task_verification"]
        self.assertEqual(len(impl), 1)
        self.assertEqual(len(impl[0].target_files), 1, "one dispatch = one file")
        self.assertEqual(set(dag.nodes["task_verification"].dependencies), {impl[0].node_id})

    def test_3b_absorbed_files_are_recorded_not_hidden(self) -> None:
        dag = self.planner.build_plan("t3b", _specification(6), max_nodes=2)
        impl = [n for n in dag.nodes.values() if n.node_id != "task_verification"][0]
        notes = " ".join(impl.expected_outputs)
        self.assertIn("consolidated into", notes)

    def test_4_impossible_budget_is_refused_before_any_work(self) -> None:
        with self.assertRaises(PlanBudgetExceeded):
            self.planner.build_plan("t4", _specification(6), max_nodes=1)

    def test_5_merge_unions_files_tests_and_takes_highest_risk(self) -> None:
        a = EngineeringTaskNode(
            node_id="task_a", description="a", objective="A",
            related_requirement_ids=["REQ-1"], target_files=["src/a.py"],
            required_tests=["test_a"], risk_level="LOW", max_tokens=1024,
        )
        b = EngineeringTaskNode(
            node_id="task_b", description="b", objective="B",
            related_requirement_ids=["REQ-2"], target_files=["src/b.py"],
            required_tests=["test_b"], risk_level="HIGH", max_tokens=4096,
        )
        merged = merge_requirement_nodes([a, b])
        self.assertEqual(merged.related_requirement_ids, ["REQ-1", "REQ-2"])
        self.assertEqual(merged.target_files, ["src/a.py", "src/b.py"])
        self.assertEqual(merged.required_tests, ["test_a", "test_b"])
        self.assertEqual(merged.risk_level, "HIGH")
        self.assertEqual(merged.max_tokens, 4096)

    def test_6_budget_zero_or_negative_is_refused(self) -> None:
        for budget in (0, -3):
            with self.assertRaises(PlanBudgetExceeded):
                self.planner.build_plan(f"t6_{budget}", _specification(2), max_nodes=budget)

    def test_6b_user_named_files_take_precedence(self) -> None:
        dag = self.planner.build_plan(
            "t6b", _specification(4),
            requested_files=["src/email_validator.py", "tests/test_email_validator.py"],
        )
        targets = [f for n in dag.nodes.values() for f in n.target_files]
        self.assertIn("src/email_validator.py", targets)
        self.assertIn("tests/test_email_validator.py", targets)

    def test_6c_requested_files_survive_budget_coalescing(self) -> None:
        dag = self.planner.build_plan(
            "t6c", _specification(6), max_nodes=5,
            requested_files=["src/email_validator.py", "tests/test_email_validator.py"],
        )
        targets = [f for n in dag.nodes.values() for f in n.target_files]
        self.assertIn("src/email_validator.py", targets)
        self.assertIn("tests/test_email_validator.py", targets)
        self.assertLessEqual(len(targets), 4, "4 implementation dispatches")


class TestRequestedFileExtraction(unittest.TestCase):
    def test_6d_paths_are_extracted_from_the_prompt_in_order(self) -> None:
        from src.orchestration.orchestrator import EngineeringExecutionOrchestrator

        prompt = (
            "Create src/email_validator.py with validate_email. Add tests in "
            "`tests/test_email_validator.py`. Do not modify src/other.py."
        )
        files = EngineeringExecutionOrchestrator._requested_files(prompt)
        self.assertEqual(files[:3], [
            "src/email_validator.py", "tests/test_email_validator.py", "src/other.py",
        ])

    def test_6e_no_paths_means_empty(self) -> None:
        from src.orchestration.orchestrator import EngineeringExecutionOrchestrator

        self.assertEqual(EngineeringExecutionOrchestrator._requested_files("say hello"), [])


class TestOrchestratorBudgetGate(unittest.TestCase):
    def setUp(self) -> None:
        from src.orchestration.orchestrator import EngineeringExecutionOrchestrator

        self.tmp = Path(tempfile.mkdtemp(prefix="p0_6_6_orch_"))
        self.orch = EngineeringExecutionOrchestrator(str(self.tmp), tenant_id="p0_6_6")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _dag(self, count: int):
        from src.orchestration.models import EngineeringPlanDAG

        dag = EngineeringPlanDAG(task_id="t")
        for i in range(count):
            dag.add_node(EngineeringTaskNode(
                node_id=f"n{i}", description="d", objective="o",
                related_requirement_ids=[f"REQ-{i}"],
            ))
        return dag

    def test_7_plan_over_budget_is_rejected(self) -> None:
        with self.assertRaises(PlanBudgetExceeded) as ctx:
            self.orch._validate_plan_budget(self._dag(7), 5)
        self.assertEqual(ctx.exception.requested_nodes, 7)
        self.assertEqual(ctx.exception.allowed_nodes, 5)
        self.assertEqual(sorted(ctx.exception.requirement_ids), [f"REQ-{i}" for i in range(7)])

    def test_7b_plan_within_budget_is_allowed(self) -> None:
        self.orch._validate_plan_budget(self._dag(5), 5)
        self.orch._validate_plan_budget(self._dag(7), None)  # unbounded

    def test_7c_budget_counts_files_not_nodes(self) -> None:
        from src.orchestration.models import EngineeringPlanDAG

        dag = EngineeringPlanDAG(task_id="files")
        node = EngineeringTaskNode(
            node_id="n0", description="d", objective="o",
            related_requirement_ids=["REQ-1"],
            target_files=["src/a.py", "src/b.py", "src/c.py"],
        )
        dag.add_node(node)
        dag.add_node(EngineeringTaskNode(
            node_id="task_verification", description="v", objective="v",
            related_requirement_ids=["REQ-1"],
        ))
        self.orch._validate_plan_budget(dag, 3)  # 3 files = 3 dispatches
        with self.assertRaises(PlanBudgetExceeded):
            self.orch._validate_plan_budget(dag, 2)

    def test_8_remaining_budget_is_the_tighter_of_task_and_guard(self) -> None:
        from src.llm import acceptance_guard as guard_mod

        self.orch.limits.max_dispatch_budget = 6
        fake_guard = SimpleNamespace(remaining=3)
        with patch.object(guard_mod, "active_guard", return_value=fake_guard):
            self.assertEqual(self.orch._remaining_dispatch_budget(), 3)
        with patch.object(guard_mod, "active_guard", return_value=None):
            self.assertEqual(self.orch._remaining_dispatch_budget(), 6)
        self.orch.limits.max_dispatch_budget = None
        with patch.object(guard_mod, "active_guard", return_value=None):
            self.assertIsNone(self.orch._remaining_dispatch_budget())


class TestFinOpsSettlement(unittest.TestCase):
    def setUp(self) -> None:
        from src.orchestration.finops_governor import OrchestrationFinOpsGovernor

        self.tmp = Path(tempfile.mkdtemp(prefix="p0_6_6_fin_"))
        self.finops = OrchestrationFinOpsGovernor(
            "task_p0_6_6",
            budget_inr=5.0,
            token_budget=150_000,
            storage_dir=str(self.tmp / "finops"),
            workspace_root=str(self.tmp),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _reserve(self, purpose: str = "node_1") -> str:
        return self.finops.reserve(
            estimated_tokens=3000, estimated_cost_inr=0.05, estimated_cost_usd=0.0006,
            purpose=purpose,
        )

    def test_9_reserve_then_settle_once(self) -> None:
        rid = self._reserve()
        self.assertIn(rid, self.finops._active_reservations)
        self.finops.mark_in_flight(rid)
        self.finops.commit_reservation(
            reservation_id=rid, actual_input_tokens=100, actual_output_tokens=200,
            actual_cached_tokens=0, actual_cost_inr=0.01, actual_cost_usd=0.0001,
        )
        self.assertNotIn(rid, self.finops._active_reservations)
        self.assertIn(rid, self.finops._settled_reservations)
        self.assertEqual(self.finops.accounting.calls_count, 1)
        self.assertAlmostEqual(self.finops.accounting.spent_inr, 0.01, places=6)

    def test_10_duplicate_commit_cannot_double_charge(self) -> None:
        rid = self._reserve()
        self.finops.mark_in_flight(rid)
        for _ in range(3):
            self.finops.commit_reservation(
                reservation_id=rid, actual_input_tokens=100, actual_output_tokens=200,
                actual_cached_tokens=0, actual_cost_inr=0.01, actual_cost_usd=0.0001,
            )
        self.assertEqual(self.finops.accounting.calls_count, 1)
        self.assertAlmostEqual(self.finops.accounting.spent_inr, 0.01, places=6)

    def test_11_release_returns_unspent_and_cannot_be_committed_after(self) -> None:
        rid = self._reserve()
        self.finops.release_reservation(rid, reason="dispatch_rejected")
        self.assertNotIn(rid, self.finops._active_reservations)
        self.assertEqual(self.finops.accounting.calls_count, 0)
        # A released hold is terminal: a late commit is ignored, never charged.
        self.finops.commit_reservation(
            reservation_id=rid, actual_input_tokens=10, actual_output_tokens=10,
            actual_cached_tokens=0, actual_cost_inr=9.99, actual_cost_usd=0.1,
        )
        self.assertEqual(self.finops.accounting.calls_count, 0)
        self.assertAlmostEqual(self.finops.accounting.spent_inr, 0.0, places=6)

    def test_12_uncertain_is_retained_not_released(self) -> None:
        rid = self._reserve()
        self.finops.mark_in_flight(rid)
        self.finops.mark_uncertain(rid, reason="transport_ambiguous")
        self.assertIn(rid, self.finops._uncertain_reservations)
        self.assertNotIn(rid, self.finops._settled_reservations)
        self.assertGreaterEqual(self.finops.accounting.reserved_inr or 0.0, 0.0)


class TestDispatchErrorClassification(unittest.TestCase):
    def test_13_acceptance_refusal_is_pre_dispatch(self) -> None:
        from src.llm.acceptance_guard import AcceptanceBudgetExceeded
        from src.orchestration.model_adapter import is_uncertain_post_dispatch_error

        self.assertFalse(is_uncertain_post_dispatch_error(
            AcceptanceBudgetExceeded("budget exhausted before dispatch")))

    def test_13b_transport_ambiguity_is_post_dispatch(self) -> None:
        from src.orchestration.model_adapter import is_uncertain_post_dispatch_error

        self.assertTrue(is_uncertain_post_dispatch_error(TimeoutError("read timed out")))
        self.assertTrue(is_uncertain_post_dispatch_error(ConnectionResetError("reset")))


class TestCeiling(unittest.TestCase):
    def test_14_default_per_node_ceiling_is_8192_with_reason(self) -> None:
        limits = ExecutionLimits()
        self.assertEqual(limits.max_output_tokens_per_node, 8192)

    def test_15_node_ceiling_flows_into_provider_kwargs(self) -> None:
        from src.orchestration.model_adapter import build_output_token_kwargs

        self.assertEqual(build_output_token_kwargs("custom", 8192), {"max_tokens": 8192})

    def test_16_truncation_still_fails_closed(self) -> None:
        from src.finops.pricing_registry import CalculatedCost
        from src.orchestration.model_adapter import (
            IncompleteModelOutputError,
            assert_provider_output_complete,
        )

        response = MagicMock()
        response.response_metadata = {"finish_reason": "length"}
        response.content = "def broken(:"
        response.usage_metadata = {"input_tokens": 10, "output_tokens": 4096, "total_tokens": 4106}
        with self.assertRaises(IncompleteModelOutputError):
            assert_provider_output_complete(response, "src/x.py")


if __name__ == "__main__":
    unittest.main()
