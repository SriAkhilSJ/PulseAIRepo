"""Process observability for the desktop acceptance harness (Windows-first).

Captures the real process facts a desktop acceptance run must be able to
prove: which executable was launched, under which PID, from which parent,
with which arguments, when it started and when/how it exited, and which
descendant processes (the Electron utility/gpu/renderer processes, and the
Python bridge the worker spawns) belong to it.

No process is invented: a missing descendant is reported as missing, never
synthesised.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    name: str
    command_line: str = ""
    created_at: str = ""
    executable: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "ppid": self.ppid,
            "name": self.name,
            "command_line": self.command_line,
            "created_at": self.created_at,
            "executable": self.executable,
        }


@dataclass
class ProcessTree:
    root: ProcessInfo | None = None
    descendants: list[ProcessInfo] = field(default_factory=list)
    captured_at: str = ""

    def find(self, needle: str) -> list[ProcessInfo]:
        needle = needle.lower()
        return [
            proc for proc in self.descendants
            if needle in proc.name.lower() or needle in proc.command_line.lower()
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root.to_dict() if self.root else None,
            "descendants": [proc.to_dict() for proc in self.descendants],
            "captured_at": self.captured_at,
        }


_WINDOWS_QUERY = (
    "Get-CimInstance Win32_Process | "
    "Select-Object ProcessId,ParentProcessId,Name,CommandLine,CreationDate,ExecutablePath | "
    "ConvertTo-Json -Compress"
)


def _capture_windows() -> list[ProcessInfo]:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_QUERY],
        capture_output=True,
        text=True,
        timeout=45,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"process query failed: {completed.stderr[:400]}")
    raw = completed.stdout.strip()
    if not raw:
        return []
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        parsed = [parsed]
    out: list[ProcessInfo] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        out.append(ProcessInfo(
            pid=int(item.get("ProcessId") or 0),
            ppid=int(item.get("ParentProcessId") or 0),
            name=str(item.get("Name") or ""),
            command_line=str(item.get("CommandLine") or ""),
            created_at=str(item.get("CreationDate") or ""),
            executable=str(item.get("ExecutablePath") or ""),
        ))
    return out


def _capture_posix() -> list[ProcessInfo]:
    completed = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,comm=,args="],
        capture_output=True,
        text=True,
        timeout=30,
    )
    out: list[ProcessInfo] = []
    for line in completed.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        out.append(ProcessInfo(
            pid=pid, ppid=ppid, name=parts[2],
            command_line=parts[3] if len(parts) > 3 else "",
        ))
    return out


def snapshot_processes() -> list[ProcessInfo]:
    if sys.platform == "win32":
        return _capture_windows()
    return _capture_posix()


def collect_tree(root_pid: int) -> ProcessTree:
    """Collect the root process and every transitive descendant."""
    procs = snapshot_processes()
    by_pid = {proc.pid: proc for proc in procs}
    children: dict[int, list[ProcessInfo]] = {}
    for proc in procs:
        children.setdefault(proc.ppid, []).append(proc)

    root = by_pid.get(root_pid)
    descendants: list[ProcessInfo] = []
    frontier = [root_pid]
    seen = {root_pid}
    while frontier:
        parent = frontier.pop()
        for child in children.get(parent, []):
            if child.pid in seen:
                continue
            seen.add(child.pid)
            descendants.append(child)
            frontier.append(child.pid)
    return ProcessTree(root=root, descendants=descendants, captured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def listening_sockets(port: int) -> list[dict[str, Any]]:
    """Return the actual listeners on ``port`` (address + owning PID).

    Used to PROVE that remote debugging is bound to loopback only — a harness
    that merely passes ``--remote-debugging-port`` proves nothing about the
    bind address the OS ended up with.
    """
    if sys.platform != "win32":
        try:
            completed = subprocess.run(
                ["ss", "-lntp"], capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        out = []
        for line in completed.stdout.splitlines():
            if f":{port}" not in line:
                continue
            fields = line.split()
            if len(fields) >= 4:
                out.append({"local_address": fields[3], "raw": line.strip()})
        return out

    query = (
        f"Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue | "
        "Select-Object LocalAddress,LocalPort,OwningProcess | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
        capture_output=True, text=True, timeout=45,
    )
    raw = completed.stdout.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        parsed = [parsed]
    out = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        out.append({
            "local_address": str(item.get("LocalAddress") or ""),
            "local_port": int(item.get("LocalPort") or 0),
            "owning_pid": int(item.get("OwningProcess") or 0),
        })
    return out


def is_loopback_bind(address: str) -> bool:
    address = (address or "").strip().strip("[]").lower()
    return address in {"127.0.0.1", "::1", "localhost"}


def read_pe_version(exe: str | os.PathLike[str]) -> dict[str, str]:
    """Best-effort product version/company from the Windows image itself."""
    path = Path(exe)
    if not path.exists():
        return {}
    try:
        completed = subprocess.run(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                f"(Get-Item -LiteralPath '{path}').VersionInfo | "
                "Select-Object FileVersion,ProductVersion,CompanyName,FileDescription | ConvertTo-Json -Compress",
            ],
            capture_output=True, text=True, timeout=45,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return {}
        parsed = json.loads(completed.stdout.strip())
        return {str(k): str(v) for k, v in parsed.items() if v}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}
