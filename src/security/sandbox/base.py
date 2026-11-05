"""
base.py - Abstract Base Class for OS-Level Sandbox Managers.

Phase 9.4: Enterprise Execution Sandbox.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.security.contracts import ExecutionRequest, SandboxBackendType


class BaseSandboxManager(abc.ABC):
    """Abstract interface implemented by OS-specific sandbox managers."""

    @property
    @abc.abstractmethod
    def backend_type(self) -> SandboxBackendType:
        """Return the concrete sandbox backend type."""
        pass

    @abc.abstractmethod
    def initialize(self, request: ExecutionRequest, staging_dir: Path) -> None:
        """Prepare the sandbox environment, resource controls, and staging."""
        pass

    @abc.abstractmethod
    def execute(
        self,
        request: ExecutionRequest,
        staging_dir: Path,
        abort_event: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Execute the target command inside the OS-isolated sandbox.
        
        Returns a dictionary containing:
        - exit_code: int
        - stdout: str
        - stderr: str
        - stdout_bytes: int
        - stderr_bytes: int
        - timed_out: bool
        - cancelled: bool
        - cpu_user_s: float
        - cpu_kernel_s: float
        - peak_memory_bytes: int
        - security_violations: List[str]
        """
        pass

    @abc.abstractmethod
    def terminate(self) -> None:
        """Forcefully terminate the complete process tree inside the sandbox."""
        pass

    @abc.abstractmethod
    def cleanup(self, staging_dir: Path) -> str:
        """Clean up all sandbox handles, temporary staging files, and resources."""
        pass

    @abc.abstractmethod
    def get_capabilities(self) -> Dict[str, bool]:
        """Return a mapping of supported isolation primitives on this platform."""
        pass

