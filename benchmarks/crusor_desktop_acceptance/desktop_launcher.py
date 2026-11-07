"""Launch and identify the real Crusor Electron application.

The launcher mirrors the repository's own dev launch (``desktop/vscode/scripts/code.bat``):
the Electron binary from ``.build/electron/<nameShort>.exe`` invoked with the
workbench folder, with ``VSCODE_DEV`` set so the compiled ``out/`` tree is the
running workbench — never a packaged substitute and never a plain browser.

Every fact recorded here comes from the OS or the binary itself: executable
path and hash, PID/PPID, image version, launch arguments, start/exit
timestamps, exit code, and the actual loopback listener that owns the
debugging port.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from benchmarks.crusor_desktop_acceptance.processes import (
    collect_tree,
    is_loopback_bind,
    listening_sockets,
    read_pe_version,
)


class LaunchError(RuntimeError):
    pass


def allocate_loopback_port() -> int:
    """Pick a free loopback TCP port for this launch (dynamic debugging port)."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def prepare_portable_profile(portable_dir: str | Path, port: int) -> Path:
    """Create an acceptance-owned portable profile whose argv.json names ``port``.

    Why this exists: VS Code reads a *per-user* ``argv.json`` from
    ``~/<product.dataFolderName>[-dev]/argv.json`` and re-applies every
    supported Electron switch from it with ``app.commandLine.appendSwitch``.
    A stale entry like ``"remote-debugging-port": "9222"`` therefore overrides
    whatever ``--remote-debugging-port`` the launcher passes — which is exactly
    the forced-port bug this milestone resolves.

    ``VSCODE_PORTABLE`` is the supported redirection: when it points at an
    existing directory, ``getArgvConfigPath()`` reads ``<dir>/argv.json`` from
    there instead of the user's home. The harness owns that file, so the port
    is the one it chose, and the user's real profile is never modified.
    """
    target = Path(portable_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    (target / "argv.json").write_text(
        json.dumps(
            {"enable-crash-reporter": False, "remote-debugging-port": str(int(port))},
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return target


def read_argv_config_override() -> dict[str, Any]:
    """Report the per-user argv.json that VS Code would apply (read-only)."""
    import os as _os

    product = read_product(Path(__file__).resolve().parents[2] / "desktop" / "vscode")
    folder = str(product.get("dataFolderName") or "")
    candidates = []
    if folder:
        candidates.append(Path(_os.path.expanduser("~")) / f"{folder}-dev" / "argv.json")
        candidates.append(Path(_os.path.expanduser("~")) / folder / "argv.json")
    out: dict[str, Any] = {"candidates": [str(c) for c in candidates]}
    for candidate in candidates:
        if candidate.exists():
            try:
                out["found"] = str(candidate)
                out["content"] = json.loads(
                    candidate.read_text(encoding="utf-8").replace("\t", " ")
                )
            except (OSError, json.JSONDecodeError):
                out["found"] = str(candidate)
                out["content"] = "(unparseable)"
            break
    return out


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_product(vscode_root: Path) -> dict[str, Any]:
    product_path = vscode_root / "product.json"
    if not product_path.exists():
        return {}
    try:
        data = json.loads(product_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {
        key: data.get(key)
        for key in ("nameShort", "nameLong", "applicationName", "dataFolderName",
                    "version", "commit", "quality")
    }


def read_build_info(vscode_root: Path) -> dict[str, Any]:
    path = vscode_root / "out" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "BUILD_INFO.json"
    if not path.exists():
        return {"present": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"present": True, "parsed": False}
    return {"present": True, "parsed": True, **data}


def resolve_electron_binary(vscode_root: Path) -> Path:
    product = read_product(vscode_root)
    name_short = str(product.get("nameShort") or "CrusorAI")
    candidates = [
        vscode_root / ".build" / "electron" / f"{name_short}.exe",
        vscode_root / ".build" / "electron" / "CrusorAI.exe",
        vscode_root / "node_modules" / "electron" / "dist" / "electron.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise LaunchError(
        f"no Crusor Electron binary found under {vscode_root / '.build' / 'electron'} "
        "(build it with `npm run compile` / the repository's preLaunch step)"
    )


@dataclass
class LaunchedApp:
    exe: Path
    pid: int
    args: list[str]
    env_keys: list[str]
    workspace: str
    port: int
    user_data_dir: str
    started_at: float
    process: subprocess.Popen = field(repr=False, default=None)  # type: ignore[assignment]
    stdout_path: str = ""
    stderr_path: str = ""
    scrubbed_env_keys: list[str] = field(default_factory=list)
    portable_dir: str = ""

    @property
    def effective_user_data_dir(self) -> str:
        """Where Chromium actually writes ``DevToolsActivePort``.

        Portable mode (``VSCODE_PORTABLE``) owns the profile: VS Code puts it
        at ``<portable>/user-data`` and ignores ``--user-data-dir``.
        """
        if self.portable_dir:
            return str(Path(self.portable_dir) / "user-data")
        return self.user_data_dir

    def to_dict(self) -> dict[str, Any]:
        return {
            "executable": str(self.exe),
            "executable_sha256": sha256_file(self.exe) if self.exe.exists() else "",
            "pid": self.pid,
            "args": self.args,
            "env_keys": self.env_keys,
            "scrubbed_env_keys": self.scrubbed_env_keys,
            "workspace": self.workspace,
            "debug_port": self.port,
            "portable_dir": self.portable_dir,
            "user_data_dir": self.user_data_dir,
            "effective_user_data_dir": self.effective_user_data_dir,
            "started_at": self.started_at,
            "stdout_log": self.stdout_path,
            "stderr_log": self.stderr_path,
        }


def build_launch_environment(*, user_data_dir: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Reproduce the repo's dev launch environment, plus profile isolation.

    The environment is SCRUBBED of:

    * ``ELECTRON_RUN_AS_NODE`` and the VS Code IPC hooks inherited from a
      parent VS Code window — leaving them set makes the Electron binary behave
      like a headless Node/IPC child, so no window (and no debugging page)
      appears;
    * every proxy variable. ``windowImpl.onConfigurationUpdated`` calls
      ``webContents.session.setProxy(...)`` whenever ``http.noProxy`` or a proxy
      env var is present. On this build (Electron 42.8.1) that call throws
      ``session.setProxy is not a function`` during the ``BrowserWindow``
      constructor and the whole app exits with code 1. Scrub the variables so
      the proxy branch is not entered; loopback traffic needs no proxy.
    """
    env = dict(os.environ)
    for inherited in (
        "ELECTRON_RUN_AS_NODE",
        "VSCODE_ESM_ENTRYPOINT",
        "VSCODE_IPC_HOOK",
        "VSCODE_PID",
        "VSCODE_CRASH_REPORTER_PROCESS_TYPE",
        "VSCODE_CLI",
        # Proxy variables: see the docstring. NO_PROXY alone is enough to
        # trigger the crashing branch.
        "NO_PROXY",
        "no_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        env.pop(inherited, None)
    env.update({
        "NODE_ENV": "development",
        "VSCODE_DEV": "1",
        "CRUSORAI_DEV": "1",
        "ELECTRON_ENABLE_LOGGING": "1",
        "ELECTRON_ENABLE_STACK_DUMPING": "1",
        "VSCODE_SKIP_PRELAUNCH": "1",  # the harness launches an already-compiled tree
    })
    if extra:
        env.update(extra)
    return env


def launch_app(
    *,
    vscode_root: Path,
    workspace: Path,
    port: int,
    logs_dir: Path,
    user_data_dir: Path,
    portable_dir: Path | None = None,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> LaunchedApp:
    """Start the real desktop app and hand back its live handle."""
    exe = resolve_electron_binary(vscode_root)
    workspace.mkdir(parents=True, exist_ok=True)
    user_data_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    if portable_dir is not None:
        prepare_portable_profile(portable_dir, port)

    args = [
        str(exe),
        # Dev launch, exactly like desktop/vscode/scripts/code.bat: the FIRST
        # positional argument is the Electron APP path (the workbench tree that
        # owns package.json -> out/main.js). Passing the user folder here
        # instead made Electron try to "find the app" in the workspace and
        # abort with "Cannot find module".
        str(vscode_root),
        str(workspace),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--remote-allow-origins=http://127.0.0.1",
        "--enable-logging",
        "--disable-gpu",
        # The repository's own desktop acceptance scripts
        # (scripts/test_phase_9_3_4_2_runtime_e2e.py,
        # scripts/test_desktop_playwright_acceptance.py) pass --no-sandbox.
        # Without it the renderer process does not attach under this account
        # (Administrator token on Windows): the window exists, /json/list stays
        # empty and main.log shows IPC events buffered forever.
        "--no-sandbox",
        "--skip-welcome",
        "--skip-release-notes",
        "--disable-telemetry",
        "--disable-crash-reporter",
    ]
    if extra_args:
        args.extend(extra_args)

    env = build_launch_environment(user_data_dir=str(user_data_dir), extra=extra_env)
    if portable_dir is not None:
        env["VSCODE_PORTABLE"] = str(portable_dir)
    stdout_path = logs_dir / "electron.stdout.log"
    stderr_path = logs_dir / "electron.stderr.log"
    stdout_handle = stdout_path.open("wb")
    stderr_handle = stderr_path.open("wb")
    started_at = time.time()
    process = subprocess.Popen(
        args,
        cwd=str(vscode_root),
        env=env,
        stdout=stdout_handle,
        stderr=stderr_handle,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,  # type: ignore[attr-defined]
    )
    # The file handles stay open for the child's lifetime; the OS keeps them.
    env_keys = sorted(
        key for key in ("NODE_ENV", "VSCODE_DEV", "VSCODE_CLI", "ELECTRON_ENABLE_LOGGING",
                        "VSCODE_SKIP_PRELAUNCH", "CRUSORAI_ENGINE_ROOT", "CRUSORAI_PYTHON_PATH")
        if key in env
    )
    scrubbed = sorted(
        key for key in ("ELECTRON_RUN_AS_NODE", "NO_PROXY", "no_proxy", "HTTP_PROXY",
                        "HTTPS_PROXY", "http_proxy", "https_proxy")
        if key in os.environ and key not in env
    )
    return LaunchedApp(
        exe=exe,
        pid=process.pid,
        args=args,
        env_keys=env_keys,
        workspace=str(workspace),
        port=port,
        user_data_dir=str(user_data_dir),
        started_at=started_at,
        process=process,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        scrubbed_env_keys=scrubbed,
        portable_dir=str(portable_dir) if portable_dir is not None else "",
    )


def scan_stderr_for_devtools(path: str | Path, *, since: float = 0.0) -> dict[str, Any] | None:
    """Read the app's OWN stderr for the DevTools endpoint it actually bound.

    Electron/Chromium prints ``DevTools listening on ws://127.0.0.1:<port>/…``
    once the debugging server is up. That line is ground truth, so the harness
    records the port the app really used instead of trusting its own argument
    (VS Code re-applies ``remote-debugging-port`` from the per-user argv.json,
    which is why a stale ``9222`` used to win — see ``prepare_portable_profile``).
    """
    log_path = Path(path)
    if not log_path.exists():
        return None
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r"DevTools listening on (ws://[^\s]+)", text)
    if not match:
        return None
    ws_url = match.group(1)
    parsed = urlparse(ws_url)
    return {
        "ws_url": ws_url,
        "port": parsed.port,
        "host": parsed.hostname,
        "loopback": (parsed.hostname or "") in {"127.0.0.1", "localhost", "::1"},
        "source": "electron_stderr",
    }


def read_devtools_active_port(user_data_dir: str | Path) -> dict[str, Any] | None:
    """Read Chromium's ``DevToolsActivePort`` file from the profile.

    Chromium writes ``<port>`` and ``/devtools/browser/<id>`` here once the
    debugging server is up. It is the second independent source (besides the
    app's stderr) for the port the build ACTUALLY bound, and it survives the
    app crashing right afterwards.
    """
    path = Path(user_data_dir) / "DevToolsActivePort"
    if not path.exists():
        return None
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    if not lines:
        return None
    try:
        port = int(lines[0])
    except ValueError:
        return None
    return {
        "port": port,
        "browser_path": lines[1] if len(lines) > 1 else "",
        "source": "DevToolsActivePort",
        "file": str(path),
    }


def crash_signature(stderr_path: str | Path, *, max_lines: int = 12) -> dict[str, Any]:
    """Summarise the first fatal lines the app printed before dying."""
    log_path = Path(stderr_path)
    if not log_path.exists():
        return {"available": False}
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {"available": False}
    interesting = [
        line for line in lines
        if any(token in line for token in (
            "TypeError:", "Error:", "uncaught exception", "Cannot find", "FATAL",
            "AssertionError", "ReferenceError:",
        ))
    ]
    return {
        "available": True,
        "line_count": len(lines),
        "head": lines[:max_lines],
        "fatal_lines": interesting[:max_lines],
    }


def wait_for_devtools(
    app: LaunchedApp,
    *,
    timeout_s: float = 120.0,
    poll_s: float = 0.5,
) -> dict[str, Any]:
    """Wait for the debugging endpoint, using the app's own reported port.

    Fails fast (with the crash signature) if the app exits before the endpoint
    is usable — a crash is not a slow start.
    """
    deadline = time.monotonic() + timeout_s
    recorded: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if recorded is None:
            found = (
                read_devtools_active_port(app.effective_user_data_dir)
                or scan_stderr_for_devtools(app.stderr_path)
            )
            if found:
                recorded = found
        active_port = int((recorded or {}).get("port") or app.port)
        listeners = listening_sockets(active_port)
        if listeners:
            non_loopback = [
                item for item in listeners
                if not is_loopback_bind(str(item.get("local_address") or ""))
            ]
            if non_loopback:
                raise LaunchError(
                    f"remote debugging on port {active_port} is bound beyond loopback: {non_loopback}"
                )
            return {
                "port": active_port,
                "requested_port": app.port,
                "port_overridden": active_port != app.port,
                "listeners": listeners,
                "loopback_only": True,
                "endpoint": recorded,
            }
        code = app.process.poll() if app.process is not None else None
        if code is not None:
            signature = crash_signature(app.stderr_path)
            bound = recorded or read_devtools_active_port(app.effective_user_data_dir) or scan_stderr_for_devtools(app.stderr_path)
            raise LaunchError(
                f"desktop app exited with code {code} before serving a debugging endpoint "
                f"(requested port {app.port}, actually bound={bound}, "
                f"stderr={signature.get('fatal_lines') or signature.get('head')})"
            ) from None
        time.sleep(poll_s)
    signature = crash_signature(app.stderr_path)
    raise LaunchError(
        f"no debugging listener appeared within {timeout_s}s "
        f"(requested port {app.port}, reported={recorded}, stderr={signature.get('fatal_lines')})"
    )



def http_json(port: int, path: str, *, timeout: float = 5.0) -> Any:
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise LaunchError(f"CDP endpoint unreachable at {url}: {exc}") from exc


def wait_for_cdp(port: int, *, timeout_s: float = 90.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return http_json(port, "/json/version")
        except (LaunchError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise LaunchError(f"CDP /json/version never answered on 127.0.0.1:{port}: {last_error}")


def wait_for_page_target(port: int, *, timeout_s: float = 120.0) -> list[dict[str, Any]]:
    """Wait until the workbench page target exists (the window has loaded).

    Chromium binds the debugging port before the workbench page is created, so
    ``/json/version`` answering is NOT proof that a renderer exists yet.
    """
    deadline = time.monotonic() + timeout_s
    last: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        try:
            payload = http_json(port, "/json/list", timeout=5.0)
        except (LaunchError, json.JSONDecodeError):
            time.sleep(0.5)
            continue
        if isinstance(payload, list):
            last = payload
            pages = [
                item for item in payload
                if isinstance(item, dict)
                and item.get("type") == "page"
                and item.get("webSocketDebuggerUrl")
            ]
            if pages:
                return payload
        time.sleep(0.5)
    raise LaunchError(f"no page target appeared on 127.0.0.1:{port} within {timeout_s}s (last={last})")



def stop_app(app: LaunchedApp, *, timeout_s: float = 20.0) -> dict[str, Any]:
    process = app.process
    if process is None:
        return {"stopped": False, "reason": "no process handle"}
    if process.poll() is not None:
        return {"stopped": True, "already_exited": True, "exit_code": process.returncode}
    process.terminate()
    try:
        code = process.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        process.kill()
        code = process.wait(timeout=10.0)
    return {
        "stopped": True,
        "exit_code": code,
        "stopped_at": time.time(),
        "runtime_seconds": round(time.time() - app.started_at, 3),
    }


def capture_identity(app: LaunchedApp, vscode_root: Path) -> dict[str, Any]:
    tree = collect_tree(app.pid)
    return {
        "exe": str(app.exe),
        "exe_sha256": sha256_file(app.exe) if app.exe.exists() else "",
        "pid": app.pid,
        "ppid": tree.root.ppid if tree.root else None,
        "image_version": read_pe_version(app.exe),
        "product": read_product(vscode_root),
        "build_info": read_build_info(vscode_root),
        "args": app.args,
        "env_keys": app.env_keys,
        "workspace": app.workspace,
        "debug_port": app.port,
        "started_at": app.started_at,
        "process_root": tree.root.to_dict() if tree.root else None,
        "descendant_count": len(tree.descendants),
        "descendant_names": sorted({proc.name for proc in tree.descendants}),
    }
