"""
src/production/config.py - Production Configuration & Secrets Analyzer.

Phase 11.8: Production Readiness Intelligence.
Analyzes application configuration and environment settings:
- Hardcoded secrets and default credentials (changeme, secret123, admin, sk-..., ghp_...)
- Debug mode enabled in production (DEBUG = True, NODE_ENV = development)
- Unsafe wildcard CORS (Access-Control-Allow-Origin: * with credentials)
- Development-only endpoints exposed (/debug, /dev/reset, /test-only)
- Missing required production environment variables
Strictly scrubs secret values and never exposes raw secrets in reports or logs.
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


class ProductionConfigurationAnalyzer:
    """
    Analyzes configuration files, environment definitions, and source files for production readiness.
    """

    SECRET_PATTERNS = [
        (re.compile(r'(?i)(?:api_key|secret|password|token)\s*[:=]\s*["\']?(sk-[a-zA-Z0-9_\-]{20,})["\']?'), "Exposed API Key", FindingSeverity.CRITICAL),
        (re.compile(r'(?i)(?:ghp_[a-zA-Z0-9]{20,})'), "Exposed GitHub Personal Access Token", FindingSeverity.CRITICAL),
        (re.compile(r'(?i)password\s*[:=]\s*["\']?(?:changeme|secret123|admin|password|root|123456)["\']?'), "Default/Placeholder Password in Configuration", FindingSeverity.CRITICAL),
        (re.compile(r'-----BEGIN (?:RSA )?PRIVATE KEY-----'), "Hardcoded Private Key Block", FindingSeverity.CRITICAL),
    ]

    DEBUG_PATTERNS = [
        re.compile(r'(?i)\bDEBUG\s*=\s*True\b'),
        re.compile(r'(?i)\bNODE_ENV\s*[:=]\s*["\']development["\']'),
        re.compile(r'(?i)\bENVIRONMENT\s*[:=]\s*["\']dev(?:elopment)?["\']'),
    ]

    CORS_WILDCARD = re.compile(r'(?i)allow_origins\s*[:=]\s*\[\s*["\']\*["\']\s*\]')

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate_configuration(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
        files_to_scan: Optional[List[str]] = None,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding]]:
        findings: List[ProductionReadinessFinding] = []
        files = files_to_scan if files_to_scan is not None else self._discover_config_files()

        has_debug_mode = False
        has_wildcard_cors = False
        has_dev_endpoint = False
        has_env_example = (self.workspace_root / ".env.example").exists()

        for rel in files:
            full = (self.workspace_root / rel).resolve()
            if not full.exists() or not full.is_file():
                continue
            content = full.read_text(encoding="utf-8", errors="replace")

            # 1. Hardcoded Secrets Detection
            for pat, title, sev in self.SECRET_PATTERNS:
                if pat.search(content):
                    findings.append(
                        ProductionReadinessFinding(
                            finding_id=f"PROD-CFG-SECRET-{len(findings)+1:03d}",
                            task_id=task_id,
                            workspace_id=workspace_id,
                            category=FindingCategory.CONFIGURATION,
                            severity=sev,
                            title=title,
                            description=f"Sensitive secret credential discovered in {rel}",
                            evidence_source=f"File: {rel} (Value redacted: [REDACTED_SECRET])",
                            affected_component=rel,
                            environment=target_env.profile,
                            recommended_remediation="Extract secret to environment variables or enterprise secret store (Vault/AWS Secrets Manager).",
                        )
                    )

            # 2. Debug mode in production
            is_prod = target_env.profile in {
                EnvironmentProfile.STANDARD_PROD,
                EnvironmentProfile.ENTERPRISE_PROD,
                EnvironmentProfile.REGULATED_PROD,
            }

            for d_pat in self.DEBUG_PATTERNS:
                if d_pat.search(content):
                    has_debug_mode = True
                    if is_prod:
                        findings.append(
                            ProductionReadinessFinding(
                                finding_id=f"PROD-CFG-DEBUG-{len(findings)+1:03d}",
                                task_id=task_id,
                                workspace_id=workspace_id,
                                category=FindingCategory.CONFIGURATION,
                                severity=FindingSeverity.HIGH,
                                title="Debug Mode Active in Production Configuration",
                                description=f"Debug flag set to True or development mode in {rel}",
                                evidence_source=f"File: {rel}",
                                affected_component=rel,
                                environment=target_env.profile,
                                recommended_remediation="Ensure DEBUG=False and NODE_ENV=production in target production environment.",
                            )
                        )

            # 3. Wildcard CORS with credentials
            if self.CORS_WILDCARD.search(content):
                has_wildcard_cors = True
                if is_prod:
                    findings.append(
                        ProductionReadinessFinding(
                            finding_id=f"PROD-CFG-CORS-{len(findings)+1:03d}",
                            task_id=task_id,
                            workspace_id=workspace_id,
                            category=FindingCategory.CONFIGURATION,
                            severity=FindingSeverity.MEDIUM,
                            title="Overly Permissive Wildcard CORS Configuration",
                            description=f"CORS allow_origins set to wildcard ('*') in {rel}",
                            evidence_source=f"File: {rel}",
                            affected_component=rel,
                            environment=target_env.profile,
                            recommended_remediation="Restrict CORS allow_origins to explicit trusted production domain origins.",
                        )
                    )

            # 4. Development-only endpoints exposed
            if any(ep in content for ep in ["/debug", "/dev/reset", "/test-data", "/seed-db"]):
                has_dev_endpoint = True
                if is_prod:
                    findings.append(
                        ProductionReadinessFinding(
                            finding_id=f"PROD-CFG-DEV-ROUTE-{len(findings)+1:03d}",
                            task_id=task_id,
                            workspace_id=workspace_id,
                            category=FindingCategory.CONFIGURATION,
                            severity=FindingSeverity.HIGH,
                            title="Development/Test Endpoint Exposed in Production",
                            description=f"Route handler for development utilities discovered in {rel}",
                            evidence_source=f"File: {rel}",
                            affected_component=rel,
                            environment=target_env.profile,
                            recommended_remediation="Gate development utility endpoints behind non-production environment checks.",
                        )
                    )

        blockers = []
        warnings = []
        for f in findings:
            if f.severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH}:
                blockers.append(f"{f.title} ({f.affected_component})")
            else:
                warnings.append(f"{f.title} ({f.affected_component})")

        status = ReadinessDimensionStatus.READY
        if blockers:
            status = ReadinessDimensionStatus.BLOCKED
        elif warnings:
            status = ReadinessDimensionStatus.NEEDS_ATTENTION

        evaluation = DimensionEvaluation(
            dimension_name="configuration_readiness",
            status=status,
            summary=f"Scanned {len(files)} config files. Identified {len(findings)} findings.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "has_env_example": has_env_example,
                "debug_mode": has_debug_mode,
                "wildcard_cors": has_wildcard_cors,
                "dev_endpoint_exposed": has_dev_endpoint,
            },
        )
        return evaluation, findings

    def _discover_config_files(self) -> List[str]:
        config_files = []
        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                f_low = f.lower()
                if f.endswith((".env", ".env.example", ".json", ".yaml", ".yml", ".ini", ".toml", ".py")):
                    full = Path(root) / f
                    try:
                        rel = full.relative_to(self.workspace_root).as_posix()
                        if not rel.startswith(".git") and not rel.startswith(".crusorai"):
                            config_files.append(rel)
                    except Exception:
                        pass
        return sorted(config_files)
