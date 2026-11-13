"""
apps/personal_finance/backend/main.py - FastAPI Application Entry Point.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apps.personal_finance.backend.config import FinanceAppConfig
from apps.personal_finance.backend.database import get_db
from apps.personal_finance.backend.routers import (
    budgets,
    categories,
    dashboard,
    export,
    transactions,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure database schema is initialized and seeded on startup
    db = get_db()
    db.initialize_schema()
    yield


app = FastAPI(
    title=FinanceAppConfig.APP_NAME,
    version=FinanceAppConfig.APP_VERSION,
    description="Full-featured personal finance and expense tracking API with minor-unit paise precision.",
    lifespan=lifespan,
)

# Enable CORS for local Vite dev frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(categories.router)
app.include_router(transactions.router)
app.include_router(budgets.router)
app.include_router(dashboard.router)
app.include_router(export.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "app": FinanceAppConfig.APP_NAME,
        "version": FinanceAppConfig.APP_VERSION,
        "currency": FinanceAppConfig.CURRENCY_CODE,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=FinanceAppConfig.HOST, port=FinanceAppConfig.PORT)

