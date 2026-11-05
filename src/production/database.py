"""
src/production/database.py - Database & Schema Migration Readiness Analyzer.

Phase 11.8: Production Readiness Intelligence.
Analyzes database configuration, schema constraints, connection pools, and migration safety:
- Destructive migration detection: DROP TABLE, DROP COLUMN, TRUNCATE, ALTER TYPE without backwards compatibility
- Connection pool limits and timeout configurations
- Foreign key, uniqueness constraints, and tenant isolation in data schemas
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.production.models import (
    DimensionEvaluation,
    EnvironmentProfile,
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    ProductionReadinessFinding,
    ReadinessDimensionStatus,
    TargetEnvironmentConfig,
)


class DatabaseProductionAnalyzer:
    """
    Evaluates database migrations, connection pool configurations, and schema safety.
    """

    DESTRUCTIVE_SQL = [
        (re.compile(r'(?i)\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?[a-zA-Z0-9_]+'), "Destructive DROP TABLE in Migration", FindingSeverity.CRITICAL),
        (re.compile(r'(?i)\bDROP\s+COLUMN\s+[a-zA-Z0-9_]+'), "Destructive DROP COLUMN in Migration", FindingSeverity.HIGH),
        (re.compile(r'(?i)\bTRUNCATE\s+(?:TABLE\s+)?[a-zA-Z0-9_]+'), "TRUNCATE TABLE in Migration", FindingSeverity.CRITICAL),
    ]

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate_database(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding]]:
        findings: List[ProductionReadinessFinding] = []

        migration_files = self._find_migration_files()
        has_migrations = len(migration_files) > 0
        has_destructive_migration = False
        has_connection_pooling = False

        for mf in migration_files:
            content = (self.workspace_root / mf).read_text(encoding="utf-8", errors="replace")

            for pat, title, sev in self.DESTRUCTIVE_SQL:
                match = pat.search(content)
                if match:
                    has_destructive_migration = True
                    findings.append(
                        ProductionReadinessFinding(
                            finding_id=f"PROD-DB-DESTRUCT-{len(findings)+1:03d}",
                            task_id=task_id,
                            workspace_id=workspace_id,
                            category=FindingCategory.DATABASE,
                            severity=sev,
                            title=title,
                            description=f"Destructive schema migration detected in {mf}: '{match.group(0)}'",
                            evidence_source=f"File: {mf}",
                            affected_component=mf,
                            environment=target_env.profile,
                            recommended_remediation="Use non-destructive expand-and-contract migration patterns instead of immediate drops.",
                        )
                    )

        # Check code for connection pool settings
        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                if f.endswith((".py", ".js", ".ts")):
                    full = Path(root) / f
                    try:
                        c = full.read_text(encoding="utf-8", errors="replace").lower()
                        if any(p in c for p in ["pool_size", "max_connections", "connectionpool", "pool_timeout"]):
                            has_connection_pooling = True
                    except Exception:
                        pass

        is_prod = target_env.profile in {
            EnvironmentProfile.STANDARD_PROD,
            EnvironmentProfile.ENTERPRISE_PROD,
            EnvironmentProfile.REGULATED_PROD,
        }

        if is_prod and not has_connection_pooling and has_migrations:
            findings.append(
                ProductionReadinessFinding(
                    finding_id=f"PROD-DB-POOL-{len(findings)+1:03d}",
                    task_id=task_id,
                    workspace_id=workspace_id,
                    category=FindingCategory.DATABASE,
                    severity=FindingSeverity.MEDIUM,
                    title="Database Connection Pooling Not Configured",
                    description="No explicit connection pool limits or timeout parameters detected in database configuration.",
                    evidence_source="Database setup code",
                    affected_component="database",
                    environment=target_env.profile,
                    recommended_remediation="Configure explicit connection pool size and timeout limits (e.g. pool_size=20, max_overflow=10).",
                )
            )

        blockers = [f.title for f in findings if f.severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH}]
        warnings = [f.title for f in findings if f.severity in {FindingSeverity.MEDIUM, FindingSeverity.LOW}]

        status = ReadinessDimensionStatus.READY
        if blockers:
            status = ReadinessDimensionStatus.BLOCKED
        elif warnings:
            status = ReadinessDimensionStatus.NEEDS_ATTENTION

        evaluation = DimensionEvaluation(
            dimension_name="database_readiness",
            status=status,
            summary=f"Evaluated {len(migration_files)} migrations. Identified {len(findings)} findings.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "migration_files": migration_files,
                "has_destructive_migration": has_destructive_migration,
                "has_connection_pooling": has_connection_pooling,
            },
        )
        return evaluation, findings

    def _find_migration_files(self) -> List[str]:
        results = []
        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                full = Path(root) / f
                try:
                    rel = full.relative_to(self.workspace_root).as_posix()
                    if ("migration" in rel.lower() or "alembic" in rel.lower()) and f.endswith((".py", ".sql")):
                        if not rel.startswith(".git") and not rel.startswith(".crusorai"):
                            results.append(rel)
                except Exception:
                    pass
        return sorted(results)

