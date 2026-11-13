"""
apps/personal_finance/backend/repositories/transaction_repo.py - Data access for Transactions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from apps.personal_finance.backend.database import DatabaseManager, get_db


class TransactionRepository:
    """Repository handling database operations for Transactions."""

    def __init__(self, db_mgr: Optional[DatabaseManager] = None) -> None:
        self.db = db_mgr or get_db()

    def create(
        self,
        date: str,
        amount_paise: int,
        type: str,
        category_id: int,
        payment_mode: str = "UPI",
        notes: str = "",
    ) -> int:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO transactions (date, amount_paise, type, category_id, payment_mode, notes)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (date, amount_paise, type, category_id, payment_mode, notes),
            )
            return int(cursor.lastrowid)

    def get_by_id(self, transaction_id: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT t.id, t.date, t.amount_paise, t.type, t.category_id,
                       t.payment_mode, t.notes, t.created_at,
                       c.name AS category_name, c.color AS category_color
                FROM transactions t
                JOIN categories c ON t.category_id = c.id
                WHERE t.id = ?;
                """,
                (transaction_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def update(
        self,
        transaction_id: int,
        date: Optional[str] = None,
        amount_paise: Optional[int] = None,
        type: Optional[str] = None,
        category_id: Optional[int] = None,
        payment_mode: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        updates = []
        params = []
        if date is not None:
            updates.append("date = ?")
            params.append(date)
        if amount_paise is not None:
            updates.append("amount_paise = ?")
            params.append(amount_paise)
        if type is not None:
            updates.append("type = ?")
            params.append(type)
        if category_id is not None:
            updates.append("category_id = ?")
            params.append(category_id)
        if payment_mode is not None:
            updates.append("payment_mode = ?")
            params.append(payment_mode)
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)

        if not updates:
            return False

        params.append(transaction_id)
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE transactions SET {', '.join(updates)} WHERE id = ?;",
                params,
            )
            return cursor.rowcount > 0

    def delete(self, transaction_id: int) -> bool:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM transactions WHERE id = ?;", (transaction_id,))
            return cursor.rowcount > 0

    def list(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        category_id: Optional[int] = None,
        type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params = []
        if start_date:
            clauses.append("t.date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("t.date <= ?")
            params.append(end_date)
        if category_id:
            clauses.append("t.category_id = ?")
            params.append(category_id)
        if type:
            clauses.append("t.type = ?")
            params.append(type)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
            SELECT t.id, t.date, t.amount_paise, t.type, t.category_id,
                   t.payment_mode, t.notes, t.created_at,
                   c.name AS category_name, c.color AS category_color
            FROM transactions t
            JOIN categories c ON t.category_id = c.id
            {where}
            ORDER BY t.date DESC, t.id DESC
            LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])

        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_totals(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, int]:
        clauses = []
        params = []
        if start_date:
            clauses.append("date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("date <= ?")
            params.append(end_date)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        query = f"""
            SELECT type, COALESCE(SUM(amount_paise), 0) AS total
            FROM transactions
            {where}
            GROUP BY type;
        """
        totals = {"income": 0, "expense": 0}
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            for row in cursor.fetchall():
                totals[row["type"]] = int(row["total"])
        return totals

    def get_category_breakdown(
        self,
        cat_type: str = "expense",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses = ["t.type = ?"]
        params = [cat_type]
        if start_date:
            clauses.append("t.date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("t.date <= ?")
            params.append(end_date)
        where = f"WHERE {' AND '.join(clauses)}"

        query = f"""
            SELECT c.id AS category_id, c.name AS category_name, c.color AS category_color,
                   c.type, COALESCE(SUM(t.amount_paise), 0) AS total_paise
            FROM categories c
            LEFT JOIN transactions t ON c.id = t.category_id AND {where.replace('WHERE ', '')}
            WHERE c.type = ?
            GROUP BY c.id, c.name, c.color, c.type
            HAVING total_paise > 0
            ORDER BY total_paise DESC;
        """
        params.append(cat_type)
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

