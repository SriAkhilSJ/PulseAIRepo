"""
apps/personal_finance/backend/services/dashboard_service.py - Financial Dashboard Aggregation.
"""

from __future__ import annotations

import datetime
from typing import Optional
from apps.personal_finance.backend.config import FinanceAppConfig
from apps.personal_finance.backend.models import (
    CategoryBreakdown,
    DashboardResponse,
    MonthlySummary,
)
from apps.personal_finance.backend.repositories.transaction_repo import TransactionRepository
from apps.personal_finance.backend.services.transaction_service import TransactionService


class DashboardService:
    """Aggregates metrics for the executive dashboard: totals, savings, breakdowns."""

    def __init__(
        self,
        trans_repo: Optional[TransactionRepository] = None,
        trans_service: Optional[TransactionService] = None,
    ) -> None:
        self.trans_repo = trans_repo or TransactionRepository()
        self.trans_service = trans_service or TransactionService(self.trans_repo)

    def get_dashboard(self, year: Optional[int] = None, month: Optional[int] = None) -> DashboardResponse:
        now = datetime.date.today()
        target_year = year or now.year
        target_month = month or now.month

        start_date = f"{target_year:04d}-{target_month:02d}-01"
        # Determine end of month
        if target_month == 12:
            next_month = f"{target_year + 1:04d}-01-01"
        else:
            next_month = f"{target_year:04d}-{target_month + 1:02d}-01"

        totals = self.trans_repo.get_totals(start_date=start_date, end_date=next_month)
        income_paise = totals.get("income", 0)
        expense_paise = totals.get("expense", 0)
        net_savings_paise = income_paise - expense_paise

        income_rupees = FinanceAppConfig.paise_to_rupees(income_paise)
        expense_rupees = FinanceAppConfig.paise_to_rupees(expense_paise)
        net_savings_rupees = FinanceAppConfig.paise_to_rupees(net_savings_paise)

        savings_rate = 0.0
        if income_paise > 0:
            savings_rate = round(max(0.0, (net_savings_paise / income_paise) * 100), 2)

        # Category breakdowns for expenses
        cat_rows = self.trans_repo.get_category_breakdown(
            cat_type="expense",
            start_date=start_date,
            end_date=next_month,
        )
        breakdowns = []
        for cr in cat_rows:
            cat_paise = int(cr["total_paise"])
            cat_rupees = FinanceAppConfig.paise_to_rupees(cat_paise)
            pct = round((cat_paise / expense_paise * 100), 1) if expense_paise > 0 else 0.0
            breakdowns.append(CategoryBreakdown(
                category_id=cr["category_id"],
                category_name=cr["category_name"],
                category_color=cr.get("category_color", "#6366F1"),
                type=cr.get("type", "expense"),
                total_paise=cat_paise,
                total_rupees=cat_rupees,
                percentage_of_total=pct,
            ))

        recent = self.trans_service.list(limit=10)

        monthly_summary = MonthlySummary(
            year=target_year,
            month=target_month,
            total_income_paise=income_paise,
            total_income_rupees=income_rupees,
            total_expense_paise=expense_paise,
            total_expense_rupees=expense_rupees,
            net_savings_paise=net_savings_paise,
            net_savings_rupees=net_savings_rupees,
            savings_rate_pct=savings_rate,
        )

        return DashboardResponse(
            total_income_rupees=income_rupees,
            total_expense_rupees=expense_rupees,
            net_savings_rupees=net_savings_rupees,
            savings_rate_pct=savings_rate,
            categories_breakdown=breakdowns,
            recent_transactions=recent,
            monthly_summary=monthly_summary,
        )

