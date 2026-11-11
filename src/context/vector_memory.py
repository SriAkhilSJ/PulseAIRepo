"""Vector Memory — Backward Compatibility Facade."""

from __future__ import annotations

from src.context.memory.vector_memory import (
    VectorMemory,
    EMBED_DIM,
    _LEGACY_SCAN_LIMIT,
    sqlite_vec,
)

__all__ = [
    "VectorMemory",
    "EMBED_DIM",
    "_LEGACY_SCAN_LIMIT",
    "sqlite_vec",
]
