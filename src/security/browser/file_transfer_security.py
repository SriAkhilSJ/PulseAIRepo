"""
file_transfer_security.py - Secure Download Quarantine & Upload Policy Enforcement.

Phase 9.5: MCP Ecosystem & Browser Agent Security.
Governs all file transfers initiated by the Browser Agent or MCP tools:
1. Downloads: Isolated quarantine directory, size caps, SHA-256 hashing, archive Zip-Slip traversal defense.
2. Uploads: Explicit user confirmation, workspace confinement, and sensitive secret/credential blocking.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# Sensitive files that must NEVER be uploaded to external web applications
PROHIBITED_UPLOAD_PATTERNS = [
    r"\.env",
    r"\.git-credentials",
    r"\.ssh",
    r"id_rsa",
    r"id_ed25519",
    r"\.aws",
    r"\.azure",
    r"\.config[/\\]gcloud",
    r".*\.pem$",
    r".*\.key$",
]

# Executable extensions that are quarantined with execution restrictions
EXECUTABLE_EXTENSIONS = frozenset({
    ".exe", ".cmd", ".bat", ".ps1", ".vbs", ".js", ".msi", ".dll", ".com", ".scr", ".sh", ".bin"
})


@dataclass(frozen=True)
class QuarantinedDownload:
    quarantine_path: Path
    source_url: str
    sha256_hash: str
    size_bytes: int
    is_executable: bool
    is_archive: bool


@dataclass(frozen=True)
class UploadValidationResult:
    allowed: bool
    file_path: Path
    file_hash: str
    file_size_bytes: int
    destination_url: str
    reason: Optional[str] = None


class FileTransferSecurityManager:
    """
    Manages secure quarantine for downloaded artifacts and enforces authorization for uploads.
    """

    def __init__(
        self,
        quarantine_root: Optional[Path] = None,
        max_download_bytes: int = 50 * 1024 * 1024,  # 50 MB
        max_upload_bytes: int = 25 * 1024 * 1024,    # 25 MB
    ) -> None:
        self.quarantine_root = quarantine_root or (Path("bench-results") / "phase95_mcp_browser_security" / "quarantine")
        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        self.max_download_bytes = max_download_bytes
        self.max_upload_bytes = max_upload_bytes

    def quarantine_download(
        self,
        raw_bytes: bytes,
        filename: str,
        source_url: str,
    ) -> Tuple[bool, Optional[QuarantinedDownload], Optional[str]]:
        """
        Quarantine downloaded file bytes:
        - Checks size limits.
        - Calculates SHA-256 hash.
        - Identifies executable extensions.
        - Writes to isolated quarantine directory with safe permissions.
        """
        size = len(raw_bytes)
        if size > self.max_download_bytes:
            return False, None, f"Download exceeds size limit of {self.max_download_bytes} bytes (observed {size} bytes)."

        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        clean_name = os.path.basename(filename).replace("/", "_").replace("\\", "_")
        target_path = self.quarantine_root / f"{sha256[:12]}_{clean_name}"

        ext = target_path.suffix.lower()
        is_exec = ext in EXECUTABLE_EXTENSIONS
        is_archive = ext in (".zip", ".tar", ".gz", ".tgz")

        try:
            target_path.write_bytes(raw_bytes)
        except Exception as exc:
            return False, None, f"Failed to write quarantined file: {exc}"

        return True, QuarantinedDownload(
            quarantine_path=target_path,
            source_url=source_url,
            sha256_hash=sha256,
            size_bytes=size,
            is_executable=is_exec,
            is_archive=is_archive,
        ), None

    @classmethod
    def inspect_archive_safety(cls, archive_path: Path) -> Tuple[bool, Optional[str], List[str]]:
        """
        Inspect archive members to prevent Zip-Slip directory traversal attacks.
        Rejects paths containing '..' or absolute roots.
        """
        ext = archive_path.suffix.lower()
        flagged_members = []

        if ext == ".zip":
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for info in zf.infolist():
                        norm = os.path.normpath(info.filename)
                        if norm.startswith("..") or os.path.isabs(info.filename) or "/../" in info.filename:
                            flagged_members.append(info.filename)
            except Exception as exc:
                return False, f"Corrupted or invalid zip archive: {exc}", []
        elif ext in (".tar", ".gz", ".tgz"):
            try:
                with tarfile.open(archive_path, "r:*") as tf:
                    for member in tf.getmembers():
                        norm = os.path.normpath(member.name)
                        if norm.startswith("..") or os.path.isabs(member.name) or "/../" in member.name:
                            flagged_members.append(member.name)
            except Exception as exc:
                return False, f"Corrupted or invalid tar archive: {exc}", []

        if flagged_members:
            return False, f"Zip-Slip directory traversal detected in archive members: {flagged_members}", flagged_members

        return True, None, []

    def validate_upload_request(
        self,
        local_file_path: str,
        destination_url: str,
        workspace_root: str,
        user_confirmed: bool = False,
    ) -> UploadValidationResult:
        """
        Validate an upload request:
        1. Check user confirmation.
        2. Verify file exists and is within workspace.
        3. Block sensitive credential files (.env, .ssh, .git-credentials).
        4. Check upload size limits.
        """
        if not user_confirmed:
            return UploadValidationResult(
                allowed=False,
                file_path=Path(local_file_path),
                file_hash="",
                file_size_bytes=0,
                destination_url=destination_url,
                reason="Explicit user confirmation required before uploading workspace files.",
            )

        resolved_file = Path(local_file_path).resolve()
        if not resolved_file.exists() or not resolved_file.is_file():
            return UploadValidationResult(
                allowed=False,
                file_path=resolved_file,
                file_hash="",
                file_size_bytes=0,
                destination_url=destination_url,
                reason=f"Upload source file does not exist: {resolved_file}",
            )

        # Verify within workspace
        ws_resolved = Path(workspace_root).resolve()
        try:
            resolved_file.relative_to(ws_resolved)
        except ValueError:
            return UploadValidationResult(
                allowed=False,
                file_path=resolved_file,
                file_hash="",
                file_size_bytes=0,
                destination_url=destination_url,
                reason=f"Upload file '{resolved_file}' resides outside authorized workspace '{ws_resolved}'.",
            )

        # Check for sensitive credentials
        file_name_lower = resolved_file.name.lower()
        full_path_str = str(resolved_file).lower()
        import re
        for pat in PROHIBITED_UPLOAD_PATTERNS:
            if re.search(pat, file_name_lower) or re.search(pat, full_path_str):
                return UploadValidationResult(
                    allowed=False,
                    file_path=resolved_file,
                    file_hash="",
                    file_size_bytes=0,
                    destination_url=destination_url,
                    reason=f"Upload blocked: '{resolved_file.name}' matches sensitive secret/credential policy pattern: {pat}",
                )

        size = resolved_file.stat().st_size
        if size > self.max_upload_bytes:
            return UploadValidationResult(
                allowed=False,
                file_path=resolved_file,
                file_hash="",
                file_size_bytes=size,
                destination_url=destination_url,
                reason=f"Upload file size ({size} bytes) exceeds maximum limit of {self.max_upload_bytes} bytes.",
            )

        content = resolved_file.read_bytes()
        sha256 = hashlib.sha256(content).hexdigest()

        return UploadValidationResult(
            allowed=True,
            file_path=resolved_file,
            file_hash=sha256,
            file_size_bytes=size,
            destination_url=destination_url,
        )

