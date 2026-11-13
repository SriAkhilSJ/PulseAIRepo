"""
apps/personal_finance/backend/repositories/category_repo.py - Data access for Categories.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from apps.personal_finance.backend.database import DatabaseManager, get_db


class CategoryRepository:
    """Repository handling all database operations for Categories."""

    def __init__(self, db_mgr: Optional[DatabaseManager] = None) -> None:
        self.db = db_mgr or get_db()

    def list_all(self) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, type, icon, color, created_at FROM categories ORDER BY type ASC, name ASC;")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_by_id(self, category_id: int) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, type, icon, color, created_at FROM categories WHERE id = ?;", (category_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_by_type(self, cat_type: str) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, name, type, icon, color, created_at FROM categories WHERE type = ? ORDER BY name ASC;", (cat_type,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

