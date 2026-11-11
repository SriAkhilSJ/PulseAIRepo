"""Deterministic content/diff binding for workspace mutation approval.

Increment 2: an approval authorizes the exact proposed operation, not just a
path. The digest below is computed from the bytes the broker is about to
apply (create/modify) or from the pre-image being removed/moved. The approval
token carries it, so a changed proposal can never reuse an earlier approval.

Pure functions only; no I/O beyond the caller-provided strings.
"""
from __future__ import annotations

import difflib
import hashlib

DIGEST_PREFIX = "sha256:"


def content_digest(text: str | bytes | None) -> str:
    """Stable sha256 digest of the proposed content bytes."""
    if text is None:
        payload = b""
    elif isinstance(text, bytes):
        payload = text
    else:
        payload = str(text).encode("utf-8", errors="replace")
    return DIGEST_PREFIX + hashlib.sha256(payload).hexdigest()


def precondition_digest(exists: bool, text: str | bytes | None) -> str:
    """Workspace precondition the human saw: absent marker or pre-image digest."""
    if not exists:
        return "absent"
    return content_digest(text)


def unified_diff_text(
    old_text: str | None,
    new_text: str | None,
    *,
    display_path: str = "",
) -> str:
    """Workspace-relative unified diff used in the approval dock."""
    old_str = old_text or ""
    new_str = new_text or ""
    diff_lines = list(
        difflib.unified_diff(
            old_str.splitlines(keepends=True),
            new_str.splitlines(keepends=True),
            fromfile=f"a/{display_path}",
            tofile=f"b/{display_path}",
        )
    )
    return "".join(diff_lines)


def diff_stats(diff_text: str) -> dict[str, int]:
    added = sum(
        1 for line in diff_text.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in diff_text.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    return {"added": added, "removed": removed}
