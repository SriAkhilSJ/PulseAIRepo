"""
redaction.py - High-Performance Sensitive Data Redaction for Desktop Observability.

Phase 9.6: Desktop Performance & Observability.
Ensures zero credential, secret, token, or private key leakage across
desktop logs, traces, IPC payloads, and diagnostic snapshots.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

# Common API key and credential patterns
SECRET_PATTERNS = [
    # Bearer tokens & JWTs
    (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{15,}", re.IGNORECASE), r"\1[REDACTED_BEARER_TOKEN]"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", re.IGNORECASE), r"[REDACTED_JWT]"),
    # OpenAI / Anthropic / Gemini API keys
    (re.compile(r"(?:sk-ant-|sk-proj-|sk-)[A-Za-z0-9_-]{20,}", re.IGNORECASE), r"[REDACTED_AI_API_KEY]"),
    # AWS Access Keys & Secrets
    (re.compile(r"(?:AKIA|ABIA|ACCA|ASIA)[0-9A-Z]{16}", re.IGNORECASE), r"[REDACTED_AWS_KEY_ID]"),
    (re.compile(r"(aws_secret_access_key\s*[:=]\s*)[A-Za-z0-9/+=]{40}", re.IGNORECASE), r"\1[REDACTED_AWS_SECRET]"),
    # GitHub Tokens
    (re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}", re.IGNORECASE), r"[REDACTED_GITHUB_TOKEN]"),
    # Private Key blocks
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), r"[REDACTED_PRIVATE_KEY_BLOCK]"),
    # Generic password / secret JSON fields
    (re.compile(r'("(?:password|client_secret|secret|api_key|token|auth)"\s*:\s*")[^"]+(")', re.IGNORECASE), r"\1[REDACTED]\2"),
]


class SecretRedactor:
    """
    Fast regex-based secret redactor ensuring diagnostic safety.
    """

    @classmethod
    def redact_text(cls, text: Optional[str]) -> str:
        if not text:
            return ""
        redacted = str(text)
        for pattern, replacement in SECRET_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    @classmethod
    def redact_data(cls, data: Any) -> Any:
        """Recursively redact dictionary, list, or scalar fields."""
        if isinstance(data, str):
            return cls.redact_text(data)
        elif isinstance(data, dict):
            clean_dict = {}
            for k, v in data.items():
                k_lower = str(k).lower()
                if any(sec in k_lower for sec in ("key", "secret", "token", "password", "auth", "credential")):
                    clean_dict[k] = "[REDACTED_SECRET]"
                else:
                    clean_dict[k] = cls.redact_data(v)
            return clean_dict
        elif isinstance(data, list):
            return [cls.redact_data(item) for item in data]
        return data


def redact_sensitive_data(val: Any) -> Any:
    return SecretRedactor.redact_data(val)

