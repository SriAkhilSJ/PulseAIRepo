"""
apps/personal_finance/backend/services/transaction_service.py - Transaction domain business logic.
"""

from __future__ import annotations

from typing import List, Optional
from apps.personal_finance.backend.config import FinanceAppConfig
from apps.personal_finance.backend.models import (
    CategoryType,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)
from apps.personal_finance.backend.repositories.category_repo import CategoryRepository
from apps.personal_finance.backend.repositories.transaction_repo import TransactionRepository


class TransactionService:
    """Business logic for validating and executing transaction operations."""

    def __init__(
        self,
        trans_repo: Optional[TransactionRepository] = None,
        cat_repo: Optional[CategoryRepository] = None,
    ) -> None:
        self.trans_repo = trans_repo or TransactionRepository()
        self.cat_repo = cat_repo or CategoryRepository()

    def _format_dto(self, row: dict) -> TransactionResponse:
        amount_paise = int(row["amount_paise"])
        rupees = FinanceAppConfig.paise_to_rupees(amount_paise)
        return TransactionResponse(
            id=row["id"],
            date=row["date"],
            amount_paise=amount_paise,
            amount_rupees=rupees,
            formatted_amount=FinanceAppConfig.format_inr(amount_paise),
            type=CategoryType(row["type"]),
            category_id=row["category_id"],
            category_name=row["category_name"],
            category_color=row.get("category_color", "#6366F1"),
            payment_mode=row.get("payment_mode", "UPI"),
            notes=row.get("notes") or "",
            created_at=row.get("created_at") or "",
        )

    def create(self, req: TransactionCreate) -> TransactionResponse:
        category = self.cat_repo.get_by_id(req.category_id)
        if not category:
            raise ValueError(f"Category with id {req.category_id} does not exist.")
        if category["type"] != req.type.value:
            raise ValueError(
                f"Category '{category['name']}' type ({category['type']}) does not match transaction type ({req.type.value})."
            )

        amount_paise = FinanceAppConfig.rupees_to_paise(req.amount_rupees)
        if amount_paise <= 0:
            raise ValueError("Transaction amount must be strictly greater than 0.")

        new_id = self.trans_repo.create(
            date=req.date,
            amount_paise=amount_paise,
            type=req.type.value,
            category_id=req.category_id,
            payment_mode=req.payment_mode.value,
            notes=req.notes,
        )
        row = self.trans_repo.get_by_id(new_id)
        if not row:
            raise RuntimeError("Failed to retrieve created transaction.")
        return self._format_dto(row)

    def get(self, transaction_id: int) -> Optional[TransactionResponse]:
        row = self.trans_repo.get_by_id(transaction_id)
        return self._format_dto(row) if row else None

    def update(self, transaction_id: int, req: TransactionUpdate) -> Optional[TransactionResponse]:
        existing = self.trans_repo.get_by_id(transaction_id)
        if not existing:
            return None

        cat_id = req.category_id if req.category_id is not None else existing["category_id"]
        tx_type = req.type.value if req.type is not None else existing["type"]

        if req.category_id is not None or req.type is not None:
            cat = self.cat_repo.get_by_id(cat_id)
            if not cat:
                raise ValueError(f"Category with id {cat_id} does not exist.")
            if cat["type"] != tx_type:
                raise ValueError(f"Category type ({cat['type']}) mismatch with transaction type ({tx_type}).")

        amount_paise = None
        if req.amount_rupees is not None:
            amount_paise = FinanceAppConfig.rupees_to_paise(req.amount_rupees)
            if amount_paise <= 0:
                raise ValueError("Transaction amount must be strictly greater than 0.")

        self.trans_repo.update(
            transaction_id=transaction_id,
            date=req.date,
            amount_paise=amount_paise,
            type=tx_type,
            category_id=cat_id,
            payment_mode=req.payment_mode.value if req.payment_mode else None,
            notes=req.notes,
        )
        updated = self.trans_repo.get_by_id(transaction_id)
        return self._format_dto(updated) if updated else None

    def delete(self, transaction_id: int) -> bool:
        return self.trans_repo.delete(transaction_id)

    def list(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category_id: Optional[int] = None,
        type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[TransactionResponse]:
        rows = self.trans_repo.list(
            start_date=start_date,
            end_date=end_date,
            category_id=category_id,
            type=type,
            limit=limit,
            offset=offset,
        )
        return [self._format_dto(r) for r in rows]

