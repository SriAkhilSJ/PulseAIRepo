"""
test_p0_4_budget_governor.py - P0.4 Provider-Call Budget Overrun Prevention Tests.

Validates:
1. Reservation within budget succeeds and encumbers funds.
2. Reservation exceeding remaining budget fails closed with BudgetExhaustedError.
3. Actual usage below reservation commits actual spend and releases unused hold.
4. Actual usage reaching the reserved maximum commits accurately without breach.
5. Actual usage exceeding the reserved maximum triggers breach state and stops subsequent paid execution.
6. Concurrent reservations are race-condition safe and cannot over-subscribe the budget.
7. Provider timeout and cancellation safely release the reservation hold without charging.
8. Reservation release and duplicate settlement are idempotent and cannot double-settle.
9. Restart recovery restores persisted financial state across process boundaries.
"""

from __future__ import annotations

import concurrent.futures
from decimal import Decimal
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from src.orchestration.finops_governor import (
    BudgetExhaustedError,
    FinOpsReservation,
    OrchestrationFinOpsGovernor,
)


class TestP04BudgetGovernor(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="crusor_p0_4_finops_")
        self.storage_dir = Path(self.tmp).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reservation_within_budget(self) -> None:
        """Verify reserving funds within the allocated budget succeeds and encumbers funds."""
        gov = OrchestrationFinOpsGovernor("task_res_1", budget_inr=10.00, token_budget=10000)

        res_id = gov.reserve(
            estimated_tokens=1000,
            estimated_cost_inr=2.50,
            estimated_cost_usd=0.03,
            purpose="test_node_1",
        )

        self.assertTrue(res_id.startswith("res_"))
        self.assertEqual(gov.accounting.spent_inr, 0.0)
        self.assertEqual(gov.accounting.reserved_inr, 2.50)
        self.assertEqual(gov.accounting.reserved_tokens, 1000)

        # Remaining available unreserved budget is 7.50
        remaining = gov.accounting.budget_inr - (gov.accounting.spent_inr + gov.accounting.reserved_inr)
        self.assertAlmostEqual(remaining, 7.50, places=4)

    def test_reservation_exceeding_remaining_budget(self) -> None:
        """Verify reservation exceeding remaining unreserved budget fails closed."""
        gov = OrchestrationFinOpsGovernor("task_res_2", budget_inr=10.00, token_budget=10000)

        # First reservation: INR 8.00 (succeeds)
        gov.reserve(estimated_tokens=3000, estimated_cost_inr=8.00, estimated_cost_usd=0.09)

        # Second reservation: INR 3.00 (8.00 + 3.00 = 11.00 > 10.00 -> fails)
        with self.assertRaises(BudgetExhaustedError) as ctx:
            gov.reserve(estimated_tokens=1000, estimated_cost_inr=3.00, estimated_cost_usd=0.035)

        self.assertIn("exceeds remaining budget", str(ctx.exception))
        # Reserved amount remains 8.00; rejected reserve does not corrupt accounting
        self.assertEqual(gov.accounting.reserved_inr, 8.00)
        self.assertEqual(gov.accounting.spent_inr, 0.0)

    def test_actual_usage_below_reservation(self) -> None:
        """Verify committing actual usage below the reserved maximum commits spend and releases unused hold."""
        gov = OrchestrationFinOpsGovernor("task_res_3", budget_inr=10.00, token_budget=10000)

        res_id = gov.reserve(estimated_tokens=2000, estimated_cost_inr=4.00, estimated_cost_usd=0.05)
        self.assertEqual(gov.accounting.reserved_inr, 4.00)

        # Actual provider response used only INR 1.50 (e.g. fewer tokens generated)
        gov.commit_reservation(
            reservation_id=res_id,
            actual_input_tokens=500,
            actual_output_tokens=300,
            actual_cached_tokens=0,
            actual_cost_inr=1.50,
            actual_cost_usd=0.018,
        )

        # Reservation hold is completely released
        self.assertEqual(gov.accounting.reserved_inr, 0.0)
        self.assertEqual(gov.accounting.reserved_tokens, 0)
        # Actual spend is committed accurately
        self.assertEqual(gov.accounting.spent_inr, 1.50)
        self.assertEqual(gov.accounting.spent_usd, 0.018)
        self.assertEqual(gov.accounting.tokens_consumed, 800)
        self.assertFalse(gov.accounting.is_breached)

    def test_actual_usage_reaching_reserved_maximum(self) -> None:
        """Verify committing actual usage exactly equal to the reserved maximum."""
        gov = OrchestrationFinOpsGovernor("task_res_4", budget_inr=10.00, token_budget=10000)

        res_id = gov.reserve(estimated_tokens=1500, estimated_cost_inr=3.00, estimated_cost_usd=0.035)

        gov.commit_reservation(
            reservation_id=res_id,
            actual_input_tokens=800,
            actual_output_tokens=700,
            actual_cached_tokens=0,
            actual_cost_inr=3.00,
            actual_cost_usd=0.035,
        )

        self.assertEqual(gov.accounting.reserved_inr, 0.0)
        self.assertEqual(gov.accounting.spent_inr, 3.00)
        self.assertFalse(gov.accounting.is_breached)

    def test_actual_usage_exceeding_reserved_maximum_blocks_subsequent_execution(self) -> None:
        """Verify actual usage exceeding the reserved maximum triggers breach state and blocks further execution."""
        gov = OrchestrationFinOpsGovernor("task_res_5", budget_inr=10.00, token_budget=10000)

        res_id = gov.reserve(estimated_tokens=1000, estimated_cost_inr=2.00, estimated_cost_usd=0.024)

        # Rogue or non-compliant provider generated more tokens than allowed (INR 2.60 > INR 2.00)
        gov.commit_reservation(
            reservation_id=res_id,
            actual_input_tokens=600,
            actual_output_tokens=800,
            actual_cached_tokens=0,
            actual_cost_inr=2.60,
            actual_cost_usd=0.031,
        )

        # Breach must be explicitly flagged
        self.assertTrue(gov.accounting.is_breached)
        self.assertIn("exceeded reserved maximum", gov.accounting.breach_reason)

        # Subsequent attempts to reserve or authorize operations are strictly blocked
        with self.assertRaises(BudgetExhaustedError) as ctx:
            gov.reserve(estimated_tokens=500, estimated_cost_inr=1.00)
        self.assertIn("task budget was breached", str(ctx.exception))

        with self.assertRaises(BudgetExhaustedError):
            gov.authorize_operation(estimated_tokens=100, estimated_cost_inr=0.10)

    def test_concurrent_reservations_prevent_oversubscription(self) -> None:
        """Verify that concurrent threads cannot race to exceed the remaining budget."""
        # Total budget: INR 10.00. Each thread attempts to reserve INR 2.00 (5 max can succeed).
        gov = OrchestrationFinOpsGovernor("task_concurrent", budget_inr=10.00, token_budget=50000)

        num_threads = 10
        successful_res: list[str] = []
        rejected_count: list[int] = [0]
        lock = concurrent.futures.thread.threading.Lock()

        def try_reserve(idx: int) -> None:
            try:
                r_id = gov.reserve(
                    estimated_tokens=1000,
                    estimated_cost_inr=2.00,
                    estimated_cost_usd=0.024,
                    purpose=f"thread_{idx}",
                )
                with lock:
                    successful_res.append(r_id)
            except BudgetExhaustedError:
                with lock:
                    rejected_count[0] += 1

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(try_reserve, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        # Exactly 5 reservations must succeed (5 * 2.00 = 10.00)
        self.assertEqual(len(successful_res), 5)
        # Exactly 5 reservations must be rejected
        self.assertEqual(rejected_count[0], 5)
        # Total encumbered funds must equal exactly 10.00, never exceeding
        self.assertEqual(gov.accounting.reserved_inr, 10.00)

    def test_provider_timeout_and_cancellation_release_reservation(self) -> None:
        """Verify provider timeout or cancellation releases the reservation hold without charging."""
        gov = OrchestrationFinOpsGovernor("task_res_timeout", budget_inr=10.00, token_budget=10000)

        res_id = gov.reserve(estimated_tokens=2000, estimated_cost_inr=4.00, estimated_cost_usd=0.048)
        self.assertEqual(gov.accounting.reserved_inr, 4.00)

        # Simulate provider failure / timeout / cancellation
        gov.release_reservation(res_id, reason="provider_timeout")

        # Reserved amount is reset to 0.00; spent remains 0.00
        self.assertEqual(gov.accounting.reserved_inr, 0.0)
        self.assertEqual(gov.accounting.reserved_tokens, 0)
        self.assertEqual(gov.accounting.spent_inr, 0.0)

        # Full original budget is once again available
        new_res = gov.reserve(estimated_tokens=4000, estimated_cost_inr=10.00)
        self.assertTrue(new_res.startswith("res_"))

    def test_reservation_release_and_duplicate_settlement(self) -> None:
        """Verify that duplicate commits or releases are idempotent and do not corrupt accounting."""
        gov = OrchestrationFinOpsGovernor("task_idempotent", budget_inr=10.00, token_budget=10000)

        # 1. Duplicate release test
        res1 = gov.reserve(estimated_tokens=500, estimated_cost_inr=1.00)
        gov.release_reservation(res1)
        self.assertEqual(gov.accounting.reserved_inr, 0.0)

        # Second release of same ID must be a safe no-op
        gov.release_reservation(res1)
        self.assertEqual(gov.accounting.reserved_inr, 0.0)

        # 2. Duplicate commit test
        res2 = gov.reserve(estimated_tokens=500, estimated_cost_inr=2.00)
        gov.commit_reservation(
            reservation_id=res2,
            actual_input_tokens=200,
            actual_output_tokens=200,
            actual_cached_tokens=0,
            actual_cost_inr=1.00,
            actual_cost_usd=0.012,
        )
        self.assertEqual(gov.accounting.spent_inr, 1.00)

        # Second commit of already settled ID must be safely ignored without double-spending
        gov.commit_reservation(
            reservation_id=res2,
            actual_input_tokens=200,
            actual_output_tokens=200,
            actual_cached_tokens=0,
            actual_cost_inr=1.00,
            actual_cost_usd=0.012,
        )
        self.assertEqual(gov.accounting.spent_inr, 1.00)

    def test_restart_recovery_from_persistence(self) -> None:
        """Verify that financial governor recovers state, active reservations, and spend across process restarts."""
        task_id = "task_restart_recover"

        # Session 1: Spend INR 3.00, create an active reservation of INR 2.00
        gov1 = OrchestrationFinOpsGovernor(
            task_id,
            budget_inr=10.00,
            token_budget=10000,
            storage_dir=str(self.storage_dir),
        )

        res1 = gov1.reserve(estimated_tokens=1000, estimated_cost_inr=3.00, estimated_cost_usd=0.035)
        gov1.commit_reservation(
            reservation_id=res1,
            actual_input_tokens=400,
            actual_output_tokens=400,
            actual_cached_tokens=0,
            actual_cost_inr=3.00,
            actual_cost_usd=0.035,
        )

        # Active in-flight reservation
        res2 = gov1.reserve(estimated_tokens=800, estimated_cost_inr=2.00, estimated_cost_usd=0.024)

        self.assertEqual(gov1.accounting.spent_inr, 3.00)
        self.assertEqual(gov1.accounting.reserved_inr, 2.00)

        # Session 2: Simulating process restart - new instance with same storage_dir
        gov2 = OrchestrationFinOpsGovernor(
            task_id,
            budget_inr=10.00,
            token_budget=10000,
            storage_dir=str(self.storage_dir),
        )

        # Recovered state must match Session 1 exactly
        self.assertEqual(gov2.accounting.spent_inr, 3.00)
        self.assertEqual(gov2.accounting.reserved_inr, 2.00)
        self.assertEqual(gov2.accounting.budget_inr, 10.00)
        self.assertIn(res2, gov2._active_reservations)

        # Committing the recovered reservation in Session 2 succeeds
        gov2.commit_reservation(
            reservation_id=res2,
            actual_input_tokens=300,
            actual_output_tokens=300,
            actual_cached_tokens=0,
            actual_cost_inr=1.50,
            actual_cost_usd=0.018,
        )

        self.assertEqual(gov2.accounting.spent_inr, 4.50)
        self.assertEqual(gov2.accounting.reserved_inr, 0.0)


if __name__ == "__main__":
    unittest.main()

