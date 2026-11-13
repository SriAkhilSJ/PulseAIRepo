"""
apps/personal_finance/backend/services/export_service.py - CSV Data Export.
"""

from __future__ import annotations

import csv
import io
from typing import Optional
from apps.personal_finance.backend.repositories.transaction_repo import TransactionRepository
from apps.personal_finance.backend.services.transaction_service import TransactionService


class ExportService:
    """Exports personal finance transactions into CSV."""

    def __init__(self, trans_service: Optional[TransactionService] = None) -> None:
        self.trans_service = trans_service or TransactionService()

    def export_csv(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category_id: Optional[int] = None,
    ) -> str:
        transactions = self.trans_service.list(
            start_date=start_date,
            end_date=end_date,
            category_id=category_id,
            limit=5000,
        )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Date", "Type", "Category", "Amount (INR)", "Payment Mode", "Notes", "Created At"])
        for t in transactions:
            writer.writerow([
                t.id,
                t.date,
                t.type.value.upper(),
                t.category_name,
                f"{t.amount_rupees:.2f}",
                t.payment_mode,
                t.notes,
                t.created_at,
            ])
        return output.getvalue()

