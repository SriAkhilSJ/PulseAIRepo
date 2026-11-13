"""
apps/personal_finance/backend/routers/categories.py - Category endpoints.
"""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from apps.personal_finance.backend.models import CategoryResponse, CategoryType
from apps.personal_finance.backend.repositories.category_repo import CategoryRepository

router = APIRouter(prefix="/api/categories", tags=["Categories"])
cat_repo = CategoryRepository()


@router.get("", response_model=List[CategoryResponse])
def get_categories(type: Optional[CategoryType] = Query(None, description="Filter by category type")) -> List[CategoryResponse]:
    if type:
        rows = cat_repo.get_by_type(type.value)
    else:
        rows = cat_repo.list_all()
    return [CategoryResponse(**r) for r in rows]


@router.get("/{category_id}", response_model=CategoryResponse)
def get_category_by_id(category_id: int) -> CategoryResponse:
    row = cat_repo.get_by_id(category_id)
    if not row:
        raise HTTPException(status_code=404, detail="Category not found")
    return CategoryResponse(**row)

