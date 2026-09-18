"""CrusorAI AgentOps backend configuration.

Zero-hardcoding rule (matches engine convention): everything from env, read per call.

  CRUSORAI_OPS_DATA_DIR         data root (default: ~/.pulseai)
  CRUSORAI_OPS_DEMO             on|off — labels the UI data source as DEMO
  CRUSORAI_OPS_TOKEN            bearer token; required off-loopback by policy
  CRUSORAI_OPS_ALLOWED_ORIGINS  comma list of CORS origins (dev vite)
  CRUSORAI_OPS_HOST / PORT      bind address (default 127.0.0.1:8300; 0.0.0.0 for previews)
  CRUSORAI_OPS_PRICES           JSON price table per 1M tokens: {"model": [in, out, cache]}
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def data_dir() -> Path:
    custom = os.environ.get("CRUSORAI_OPS_DATA_DIR", "").strip()
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".pulseai"


def journal_path() -> Path:
    return data_dir() / "runtime_events.db"


def receipts_path() -> Path:
    return data_dir() / "observability" / "turns.jsonl"


def demo_mode() -> bool:
    return os.environ.get("CRUSORAI_OPS_DEMO", "off").strip().lower() in {"1", "true", "yes", "on"}


def token() -> str:
    return os.environ.get("CRUSORAI_OPS_TOKEN", "").strip()


def allowed_origins() -> list[str]:
    raw = os.environ.get(
        "CRUSORAI_OPS_ALLOWED_ORIGINS",
        "http://127.0.0.1:5180,http://localhost:5180",
    )
    return [o.strip() for o in raw.split(",") if o.strip()]


def slo_targets() -> dict[str, float]:
    raw = os.environ.get("CRUSORAI_OPS_SLO_TARGETS", "").strip()
    base = {"completion": 0.90, "p95_latency_s": 120.0, "uptime": 0.999}
    if raw:
        try:
            base.update({k: float(v) for k, v in json.loads(raw).items()})
        except Exception:
            pass
    return base


def host_port() -> tuple[str, int]:
    host = os.environ.get("CRUSORAI_OPS_HOST", "127.0.0.1").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("CRUSORAI_OPS_PORT", "8300"))
    except ValueError:
        port = 8300
    return host, port
