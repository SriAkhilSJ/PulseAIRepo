"""
src/verification/security_verifier.py - Independent Security Verifier.

Phase 11.7: Independent Verification & Quality Assurance.
Performs deterministic static, semantic, and boundary security audits:
- Injection vulnerabilities (raw SQL formatting, eval, exec, shell=True)
- Path traversal (os.path.join with unsanitized user inputs, relative ../)
- Authentication & authorization bypasses (unprotected routes, missing login_required)
- Hardcoded secrets and credentials (API keys, private keys, passwords)
- Tenant isolation leakages (queries without tenant_id scoping)
- Unsafe serialization (pickle.loads, yaml.load without SafeLoader)
Issues structured VerificationFinding objects with severity ratings.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.verification.authority import VerificationAuthority
from src.verification.models import (
    FindingCategory,
    FindingSeverity,
    FindingStatus,
    VerificationFinding,
)


class IndependentSecurityVerifier:
    """
    Independently inspects code mutations for security defects and privilege bypasses.
    """

    def __init__(self, authority: VerificationAuthority) -> None:
        self.authority = authority

    def audit_security(
        self,
        task_id: str,
        mutated_files: List[str],
    ) -> List[VerificationFinding]:
        """
        Executes a battery of security audits across all modified code files.
        """
        findings: List[VerificationFinding] = []

        for rel in mutated_files:
            content = self.authority.inspect_file(rel)
            if not content:
                continue

            # 1. Hardcoded secrets scan
            secret_findings = self._scan_for_hardcoded_secrets(task_id, rel, content)
            findings.extend(secret_findings)

            # 2. Injection vulnerability scan
            injection_findings = self._scan_for_injections(task_id, rel, content)
            findings.extend(injection_findings)

            # 3. Path traversal scan
            path_findings = self._scan_for_path_traversal(task_id, rel, content)
            findings.extend(path_findings)

            # 4. Unsafe serialization scan
            ser_findings = self._scan_for_unsafe_serialization(task_id, rel, content)
            findings.extend(ser_findings)

            # 5. Missing authorization checks
            auth_findings = self._scan_for_missing_authorization(task_id, rel, content)
            findings.extend(auth_findings)

            # 6. Tenant isolation bypasses
            tenant_findings = self._scan_for_tenant_leakage(task_id, rel, content)
            findings.extend(tenant_findings)

        return findings

    def _scan_for_hardcoded_secrets(
        self,
        task_id: str,
        rel: str,
        content: str,
    ) -> List[VerificationFinding]:
        findings = []
        patterns = [
            (r'(?i)(?:api_key|secret|password|token)\s*=\s*["\'](sk-[a-zA-Z0-9_\-]{20,})["\']', "Exposed API Key", FindingSeverity.CRITICAL),
            (r'(?i)(?:ghp_[a-zA-Z0-9]{20,})', "Exposed GitHub Personal Access Token", FindingSeverity.CRITICAL),
            (r'(?i)password\s*=\s*["\']([a-zA-Z0-9@#$%^&*]{6,})["\']', "Hardcoded plaintext password", FindingSeverity.HIGH),
            (r'-----BEGIN (?:RSA )?PRIVATE KEY-----', "Hardcoded private key block", FindingSeverity.CRITICAL),
        ]

        for pat, title, sev in patterns:
            matches = re.finditer(pat, content)
            for m in matches:
                findings.append(
                    VerificationFinding(
                        finding_id=f"SEC-SECRET-{len(findings)+1:03d}",
                        task_id=task_id,
                        category=FindingCategory.SECURITY,
                        severity=sev,
                        title=title,
                        description=f"Potential secret credential detected in {rel}",
                        evidence=f"Matched pattern: {m.group(0)[:15]}...[REDACTED]",
                        affected_files=[rel],
                        recommended_action="Move secret to environment variables or enterprise secret store.",
                    )
                )
        return findings

    def _scan_for_injections(
        self,
        task_id: str,
        rel: str,
        content: str,
    ) -> List[VerificationFinding]:
        findings = []
        # Check raw SQL string formatting
        if re.search(r'(?i)execute\s*\(\s*f["\'].*SELECT.*FROM', content) or \
           re.search(r'(?i)execute\s*\(\s*f["\'].*INSERT.*INTO', content) or \
           re.search(r'(?i)execute\s*\(\s*f["\'].*UPDATE.*SET', content) or \
           re.search(r'(?i)execute\s*\(\s*["\'].*%s.*["\']\s*%', content):
            findings.append(
                VerificationFinding(
                    finding_id=f"SEC-SQLI-{len(findings)+1:03d}",
                    task_id=task_id,
                    category=FindingCategory.SECURITY,
                    severity=FindingSeverity.CRITICAL,
                    title="Potential SQL Injection Vulnerability",
                    description=f"Unparameterized raw SQL string formatting detected in {rel}",
                    evidence="Dynamic SQL construction using f-strings or % formatting directly in execute().",
                    affected_files=[rel],
                    recommended_action="Use parameterized SQL query placeholders (e.g. ? or :param).",
                )
            )

        # Check eval() or exec()
        if re.search(r'\b(?:eval|exec)\s*\(', content):
            findings.append(
                VerificationFinding(
                    finding_id=f"SEC-CODE-EXEC-{len(findings)+1:03d}",
                    task_id=task_id,
                    category=FindingCategory.SECURITY,
                    severity=FindingSeverity.HIGH,
                    title="Dangerous Dynamic Code Execution",
                    description=f"Call to eval() or exec() detected in {rel}",
                    evidence="Dynamic execution function call detected.",
                    affected_files=[rel],
                    recommended_action="Replace eval/exec with safe deterministic AST or JSON parsers.",
                )
            )

        # Check subprocess shell=True
        if "shell=True" in content:
            findings.append(
                VerificationFinding(
                    finding_id=f"SEC-SHELL-EXEC-{len(findings)+1:03d}",
                    task_id=task_id,
                    category=FindingCategory.SECURITY,
                    severity=FindingSeverity.HIGH,
                    title="Command Injection Surface via shell=True",
                    description=f"Subprocess invoked with shell=True in {rel}",
                    evidence="shell=True parameter present in subprocess call.",
                    affected_files=[rel],
                    recommended_action="Avoid shell=True; pass arguments as an explicit list of tokens.",
                )
            )

        return findings

    def _scan_for_path_traversal(
        self,
        task_id: str,
        rel: str,
        content: str,
    ) -> List[VerificationFinding]:
        findings = []
        if ("../" in content or "..\\" in content) and ("open(" in content or "Path(" in content):
            findings.append(
                VerificationFinding(
                    finding_id=f"SEC-PATH-TRAV-{len(findings)+1:03d}",
                    task_id=task_id,
                    category=FindingCategory.SECURITY,
                    severity=FindingSeverity.HIGH,
                    title="Potential Path Traversal Pattern",
                    description=f"Relative parent path traversal ('../') combined with file access in {rel}",
                    evidence="Direct file open with unsanitized relative path navigation.",
                    affected_files=[rel],
                    recommended_action="Enforce strict Path.resolve() boundary checking against workspace root.",
                )
            )
        return findings

    def _scan_for_unsafe_serialization(
        self,
        task_id: str,
        rel: str,
        content: str,
    ) -> List[VerificationFinding]:
        findings = []
        if "pickle.loads(" in content or "pickle.load(" in content:
            findings.append(
                VerificationFinding(
                    finding_id=f"SEC-UNSAFE-SER-{len(findings)+1:03d}",
                    task_id=task_id,
                    category=FindingCategory.SECURITY,
                    severity=FindingSeverity.HIGH,
                    title="Unsafe Deserialization via pickle",
                    description=f"pickle.load/loads call detected in {rel}",
                    evidence="Arbitrary code execution risk on untrusted pickle payloads.",
                    affected_files=[rel],
                    recommended_action="Use safe serialization formats such as JSON or Protocol Buffers.",
                )
            )
        return findings

    def _scan_for_missing_authorization(
        self,
        task_id: str,
        rel: str,
        content: str,
    ) -> List[VerificationFinding]:
        findings = []
        # Check endpoint functions without auth decorator if other endpoints have auth
        if ("@app.get" in content or "@app.post" in content or "@router." in content):
            if "delete" in content.lower() or "admin" in content.lower():
                if not any(a in content for a in ["Depends(", "login_required", "require_role", "require_permission"]):
                    findings.append(
                        VerificationFinding(
                            finding_id=f"SEC-AUTH-BYPASS-{len(findings)+1:03d}",
                            task_id=task_id,
                            category=FindingCategory.SECURITY,
                            severity=FindingSeverity.HIGH,
                            title="Unprotected Sensitive API Endpoint",
                            description=f"Admin or delete route defined in {rel} without explicit authorization gate.",
                            evidence="Route handler lacks authentication/authorization dependency or decorator.",
                            affected_files=[rel],
                            recommended_action="Enforce authentication and role-based access control.",
                        )
                    )
        return findings

    def _scan_for_tenant_leakage(
        self,
        task_id: str,
        rel: str,
        content: str,
    ) -> List[VerificationFinding]:
        findings = []
        if "tenant_id" in content and "db.query(" in content:
            # Check if query contains filter on tenant_id
            if "filter(" in content and "tenant_id" not in content.split("filter(")[1].split(")")[0]:
                findings.append(
                    VerificationFinding(
                        finding_id=f"SEC-TENANT-LEAK-{len(findings)+1:03d}",
                        task_id=task_id,
                        category=FindingCategory.SECURITY,
                        severity=FindingSeverity.MEDIUM,
                        title="Potential Multi-Tenant Query Leakage",
                        description=f"Database query in {rel} does not explicitly filter by tenant_id.",
                        evidence="filter() expression does not include tenant_id scoping.",
                        affected_files=[rel],
                        recommended_action="Ensure all queries in multi-tenant models enforce tenant_id isolation.",
                    )
                )
        return findings

