"""
apps/personal_finance/backend/services/budget_service.py - Budget domain business logic.
"""

from __future__ import annotations

from typing import List, Optional
from apps.personal_finance.backend.config import FinanceAppConfig
from apps.personal_finance.backend.models import BudgetCreate, BudgetResponse
from apps.personal_finance.backend.repositories.budget_repo import BudgetRepository
from apps.personal_finance.backend.repositories.category_repo import CategoryRepository


class BudgetService:
    """Business logic for setting and monitoring category budgets."""

    def __init__(
        self,
        budget_repo: Optional[BudgetRepository] = None,
        cat_repo: Optional[CategoryRepository] = None,
    ) -> None:
        self.budget_repo = budget_repo or BudgetRepository()
        self.cat_repo = cat_repo or CategoryRepository()

    def set_budget(self, req: BudgetCreate) -> BudgetResponse:
        cat = self.cat_repo.get_by_id(req.category_id)
        if not cat:
            raise ValueError(f"Category with id {req.category_id} does not exist.")
        if cat["type"] != "expense":
            raise ValueError(f"Budgets can only be set for expense categories, got '{cat['type']}'.")

        amount_paise = FinanceAppConfig.rupees_to_paise(req.amount_rupees)
        self.budget_repo.upsert(
            category_id=req.category_id,
            year=req.year,
            month=req.month,
            amount_paise=amount_paise,
        )
        res = self.get_budget(req.category_id, req.year, req.month)
        if not res:
            raise RuntimeError("Failed to retrieve saved budget.")
        return res

    def get_budget(self, category_id: int, year: int, month: int) -> Optional[BudgetResponse]:
        budgets = self.budget_repo.list_for_month(year, month)
        for b in budgets:
            if b["category_id"] == category_id:
                amount_paise = int(b["amount_paise"])
                spent_paise = int(b.get("spent_paise") or 0)
                amount_rupees = FinanceAppConfig.paise_to_rupees(amount_paise)
                spent_rupees = FinanceAppConfig.paise_to_rupees(spent_paise)
                remaining = round(amount_rupees - spent_rupees, 2)
                pct = round((spent_paise / amount_paise * 100), 1) if amount_paise > 0 else 0.0
                return BudgetResponse(
                    id=b["id"],
                    category_id=b["category_id"],
                    category_name=b["category_name"],
                    year=b["year"],
                    month=b["month"],
                    amount_paise=amount_paise,
                    amount_rupees=amount_rupees,
                    spent_paise=spent_paise,
                    spent_rupees=spent_rupees,
                    remaining_rupees=remaining,
                    percentage_used=pct,
                )
        return None

    def list_month(self, year: int, month: int) -> List[BudgetResponse]:
        rows = self.budget_repo.list_for_month(year, month)
        result = []
        for b in rows:
            amount_paise = int(b["amount_paise"])
            spent_paise = int(b.get("spent_paise") or 0)
            amount_rupees = FinanceAppConfig.paise_to_rupees(amount_paise)
            spent_rupees = FinanceAppConfig.paise_to_rupees(spent_paise)
            remaining = round(amount_rupees - spent_rupees, 2)
            pct = round((spent_paise / amount_paise * 100), 1) if amount_paise > 0 else 0.0
            result.append(BudgetResponse(
                id=b["id"],
                category_id=b["category_id"],
                category_name=b["category_name"],
                year=b["year"],
                month=b["month"],
                amount_paise=amount_paise,
                amount_rupees=amount_rupees,
                spent_paise=spent_paise,
                spent_rupees=spent_rupees,
                remaining_rupees=remaining,
                percentage_used=pct,
            ))
        return result

