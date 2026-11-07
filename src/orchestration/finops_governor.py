"""
src/orchestration/finops_governor.py - Phase 9.7 FinOps Cost & Token Governance.

Phase 11.6: Autonomous Engineering Execution.
Integrates directly with Phase 9.7 FinOps:
- Tracks tokens, cached tokens, model tiers, and monetary costs.
- Enforces strict hard budget gates (default budget: INR 0.00 for paid LLM APIs).
- Bounded retry expenditure accounting.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("crusor.orchestration.finops")


class BudgetExhaustedError(RuntimeError):
    """Raised when an operation would exceed allocated task or workspace budgets."""
    pass


@dataclass
class TaskFinOpsExpenditure:
    """Detailed financial and token accounting for an engineering task."""
    task_id: str
    budget_inr: float = 0.00
    spent_inr: float = 0.00
    spent_usd: float = 0.00
    token_budget: int = 150000
    tokens_consumed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    tool_execution_seconds: float = 0.0
    test_execution_seconds: float = 0.0
    calls_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "budget_inr": self.budget_inr,
            "spent_inr": self.spent_inr,
            "spent_usd": self.spent_usd,
            "token_budget": self.token_budget,
            "tokens_consumed": self.tokens_consumed,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "tool_execution_seconds": round(self.tool_execution_seconds, 2),
            "test_execution_seconds": round(self.test_execution_seconds, 2),
            "calls_count": self.calls_count,
        }


class OrchestrationFinOpsGovernor:
    """
    Guarantees that autonomous execution stays strictly within allocated FinOps boundaries.
    """

    def __init__(self, task_id: str, budget_inr: float = 0.00, token_budget: int = 150000) -> None:
        self.accounting = TaskFinOpsExpenditure(
            task_id=task_id,
            budget_inr=budget_inr,
            token_budget=token_budget,
        )

    def authorize_operation(self, estimated_tokens: int = 0, estimated_cost_inr: float = 0.00) -> None:
        """Checks if operation can proceed without exceeding budget."""
        if self.accounting.spent_inr + estimated_cost_inr > self.accounting.budget_inr:
            raise BudgetExhaustedError(
                f"Operation rejected: estimated cost INR {estimated_cost_inr:.2f} exceeds "
                f"remaining budget INR {(self.accounting.budget_inr - self.accounting.spent_inr):.2f}"
            )
        if self.accounting.tokens_consumed + estimated_tokens > self.accounting.token_budget:
            raise BudgetExhaustedError(
                f"Operation rejected: estimated tokens {estimated_tokens} exceeds "
                f"remaining budget {self.accounting.token_budget - self.accounting.tokens_consumed}"
            )

    def record_usage(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cached_tokens: int = 0,
        cost_inr: float = 0.00,
        cost_usd: float = 0.00,
        tool_seconds: float = 0.0,
        test_seconds: float = 0.0,
    ) -> None:
        """Records actual consumed resources and verifies limits."""
        total_tok = input_tokens + output_tokens
        self.accounting.input_tokens += input_tokens
        self.accounting.output_tokens += output_tokens
        self.accounting.cached_tokens += cached_tokens
        self.accounting.tokens_consumed += total_tok
        self.accounting.spent_inr = round(self.accounting.spent_inr + cost_inr, 6)
        self.accounting.spent_usd = round(self.accounting.spent_usd + cost_usd, 6)
        self.accounting.tool_execution_seconds += tool_seconds
        self.accounting.test_execution_seconds += test_seconds
        self.accounting.calls_count += 1

        if self.accounting.spent_inr > self.accounting.budget_inr:
            log.warning(f"Task {self.accounting.task_id} exhausted monetary budget: INR {self.accounting.spent_inr:.4f}")

