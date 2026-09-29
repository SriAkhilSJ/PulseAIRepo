"""Crusor Preview — the engine starts the proxy, so the desktop app alone is enough.

Why this module exists
----------------------
Nothing used to start the preview proxy. The setup guide therefore asked for a **second terminal**
(``python -m src.preview.server --workspace <opened folder> --endpoint-session ide``) *before* the
Preview chip could ever light, and the Windows launcher (``crusor.bat``) opened a minimized Python
console next to the app for it. Two visible windows for one product, and the second one had to be
pointed at the exact folder the user opened or the IDE silently found no proxy at all (the endpoint
file matches by ``workspace``).

The engine already knows the one thing the proxy needs — the folder the user opened — because every
session frame carries it (:mod:`src.bridge.__main__` binds a session to its workspace and refuses to
re-home it). So the engine starts the proxy itself: hidden, once per workspace, reused when one is
already healthy.

What this deliberately does **not** do
--------------------------------------
* It does not tie the proxy to the bridge's lifetime. A preview window is open *while* sessions come
  and go (an engine restart must not kill the page the user is inspecting), and the published
  endpoint is how the IDE finds it again — the same contract the manual launcher has always had.
  The proxy is therefore a small local daemon: found by :func:`find_serving_endpoint`, reused, or
  replaced. ``prune_stale`` (endpoint.py) keeps dead registrations from accumulating.
* It never raises into a caller. A preview that cannot start must not break an agent turn; failures
  are logged once and returned as ``None``.

The switch: ``CRUSORAI_PREVIEW_AUTOSTART=0`` (also ``off``/``false``/``no``) disables the whole
thing for anyone who wants the manual flow back.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final, Mapping

from .endpoint import endpoint_path, preview_home, read_endpoint

__all__ = [
    "AUTOSTART_ENV",
    "DEFAULT_PORT",
    "DEFAULT_SESSION",
    "PreviewAutostart",
    "ProxyHandle",
    "ensure_proxy",
    "ensure_stdio",
    "find_serving_endpoint",
    "normalize_workspace",
    "resolve_workspace",
]

#: The session id the proxy publishes its endpoint under. The IDE resolves a proxy by the
#: ``workspace`` in that file, not by its name, so this only has to stay stable — "ide" is what the
#: setup guide and ``crusor.bat`` have always used, and keeping it means a launcher-started proxy and
#: an engine-started one are the same registration.
DEFAULT_SESSION: Final = "ide"

#: The port the manual flow documents. Taken first because it is the one a human expects to see in
#: a log or a devtools URL; if it is busy (another workspace's proxy, an unrelated server) the
#: spawn is retried on a free port, which the endpoint file carries anyway.
DEFAULT_PORT: Final = 8931

AUTOSTART_ENV: Final = "CRUSORAI_PREVIEW_AUTOSTART"

_DISABLED_VALUES: Final = frozenset({"0", "false", "no", "off"})

#: How long a first spawn may take before we call it a failure. The proxy binds a socket and writes
#: the endpoint before serving — this is a cold Python start, not network latency.
DEFAULT_WAIT_SECONDS: Final = 12.0

#: Minimum gap between two *attempts* for the same workspace inside one engine process. A failed
#: start (port race, a proxy that died mid-handshake) should not be retried on every frame, but it
#: should also not be remembered as permanent: a minute later the world may have moved.
RETRY_COOLDOWN_SECONDS: Final = 60.0

_HEALTH_TIMEOUT_SECONDS: Final = 2.0
_POLL_INTERVAL_SECONDS: Final = 0.1
_TERMINATE_GRACE_SECONDS: Final = 3.0

#: Subtree that owns the proxy CLI. This file lives in ``<engine root>/src/preview``, so the engine
#: root is two parents up — the same root the bridge runs from, so ``python -m src.preview.server``
#: resolves in the child regardless of the folder the user opened.
ENGINE_ROOT: Final = Path(__file__).resolve().parents[2]


def _log(message: str) -> None:
    """One line to the engine's stderr, which the app surfaces as ``[CrusorAI Engine] …``."""
    print(f"[preview] {message}", file=sys.stderr, flush=True)


def resolve_workspace(workspace: str | Path) -> str:
    """The absolute folder a proxy would be pointed at — and what goes into its endpoint file."""
    return str(Path(str(workspace)).expanduser().resolve())


def normalize_workspace(workspace: str | Path) -> str:
    """The comparison form: :func:`resolve_workspace`, folded on case-insensitive platforms.

    The proxy publishes ``Path(workspace).resolve()`` (see :class:`src.preview.server.PreviewServer`),
    and the workbench compares with ``normcase`` too, so reuse has to compare the same way: without
    it, ``D:\\Proj`` and ``d:\\proj`` would be two different proxies. Spawning still uses the
    *resolved* spelling — a lowercase `c:\\users\\…` in a log file is valid on Windows but reads like
    a bug.
    """
    return os.path.normcase(resolve_workspace(workspace))


def _session_log_path(session_id: str) -> Path:
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in str(session_id or "")).strip("._")
    return preview_home() / f"proxy-{safe or 'default'}.log"


def ensure_stdio(session_id: str) -> Path | None:
    """Bind stdout/stderr to the proxy log when the process has neither.

    A windowless start is the point of this whole feature (:meth:`PreviewAutostart._start_process`
    uses ``CREATE_NO_WINDOW`` and points stdout at the log), but not every caller redirects: run
    ``pythonw.exe`` — or any GUI-subsystem/interpreter with no console — and CPython sets
    ``sys.stdout``/``sys.stderr`` to ``None``. Then ``print()`` is a silent no-op, argparse cannot
    even report a bad flag, and a startup traceback dies with the process: a proxy nobody can debug.
    So when there is no stream, open one — ``<runtime home>/preview/proxy-<session>.log``, the same
    file the launcher tells the user to read.

    Returns the path when it bound one, ``None`` when the process already had usable streams (the
    normal case: a terminal, or a parent that redirected them).
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None
    path = _session_log_path(session_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = open(path, "a", encoding="utf-8", errors="backslashreplace", buffering=1)
    except OSError:  # pragma: no cover - unwritable runtime home
        return None
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    sys.stdout = stream
    sys.stderr = stream
    print(f"--- crusor preview proxy start {stamp} pid {os.getpid()} (no console; output bound to this file) ---")
    return path


@dataclass(frozen=True)
class ProxyHandle:
    """What :meth:`PreviewAutostart.ensure` found or started.

    ``process`` is only handed back so a caller (or a test) can stop what this process started;
    nothing in production needs it, and it is ``None`` for a reused proxy.
    """

    workspace: str
    origin: str
    pid: int | None = None
    reused: bool = False
    endpoint_path: str | None = None
    log_path: str | None = None
    process: Any = None

    @property
    def started(self) -> bool:
        return not self.reused


def _healthy(origin: str, *, timeout: float = _HEALTH_TIMEOUT_SECONDS) -> bool:
    """``GET <origin>/crusor-preview/health`` → 200. Any other answer (or none) is not healthy."""
    url = origin.rstrip("/") + "/crusor-preview/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return int(getattr(response, "status", response.getcode())) == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def find_serving_endpoint(workspace: str | Path) -> dict[str, Any] | None:
    """The freshest published endpoint that (a) serves this workspace and (b) still answers.

    Both halves matter. A file left behind by a killed proxy names a dead origin — reusing it would
    hand the IDE a URL that shows nothing, which is the failure the health probe exists to prevent.
    A healthy proxy for a *different* folder is not ours either: a proxy can only confine file
    targets to one workspace, so the workspace is part of the identity.
    """
    wanted = normalize_workspace(workspace)
    directory = preview_home()
    if not directory.is_dir():
        return None
    candidates: list[tuple[float, dict[str, Any]]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(payload, dict) or not payload.get("origin"):
            continue
        published = str(payload.get("workspace") or "")
        if not published:
            continue  # no workspace recorded: it cannot be proven to be this folder's proxy
        try:
            if normalize_workspace(published) != wanted:
                continue
        except OSError:  # pragma: no cover - unresolvable path in a hand-edited file
            continue
        candidates.append((float(payload.get("started_at") or 0.0), payload))
    # Newest first, and the first one that actually answers wins: a dead registration is normal
    # (the process was killed, the finally never ran), and an older live one is still a live one.
    for _, payload in sorted(candidates, key=lambda item: item[0], reverse=True):
        if _healthy(str(payload["origin"])):
            return payload
    return None


class PreviewAutostart:
    """Start (or adopt) the preview proxy for one workspace, at most once per cooldown window.

    One instance per engine process is enough — :func:`ensure_proxy` keeps the default one — but the
    state lives on the instance so tests (and a future embedded use) can hold their own.
    """

    def __init__(
        self,
        *,
        session: str = DEFAULT_SESSION,
        port: int = DEFAULT_PORT,
        wait_seconds: float = DEFAULT_WAIT_SECONDS,
        python: str | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.session = session
        self.port = port
        self.wait_seconds = wait_seconds
        self.python = python or sys.executable
        self._popen = popen
        self._environ = environ if environ is not None else os.environ
        self._lock = threading.Lock()
        #: normalized workspace -> (monotonic time of the attempt, handle or None)
        self._attempted: dict[str, tuple[float, ProxyHandle | None]] = {}
        #: workspaces another thread is starting right now (so two frames cannot race a spawn)
        self._starting: set[str] = set()

    # -- env -----------------------------------------------------------------------------------

    def enabled(self) -> bool:
        value = str(self._environ.get(AUTOSTART_ENV, "")).strip().lower()
        return value not in _DISABLED_VALUES

    # -- the one entry point -------------------------------------------------------------------

    def ensure(self, workspace: str | Path) -> ProxyHandle | None:
        """A live proxy for ``workspace``: adopt a healthy one, else spawn one. Never raises.

        Called on a background thread by the engine, so it may block for a few seconds on a cold
        start. Repeating it for the same workspace is cheap and returns the same handle.
        """
        # An empty workspace is not "the current directory": `Path("").resolve()` is the engine root,
        # and a proxy bound to that would serve the wrong folder's files (the workspace contract the
        # bridge enforces for sessions applies here too).
        if not str(workspace or "").strip():
            return None
        try:
            target = normalize_workspace(workspace)
            resolved = resolve_workspace(workspace)
        except OSError:
            return None
        if not self.enabled():
            return None

        now = time.monotonic()
        with self._lock:
            remembered = self._attempted.get(target)
            if remembered is not None and now - remembered[0] < RETRY_COOLDOWN_SECONDS:
                return remembered[1]
            if target in self._starting:
                return None
            self._starting.add(target)
        try:
            existing = find_serving_endpoint(target)
            if existing is not None:
                handle = ProxyHandle(
                    workspace=str(existing.get("workspace") or resolved),
                    origin=str(existing["origin"]),
                    pid=existing.get("pid"),
                    reused=True,
                    endpoint_path=str(endpoint_path(self.session)),
                )
                _log(f"preview proxy already serving {resolved} at {handle.origin} — reusing it")
                return self._remember(target, handle)
            handle = self._spawn_until_healthy(target, resolved)
            return self._remember(target, handle)
        except Exception as exc:  # pragma: no cover - defence in depth; the engine must never fail here
            _log(f"preview proxy autostart errored for {resolved!r}: {exc!r}")
            return self._remember(target, None)
        finally:
            with self._lock:
                self._starting.discard(target)

    def forget(self, workspace: str | Path | None = None) -> None:
        """Drop the per-process memory, so the next :meth:`ensure` probes and starts again."""
        with self._lock:
            if workspace is None:
                self._attempted.clear()
            else:
                self._attempted.pop(normalize_workspace(workspace), None)

    # -- internals -----------------------------------------------------------------------------

    def _remember(self, target: str, handle: ProxyHandle | None) -> ProxyHandle | None:
        with self._lock:
            self._attempted[target] = (time.monotonic(), handle)
        return handle

    def _spawn_until_healthy(self, target: str, workspace: str) -> ProxyHandle | None:
        """One attempt on the documented port, then one on a free port. ``None`` if neither takes."""
        attempts = (self.port, 0) if self.port else (0,)
        for index, port in enumerate(attempts):
            try:
                process = self._start_process(workspace, port)
            except OSError as exc:
                _log(f"could not start the preview proxy ({exc})")
                return None
            origin = self._await_health(process, target)
            if origin is not None:
                _log(f"preview proxy for {workspace} is up at {origin} (session {self.session!r})")
                return ProxyHandle(
                    workspace=workspace,
                    origin=origin,
                    pid=process.pid,
                    reused=False,
                    endpoint_path=str(endpoint_path(self.session)),
                    log_path=str(_session_log_path(self.session)),
                    process=process,
                )
            self._terminate(process)
            if index + 1 < len(attempts):
                _log(f"preview proxy did not answer on port {port} — retrying on a free port")
        _log(f"preview proxy did not come up for {workspace} — see {_session_log_path(self.session)}")
        return None

    def _start_process(self, workspace: str, port: int) -> Any:
        """Spawn the proxy detached, windowless, with its output appended to the session log."""
        command = [
            # -u: stdout is a log file here, not a console, so CPython block-buffers it — the proxy's
            # own "proxy on http://…" lines would sit in an 8 KiB buffer and never reach the file.
            self.python, "-u", "-m", "src.preview.server",
            "--workspace", workspace,
            "--port", str(port),
            "--endpoint-session", self.session,
        ]
        log_path = _session_log_path(self.session)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = {
            "cwd": str(ENGINE_ROOT),
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt":
            # CREATE_NO_WINDOW is the whole point: the user must not get a second window next to
            # the desktop app (the field report this module answers). Both knobs are Windows-only —
            # Popen rejects `windowsHide` (and the creation flag) elsewhere.
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            kwargs["windowsHide"] = True
        else:
            # A session of its own: closing the terminal the app was launched from must not take
            # the preview down with it.
            kwargs["start_new_session"] = True
        with open(log_path, "ab", buffering=0) as sink:
            kwargs["stdout"] = sink
            kwargs["stderr"] = subprocess.STDOUT
            banner = f"\n--- crusor preview proxy for {workspace} (session {self.session}) ---\n".encode("utf-8")
            try:
                sink.write(banner)
            except OSError:  # pragma: no cover - log not writable
                pass
            return self._popen(command, **kwargs)

    def _await_health(self, process: Any, target: str) -> str | None:
        """Poll the endpoint this child publishes until it answers, or the wait runs out.

        The workspace is checked, not just the origin: the endpoint file is named by *session*, so a
        registration left by an earlier proxy for another folder is still sitting there while the
        new child boots. Accepting it would report a start that never happened and hand the IDE a
        proxy for the wrong workspace.
        """
        deadline = time.monotonic() + self.wait_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return None  # it exited (bad flags, no src.preview, a bind failure)
            endpoint = read_endpoint(self.session)
            if endpoint and endpoint.get("origin"):
                published = str(endpoint.get("workspace") or "")
                try:
                    same = bool(published) and normalize_workspace(published) == target
                except OSError:
                    same = False
                if same and _healthy(str(endpoint["origin"])):
                    return str(endpoint["origin"]).rstrip("/")
            time.sleep(_POLL_INTERVAL_SECONDS)
        return None

    @staticmethod
    def _terminate(process: Any) -> None:
        try:
            process.terminate()
            process.wait(timeout=_TERMINATE_GRACE_SECONDS)
        except Exception:  # pragma: no cover - already gone / not a real process (tests)
            pass


_default: PreviewAutostart | None = None
_default_lock = threading.Lock()


def default() -> PreviewAutostart:
    """The process-wide instance the engine calls into."""
    global _default
    with _default_lock:
        if _default is None:
            _default = PreviewAutostart()
        return _default


def ensure_proxy(workspace: str | Path) -> ProxyHandle | None:
    """``default().ensure(workspace)`` — what :mod:`src.bridge.__main__` calls, off the frame path."""
    return default().ensure(workspace)
