"""
apps/personal_finance/backend/routers/transactions.py - Transaction endpoints.
"""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from apps.personal_finance.backend.models import (
    CategoryType,
    TransactionCreate,
    TransactionResponse,
    TransactionUpdate,
)
from apps.personal_finance.backend.services.transaction_service import TransactionService

router = APIRouter(prefix="/api/transactions", tags=["Transactions"])
service = TransactionService()


@router.post("", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
def create_transaction(req: TransactionCreate) -> TransactionResponse:
    try:
        return service.create(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[TransactionResponse])
def list_transactions(
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    category_id: Optional[int] = Query(None, description="Filter by category ID"),
    type: Optional[CategoryType] = Query(None, description="Filter by transaction type"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> List[TransactionResponse]:
    return service.list(
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
        type=type.value if type else None,
        limit=limit,
        offset=offset,
    )


@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(transaction_id: int) -> TransactionResponse:
    tx = service.get(transaction_id)
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return tx


@router.put("/{transaction_id}", response_model=TransactionResponse)
def update_transaction(transaction_id: int, req: TransactionUpdate) -> TransactionResponse:
    try:
        tx = service.update(transaction_id, req)
        if not tx:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return tx
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(transaction_id: int) -> None:
    ok = service.delete(transaction_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Transaction not found")

