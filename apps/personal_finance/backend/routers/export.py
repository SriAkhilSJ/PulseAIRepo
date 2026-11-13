"""
apps/personal_finance/backend/routers/export.py - Export data endpoints.
"""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Query, Response
from apps.personal_finance.backend.services.export_service import ExportService

router = APIRouter(prefix="/api/export", tags=["Export"])
service = ExportService()


@router.get("/csv")
def export_csv(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    category_id: Optional[int] = Query(None, description="Filter category"),
) -> Response:
    csv_content = service.export_csv(start_date=start_date, end_date=end_date, category_id=category_id)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )

