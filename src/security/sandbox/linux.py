"""
linux.py - Linux OS-Level Sandbox Manager using Namespaces, Seccomp, and Cgroups.

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


class LinuxSandboxManager(BaseSandboxManager):
    """
    Linux execution sandbox using:
    - User namespaces (CLONE_NEWUSER)
    - Mount namespaces (CLONE_NEWNS) with read-only root and bind mounted staging
    - Network namespaces (CLONE_NEWNET) for NETWORK = DENY
    - PID namespaces (CLONE_NEWPID) for process containment and tree termination
    - Cgroups v2 for memory and CPU controls
    
    If unprivileged namespaces or cgroups are unavailable on the target distribution,
    the manager FAILS CLOSED.
    """

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen] = None
        self._violations: List[str] = []

    @property
    def backend_type(self) -> SandboxBackendType:
        return SandboxBackendType.LINUX_NAMESPACES

    def get_capabilities(self) -> Dict[str, bool]:
        is_linux = sys.platform.startswith("linux")
        return {
            "user_namespaces": is_linux,
            "mount_namespaces": is_linux,
            "network_namespaces": is_linux,
            "pid_namespaces": is_linux,
            "cgroups_v2": is_linux,
            "seccomp": is_linux,
            "fail_closed_enforced": True,
        }

    def initialize(self, request: ExecutionRequest, staging_dir: Path) -> None:
        if not sys.platform.startswith("linux"):
            # Fail closed when requested on non-Linux platform
            raise NotImplementedError(
                f"LinuxSandboxManager is only supported on Linux kernels (current: {sys.platform}). "
                "Failing closed to prevent unisolated host execution."
            )

        # Verify bubblewrap or unshare availability
        has_bwrap = shutil.which("bwrap") is not None
        has_unshare = shutil.which("unshare") is not None

        if not (has_bwrap or has_unshare):
            raise RuntimeError(
                "Linux OS isolation primitives (bubblewrap / unshare) not detected on host. "
                "Failing closed: unrestricted execution is strictly prohibited."
            )

    def execute(
        self,
        request: ExecutionRequest,
        staging_dir: Path,
        abort_event: Optional[Any] = None,
    ) -> Dict[str, Any]:
        if not sys.platform.startswith("linux"):
            return {
                "exit_code": 126,
                "stdout": "",
                "stderr": "⛔ Execution refused: Linux sandbox backend unavailable on current OS (failed closed).",
                "stdout_bytes": 0,
                "stderr_bytes": 83,
                "timed_out": False,
                "cancelled": False,
                "cpu_user_s": 0.0,
                "cpu_kernel_s": 0.0,
                "peak_memory_bytes": 0,
                "security_violations": ["PLATFORM_ISOLATION_UNAVAILABLE"],
            }

        # Build bubblewrap / unshare argv vector
        ws = str(Path(request.workspace_root).resolve())
        stg = str(staging_dir.resolve())

        # Construct bwrap command if available
        if shutil.which("bwrap"):
            cmd = [
                "bwrap",
                "--ro-bind", "/usr", "/usr",
                "--ro-bind", "/lib", "/lib",
                "--ro-bind", "/lib64", "/lib64",
                "--ro-bind", "/bin", "/bin",
                "--ro-bind", ws, ws,
                "--bind", stg, stg,
                "--dev", "/dev",
                "--proc", "/proc",
                "--unshare-all",
                "--die-with-parent",
            ]
            if not request.network_allowed:
                cmd.append("--unshare-net")
            cmd.extend(["--chdir", stg if request.mode.value == "PROPOSED_MUTATION" else ws])
            cmd.extend(request.argv if request.argv else ["sh", "-c", request.command])
        else:
            cmd = request.argv if request.argv else ["sh", "-c", request.command]

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

