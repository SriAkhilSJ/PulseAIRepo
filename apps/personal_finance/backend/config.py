"""
apps/personal-finance/backend/config.py - Configuration for Personal Finance Application.
"""

from __future__ import annotations

import os
from pathlib import Path


class FinanceAppConfig:
    """Application runtime settings and financial invariants."""
    APP_NAME: str = "Personal Finance Management"
    APP_VERSION: str = "1.0.0"
    CURRENCY_CODE: str = "INR"
    CURRENCY_SYMBOL: str = "₹"
    PAISE_PER_RUPEE: int = 100  # 1 INR = 100 paise

    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    DB_NAME: str = os.environ.get("FINANCE_DB_NAME", "finance.db")

    HOST: str = os.environ.get("FINANCE_HOST", "127.0.0.1")
    PORT: int = int(os.environ.get("FINANCE_PORT", "8000"))

    @classmethod
    def get_db_path(cls) -> Path:
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        return cls.DATA_DIR / cls.DB_NAME

    @classmethod
    def rupees_to_paise(cls, rupees: float) -> int:
        """Converts decimal rupees to integer minor units (paise) with exact rounding."""
        return int(round(rupees * cls.PAISE_PER_RUPEE))

    @classmethod
    def paise_to_rupees(cls, paise: int) -> float:
        """Converts integer paise to decimal rupees."""
        return round(paise / cls.PAISE_PER_RUPEE, 2)

    @classmethod
    def format_inr(cls, paise: int) -> str:
        """Formats integer paise into readable Indian Rupee string: ₹X,XX,XXX.XX"""
        rupees_part = paise // cls.PAISE_PER_RUPEE
        paise_part = paise % cls.PAISE_PER_RUPEE
        s = str(abs(rupees_part))
        if len(s) <= 3:
            formatted_int = s
        else:
            last3 = s[-3:]
            rest = s[:-3]
            chunks = []
            while len(rest) > 2:
                chunks.append(rest[-2:])
                rest = rest[:-2]
            if rest:
                chunks.append(rest)
            formatted_int = ",".join(reversed(chunks)) + "," + last3
        prefix = "-" if paise < 0 else ""
        return f"{prefix}{cls.CURRENCY_SYMBOL}{formatted_int}.{paise_part:02d}"
