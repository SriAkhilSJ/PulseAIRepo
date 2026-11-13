"""
apps/personal_finance/tests/test_transactions.py - Automated tests for transaction management.
"""

import pytest
import tempfile
from pathlib import Path
from apps.personal_finance.backend.database import DatabaseManager
from apps.personal_finance.backend.models import CategoryType, TransactionCreate, TransactionUpdate
from apps.personal_finance.backend.repositories.category_repo import CategoryRepository
from apps.personal_finance.backend.repositories.transaction_repo import TransactionRepository
from apps.personal_finance.backend.services.transaction_service import TransactionService


@pytest.fixture
def test_db():
    tmp_dir = tempfile.mkdtemp()
    db_file = Path(tmp_dir) / "test_trans.db"
    db_mgr = DatabaseManager(db_file)
    db_mgr.initialize_schema()
    return db_mgr


@pytest.fixture
def service(test_db):
    cat_repo = CategoryRepository(test_db)
    trans_repo = TransactionRepository(test_db)
    return TransactionService(trans_repo, cat_repo)


def test_create_and_get_transaction(service, test_db):
    # Groceries category exists
    cat_repo = CategoryRepository(test_db)
    cats = cat_repo.get_by_type("expense")
    assert len(cats) > 0
    cat_id = cats[0]["id"]

    req = TransactionCreate(
        date="2026-11-06",
        amount_rupees=1250.50,
        type=CategoryType.EXPENSE,
        category_id=cat_id,
        notes="Weekly grocery shopping",
    )
    res = service.create(req)
    assert res.id is not None
    assert res.amount_rupees == 1250.50
    assert res.amount_paise == 125050
    assert res.type == CategoryType.EXPENSE
    assert res.category_id == cat_id
    assert "₹" in res.formatted_amount

    # Get by id
    fetched = service.get(res.id)
    assert fetched is not None
    assert fetched.id == res.id
    assert fetched.notes == "Weekly grocery shopping"


def test_validation_rejects_non_positive_amount():
    with pytest.raises(Exception):
        TransactionCreate(
            date="2026-11-06",
            amount_rupees=0.0,
            type=CategoryType.EXPENSE,
            category_id=1,
        )

    with pytest.raises(Exception):
        TransactionCreate(
            date="2026-11-06",
            amount_rupees=-50.0,
            type=CategoryType.EXPENSE,
            category_id=1,
        )


def test_validation_rejects_invalid_date():
    with pytest.raises(ValueError):
        TransactionCreate(
            date="invalid-date",
            amount_rupees=100.0,
            type=CategoryType.EXPENSE,
            category_id=1,
        )


def test_category_type_mismatch_rejected(service, test_db):
    cat_repo = CategoryRepository(test_db)
    income_cats = cat_repo.get_by_type("income")
    assert len(income_cats) > 0
    income_cat_id = income_cats[0]["id"]

    # Attempt to create an EXPENSE with an INCOME category
    req = TransactionCreate(
        date="2026-11-06",
        amount_rupees=500.0,
        type=CategoryType.EXPENSE,
        category_id=income_cat_id,
    )
    with pytest.raises(ValueError) as exc:
        service.create(req)
    assert "match" in str(exc.value).lower()


def test_update_and_delete_transaction(service, test_db):
    cat_repo = CategoryRepository(test_db)
    cats = cat_repo.get_by_type("expense")
    cat_id = cats[0]["id"]

    created = service.create(TransactionCreate(
        date="2026-11-06",
        amount_rupees=300.0,
        type=CategoryType.EXPENSE,
        category_id=cat_id,
        notes="Lunch",
    ))

    # Update amount and notes
    updated = service.update(created.id, TransactionUpdate(
        amount_rupees=450.0,
        notes="Lunch with dessert",
    ))
    assert updated is not None
    assert updated.amount_rupees == 450.0
    assert updated.notes == "Lunch with dessert"

    # Delete
    deleted = service.delete(created.id)
    assert deleted is True
    assert service.get(created.id) is None
