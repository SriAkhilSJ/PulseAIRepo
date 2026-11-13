"""
apps/personal_finance/backend/routers/budgets.py - Budget endpoints.
"""

from __future__ import annotations

import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from apps.personal_finance.backend.models import BudgetCreate, BudgetResponse
from apps.personal_finance.backend.services.budget_service import BudgetService

router = APIRouter(prefix="/api/budgets", tags=["Budgets"])
service = BudgetService()


@router.post("", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED)
def set_budget(req: BudgetCreate) -> BudgetResponse:
    try:
        return service.set_budget(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[BudgetResponse])
def list_budgets(
    year: Optional[int] = Query(None, description="Year (e.g. 2026)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month (1-12)"),
) -> List[BudgetResponse]:
    now = datetime.date.today()
    y = year or now.year
    m = month or now.month
    return service.list_month(y, m)

