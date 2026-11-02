"""
Context Engine Shared Domain Types
==================================

Neutral shared data structures and types for the Context Engine.
Decouples retrieval, indexing, and core orchestration without circular dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ChunkResult:
    id: str
    file_path: str
    symbol_name: str
    symbol_type: str  # module | function | class
    start_line: int
    end_line: int
    signature: str
    docstring: Optional[str]
    body: str  # display body for LLM context
    score: float  # fused score
    modified_time: float = 0.0  # file mtime at last sync (D13 hot feature)


__all__ = ["ChunkResult"]
