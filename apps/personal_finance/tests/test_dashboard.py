"""
apps/personal_finance/tests/test_dashboard.py - Automated tests for dashboard metrics & summaries.
"""

import pytest
import tempfile
from pathlib import Path
from apps.personal_finance.backend.database import DatabaseManager
from apps.personal_finance.backend.models import CategoryType, TransactionCreate, BudgetCreate
from apps.personal_finance.backend.repositories.budget_repo import BudgetRepository
from apps.personal_finance.backend.repositories.category_repo import CategoryRepository
from apps.personal_finance.backend.repositories.transaction_repo import TransactionRepository
from apps.personal_finance.backend.services.budget_service import BudgetService
from apps.personal_finance.backend.services.dashboard_service import DashboardService
from apps.personal_finance.backend.services.transaction_service import TransactionService


@pytest.fixture
def test_db():
    tmp_dir = tempfile.mkdtemp()
    db_file = Path(tmp_dir) / "test_dash.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()
    return db_mgr


def test_dashboard_metrics_calculation(test_db):
    cat_repo = CategoryRepository(test_db)
    trans_repo = TransactionRepository(test_db)
    trans_service = TransactionService(trans_repo, cat_repo)
    dash_service = DashboardService(trans_repo, trans_service)

    inc_cats = cat_repo.get_by_type("income")
    exp_cats = cat_repo.get_by_type("expense")

    # Add Income: 50,000 INR
    trans_service.create(TransactionCreate(
        date="2026-11-01",
        amount_rupees=50000.0,
        type=CategoryType.INCOME,
        category_id=inc_cats[0]["id"],
        notes="Monthly Salary",
    ))

    # Add Expense 1: 5,000 INR
    trans_service.create(TransactionCreate(
        date="2026-11-02",
        amount_rupees=5000.0,
        type=CategoryType.EXPENSE,
        category_id=exp_cats[0]["id"],
        notes="Groceries",
    ))

    # Add Expense 2: 5,000 INR
    trans_service.create(TransactionCreate(
        date="2026-11-03",
        amount_rupees=5000.0,
        type=CategoryType.EXPENSE,
        category_id=exp_cats[1]["id"],
        notes="Utilities",
    ))

    dash = dash_service.get_dashboard(year=2026, month=11)
    assert dash.total_income_rupees == 50000.0
    assert dash.total_expense_rupees == 10000.0
    assert dash.net_savings_rupees == 40000.0
    # Savings rate = (40000 / 50000) * 100 = 80.0%
    assert dash.savings_rate_pct == 80.0

    # Category breakdown check
    assert len(dash.categories_breakdown) == 2
    for b in dash.categories_breakdown:
        assert b.percentage_of_total == 50.0


def test_budget_monitoring(test_db):
    cat_repo = CategoryRepository(test_db)
    budget_repo = BudgetRepository(test_db)
    trans_repo = TransactionRepository(test_db)
    trans_service = TransactionService(trans_repo, cat_repo)
    budget_service = BudgetService(budget_repo, cat_repo)

    exp_cats = cat_repo.get_by_type("expense")
    cat_id = exp_cats[0]["id"]

    # Set budget: 10,000 INR for November 2026
    budget = budget_service.set_budget(BudgetCreate(
        category_id=cat_id,
        year=2026,
        month=11,
        amount_rupees=10000.0,
    ))
    assert budget.amount_rupees == 10000.0
    assert budget.percentage_used == 0.0

    # Add expense under that category: 2,500 INR
    trans_service.create(TransactionCreate(
        date="2026-11-04",
        amount_rupees=2500.0,
        type=CategoryType.EXPENSE,
        category_id=cat_id,
    ))

    # Check updated budget
    updated_b = budget_service.get_budget(cat_id, 2026, 11)
    assert updated_b is not None
    assert updated_b.spent_rupees == 2500.0
    assert updated_b.remaining_rupees == 7500.0
    assert updated_b.percentage_used == 25.0

