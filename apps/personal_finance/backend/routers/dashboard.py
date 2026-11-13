"""
apps/personal_finance/backend/routers/dashboard.py - Dashboard metrics endpoints.
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Query
from apps.personal_finance.backend.models import DashboardResponse
from apps.personal_finance.backend.services.dashboard_service import DashboardService

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])
service = DashboardService()


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    year: Optional[int] = Query(None, description="Year (e.g. 2026)"),
    month: Optional[int] = Query(None, ge=1, le=12, description="Month (1-12)"),
) -> DashboardResponse:
    return service.get_dashboard(year=year, month=month)

