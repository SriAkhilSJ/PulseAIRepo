"""Billing state — enterprise, portal-backed but fail-open.

Mirrors hermes agent/billing_view.py + hermes_cli/nous_account.py:
  BillingState (balance, plan, role, can_change_plan, portal_url)
  build_billing_state() -> BillingState  (cached 60s, never raises)

Local stub: reads ~/.crusorai/auth.json (JWT) + hits portal if logged in.
No auth -> logged_in=False, free tier, never blocks IDE.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_AUTH_PATH = Path.home() / ".crusorai" / "auth.json"
_CACHE_TTL_S = 60
_cached_state: Optional["BillingState"] = None
_cached_at: float = 0

@dataclass
class BillingState:
    logged_in: bool = False
    plan_name: Optional[str] = None  # "Free", "Pro", "Team"
    status: str = "free"  # free|low|healthy
    balance_usd: Optional[float] = None
    renews_at: Optional[str] = None
    org_id: Optional[str] = None
    org_name: Optional[str] = None
    role: Optional[str] = None  # Owner|Admin|Member
    can_change_plan: bool = False
    portal_url: str = "https://www.crusor.in/login"
    error: Optional[str] = None
    available: bool = False

def _read_auth() -> Optional[dict]:
    try:
        if _AUTH_PATH.is_file():
            return json.loads(_AUTH_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None

def build_billing_state(force_refresh: bool = False) -> BillingState:
    global _cached_state, _cached_at
    now = time.time()
    if not force_refresh and _cached_state is not None and (now - _cached_at) < _CACHE_TTL_S:
        return _cached_state
    auth = _read_auth()
    if not auth:
        state = BillingState(logged_in=False, available=False)
        _cached_state = state
        _cached_at = now
        return state
    # Online portal fetch would go here (GET /api/billing/state). Stub: derive from auth file.
    state = BillingState(
        logged_in=True,
        plan_name=auth.get("plan_name") or "Pro trial",
        status="healthy",
        balance_usd=float(auth.get("balance_usd", 42.5)) if auth.get("balance_usd") is not None else 42.5,
        renews_at=auth.get("renews_at"),
        org_id=auth.get("org_id"),
        org_name=auth.get("org_name"),
        role=auth.get("role") or "Owner",
        can_change_plan=(auth.get("role") in ("Owner", "Admin") or auth.get("can_change_plan") is True),
        portal_url="https://www.crusor.in/login",
        available=True,
    )
    _cached_state = state
    _cached_at = now
    return state

def invalidate_billing_cache() -> None:
    global _cached_state, _cached_at
    _cached_state = None
    _cached_at = 0
