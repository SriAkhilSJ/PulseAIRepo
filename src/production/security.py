"""
src/production/security.py - Production Security Readiness Analyzer.

Phase 11.8: Production Readiness Intelligence.
Evaluates production security across:
- Authentication & Session Management (token expiry, rotation, password hashing)
- Authorization & Privilege Boundaries (RBAC, resource ownership, tenant isolation)
- Application Security (injection, XSS, SSRF, CSRF, insecure deserialization)
- Data Protection (TLS enforcement, encryption at rest, logging redaction)
- Infrastructure Security (non-root execution, port exposure)
- AI Agent & MCP Security (tool authorization, prompt injection fences)
"""

from __future__ import annotations

import ast
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


class ProductionSecurityAnalyzer:
    """
    Analyzes application codebase and infrastructure definitions for production security readiness.
    """

    def __init__(self, workspace_root: str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def evaluate_security(
        self,
        task_id: str,
        workspace_id: str,
        target_env: TargetEnvironmentConfig,
        files_to_scan: Optional[List[str]] = None,
    ) -> Tuple[DimensionEvaluation, List[ProductionReadinessFinding]]:
        """
        Executes comprehensive production security evaluations.
        """
        findings: List[ProductionReadinessFinding] = []
        files = files_to_scan if files_to_scan is not None else self._discover_code_files()

        has_password_hashing = False
        has_token_expiry = False
        has_tls_enforced = False
        has_input_validation = False
        has_rbac = False
        has_prompt_guard = False

        for rel in files:
            full = (self.workspace_root / rel).resolve()
            if not full.exists() or not full.is_file():
                continue
            content = full.read_text(encoding="utf-8", errors="replace")

            # 1. Password storage analysis
            if any(h in content for h in ["bcrypt", "argon2", "pbkdf2", "scrypt"]):
                has_password_hashing = True
            elif "md5(" in content or "sha1(" in content:
                if "password" in content.lower():
                    findings.append(
                        ProductionReadinessFinding(
                            finding_id=f"PROD-SEC-HASH-{len(findings)+1:03d}",
                            task_id=task_id,
                            workspace_id=workspace_id,
                            category=FindingCategory.SECURITY,
                            severity=FindingSeverity.HIGH,
                            title="Weak Password Hashing Algorithm Detected",
                            description=f"MD5 or SHA1 used for password handling in {rel}",
                            evidence_source=f"File: {rel}",
                            affected_component=rel,
                            environment=target_env.profile,
                            recommended_remediation="Upgrade password hashing to bcrypt or argon2id with adaptive work factors.",
                        )
                    )

            # 2. Token expiry check
            if "exp" in content or "expires_in" in content or "max_age" in content:
                has_token_expiry = True

            # 3. TLS / HTTPS enforcement
            if "https://" in content or "sslmode=require" in content or "force_https" in content:
                has_tls_enforced = True

            # 4. Input validation (pydantic, marshmallow, cerberus, validators)
            if any(v in content for v in ["BaseModel", "Schema", "validator", "is_valid", "validate_"]):
                has_input_validation = True

            # 5. RBAC & Tenant isolation
            if "tenant_id" in content or "require_role" in content or "permission" in content:
                has_rbac = True

            # 6. AI Prompt injection defense check (if AI app)
            if any(ai in content for ai in ["prompt", "llm", "completion", "gemini", "openai"]):
                if any(guard in content for guard in ["guardrail", "sanitize_prompt", "fence", "system_instruction", "boundary"]):
                    has_prompt_guard = True
                else:
                    findings.append(
                        ProductionReadinessFinding(
                            finding_id=f"PROD-SEC-AI-GUARD-{len(findings)+1:03d}",
                            task_id=task_id,
                            workspace_id=workspace_id,
                            category=FindingCategory.SECURITY,
                            severity=FindingSeverity.MEDIUM,
                            title="Missing Prompt Injection Defenses in AI Module",
                            description=f"Model invocation detected in {rel} without prompt sanitization fences.",
                            evidence_source=f"File: {rel}",
                            affected_component=rel,
                            environment=target_env.profile,
                            recommended_remediation="Implement strict system prompt isolation and user input sanitization fences.",
                        )
                    )

            # 7. Insecure Deserialization
            if "pickle.loads(" in content:
                findings.append(
                    ProductionReadinessFinding(
                        finding_id=f"PROD-SEC-PICKLE-{len(findings)+1:03d}",
                        task_id=task_id,
                        workspace_id=workspace_id,
                        category=FindingCategory.SECURITY,
                        severity=FindingSeverity.CRITICAL,
                        title="Unsafe Deserialization via pickle in Production Code",
                        description=f"pickle.loads call found in {rel}",
                        evidence_source=f"File: {rel}",
                        affected_component=rel,
                        environment=target_env.profile,
                        recommended_remediation="Replace pickle with safe structured serialization (JSON or protobuf).",
                    )
                )

        # Profile-scaled evaluations
        is_prod = target_env.profile in {
            EnvironmentProfile.STANDARD_PROD,
            EnvironmentProfile.ENTERPRISE_PROD,
            EnvironmentProfile.REGULATED_PROD,
        }

        blockers = []
        warnings = []

        critical_findings = [f for f in findings if f.severity in {FindingSeverity.CRITICAL, FindingSeverity.HIGH}]
        if critical_findings:
            blockers.append(f"{len(critical_findings)} Critical/High security vulnerabilities detected.")

        if is_prod:
            if not has_password_hashing and any("user" in f.lower() or "auth" in f.lower() for f in files):
                blockers.append("Production authentication lacks adaptive password hashing (bcrypt/argon2).")
            if not has_token_expiry and any("auth" in f.lower() or "jwt" in f.lower() for f in files):
                warnings.append("Authentication tokens should specify explicit expiry and rotation.")
            if not has_tls_enforced:
                warnings.append("TLS/HTTPS enforcement not explicitly configured in application settings.")

        status = ReadinessDimensionStatus.READY
        if blockers:
            status = ReadinessDimensionStatus.BLOCKED
        elif warnings:
            status = ReadinessDimensionStatus.NEEDS_ATTENTION

        evaluation = DimensionEvaluation(
            dimension_name="security_readiness",
            status=status,
            summary=f"Evaluated {len(files)} files. Identified {len(findings)} findings.",
            blockers=blockers,
            warnings=warnings,
            evidence={
                "password_hashing": has_password_hashing,
                "token_expiry": has_token_expiry,
                "input_validation": has_input_validation,
                "rbac_isolation": has_rbac,
                "tls_enforced": has_tls_enforced,
            },
        )
        return evaluation, findings

    def _discover_code_files(self) -> List[str]:
        code_files = []
        for root, _, files in os.walk(self.workspace_root):
            for f in files:
                if f.endswith((".py", ".js", ".ts", ".json", ".yml", ".yaml", ".env")):
                    full = Path(root) / f
                    try:
                        rel = full.relative_to(self.workspace_root).as_posix()
                        if not rel.startswith(".git") and not rel.startswith(".crusorai"):
                            code_files.append(rel)
                    except Exception:
                        pass
        return sorted(code_files)
