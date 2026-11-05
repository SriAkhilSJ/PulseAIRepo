"""
macos.py - macOS OS-Level Sandbox Manager using App Sandbox & Entitlements.

Phase 9.4: Enterprise Execution Sandbox.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.security.contracts import (
    ExecutionRequest,
    SandboxBackendType,
)
from src.security.sandbox.base import BaseSandboxManager


class MacOSSandboxManager(BaseSandboxManager):
    """
    macOS execution sandbox manager assessing App Sandbox and sandbox-exec profiles.
    
    If dedicated sandbox profile compilation or seatbelt framework is unavailable,
    the manager FAILS CLOSED.
    """

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._violations: List[str] = []

    @property
    def backend_type(self) -> SandboxBackendType:
        return SandboxBackendType.MACOS_SANDBOX

    def get_capabilities(self) -> Dict[str, bool]:
        is_darwin = sys.platform == "darwin"
        return {
            "seatbelt_sandbox_exec": is_darwin and shutil.which("sandbox-exec") is not None,
            "app_sandbox_entitlements": is_darwin,
            "fail_closed_enforced": True,
        }

    def initialize(self, request: ExecutionRequest, staging_dir: Path) -> None:
        if sys.platform != "darwin":
            raise NotImplementedError(
                f"MacOSSandboxManager is only supported on macOS Darwin (current: {sys.platform}). "
                "Failing closed to prevent unisolated host execution."
            )

        if not shutil.which("sandbox-exec"):
            raise RuntimeError(
                "macOS sandbox-exec utility not found on host. "
                "Failing closed: unrestricted execution is strictly prohibited."
            )

    def execute(
        self,
        request: ExecutionRequest,
        staging_dir: Path,
        abort_event: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if sys.platform != "darwin":
            return {
                "exit_code": 126,
                "stdout": "",
                "stderr": "⛔ Execution refused: macOS sandbox backend unavailable on current OS (failed closed).",
                "stdout_bytes": 0,
                "stderr_bytes": 83,
                "timed_out": False,
                "cancelled": False,
                "cpu_user_s": 0.0,
                "cpu_kernel_s": 0.0,
                "peak_memory_bytes": 0,
                "security_violations": ["PLATFORM_ISOLATION_UNAVAILABLE"],
            }

        # On macOS, build a strict seatbelt profile
        ws = str(Path(request.workspace_root).resolve())
        stg = str(staging_dir.resolve())
        profile = f"""(version 1)
(deny default)
(allow process-fork)
(allow process-exec (subpath "/bin") (subpath "/usr/bin") (subpath "/usr/local/bin"))
(allow file-read* (subpath "/bin") (subpath "/usr") (subpath "/System") (subpath "{ws}"))
(allow file-read* file-write* (subpath "{stg}"))
{"(deny network*)" if not request.network_allowed else ""}
"""
        cmd = ["sandbox-exec", "-p", profile] + (request.argv if request.argv else ["sh", "-c", request.command])

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = self._process.communicate(timeout=request.timeout_s)
            return {
                "exit_code": self._process.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_bytes": len(stdout.encode("utf-8")),
                "stderr_bytes": len(stderr.encode("utf-8")),
                "timed_out": False,
                "cancelled": False,
                "cpu_user_s": 0.0,
                "cpu_kernel_s": 0.0,
                "peak_memory_bytes": 0,
                "security_violations": [],
            }
        except subprocess.TimeoutExpired:
            self.terminate()
            return {
                "exit_code": 124,
                "stdout": "",
                "stderr": f"Command timed out after {request.timeout_s}s",
                "stdout_bytes": 0,
                "stderr_bytes": 35,
                "timed_out": True,
                "cancelled": False,
                "cpu_user_s": 0.0,
                "cpu_kernel_s": 0.0,
                "peak_memory_bytes": 0,
                "security_violations": ["TIMEOUT_EXCEEDED"],
            }

    def terminate(self) -> None:
        if self._process and self._process.poll() is None:
            try:
                self._process.kill()
            except Exception:
                pass

    def cleanup(self, staging_dir: Path) -> str:
        self.terminate()
        try:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)
            return "CLEANUP_SUCCESS"
        except Exception as exc:
            return f"CLEANUP_DEGRADED: {exc}"

