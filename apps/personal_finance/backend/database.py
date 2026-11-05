"""
apps/personal-finance/backend/database.py - SQLite Connection and Schema Management.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from apps.personal_finance.backend.config import FinanceAppConfig

DEFAULT_CATEGORIES = [
    # Income categories
    ("Salary", "income", "briefcase", "#10B981"),
    ("Freelance", "income", "laptop", "#3B82F6"),
    ("Investments", "income", "trending-up", "#8B5CF6"),
    ("Rental Income", "income", "home", "#06B6D4"),
    ("Other Income", "income", "plus-circle", "#6EE7B7"),
    # Expense categories
    ("Groceries", "expense", "shopping-cart", "#F59E0B"),
    ("Rent & Housing", "expense", "home", "#EF4444"),
    ("Utilities & Bills", "expense", "zap", "#EC4899"),
    ("Food & Dining", "expense", "coffee", "#F97316"),
    ("Transportation & Fuel", "expense", "truck", "#6366F1"),
    ("Entertainment & Leisure", "expense", "film", "#14B8A6"),
    ("Healthcare & Medical", "expense", "heart", "#E11D48"),
    ("Shopping & Personal", "expense", "tag", "#A855F7"),
    ("Education", "expense", "book-open", "#0EA5E9"),
    ("Other Expense", "expense", "more-horizontal", "#9CA3AF"),
]


class DatabaseManager:
    """Manages SQLite connections, pragmas, and schema migrations with integer paise representation."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or FinanceAppConfig.get_db_path()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=10.0,
        )
        conn.row_factory = sqlite3.Row
        # Enforce SQLite performance & integrity pragmas
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize_schema(self) -> None:
        """Initializes tables and indexes with INTEGER minor units (paise)."""
        with self.connection() as conn:
            cursor = conn.cursor()

            # 1. Categories
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
                    icon TEXT NOT NULL DEFAULT 'tag',
                    color TEXT NOT NULL DEFAULT '#6366F1',
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
            """)

            # 2. Transactions (amount_paise is INTEGER)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    amount_paise INTEGER NOT NULL CHECK(amount_paise > 0),
                    type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
                    category_id INTEGER NOT NULL,
                    payment_mode TEXT NOT NULL DEFAULT 'UPI',
                    notes TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trans_date ON transactions(date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trans_cat ON transactions(category_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trans_type ON transactions(type);")

            # 3. Monthly Budgets (amount_paise is INTEGER)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS budgets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_id INTEGER NOT NULL,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12),
                    amount_paise INTEGER NOT NULL CHECK(amount_paise >= 0),
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
                    UNIQUE(category_id, year, month)
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_budget_ym ON budgets(year, month);")

            # 4. Seed default categories if empty
            cursor.execute("SELECT COUNT(*) FROM categories;")
            count = cursor.fetchone()[0]
            if count == 0:
                for name, cat_type, icon, color in DEFAULT_CATEGORIES:
                    cursor.execute(
                        "INSERT INTO categories (name, type, icon, color) VALUES (?, ?, ?, ?);",
                        (name, cat_type, icon, color),
                    )


_db_instance: Optional[DatabaseManager] = None


def get_db(custom_path: Optional[Path] = None) -> DatabaseManager:
    global _db_instance
    if custom_path is not None:
        return DatabaseManager(custom_path)
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance
