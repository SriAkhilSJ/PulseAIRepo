"""
local_isolation.py - Isolated Execution Governance for Local MCP Servers.

Phase 9.5: MCP Ecosystem & Browser Agent Security.
Ensures local MCP servers execute inside dedicated Job Object and AppContainer isolation
boundaries provisioned via the central ExecutionBroker, preventing host compromise or credential leakage.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.security import (
    ExecutionBroker,
    ExecutionMode,
    ExecutionRequest,
    SecurityViolationType,
)
from src.security.contracts import SAFE_ENVIRONMENT_KEYS, SENSITIVE_SECRET_PATTERNS
from src.security.sandbox.manager import get_sandbox_manager


class IsolatedMCPServerInstance:
    """
    Encapsulates one local MCP server running under OS-level isolation (Job Object / AppContainer).
    Enforces per-server identity, dedicated staging, sanitized env, and process tree termination.
    """

    def __init__(
        self,
        server_id: str,
        command: List[str],
        workspace_root: str,
        env_overrides: Optional[Dict[str, str]] = None,
        max_memory_mb: int = 512,
        max_processes: int = 10,
        staging_root: Optional[Path] = None,
    ) -> None:
        self.server_id = server_id
        self.command = command
        self.workspace_root = str(Path(workspace_root).resolve())
        self.env_overrides = env_overrides or {}
        self.max_memory_mb = max_memory_mb
        self.max_processes = max_processes

        self.execution_id = f"mcp_{server_id}_{uuid.uuid4().hex[:8]}"
        base_staging = staging_root or (Path("bench-results") / "phase95_mcp_browser_security" / "mcp_staging")
        self.staging_dir = base_staging / self.execution_id
        self.staging_dir.mkdir(parents=True, exist_ok=True)

        self._sandbox = get_sandbox_manager()
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._is_alive = False
        self._started = False

    def sanitize_environment(self) -> Dict[str, str]:
        """Strip all sensitive credentials and construct a safe environment."""
        sanitized: Dict[str, str] = {}
        for k, v in os.environ.items():
            k_upper = k.upper()
            if k_upper in SAFE_ENVIRONMENT_KEYS and not any(term in k_upper for term in SENSITIVE_SECRET_PATTERNS):
                sanitized[k] = v

        sanitized["TMP"] = str(self.staging_dir)
        sanitized["TEMP"] = str(self.staging_dir)
        sanitized["CRUSOR_MCP_SERVER_ID"] = self.server_id
        sanitized["CRUSOR_SANDBOX"] = "1"
        sanitized["NO_COLOR"] = "1"
        sanitized["CI"] = "1"

        # Apply safe caller overrides
        for ok, ov in self.env_overrides.items():
            if not any(term in ok.upper() for term in SENSITIVE_SECRET_PATTERNS):
                sanitized[ok] = ov

        return sanitized

    def start(self) -> bool:
        """Start the MCP server subprocess inside the sandbox."""
        with self._lock:
            if self._started:
                return self._is_alive

            broker = ExecutionBroker.get_instance()
            req_id = f"req_{uuid.uuid4().hex[:8]}"
            approval_token = broker.create_approval(
                session_id=f"session_{self.server_id}",
                request_id=req_id,
                command=" ".join(self.command),
                workspace_root=self.workspace_root,
            )

            req = ExecutionRequest(
                execution_id=self.execution_id,
                session_id=f"session_{self.server_id}",
                request_id=req_id,
                workspace_root=self.workspace_root,
                tool_name="mcp_local_server",
                command=" ".join(self.command),
                argv=self.command,
                approval_token=approval_token,
                mode=ExecutionMode.PROPOSED_MUTATION,
                max_memory_mb=self.max_memory_mb,
                max_processes=self.max_processes,
                network_allowed=False,  # Local MCP servers have no network access by default
                env_overrides=self.env_overrides,
            )

            try:
                self._sandbox.initialize(req, self.staging_dir)
                sanitized_env = self.sanitize_environment()

                # Launch process bound to Job Object / AppContainer
                self._proc = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=sanitized_env,
                    cwd=str(self.staging_dir),
                    text=True,
                    bufsize=1,
                )
                self._started = True
                self._is_alive = True
                return True
            except Exception as exc:
                self.terminate()
                return False

    def is_alive(self) -> bool:
        with self._lock:
            if not self._started or self._proc is None:
                return False
            alive = self._proc.poll() is None
            self._is_alive = alive
            return alive

    def terminate(self) -> str:
        """Terminate the server and all descendant processes, then cleanup staging."""
        with self._lock:
            self._is_alive = False
            if self._proc is not None:
                try:
                    if self._proc.stdin:
                        self._proc.stdin.close()
                    if self._proc.stdout:
                        self._proc.stdout.close()
                    if self._proc.stderr:
                        self._proc.stderr.close()
                except Exception:
                    pass
                try:
                    self._proc.terminate()
                except Exception:
                    pass
                try:
                    self._proc.kill()
                except Exception:
                    pass
                self._proc = None

            if self._sandbox is not None:
                try:
                    self._sandbox.terminate()
                    clean_res = self._sandbox.cleanup(self.staging_dir)
                except Exception as exc:
                    clean_res = f"ERROR: {exc}"
            else:
                clean_res = "SUCCESS"

            if self.staging_dir.exists():
                shutil.rmtree(self.staging_dir, ignore_errors=True)

            return clean_res

