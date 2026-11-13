"""
apps/personal_finance/backend/models.py - Pydantic Schemas and Domain DTOs.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class CategoryType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"


class PaymentMode(str, Enum):
    UPI = "UPI"
    CASH = "CASH"
    CARD = "CARD"
    NETBANKING = "NETBANKING"
    OTHER = "OTHER"


class CategoryResponse(BaseModel):
    id: int
    name: str
    type: CategoryType
    icon: str
    color: str
    created_at: str


class TransactionCreate(BaseModel):
    date: str = Field(description="ISO date string YYYY-MM-DD")
    amount_rupees: float = Field(gt=0, description="Transaction amount in INR rupees (must be positive)")
    type: CategoryType
    category_id: int
    payment_mode: PaymentMode = PaymentMode.UPI
    notes: str = ""

    @field_validator("date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        parts = v.strip().split("-")
        if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
            raise ValueError("date must be in YYYY-MM-DD format")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        if not (1 <= month <= 12 and 1 <= day <= 31):
            raise ValueError("invalid month or day in date")
        return v.strip()


class TransactionUpdate(BaseModel):
    date: Optional[str] = None
    amount_rupees: Optional[float] = Field(default=None, gt=0)
    type: Optional[CategoryType] = None
    category_id: Optional[int] = None
    payment_mode: Optional[PaymentMode] = None
    notes: Optional[str] = None

    @field_validator("date")
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        parts = v.strip().split("-")
        if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
            raise ValueError("date must be in YYYY-MM-DD format")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        if not (1 <= month <= 12 and 1 <= day <= 31):
            raise ValueError("invalid month or day in date")
        return v.strip()


class TransactionResponse(BaseModel):
    id: int
    date: str
    amount_paise: int
    amount_rupees: float
    formatted_amount: str
    type: CategoryType
    category_id: int
    category_name: str
    category_color: str
    payment_mode: str
    notes: str
    created_at: str


class BudgetCreate(BaseModel):
    category_id: int
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    amount_rupees: float = Field(ge=0)


class BudgetResponse(BaseModel):
    id: int
    category_id: int
    category_name: str
    year: int
    month: int
    amount_paise: int
    amount_rupees: float
    spent_paise: int
    spent_rupees: float
    remaining_rupees: float
    percentage_used: float


class CategoryBreakdown(BaseModel):
    category_id: int
    category_name: str
    category_color: str
    type: str
    total_paise: int
    total_rupees: float
    percentage_of_total: float


class MonthlySummary(BaseModel):
    year: int
    month: int
    total_income_paise: int
    total_income_rupees: float
    total_expense_paise: int
    total_expense_rupees: float
    net_savings_paise: int
    net_savings_rupees: float
    savings_rate_pct: float


class DashboardResponse(BaseModel):
    total_income_rupees: float
    total_expense_rupees: float
    net_savings_rupees: float
    savings_rate_pct: float
    categories_breakdown: List[CategoryBreakdown]
    recent_transactions: List[TransactionResponse]
    monthly_summary: MonthlySummary

