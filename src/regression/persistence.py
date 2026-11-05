"""
src/regression/persistence.py - Regression Artifact Persistence & Secret Redaction.

Phase 11.5: Regression Prevention & Recovery.
Manages persistent storage of RegressionReports and test baselines:
- Tenant-scoped path: .crusorai/tenants/{tenant_id}/regression/reports/
- Redacts secrets (API keys, tokens, passwords) before disk writing.
- Atomic commits via tempfile + os.replace() to prevent file corruption.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from src.regression.models import RegressionReport

log = logging.getLogger("crusor.regression.persistence")

SECRET_PATTERNS = [
    re.compile(r"""(sk-[a-zA-Z0-9]{20,})"""),
    re.compile(r"""(ghp_[a-zA-Z0-9]{20,})"""),
    re.compile(r"""(bearer\s+[a-zA-Z0-9_\-\.]{20,})""", re.IGNORECASE),
    re.compile(r"""(password\s*[:=]\s*['"][^'"]+['"])""", re.IGNORECASE),
]


def redact_secrets_from_dict(data: Any) -> Any:
    """Recursively redact sensitive tokens or credentials from dictionary structures."""
    if isinstance(data, dict):
        return {k: redact_secrets_from_dict(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [redact_secrets_from_dict(item) for item in data]
    elif isinstance(data, str):
        cleaned = data
        for pat in SECRET_PATTERNS:
            cleaned = pat.sub("[REDACTED_SECRET]", cleaned)
        return cleaned
    return data


class RegressionPersistence:
    """
    Handles atomic serialization and retrieval of regression reports.
    """

    def __init__(
        self,
        workspace_root: str,
        tenant_id: str = "default_tenant",
        storage_dir: Optional[str] = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.tenant_id = tenant_id

        if storage_dir:
            self.storage_dir = Path(storage_dir).resolve()
        else:
            self.storage_dir = (
                self.workspace_root
                / ".crusorai"
                / "tenants"
                / tenant_id
                / "regression"
                / "reports"
            )

        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_report(self, report: RegressionReport) -> bool:
        """Atomically persist redacted regression report."""
        target_file = self.storage_dir / f"{report.task_id}_regression_report.json"
        temp_file = self.storage_dir / f"tmp_report_{uuid.uuid4().hex[:8]}.json"

        try:
            raw_dict = report.to_dict()
            clean_dict = redact_secrets_from_dict(raw_dict)

            temp_file.write_text(json.dumps(clean_dict, indent=2), encoding="utf-8")
            temp_file.replace(target_file)
            return True
        except Exception as e:
            log.error(f"Failed to persist regression report: {e}")
            if temp_file.exists():
                try:
                    temp_file.unlink()
                except Exception:
                    pass
            return False

    def load_report(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Load persistent regression report."""
        target_file = self.storage_dir / f"{task_id}_regression_report.json"
        if not target_file.exists():
            return None
        try:
            return json.loads(target_file.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"Failed to load report {target_file}: {e}")
            return None

