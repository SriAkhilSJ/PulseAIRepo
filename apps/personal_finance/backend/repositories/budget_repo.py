"""
apps/personal_finance/backend/repositories/budget_repo.py - Data access for Budgets.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from apps.personal_finance.backend.database import DatabaseManager, get_db


class BudgetRepository:
    """Repository handling database operations for Budgets."""

    def __init__(self, db_mgr: Optional[DatabaseManager] = None) -> None:
        self.db = db_mgr or get_db()

    def upsert(self, category_id: int, year: int, month: int, amount_paise: int) -> int:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO budgets (category_id, year, month, amount_paise)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(category_id, year, month)
                DO UPDATE SET amount_paise = excluded.amount_paise;
                """,
                (category_id, year, month, amount_paise),
            )
            return int(cursor.lastrowid)

    def get(self, category_id: int, year: int, month: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT b.id, b.category_id, b.year, b.month, b.amount_paise, b.created_at,
                       c.name AS category_name
                FROM budgets b
                JOIN categories c ON b.category_id = c.id
                WHERE b.category_id = ? AND b.year = ? AND b.month = ?;
                """,
                (category_id, year, month),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_for_month(self, year: int, month: int) -> List[Dict[str, Any]]:
        month_str = f"{year:04d}-{month:02d}"
        query = """
            SELECT b.id, b.category_id, b.year, b.month, b.amount_paise,
                   c.name AS category_name,
                   COALESCE((
                       SELECT SUM(t.amount_paise)
                       FROM transactions t
                       WHERE t.category_id = b.category_id
                         AND strftime('%Y-%m', t.date) = ?
                   ), 0) AS spent_paise
            FROM budgets b
            JOIN categories c ON b.category_id = c.id
            WHERE b.year = ? AND b.month = ?
            ORDER BY c.name ASC;
        """
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (month_str, year, month))
            return [dict(r) for r in cursor.fetchall()]

