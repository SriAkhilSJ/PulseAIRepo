# src/tools/browser_tools.py
"""
Browser tools — hermes' local browser stack, ported (agent-browser CLI).
=========================================================================

Hermes source of truth: tools/browser_tool.py + browser_tool_session.py +
browser_tool_install.py. Hermes drives a real browser through the
`agent-browser` Node CLI (resolved on PATH or via `npx agent-browser@^0.26.0`),
one persistent daemon session per task, every command answering JSON:

    agent-browser --session <name> --json <command> [args...]

navigate returns a compact accessibility snapshot with element ref IDs
(@e1, @e2, ...); click/type address elements BY REF from that snapshot.
That loop — snapshot, act by ref, re-snapshot — is hermes' whole browser
ergonomics and is what makes "browser agent test" a model behavior instead
of a hand-written script.

Ported here (local backend only): navigate (auto compact snapshot,
bot-detection title warning), snapshot (compact/full, threshold
truncation with full copy stored for read_file paging), click, type
(fill), scroll (500px), back, press, console (messages + JS errors +
`expression` eval), get_images. Response shapes, error shapes, timeouts
(30s default; 60s/120s floors for open), URL floors (secret-in-URL block,
cloud-metadata block) and session-per-thread naming all mirror hermes.

NOT ported (hermes has them; crusor lacks the plumbing — stated, not
silently dropped): browser_vision (needs an aux vision-model call — crusor
has no image-carrying message pipeline yet), cloud providers
(Browserbase/browser-use), Camofox, CDP supervisor, Lightpanda engine
fallback, real-profile Chrome. The SSRF page-guard is
a cloud-mode protection in hermes and fails open for local backends; the
local floors (secret URLs, metadata endpoints) ARE kept.

Replaces browser_mcp.py (puppeteer-MCP lab backend with a hardcoded
Administrator-path server directory — never hermes' implementation, and
unspawnable on any machine but the lab's).

There are exactly TWO window options — headed or headless — picked by env,
read PER CALL (standing rule):
    CRUSORAI_BROWSER_HEADED = headed | on | true | 1 | yes    -> visible window
    CRUSORAI_BROWSER_HEADED = headless | off | false | 0 | no -> no window
Unset falls back to hermes' own knob (AGENT_BROWSER_HEADED=true|1|yes,
hermes browser_tool_cloud._is_headed_mode), then to the crusor default
HEADED. Hermes' own default is headless; CRUSORAI_BROWSER_HEADED=headless
restores it. An unrecognized value states itself on stderr once and takes
the default — a silent typo must not silently flip the owner's
visible-testing posture. CRUSORAI_BROWSER_RECORD uses the same word
families (on/off), default ON (hermes browser.record_sessions, default
off, _maybe_start_recording).

`CRUSORAI_AGENT_BROWSER` — explicit path override for the CLI, read PER
CALL (standing rule). `CRUSORAI_BROWSER_INACTIVITY_TIMEOUT` — session idle
seconds before the agent-browser daemon self-terminates (hermes
browser.inactivity_timeout; default 120s, 30s floor).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from pydantic import Field

# ---------------------------------------------------------------------------
# hermes constants (tools/browser_tool.py)
# ---------------------------------------------------------------------------
NPX_AGENT_BROWSER_SENTINEL = "npx agent-browser"
AGENT_BROWSER_NPX_SPEC = "agent-browser@^0.26.0"

DEFAULT_COMMAND_TIMEOUT = 30
MIN_OPEN_TIMEOUT = 60
MIN_FIRST_OPEN_TIMEOUT = 120

# hermes hermes_cli/_subprocess_compat: hide the child's console without
# detaching it (no flash, Ctrl+C and job teardown still propagate).
_CREATE_NO_WINDOW = 0x08000000

DEFAULT_SNAPSHOT_THRESHOLD = 15_000
MIN_SNAPSHOT_THRESHOLD = 1_000
MAX_STORED_SNAPSHOT_CHARS = 2_000_000
_EMPTY_OK_COMMANDS = frozenset({"close", "record"})  # hermes :119

# hermes browser_tool_snapshot._SCREENSHOT_PATH_PATTERNS, verbatim: recover a
# saved screenshot path from prose output (agent-browser versions that answer
# in text instead of JSON). Windows paths (e.g. C:/... or C:\...) supported.
_SCREENSHOT_PATH_PATTERNS = (
    r"Screenshot saved to ['\"](?P<path>(?:[a-zA-Z]:)?[/\\].+?\.png)['\"]",
    r"Screenshot saved to (?P<path>(?:[a-zA-Z]:)?[/\\].+?\.png)(?:\s|$)",
    r"(?P<path>(?:[a-zA-Z]:)?[/\\].+?\.png)(?:\s|$)",
)


def _user_home() -> Path:
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
    return Path(home) if home else Path.home()


def _extract_screenshot_path_from_text(text: str) -> Optional[str]:
    """hermes _extract_screenshot_path_from_text, verbatim."""
    if not text:
        return None
    for pattern in _SCREENSHOT_PATH_PATTERNS:
        match = re.search(pattern, text)
        if match:
            path = match.group("path").strip().strip("'\"")
            if path:
                return path
    return None

_SCROLL_PIXELS = 500
DEFAULT_SESSION_INACTIVITY_TIMEOUT = 120  # hermes browser.inactivity_timeout default
_MIN_INACTIVITY_S = 30  # hermes floor: no instant reaping

_NO_SESSION_ERROR = "No browser session. Call browser_navigate first."

# Unconditionally blocked: cloud metadata / IMDS endpoints (hermes
# _is_always_blocked_url floor — fires for EVERY backend, local included).
_METADATA_HOSTS = frozenset({
    "169.254.169.254", "169.254.170.2", "metadata.google.internal",
    "metadata", "100.100.100.200",
})

# hermes agent/redact.py _PREFIX_PATTERNS + _compile_prefix_matcher, verbatim
# (the URL-floor consumer, not the masker). Invented substrings missed whole
# provider families and had no token-boundary guards.
_PREFIX_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{10,}",           # OpenAI / OpenRouter / Anthropic (sk-ant-*)
    r"ghp_[A-Za-z0-9]{10,}",            # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{10,}",    # GitHub PAT (fine-grained)
    r"gho_[A-Za-z0-9]{10,}",            # GitHub OAuth access token
    r"ghu_[A-Za-z0-9]{10,}",            # GitHub user-to-server token
    r"ghs_[A-Za-z0-9]{10,}",            # GitHub server-to-server token
    r"ghr_[A-Za-z0-9]{10,}",            # GitHub refresh token
    r"xapp-\d+-[A-Za-z0-9-]{10,}",      # Slack app-level token
    r"xox[baprs]-[A-Za-z0-9-]{10,}",    # Slack bot/app/user tokens
    r"AIza[A-Za-z0-9_-]{30,}",          # Google API keys
    r"pplx-[A-Za-z0-9]{10,}",           # Perplexity
    r"fal_[A-Za-z0-9_-]{10,}",          # Fal.ai
    r"fc-[A-Za-z0-9]{10,}",             # Firecrawl
    r"bb_live_[A-Za-z0-9_-]{10,}",      # BrowserBase
    r"gAAAA[A-Za-z0-9_=-]{20,}",        # Codex encrypted tokens
    r"AKIA[A-Z0-9]{16}",                # AWS Access Key ID
    r"sk_live_[A-Za-z0-9]{10,}",        # Stripe secret key (live)
    r"sk_test_[A-Za-z0-9]{10,}",        # Stripe secret key (test)
    r"rk_live_[A-Za-z0-9]{10,}",        # Stripe restricted key
    r"SG\.[A-Za-z0-9_-]{10,}",          # SendGrid API key
    r"hf_[A-Za-z0-9]{10,}",             # HuggingFace token
    r"r8_[A-Za-z0-9]{10,}",             # Replicate API token
    r"npm_[A-Za-z0-9]{10,}",            # npm access token
    r"pypi-[A-Za-z0-9_-]{10,}",         # PyPI API token
    r"dop_v1_[A-Za-z0-9]{10,}",         # DigitalOcean PAT
    r"doo_v1_[A-Za-z0-9]{10,}",         # DigitalOcean OAuth
    r"am_[A-Za-z0-9_-]{10,}",           # AgentMail API key
    r"sk_[A-Za-z0-9_]{10,}",            # ElevenLabs TTS key
    r"tvly-[A-Za-z0-9]{10,}",           # Tavily search API key
    r"exa_[A-Za-z0-9]{10,}",            # Exa search API key
]


def _compile_prefix_matcher(patterns: list) -> "re.Pattern[str]":
    # hermes redact: boundary guards so a match can never sit inside a longer
    # token (a path segment, an id) and cry wolf.
    return re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(patterns) + r")(?![A-Za-z0-9_-])")


_SECRET_PREFIX_RE = _compile_prefix_matcher(_PREFIX_PATTERNS)

_GET_IMAGES_JS = """JSON.stringify(
        [...document.images].map(img => ({
            src: img.src, alt: img.alt || '', width: img.naturalWidth, height: img.naturalHeight
        })).filter(img => img.src && !img.src.startsWith('data:'))
    )"""

_BOT_DETECTION_TITLE_PATTERNS = (
    "access denied", "access to this page has been denied", "blocked", "bot detected", "verification required",
    "please verify", "are you a robot", "captcha", "cloudflare", "ddos protection", "checking your browser",
    "just a moment", "attention required",
)


def _err(error: str, **extra: Any) -> Dict[str, Any]:
    return {"success": False, "error": error, **extra}


def _dumps(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# CLI resolution — hermes browser_tool_install._find_agent_browser, crusor-sized
# ---------------------------------------------------------------------------
_cli_lock = threading.Lock()
_cached_cli: Any = False  # False = not yet resolved; None = resolved missing; str = path/sentinel
_cli_probe_ok: Any = False  # False = not yet probed; True/False = npx availability


def _install_hint() -> str:
    return ("Install it with: npm install -g agent-browser "
            f"(or rely on npx: {AGENT_BROWSER_NPX_SPEC}). "
            "Then run `agent-browser install` once so a local Chromium is present.")


def _run_ok(argv: List[str], timeout: int = 15) -> bool:
    """True when `argv --version`-style probe exits 0 (hermes validates candidates
    too — a `which` hit alone can be a dangling npm symlink)."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv, no shell
            argv, capture_output=True, timeout=timeout, shell=False,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _validate_candidate(candidate: str) -> bool:
    argv = candidate.split() if candidate == NPX_AGENT_BROWSER_SENTINEL else [candidate]
    return _run_ok([*argv, "--version"])


def _resolve_npx_bin() -> Optional[str]:
    global _cli_probe_ok
    if _cli_probe_ok is False:
        _cli_probe_ok = shutil.which("npx") is not None
    return shutil.which("npx") if _cli_probe_ok else None


def find_agent_browser() -> str:
    """PATH (validated) -> npx sentinel. Env override `CRUSORAI_AGENT_BROWSER`
    wins per call. Raises FileNotFoundError with the install hint."""
    override = os.environ.get("CRUSORAI_AGENT_BROWSER", "").strip()
    if override:
        if _validate_candidate(override):
            return override
        raise FileNotFoundError(
            f"CRUSORAI_AGENT_BROWSER={override!r} is not a runnable agent-browser CLI. {_install_hint()}")
    global _cached_cli
    with _cli_lock:
        if _cached_cli is not False:
            if _cached_cli is None:
                raise FileNotFoundError(f"agent-browser CLI not found (cached). {_install_hint()}")
            return _cached_cli
        found = shutil.which("agent-browser")
        if found and _validate_candidate(found):
            _cached_cli = found
            return found
        if _resolve_npx_bin():
            _cached_cli = NPX_AGENT_BROWSER_SENTINEL
            return _cached_cli
        _cached_cli = None
        raise FileNotFoundError(f"agent-browser CLI not found. {_install_hint()}")


def invalidate_cli_cache() -> None:
    """A spawn failure invalidates the cached resolution once (hermes re-resolves
    rather than trusting a stale path)."""
    global _cached_cli, _cli_probe_ok
    with _cli_lock:
        _cached_cli = False
        _cli_probe_ok = False


def _agent_browser_argv(browser_cmd: str) -> List[str]:
    """hermes browser_tool_session._agent_browser_argv: the sentinel expands to a
    pinned npx invocation. `--ignore-scripts`: a floating range must not run
    install scripts; `--prefer-offline`: warm caches win."""
    if browser_cmd == NPX_AGENT_BROWSER_SENTINEL:
        npx = _resolve_npx_bin() or "npx"
        return [npx, "--ignore-scripts", "--prefer-offline", "-y", AGENT_BROWSER_NPX_SPEC]
    return [browser_cmd]


# ---------------------------------------------------------------------------
# Sessions + command execution — hermes browser_tool_session, local shape
# ---------------------------------------------------------------------------
def _session_name(thread_id: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(thread_id)).strip("-") or "default"
    return f"crusorai-{sanitized[:60]}"


def _session_socket_dir(session_name: str) -> str:
    """hermes gives each session its own socket dir so parallel daemons never
    share one; agent-browser reads it from the env."""
    d = os.path.join(tempfile.gettempdir(), f"agent-browser-{session_name}")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _inactivity_timeout_s() -> int:
    raw = os.environ.get("CRUSORAI_BROWSER_INACTIVITY_TIMEOUT", "").strip()
    try:
        val = int(raw) if raw else DEFAULT_SESSION_INACTIVITY_TIMEOUT
    except ValueError:
        val = DEFAULT_SESSION_INACTIVITY_TIMEOUT
    return max(val, _MIN_INACTIVITY_S)


# ---------------------------------------------------------------------------
# Visible testing — hermes headed flag + record start/stop, owner-defaulted on
# ---------------------------------------------------------------------------
_ON_WORDS = {"headed", "on", "1", "true", "yes", "enabled"}
_OFF_WORDS = {"headless", "off", "0", "false", "no", "disabled"}
# hermes' own env knob (browser_tool_cloud._is_headed_mode): only turns ON —
# hermes computes `config OR env in (true,1,yes)` with default False.
_HERMES_HEADED_WORDS = {"true", "1", "yes"}
_unrecognized_headed_warned: set[str] = set()


def headed_mode() -> bool:
    """The window option — headed (visible) or headless — from env.

    CRUSORAI_BROWSER_HEADED accepts the two option names and their on/off
    aliases (module docstring table). Unset -> hermes' AGENT_BROWSER_HEADED
    (true/1/yes). Unset there too -> crusor default HEADED (owner 2026-09-07:
    'in front of users eyes'); CRUSORAI_BROWSER_HEADED=headless restores
    hermes' headless posture. An unrecognized value is stated once on
    stderr and takes the default."""
    raw = os.environ.get("CRUSORAI_BROWSER_HEADED", "").strip().lower()
    if raw:
        if raw in _OFF_WORDS:
            return False
        if raw in _ON_WORDS:
            return True
        if raw not in _unrecognized_headed_warned:
            _unrecognized_headed_warned.add(raw)
            print(
                f"[browser] CRUSORAI_BROWSER_HEADED={raw!r} is not a window "
                "option (headed|headless, on|off, true|false, 1|0, yes|no) "
                "— using the default (headed).",
                flush=True,
            )
        return True
    hermes_raw = os.environ.get("AGENT_BROWSER_HEADED", "").strip().lower()
    if hermes_raw in _HERMES_HEADED_WORDS:
        return True
    return True


_recording_lock = threading.Lock()
_RECORDING_SESSIONS: set[str] = set()  # hermes _recording_sessions shape
# Sessions THIS process actually opened a browser window for. Turn teardown
# uses it to skip `close` on browser-free turns: a cold `close` starts the
# daemon and, in headed mode, launches a Chromium window only to close it —
# the white-window flash + seconds the user sees on Stop/Esc.
_OPEN_SESSIONS: set[str] = set()


def recording_enabled() -> bool:
    """hermes gates on browser.record_sessions (default False); crusor defaults
    ON per the owner's visible-testing direction. CRUSORAI_BROWSER_RECORD=off
    restores hermes' posture."""
    raw = os.environ.get("CRUSORAI_BROWSER_RECORD", "").strip().lower()
    if raw in _OFF_WORDS:
        return False
    if raw in _ON_WORDS:
        return True
    return True


def recordings_dir() -> Path:
    """hermes: <hermes_home>/browser_recordings, cleaned at 72h. Crusor: under
    the home dot-dir, with an env override for desktop installs."""
    override = os.environ.get("CRUSORAI_BROWSER_RECORDINGS_DIR", "").strip()
    base = Path(override) if override else _user_home() / ".crusorai" / "browser_recordings"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _recording_path(session: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return recordings_dir() / f"session_{stamp}_{session[-16:]}.webm"


def maybe_start_recording(session: str) -> Optional[str]:
    """hermes _maybe_start_recording: `record start <path>` once per session,
    first navigate; failures are debug noise, never tool errors."""
    with _recording_lock:
        if session in _RECORDING_SESSIONS:
            return None
    if not recording_enabled():
        return None
    path = _recording_path(session)
    result = run_browser_command(session, "record", ["start", str(path)])
    if not result.get("success"):
        return None
    with _recording_lock:
        _RECORDING_SESSIONS.add(session)
    return str(path)


def stop_browser_recording(session: str) -> Optional[str]:
    """hermes _maybe_stop_recording: `record stop`, save the .webm, return the
    saved path (None when nothing was recording)."""
    with _recording_lock:
        if session not in _RECORDING_SESSIONS:
            return None
    result = run_browser_command(session, "record", ["stop"])
    with _recording_lock:
        _RECORDING_SESSIONS.discard(session)
    if not result.get("success"):
        return None
    return str((result.get("data", {}) or {}).get("path", "")) or None


def stop_browser_recording_for_thread(thread_id: str) -> Optional[str]:
    """Turn-end hook (chat_graph): save the recording for this turn's session.
    hermes stops in cleanup_browser ('saves the file before close'); the turn
    end is crusor's closest equivalent of session close."""
    return stop_browser_recording(_session_name(thread_id))


def close_browser_session(session: str) -> bool:
    """Close one session's browser (windows and every tab); the daemon stays
    up, so the next navigate cold-opens a fresh single-tab browser. Best
    effort: failure is debug noise, never a tool error."""
    result = run_browser_command(session, "close", [], timeout=20)
    return bool(result.get("success"))


def close_browser_for_thread(thread_id: str) -> bool:
    """Turn-end hook (chat_graph), the second half of hermes cleanup_browser:
    after the recording is saved, CLOSE the browser so a testing turn leaves
    no headed window or tab cluster behind — the user asked for visible
    tests, not a desktop full of leftover pages."""
    session = _session_name(thread_id)
    if session not in _OPEN_SESSIONS:
        # Nothing to clean: this turn never opened a window. Calling `close`
        # anyway would cold-start the agent-browser daemon — and in headed
        # mode launch a visible Chromium window just to close it again (the
        # white flash + teardown seconds on Stop/Esc for browser-free turns).
        return False
    _OPEN_SESSIONS.discard(session)
    try:
        return close_browser_session(session)
    except Exception:
        return False


def _consolidate_tabs(session: str) -> int:
    """hermes' one-tab rule: repeated browser_navigate calls used to leave a
    tab cluster behind (open used to spawn a page per call). Before a warm
    navigation, park on the first tab and close every other one so the
    session always tests in exactly ONE tab. Returns how many were closed;
    failures are debug noise."""
    listing = run_browser_command(session, "tab", ["list", "--json"], timeout=15)
    if not listing.get("success"):
        return 0
    payload = listing.get("data")
    tabs = payload.get("tabs") if isinstance(payload, dict) else payload
    if not isinstance(tabs, list) or len(tabs) <= 1:
        return 0
    run_browser_command(session, "tab", ["t1"], timeout=10)
    closed = 0
    for tab in tabs:
        ref = ""
        if isinstance(tab, dict):
            ref = str(tab.get("id") or tab.get("label") or tab.get("targetId") or "")
        else:
            ref = str(tab or "")
        if not ref or ref == "t1":
            continue
        if run_browser_command(session, "tab", ["close", ref], timeout=10).get("success"):
            closed += 1
    return closed


def _command_env(session_name: str) -> Dict[str, str]:
    env = dict(os.environ)
    env["AGENT_BROWSER_SOCKET_DIR"] = _session_socket_dir(session_name)
    # Daemon-side idle self-termination (agent-browser 0.24+), mirroring hermes'
    # janitor, unless the operator set the knob explicitly.
    if "AGENT_BROWSER_IDLE_TIMEOUT_MS" not in env:
        env["AGENT_BROWSER_IDLE_TIMEOUT_MS"] = str(_inactivity_timeout_s() * 1000)
    return env


def _command_timeout() -> int:
    """hermes browser.command_timeout (default 30s, floor 5s); crusor's config
    shape is the env, read PER CALL (standing rule)."""
    raw = os.environ.get("CRUSORAI_BROWSER_COMMAND_TIMEOUT", "").strip()
    try:
        return max(int(raw), 5) if raw else DEFAULT_COMMAND_TIMEOUT
    except ValueError:
        return DEFAULT_COMMAND_TIMEOUT


def _open_timeout(*, first_open: bool) -> int:
    """Floors for `open`: cold daemon + first Chromium launch can exceed the
    generic timeout on slow hosts (hermes MIN_OPEN_TIMEOUT family)."""
    base = _command_timeout()
    return max(base, MIN_FIRST_OPEN_TIMEOUT if first_open else MIN_OPEN_TIMEOUT)


def build_session_args(session: str) -> List[str]:
    """hermes browser_tool_session (:589-591): local sessions ride
    `--session <name>`, plus `--headed` when the window should be visible
    (hermes _is_headed_mode; crusor default ON — owner visible-testing)."""
    backend_args = ["--session", session]
    if headed_mode():
        backend_args.append("--headed")
    return backend_args


def _interpret_output(command: str, stdout: str, stderr: str, returncode: int) -> Dict[str, Any]:
    """hermes _interpret_browser_command_output: JSON stdout is the contract;
    empty stdout with rc=0 is a broken state (stale daemon) except for the
    legitimately-empty commands; non-JSON output is an error."""
    stdout_text = (stdout or "").strip()
    if not stdout_text:
        if returncode != 0:
            return {"success": False,
                    "error": (stderr or "").strip() or f"Command failed with code {returncode}"}
        if command not in _EMPTY_OK_COMMANDS:
            return {"success": False, "error": f"Browser command '{command}' returned no output"}
        return {"success": True, "data": {}}
    try:
        parsed = json.loads(stdout_text)
    except json.JSONDecodeError:
        raw = stdout_text[:2000]
        # hermes: a screenshot that answers in prose still saved a file —
        # recover the path and verify it exists before reporting success.
        if command == "screenshot":
            combined = "\n".join(p for p in (stdout_text, (stderr or "").strip()) if p)
            recovered = _extract_screenshot_path_from_text(combined)
            if recovered and Path(recovered).exists():
                return {"success": True, "data": {"path": recovered, "raw": raw}}
        return {"success": False,
                "error": f"Non-JSON output from agent-browser for '{command}': {raw}"}
    if isinstance(parsed, dict) and "success" in parsed:
        return parsed
    return {"success": True, "data": parsed if isinstance(parsed, dict) else {"result": parsed}}


def _popen_agent_browser(argv: List[str], env: Dict[str, str], socket_dir: str, tag: str):
    """hermes browser_tool_session._popen_agent_browser, verbatim shape.

    Temp files, not pipes: the CLI forks a daemon that inherits its fds, so
    pipes never see EOF until the timeout. Windows: CREATE_NO_WINDOW only
    (CREATE_NEW_PROCESS_GROUP cancels asyncio's running task on 3.11),
    STARTF_USESTDHANDLES + close_fds so the child gets ONLY our three handles
    (leaked console handles kill the Rust daemon grandchild)."""
    fds = [os.open(os.path.join(socket_dir, f"_{slot}_{tag}"),
                   os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
           for slot in ("stdout", "stderr")]
    try:
        extra: Dict[str, Any] = {}
        if os.name == "nt":
            _si = subprocess.STARTUPINFO()
            _si.dwFlags |= subprocess.STARTF_USESTDHANDLES
            extra = {"creationflags": _CREATE_NO_WINDOW, "close_fds": True,
                     "startupinfo": _si}
        return subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            argv, stdout=fds[0], stderr=fds[1], stdin=subprocess.DEVNULL,
            env=env, **extra)
    finally:
        for fd in fds:
            os.close(fd)


def _read_command_output_files(stdout_path: str, stderr_path: str) -> tuple:
    """hermes _read_command_output_files: best-effort reads of the temp files."""
    out = err = ""
    try:
        out = Path(stdout_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    try:
        err = Path(stderr_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return out, err


def _unlink_command_output_files(*paths: str) -> None:
    for p in paths:
        try:
            os.unlink(p)
        except OSError:
            pass


_CHROMIUM_INSTALL_HINT = ("npx agent-browser install --with-deps")


def _format_browser_timeout_error(command: str, timeout: int, stdout: str, stderr: str) -> str:
    """hermes _format_browser_timeout_error (local shape): an actionable
    timeout message from the daemon's captured output."""
    parts = [f"Command timed out after {timeout} seconds"]
    detail = (stderr or stdout or "").strip()
    if detail:
        parts.append(detail[:1500])
    if "sandbox" in f"{stderr}\n{stdout}".lower():
        parts.append("Chromium sandbox launch failed. Set AGENT_BROWSER_ARGS="
                     "'--no-sandbox,--disable-dev-shm-usage' in your environment, "
                     "or run: " + _CHROMIUM_INSTALL_HINT)
    elif command == "open":
        parts.append("The browser daemon may still be starting, or Chromium may be "
                     "missing system libraries. Install/repair with: "
                     + _CHROMIUM_INSTALL_HINT)
    return "\n".join(parts)


def _read_daemon_pid(socket_dir: str, session: str) -> Optional[int]:
    """hermes _read_browser_daemon_pid: best-effort read of <session>.pid."""
    try:
        return int((Path(socket_dir) / f"{session}.pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _daemon_responsive(socket_dir: str, probe_timeout_s: float = 1.0) -> bool:
    """hermes _browser_daemon_responsive: a connect to the daemon's unix control
    socket proves the accept loop is alive. Windows named pipes can't be probed
    -> report unresponsive (tree-kill + respawn is the safe recovery)."""
    if os.name == "nt":
        return False
    import socket as socket_mod
    if not hasattr(socket_mod, "AF_UNIX"):
        return False
    try:
        entries = os.listdir(socket_dir)
    except OSError:
        return False
    for entry in (e for e in entries if e.endswith(".sock")):
        try:
            with socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM) as s:
                s.settimeout(probe_timeout_s)
                s.connect(os.path.join(socket_dir, entry))
                return True
        except OSError:
            continue
    return False


def _kill_process_tree(pid: int) -> bool:
    """hermes agent/deadline.kill_process_tree, portable core. Windows:
    `taskkill /F /T` (tree-kill; terminating only the daemon PID leaks the
    Chromium tree). POSIX: best-effort child kill via psutil when present,
    then the pid itself."""
    if os.name == "nt":
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=15, check=False,
                creationflags=_CREATE_NO_WINDOW,
            )
            return proc.returncode == 0
        except Exception:
            return False
    try:
        import psutil  # type: ignore
        try:
            children = psutil.Process(pid).children(recursive=True)
        except psutil.Error:
            children = []
        for child in children:
            try:
                child.kill()
            except psutil.Error:
                pass
    except Exception:
        pass
    try:
        os.kill(pid, 9)
        return True
    except OSError:
        return False


def _handle_command_timeout(session: str, socket_dir: str) -> None:
    """hermes _handle_browser_command_timeout (local shape). The command wedged
    page/CDP-side or the daemon is wedged/dead; on Windows the liveness probe
    cannot attach to named pipes, so unresponsive -> tree-kill + evict is the
    safe recovery (hermes' own Windows branch). A live POSIX daemon is left
    alone: only the command died, and killing it would be overkill and slow."""
    if _daemon_responsive(socket_dir):
        return
    pid = _read_daemon_pid(socket_dir, session)
    if pid is not None:
        _kill_process_tree(pid)
    shutil.rmtree(socket_dir, ignore_errors=True)
    # the daemon is gone: the session state goes with it (hermes evicts the
    # session record; crusor's session is stateless, so just the flags)
    with _recording_lock:
        _RECORDING_SESSIONS.discard(session)
        _FIRST_NAV_SEEN.discard(session)


# Per-session first-navigation flag (hermes keeps `_first_nav` on the session
# record; crusor's session is a name, so the flag lives here and dies with the
# daemon in _handle_command_timeout).
_FIRST_NAV_SEEN: set = set()


def run_browser_command(
    session: str,
    command: str,
    args: Optional[List[str]] = None,
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Run one agent-browser CLI command against the session; parsed JSON out."""
    args = args or []
    if timeout is None:
        timeout = _command_timeout()
    try:
        browser_cmd = find_agent_browser()
    except FileNotFoundError as exc:
        return {"success": False, "error": str(exc)}
    cmd_parts = [
        *_agent_browser_argv(browser_cmd),
        *build_session_args(session), "--json", command, *args,
    ]
    socket_dir = _session_socket_dir(session)
    stdout_path = os.path.join(socket_dir, f"_stdout_{command}")
    stderr_path = os.path.join(socket_dir, f"_stderr_{command}")
    try:
        proc = _popen_agent_browser(
            cmd_parts, _command_env(session), socket_dir, command)
    except OSError as exc:
        return {"success": False, "error": f"Failed to launch agent-browser: {exc}"}
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        stdout, stderr = _read_command_output_files(stdout_path, stderr_path)
        _unlink_command_output_files(stdout_path, stderr_path)
        # hermes: recover session state after a command timeout (daemon probe
        # -> tree-kill + evict when wedged). The CLI cache stays: a wedged
        # page is not a vanished binary.
        _handle_command_timeout(session, socket_dir)
        return {"success": False,
                "error": _format_browser_timeout_error(command, timeout, stdout, stderr)}
    stdout, stderr = _read_command_output_files(stdout_path, stderr_path)
    _unlink_command_output_files(stdout_path, stderr_path)
    return _interpret_output(command, stdout, stderr, proc.returncode)


# ---------------------------------------------------------------------------
# URL floors — hermes browser_tool._secret_url_error / _is_always_blocked_url
# ---------------------------------------------------------------------------
def _secret_url_error(url: str) -> Optional[Dict[str, Any]]:
    # hermes _secret_url_error: refuse URLs embedding an API key/token raw
    # AND URL-decoded (catching "%2D" tricks) — a prompt injection could
    # otherwise exfiltrate secrets via the URL.
    import urllib.parse
    if _SECRET_PREFIX_RE.search(url) or _SECRET_PREFIX_RE.search(urllib.parse.unquote(url)):
        return _err("Blocked: URL contains what appears to be an API key or token. "
                    "Secrets must not be sent in URLs.")
    return None


def _always_blocked_url_error(url: str) -> Optional[Dict[str, Any]]:
    try:
        host = (url.split("//", 1)[-1].split("/", 1)[0].split(":", 1)[0] or "").strip().lower()
    except Exception:
        return None
    if host in _METADATA_HOSTS:
        return _err("Blocked: URL targets a cloud metadata endpoint")
    return None


def _url_policy_error(url: str) -> Optional[Dict[str, Any]]:
    return _secret_url_error(url) or _always_blocked_url_error(url)


# hermes runs a normalize step on every navigate URL (url_safety.
# normalize_url_for_request — whitespace repair, IRI->URI). Crusor's field
# adds two model-emitted shapes that Chrome silently blanks: a bare
# host:port ("localhost:3000" parses as scheme "localhost:") and Windows
# paths ("d:\app\index.html", git-bash "/d/app/index.html"). Same
# position, same purpose — repair the input, never guess at intent.
def normalize_browser_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return raw
    # hermes: repair model-emitted whitespace after the scheme separator
    raw = re.sub(r"^([A-Za-z][A-Za-z0-9+.-]*://)\s+", r"\1", raw)
    if "://" in raw:
        return raw  # has a scheme (https://, file://, about:) — pass through
    # Windows host only: on POSIX, /d/app is a real path, not a drive.
    if os.name == "nt":
        # git-bash absolute path: /d/app/index.html -> file:///d:/app/index.html
        m = re.match(r"^/([a-z])/(.+)$", raw, re.IGNORECASE)
        if m:
            return f"file:///{m.group(1).lower()}:/{m.group(2)}"
    # Windows drive path: d:\app\index.html or d:/app/index.html
        m = re.match(r"^([a-z]):[/\\](.+)$", raw, re.IGNORECASE)
        if m:
            return f"file:///{m.group(1).lower()}:/{m.group(2).replace(chr(92), '/')}"
    # bare host[:port][/path] -> http://
    if re.match(r"^[a-z0-9][a-z0-9.-]*(:\d+)?(/.*)?$", raw, re.IGNORECASE):
        return f"http://{raw}"
    return raw


# ---------------------------------------------------------------------------
# Shared response shaping — hermes browser_tool
# ---------------------------------------------------------------------------
def _snapshot_threshold() -> int:
    """hermes browser.snapshot_threshold (default 15000, floor 1000), read
    PER CALL."""
    raw = os.environ.get("CRUSORAI_BROWSER_SNAPSHOT_THRESHOLD", "").strip()
    try:
        return max(int(raw), MIN_SNAPSHOT_THRESHOLD) if raw else DEFAULT_SNAPSHOT_THRESHOLD
    except ValueError:
        return DEFAULT_SNAPSHOT_THRESHOLD


def _redact_browser_output(value: Any) -> Any:
    """hermes browser_tool_snapshot._redact_browser_output, verbatim shape:
    force-redact secrets in browser-originated data (snapshots, console, eval
    results can carry page-rendered keys/cookies/tokens). Tool output is a
    model boundary, so this applies even when global log redaction is off."""
    from src.utils.redact import redact_sensitive_text

    if isinstance(value, str):
        return redact_sensitive_text(value, force=True)
    if isinstance(value, list):
        return [_redact_browser_output(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_browser_output(item) for item in value)
    if isinstance(value, dict):
        return {key: _redact_browser_output(item) for key, item in value.items()}
    return value


def _snapshot_fields(result: Dict[str, Any]) -> Dict[str, Any]:
    """`snapshot` + `element_count`; oversized snapshots truncate at line
    boundaries and the full tree is stored for read_file paging (hermes)."""
    data = result.get("data", {}) or {}
    snapshot_text = data.get("snapshot", "") or ""
    refs = data.get("refs") or {}
    full_path: Optional[str] = None
    threshold = _snapshot_threshold()
    if len(snapshot_text) > threshold:
        cut = snapshot_text.rfind("\n", 0, threshold)
        if cut < MIN_SNAPSHOT_THRESHOLD:
            cut = threshold
        try:
            snap_dir = _user_home() / ".crusorai" / "browser" / "snapshots"
            snap_dir.mkdir(parents=True, exist_ok=True)
            stored = snap_dir / "last-full-snapshot.txt"
            stored.write_text(snapshot_text[:MAX_STORED_SNAPSHOT_CHARS], encoding="utf-8")
            full_path = str(stored)
        except OSError:
            full_path = None
        snapshot_text = (
            snapshot_text[:cut]
            + f"\n\n[Snapshot truncated at {cut} of {len(snapshot_text)} chars."
            + (f" Full snapshot saved to {full_path} — page through it with read_file."
               if full_path else "]")
        )
    return {"snapshot": _redact_browser_output(snapshot_text),
            "element_count": len(refs) if refs else 0}


def _failed_response(result: Dict[str, Any], default_error: str) -> str:
    return _dumps(_err(result.get("error", default_error)))


def _tool_response(result: Dict[str, Any], ok: Dict[str, Any], default_error: str) -> str:
    if not result.get("success"):
        return _failed_response(result, default_error)
    return _dumps({"success": True, **ok})


def _at_ref(ref: str) -> str:
    return ref if ref.startswith("@") else f"@{ref}"


def _session_from_config(config: RunnableConfig) -> str:
    thread_id = str((config or {}).get("configurable", {}).get("thread_id") or "default")
    return _session_name(thread_id)


# ---------------------------------------------------------------------------
# The tools — hermes BROWSER_TOOL_SCHEMAS: names, contracts, descriptions.
# Descriptions are the teaching; only references to tools crusor lacks are
# adapted (web_extract -> web_fetch; the vision-tool sentence in get_images),
# per the port rule: the block never names a tool the runtime lacks.
# ---------------------------------------------------------------------------
@tool
def browser_navigate(
    url: Annotated[str, Field(description="The URL to navigate to (e.g., 'https://example.com')")],
    config: RunnableConfig = None,
) -> str:
    """Navigate to a URL in the browser. Initializes the session and loads the page. Must be called before other browser tools. The browser opens VISIBLE on the user's screen and the session is recorded to a .webm — when the user asks to 'test', 'verify', or 'try' an app, THIS is what they want to watch: these browser tools, live, not a scripted playwright/puppeteer run hidden inside the terminal. For simple information retrieval, prefer web_search or web_extract (faster, cheaper). For plain-text endpoints — URLs ending in .md, .txt, .json, .yaml, .yml, .csv, .xml, raw.githubusercontent.com, or any documented API endpoint — prefer curl via the terminal tool or web_extract; the browser stack is overkill and much slower for these. Use browser tools when you need to interact with a page (click, fill forms, dynamic content) or to verify that a web app you built actually renders and works. Returns a compact page snapshot with interactive elements and ref IDs — no need to call browser_snapshot separately after navigating."""
    session = _session_from_config(config)
    url = normalize_browser_url(url)
    policy_error = _url_policy_error(url)
    if policy_error is not None:
        return _dumps(policy_error)
    # hermes browser_navigate: only the session's FIRST navigation pays the
    # 120s cold first-open floor; every later navigation runs warm with the
    # 60s floor (hermes `_first_nav` on the session record). The recording
    # start keeps crusor's own once-per-recording-era guard (turn-scoped:
    # stop_browser_recording re-arms it, the owner's visible-testing
    # contract). _handle_command_timeout forgets the flag together with the
    # daemon it tree-killed, so a fresh daemon is cold again — hermes' rule.
    is_first_nav = session not in _FIRST_NAV_SEEN
    recording_path = maybe_start_recording(session)
    result = run_browser_command(session, "open", [url],
                                 timeout=_open_timeout(first_open=is_first_nav))
    if result.get("success"):
        _FIRST_NAV_SEEN.add(session)
        _OPEN_SESSIONS.add(session)
    if not result.get("success"):
        return _failed_response(result, "Navigation failed")
    if not is_first_nav:
        # One tab per test (hermes' one-tab rule): the new URL is already the
        # live tab, so fold the leftover pages from earlier navigations — same
        # end state as tidying first, without delaying the navigation itself.
        _consolidate_tabs(session)
    data = result.get("data", {}) or {}
    title = data.get("title", "")
    final_url = data.get("url", url)
    redirect_block = _always_blocked_url_error(final_url) if final_url and final_url != url else None
    if redirect_block is not None:
        run_browser_command(session, "open", ["about:blank"], timeout=10)
        return _dumps(redirect_block)
    response: Dict[str, Any] = {"success": True, "url": final_url, "title": title}
    if recording_path:
        # The receipt is the show: the user can watch the window now and the
        # .webm afterwards; the model can name it in its report.
        response["recording"] = recording_path
    title_lower = (title or "").lower()
    if any(pattern in title_lower for pattern in _BOT_DETECTION_TITLE_PATTERNS):
        response["bot_detection_warning"] = (
            f"Page title '{title}' suggests bot detection. The site may have blocked this request. "
            "Options: 1) Try adding delays between actions, 2) Access different pages first, "
            "3) Some sites have very aggressive bot detection that may be unavoidable.")
    snap = run_browser_command(session, "snapshot", ["-c"])
    if snap.get("success"):
        response.update(_snapshot_fields(snap))
    return _dumps(response)


@tool
def browser_snapshot(
    full: Annotated[bool, Field(description="If true, returns complete page content. If false (default), returns compact view with interactive elements only.")] = False,
    config: RunnableConfig = None,
) -> str:
    """Get a text-based snapshot of the current page's accessibility tree. Returns interactive elements with ref IDs (like @e1, @e2) for browser_click and browser_type. full=false (default): compact view with interactive elements. full=true: complete page content. Snapshots over 15000 chars are truncated; when that happens the complete snapshot is saved to a file and the output includes its path so you can page through the rest with read_file. Requires browser_navigate first. Note: browser_navigate already returns a compact snapshot — use this to refresh after interactions that change the page, or with full=true for complete content."""
    session = _session_from_config(config)
    result = run_browser_command(session, "snapshot", [] if full else ["-c"])
    if not result.get("success"):
        return _failed_response(result, "Failed to get snapshot")
    return _dumps({"success": True, **_snapshot_fields(result)})


@tool
def browser_click(
    ref: Annotated[str, Field(description="The element reference from the snapshot (e.g., '@e5', '@e12')")],
    config: RunnableConfig = None,
) -> str:
    """Click on an element identified by its ref ID from the snapshot (e.g., '@e5'). The ref IDs are shown in square brackets in the snapshot output. Requires browser_navigate and browser_snapshot to be called first."""
    session = _session_from_config(config)
    ref = _at_ref(ref)
    result = run_browser_command(session, "click", [ref])
    return _tool_response(result, {"clicked": ref}, f"Failed to click {ref}")


@tool
def browser_type(
    ref: Annotated[str, Field(description="The element reference from the snapshot (e.g., '@e3')")],
    text: Annotated[str, Field(description="The text to type into the field")],
    config: RunnableConfig = None,
) -> str:
    """Type text into an input field identified by its ref ID. Clears the field first, then types the new text. Requires browser_navigate and browser_snapshot to be called first."""
    session = _session_from_config(config)
    ref = _at_ref(ref)
    result = run_browser_command(session, "fill", [ref, text])
    if result.get("success"):
        return _dumps({"success": True, "typed": text, "element": ref})
    return _failed_response(result, f"Failed to type into {ref}")


@tool
def browser_scroll(
    direction: Annotated[Literal["up", "down"], Field(description="Direction to scroll")],
    config: RunnableConfig = None,
) -> str:
    """Scroll the page in a direction. Use this to reveal more content that may be below or above the current viewport. Requires browser_navigate to be called first."""
    # hermes validates direction in the SCHEMA (enum ["up","down"]); the body
    # trusts it -- a bad direction dies in pydantic, never here.
    session = _session_from_config(config)
    result = run_browser_command(session, "scroll", [direction, str(_SCROLL_PIXELS)])
    return _tool_response(result, {"scrolled": direction}, f"Failed to scroll {direction}")


@tool
def browser_back(config: RunnableConfig = None) -> str:
    """Navigate back to the previous page in browser history. Requires browser_navigate to be called first."""
    session = _session_from_config(config)
    result = run_browser_command(session, "back", [])
    return _tool_response(result, {"url": (result.get("data", {}) or {}).get("url", "")},
                          "Failed to go back")


@tool
def browser_press(
    key: Annotated[str, Field(description="Key to press (e.g., 'Enter', 'Tab', 'Escape', 'ArrowDown')")],
    config: RunnableConfig = None,
) -> str:
    """Press a keyboard key. Useful for submitting forms (Enter), navigating (Tab), or keyboard shortcuts. Requires browser_navigate to be called first."""
    session = _session_from_config(config)
    result = run_browser_command(session, "press", [key])
    return _tool_response(result, {"pressed": key}, f"Failed to press {key}")


@tool
def browser_console(
    clear: Annotated[bool, Field(description="If true, clear the message buffers after reading")] = False,
    expression: Annotated[str, Field(description="JavaScript expression to evaluate in the page context. Runs in the browser like DevTools console — full access to DOM, window, document. Return values are serialized to JSON. Example: 'document.title' or 'document.querySelectorAll(\"a\").length'")] = "",
    config: RunnableConfig = None,
) -> str:
    """Get browser console output and JavaScript errors from the current page. Returns console.log/warn/error/info messages and uncaught JS exceptions. Use this to detect silent JavaScript errors, failed API calls, and application warnings. Requires browser_navigate to be called first. When 'expression' is provided, evaluates JavaScript in the page context and returns the result — use this for DOM inspection, reading page state, or extracting data programmatically."""
    session = _session_from_config(config)
    if expression:
        result = run_browser_command(session, "eval", [expression])
        if not result.get("success"):
            return _failed_response(result, "Failed to evaluate expression")
        raw = (result.get("data", {}) or {}).get("result", "")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, ValueError):
            parsed = raw
        return _dumps({"success": True, "result": _redact_browser_output(parsed),
                       "result_type": type(parsed).__name__})
    clear_args = ["--clear"] if clear else []
    console_result = run_browser_command(session, "console", clear_args)
    errors_result = run_browser_command(session, "errors", clear_args)
    messages = [
        {"type": msg.get("type", "log"),
         "text": _redact_browser_output(msg.get("text", "")), "source": "console"}
        for msg in ((console_result.get("data", {}) or {}).get("messages", []) or [])
    ] if console_result.get("success") else []
    errors = [
        {"message": _redact_browser_output(err.get("message", "")), "source": "exception"}
        for err in ((errors_result.get("data", {}) or {}).get("errors", []) or [])
    ] if errors_result.get("success") else []
    return _dumps({
        "success": True, "console_messages": messages, "js_errors": errors,
        "total_messages": len(messages), "total_errors": len(errors),
    })


@tool
def browser_get_images(config: RunnableConfig = None) -> str:
    """Get a list of all images on the current page with their URLs and alt text. Useful for finding images to analyze or to confirm that a page's assets actually loaded. Requires browser_navigate to be called first."""
    session = _session_from_config(config)
    result = run_browser_command(session, "eval", [_GET_IMAGES_JS])
    if not result.get("success"):
        return _failed_response(result, "Failed to get images")
    raw = (result.get("data", {}) or {}).get("result", "[]")
    try:
        images = json.loads(raw) if isinstance(raw, str) else raw
        return _dumps({"success": True, "images": _redact_browser_output(images),
                       "count": len(images)})
    except json.JSONDecodeError:
        return _dumps({"success": True, "images": [], "count": 0,
                       "warning": "Could not parse image data"})


@tool
def browser_screenshot(name: str = "page", config: RunnableConfig = None) -> str:
    """Take a screenshot of the current page so you can inspect it visually and show the user what actually rendered. Use this when you need to understand what the page looks like — especially visual verification, complex layouts, styling problems, or cases where the text snapshot misses important visual information — and whenever the user asks for screenshots as proof. Saves to <workspace>/screenshots/<name>.png with a visual-quality receipt. Requires browser_navigate to be called first.

    Not a hermes SCHEMA — hermes reaches this agent-browser command only
    inside browser_vision (`screenshot [--full] <path>`, hermes
    _capture_vision_screenshot); the description above is hermes
    browser_vision's teaching adapted to this tool (the auxiliary
    vision-model fallback sentence is crusor's browser_vision counterpart
    that does not exist here). Crusor keeps it as its own tool because the
    deterministic verify_ui_* pipeline consumes the quality receipt; the
    backend is hermes' exactly (agent-browser screenshot command).
    """
    session = _session_from_config(config)
    configurable = (config or {}).get("configurable", {}) or {}
    workspace = os.fspath(configurable.get("workspace", ".") or ".")
    safe = "".join(c for c in (name or "page") if c.isalnum() or c in "-_") or "page"
    shot_dir = os.path.join(workspace, "screenshots")
    os.makedirs(shot_dir, exist_ok=True)
    path = os.path.join(shot_dir, f"{safe}.png")
    result = run_browser_command(session, "screenshot", ["--full", path],
                                 timeout=max(_command_timeout(), MIN_OPEN_TIMEOUT))
    if not result.get("success"):
        return _failed_response(result, "Failed to take screenshot")
    saved = (result.get("data", {}) or {}).get("path", path)
    if not os.path.exists(saved):
        return _dumps(_err(
            f"Screenshot file was not created at {saved}. This may indicate a missing "
            "Chromium install ('agent-browser install') or a stale daemon process."))
    from src.tools.visual_quality import analyze_screenshot, format_quality_receipt
    quality = analyze_screenshot(saved)
    marker = "✅" if quality.get("passed") else "⚠️"
    try:
        rel = os.path.relpath(saved, start=workspace)
    except ValueError:
        rel = saved
    size = os.path.getsize(saved)
    return (f"{marker} Screenshot saved: {rel} ({size} bytes). "
            f"{format_quality_receipt(quality)}")


BROWSER_TOOLS = [
    browser_navigate, browser_snapshot, browser_click, browser_type,
    browser_scroll, browser_back, browser_press, browser_console,
    browser_get_images, browser_screenshot,
]
