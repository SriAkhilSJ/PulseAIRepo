"""
attribution.py -- Cost Attribution & Aggregation Engine.

Phase 9.7: Enterprise FinOps & Intelligent Cost Governance.
Provides multi-dimensional financial visibility and breakdown across:
- Request, Task, Session/Conversation, Workspace, Project, Model, Provider, User.
- Temporal slice aggregations: Daily, Weekly, Monthly, and arbitrary date ranges.
- Top spending drivers identification (Pareto analysis of high-cost operations).
- Historical audit integrity: past usage records retain the rates applicable at execution time.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from src.finops.accounting import TokenAccountingEngine, UsageRecord, get_accounting_engine
from src.finops.pricing_registry import quantize_currency

log = logging.getLogger("crusorai.finops.attribution")


@dataclass
class CostAggregationSummary:
    """Consolidated financial summary for an attribution dimension."""
    dimension_key: str
    dimension_value: str
    call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal("0.000000"))
    cost_inr: Decimal = field(default_factory=lambda: Decimal("0.000000"))
    unrated_calls: int = 0
    cached_savings_usd: Decimal = field(default_factory=lambda: Decimal("0.000000"))
    cached_savings_inr: Decimal = field(default_factory=lambda: Decimal("0.000000"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension_key": self.dimension_key,
            "dimension_value": self.dimension_value,
            "call_count": self.call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": float(self.cost_usd),
            "cost_inr": float(self.cost_inr),
            "unrated_calls": self.unrated_calls,
            "cached_savings_usd": float(self.cached_savings_usd),
            "cached_savings_inr": float(self.cached_savings_inr),
        }


class CostAttributionEngine:
    """
    Analyzes and groups token accounting events across multiple dimensions.
    """

    def __init__(self, accounting_engine: Optional[TokenAccountingEngine] = None) -> None:
        self._lock = threading.RLock()
        self._accounting = accounting_engine or get_accounting_engine()

    def attribute_by_dimension(
        self,
        dimension: str,
        records: Optional[List[UsageRecord]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> Dict[str, CostAggregationSummary]:
        """
        Aggregate records by a specific dimension:
        'task_id', 'workspace_id', 'session_id', 'provider', 'model', 'operation_type', 'user_id'.
        """
        source_records = records if records is not None else self._accounting.list_records()
        filtered = self._filter_time_window(source_records, start_time, end_time)

        groups: Dict[str, CostAggregationSummary] = {}

        with self._lock:
            for rec in filtered:
                val = self._extract_dimension_value(rec, dimension)
                if val not in groups:
                    groups[val] = CostAggregationSummary(dimension_key=dimension, dimension_value=val)

                summary = groups[val]
                summary.call_count += 1
                summary.input_tokens += rec.input_tokens
                summary.output_tokens += rec.output_tokens
                summary.cached_tokens += rec.cached_tokens
                summary.reasoning_tokens += rec.reasoning_tokens
                summary.total_tokens += rec.total_tokens

                if rec.cost_usd is not None:
                    summary.cost_usd = quantize_currency(summary.cost_usd + rec.cost_usd)
                else:
                    summary.unrated_calls += 1

                if rec.cost_inr is not None:
                    summary.cost_inr = quantize_currency(summary.cost_inr + rec.cost_inr)

        return groups

    def attribute_by_time_bucket(
        self,
        bucket: str = "daily",  # 'hourly', 'daily', 'monthly'
        records: Optional[List[UsageRecord]] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> Dict[str, CostAggregationSummary]:
        """Group spending into calendar time buckets (YYYY-MM-DD or YYYY-MM)."""
        source_records = records if records is not None else self._accounting.list_records()
        filtered = self._filter_time_window(source_records, start_time, end_time)

        groups: Dict[str, CostAggregationSummary] = {}

        with self._lock:
            for rec in filtered:
                dt = datetime.fromtimestamp(rec.timestamp, tz=timezone.utc)
                if bucket == "hourly":
                    key = dt.strftime("%Y-%m-%d %H:00")
                elif bucket == "monthly":
                    key = dt.strftime("%Y-%m")
                else:  # daily
                    key = dt.strftime("%Y-%m-%d")

                if key not in groups:
                    groups[key] = CostAggregationSummary(dimension_key=f"time_{bucket}", dimension_value=key)

                summary = groups[key]
                summary.call_count += 1
                summary.input_tokens += rec.input_tokens
                summary.output_tokens += rec.output_tokens
                summary.cached_tokens += rec.cached_tokens
                summary.reasoning_tokens += rec.reasoning_tokens
                summary.total_tokens += rec.total_tokens

                if rec.cost_usd is not None:
                    summary.cost_usd = quantize_currency(summary.cost_usd + rec.cost_usd)
                else:
                    summary.unrated_calls += 1

                if rec.cost_inr is not None:
                    summary.cost_inr = quantize_currency(summary.cost_inr + rec.cost_inr)

        return groups

    def get_top_spending_drivers(
        self,
        limit: int = 5,
        dimension: str = "model",
        records: Optional[List[UsageRecord]] = None,
    ) -> List[CostAggregationSummary]:
        """Return the top spending items sorted descending by cost."""
        attributed = self.attribute_by_dimension(dimension, records=records)
        sorted_summaries = sorted(attributed.values(), key=lambda s: s.cost_usd, reverse=True)
        return sorted_summaries[:limit]

    def _extract_dimension_value(self, record: UsageRecord, dimension: str) -> str:
        if dimension == "task_id":
            return record.task_id or "unassigned_task"
        elif dimension == "workspace_id":
            return record.workspace_id or "default_workspace"
        elif dimension == "session_id":
            return record.session_id or "unassigned_session"
        elif dimension == "provider":
            return record.provider or "unknown_provider"
        elif dimension == "model":
            return record.model or "unknown_model"
        elif dimension == "operation_type":
            return record.operation_type or "general"
        elif dimension == "user_id":
            return str(record.metadata.get("user_id", "default_user"))
        elif dimension == "project":
            return str(record.metadata.get("project", record.workspace_id or "default_project"))
        return getattr(record, dimension, "unknown")

    def _filter_time_window(
        self,
        records: List[UsageRecord],
        start_time: Optional[float],
        end_time: Optional[float],
    ) -> List[UsageRecord]:
        if start_time is None and end_time is None:
            return records
        filtered = []
        for r in records:
            if start_time is not None and r.timestamp < start_time:
                continue
            if end_time is not None and r.timestamp > end_time:
                continue
            filtered.append(r)
        return filtered


_GLOBAL_ATTRIBUTION: Optional[CostAttributionEngine] = None
_ATTRIBUTION_LOCK = threading.Lock()


def get_attribution_engine() -> CostAttributionEngine:
    global _GLOBAL_ATTRIBUTION
    with _ATTRIBUTION_LOCK:
        if _GLOBAL_ATTRIBUTION is None:
            _GLOBAL_ATTRIBUTION = CostAttributionEngine()
        return _GLOBAL_ATTRIBUTION

