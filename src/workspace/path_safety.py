"""
src/workspace/path_safety.py - Path and Workspace Boundary Security.

Phase 11.3: Workspace Discipline & Change Management.
Implements fail-closed path normalization and containment verification on Windows.
Defends against:
- `../` directory traversal
- Absolute path escaping and root escape
- Windows drive switching (e.g. C: vs D:)
- UNC network paths (\\\\server\\share)
- Symlink and junction escape outside authorized workspace
- Windows Alternate Data Streams (file:stream)
- DOS device reserved names (CON, PRN, AUX, NUL, COM1..9, LPT1..9)
- Case-insensitive path collision and path representation anomalies
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, Union

# Reserved MS-DOS device names on Windows (case-insensitive)
RESERVED_DEVICE_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
})

# Forbidden sensitive file or directory names that cannot be mutated
SENSITIVE_TARGETS = frozenset({
    ".git", ".env", ".ssh", ".aws", ".gnupg", "id_rsa", "id_ed25519", "credentials.json",
})


class PathSecurityViolation(ValueError):
    """Raised when an operation attempts to access or mutate an unauthorized path."""
    pass


class PathSafetyValidator:
    """
    Deterministic path containment and safety validator.
    Ensures all file operations remain strictly confined to the authorized workspace root.
    """

    @staticmethod
    def is_dos_device_name(filename: str) -> bool:
        """Check if any path component is a reserved Windows/DOS device name."""
        stem = Path(filename).stem.upper()
        name = Path(filename).name.upper()
        return stem in RESERVED_DEVICE_NAMES or name in RESERVED_DEVICE_NAMES

    @staticmethod
    def contains_alternate_data_stream(path_str: str) -> bool:
        """Check if path targets a Windows Alternate Data Stream (e.g., file.txt:hidden)."""
        # On Windows, drive letters like C:\ are valid, but subsequent colons indicate ADS
        # Strip drive letter if present
        clean = path_str
        if len(clean) >= 2 and clean[1] == ":" and clean[0].isalpha():
            clean = clean[2:]
        return ":" in clean

    @classmethod
    def resolve_and_verify(
        cls,
        workspace_root: Union[str, Path],
        requested_path: Union[str, Path],
        allow_symlinks_within_workspace: bool = True,
    ) -> Path:
        """
        Normalize and securely resolve a path within the authorized workspace.
        Raises PathSecurityViolation on any violation.
        """
        if not workspace_root:
            raise PathSecurityViolation("⛔ Missing or empty workspace root.")

        ws_path = Path(workspace_root).resolve()
        if not ws_path.exists():
            # Workspace root itself must exist
            try:
                ws_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                raise PathSecurityViolation(f"⛔ Workspace root cannot be accessed: {e}")

        req_str = str(requested_path).strip()
        if not req_str:
            raise PathSecurityViolation("⛔ Target path must be a non-empty string.")

        # 1. Defend against Windows UNC network paths
        if req_str.startswith("\\\\") or req_str.startswith("//"):
            raise PathSecurityViolation(f"⛔ UNC network paths prohibited: '{req_str}'")

        # 2. Defend against Windows Alternate Data Streams (ADS)
        if cls.contains_alternate_data_stream(req_str):
            raise PathSecurityViolation(f"⛔ Alternate Data Streams (ADS) prohibited: '{req_str}'")

        # 3. Defend against DOS device names and sensitive targets
        p_obj = Path(req_str)
        for part in p_obj.parts:
            if cls.is_dos_device_name(part):
                raise PathSecurityViolation(f"⛔ Reserved Windows device name prohibited: '{part}'")
            part_lower = part.lower()
            if part_lower in SENSITIVE_TARGETS or part_lower.startswith(".env"):
                raise PathSecurityViolation(f"⛔ Sensitive path prohibited: '{part}'")

        # 4. Resolve path relative to workspace
        if p_obj.is_absolute():
            # If absolute, it must reside on the same drive and resolve strictly inside workspace
            try:
                resolved = p_obj.resolve()
            except Exception as e:
                raise PathSecurityViolation(f"⛔ Path cannot be resolved: {e}")
        else:
            # Model may prefix with workspace basename; strip redundant prefix if present
            parts = p_obj.parts
            if parts and parts[0] == ws_path.name:
                p_obj = Path(*parts[1:])
            resolved = (ws_path / p_obj).resolve()

        # 5. Check drive letter match on Windows
        if sys.platform == "win32":
            ws_drive = ws_path.drive.upper()
            res_drive = resolved.drive.upper()
            if ws_drive and res_drive and ws_drive != res_drive:
                raise PathSecurityViolation(
                    f"⛔ Windows drive mismatch: requested drive '{res_drive}' differs from workspace '{ws_drive}'"
                )

        # 6. Verify strictly relative to workspace root (case-insensitive comparison on Windows)
        try:
            if sys.platform == "win32":
                # Windows is case-insensitive: compare lowercase resolved strings
                ws_str = str(ws_path).lower()
                res_str = str(resolved).lower()
                if not (res_str == ws_str or res_str.startswith(ws_str + os.sep) or res_str.startswith(ws_str + "/")):
                    raise PathSecurityViolation(
                        f"⛔ Path escapes workspace root: '{resolved}' is outside '{ws_path}'"
                    )
            else:
                resolved.relative_to(ws_path)
        except ValueError:
            raise PathSecurityViolation(
                f"⛔ Path escapes workspace root: '{resolved}' is outside '{ws_path}'"
            )

        # 7. Symlink and junction inspection
        # If target or any parent is a symlink/reparse point, ensure target resolves within workspace
        curr = resolved
        while curr != ws_path and curr != curr.parent:
            if curr.is_symlink():
                try:
                    sym_target = curr.resolve()
                    if sys.platform == "win32":
                        sym_target_str = str(sym_target).lower()
                        if not (sym_target_str == str(ws_path).lower() or sym_target_str.startswith(str(ws_path).lower() + os.sep)):
                            raise PathSecurityViolation(f"⛔ Symlink points outside workspace: '{curr}' -> '{sym_target}'")
                    else:
                        sym_target.relative_to(ws_path)
                except (ValueError, RuntimeError):
                    raise PathSecurityViolation(f"⛔ Symlink traversal escape: '{curr}'")
            curr = curr.parent

        return resolved

    @classmethod
    def get_relative_normalized(cls, workspace_root: Union[str, Path], resolved_path: Path) -> str:
        """Get forward-slash normalized relative path string."""
        ws = Path(workspace_root).resolve()
        try:
            rel = resolved_path.relative_to(ws)
            return str(rel).replace("\\", "/")
        except ValueError:
            # On Windows with different case, derive manually
            ws_str = str(ws)
            res_str = str(resolved_path)
            if res_str.lower().startswith(ws_str.lower()):
                suffix = res_str[len(ws_str):].lstrip("\\/")
                return suffix.replace("\\", "/")
            return str(resolved_path).replace("\\", "/")
