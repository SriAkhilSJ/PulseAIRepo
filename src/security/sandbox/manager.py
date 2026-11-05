"""
manager.py - Factory for Platform-Specific Sandbox Managers.

Phase 9.4: Enterprise Execution Sandbox.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from src.security.contracts import SandboxBackendType
from src.security.sandbox.base import BaseSandboxManager
from src.security.sandbox.linux import LinuxSandboxManager
from src.security.sandbox.macos import MacOSSandboxManager
from src.security.sandbox.windows import WindowsSandboxManager


def get_sandbox_manager(
    platform_name: Optional[str] = None,
    use_appcontainer: Optional[bool] = None,
) -> BaseSandboxManager:
    """Return the authoritative OS-level sandbox manager for the current or specified platform."""
    plat = (platform_name or sys.platform).lower()

    if plat.startswith("win"):
        if use_appcontainer is None:
            flag = os.environ.get("CRUSOR_ENABLE_APPCONTAINER", "1").lower()
            use_ac = flag not in ("0", "false", "no")
        else:
            use_ac = use_appcontainer
        return WindowsSandboxManager(use_appcontainer=use_ac)
    elif plat.startswith("linux"):
        return LinuxSandboxManager()
    elif plat == "darwin":
        return MacOSSandboxManager()
    else:
        # Unsupported platform: return a fail-closed manager
        raise NotImplementedError(
            f"Unsupported operating system '{plat}' for enterprise sandbox isolation. "
            "Crusor AI IDE fails closed: unrestricted execution is strictly forbidden."
        )

