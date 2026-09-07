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

NOT ported (hermes has them; pulse lacks the plumbing — stated, not
silently dropped): browser_vision (needs an aux vision-model call — pulse
has no image-carrying message pipeline yet), cloud providers
(Browserbase/browser-use), Camofox, CDP supervisor, Lightpanda engine
fallback, real-profile Chrome, session recording. The SSRF page-guard is
a cloud-mode protection in hermes and fails open for local backends; the
local floors (secret URLs, metadata endpoints) ARE kept.

Replaces browser_mcp.py (puppeteer-MCP lab backend with a hardcoded
Administrator-path server directory — never hermes' implementation, and
unspawnable on any machine but the lab's).

`PULSEAI_AGENT_BROWSER` — explicit path override for the CLI, read PER
CALL (standing rule). `PULSEAI_BROWSER_INACTIVITY_TIMEOUT` — session idle
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
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

# ---------------------------------------------------------------------------
# hermes constants (tools/browser_tool.py)
# ---------------------------------------------------------------------------
NPX_AGENT_BROWSER_SENTINEL = "npx agent-browser"
AGENT_BROWSER_NPX_SPEC = "agent-browser@^0.26.0"

DEFAULT_COMMAND_TIMEOUT = 30
MIN_OPEN_TIMEOUT = 60
MIN_FIRST_OPEN_TIMEOUT = 120

DEFAULT_SNAPSHOT_THRESHOLD = 15_000
MIN_SNAPSHOT_THRESHOLD = 1_000
MAX_STORED_SNAPSHOT_CHARS = 2_000_000
_EMPTY_OK_COMMANDS = frozenset({"close"})

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

# hermes blocks URLs carrying credential-shaped strings via agent.redact's
# prefix regex; this is pulse's equivalent conservative set.
_SECRET_PREFIX_RE = re.compile(
    r"(sk-[A-Za-z0-9]|ghp_[A-Za-z0-9]|gho_[A-Za-z0-9]|github_pat_|AKIA[A-Z0-9]{16}"
    r"|xox[baprs]-|Bearer\s+[A-Za-z0-9._\-]+|api[_-]?key\s*=|[A-Za-z0-9_]*token\s*=)",
    re.IGNORECASE,
)

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
# CLI resolution — hermes browser_tool_install._find_agent_browser, pulse-sized
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
    """PATH (validated) -> npx sentinel. Env override `PULSEAI_AGENT_BROWSER`
    wins per call. Raises FileNotFoundError with the install hint."""
    override = os.environ.get("PULSEAI_AGENT_BROWSER", "").strip()
    if override:
        if _validate_candidate(override):
            return override
        raise FileNotFoundError(
            f"PULSEAI_AGENT_BROWSER={override!r} is not a runnable agent-browser CLI. {_install_hint()}")
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
    return f"pulseai-{sanitized[:60]}"


def _session_socket_dir(session_name: str) -> str:
    """hermes gives each session its own socket dir so parallel daemons never
    share one; agent-browser reads it from the env."""
    d = os.path.join(tempfile.gettempdir(), f"agent-browser-{session_name}")
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def _inactivity_timeout_s() -> int:
    raw = os.environ.get("PULSEAI_BROWSER_INACTIVITY_TIMEOUT", "").strip()
    try:
        val = int(raw) if raw else DEFAULT_SESSION_INACTIVITY_TIMEOUT
    except ValueError:
        val = DEFAULT_SESSION_INACTIVITY_TIMEOUT
    return max(val, _MIN_INACTIVITY_S)


# ---------------------------------------------------------------------------
# Visible testing — hermes headed flag + record start/stop, owner-defaulted on
# ---------------------------------------------------------------------------
_ON_WORDS = {"on", "1", "true", "yes", "enabled"}
_OFF_WORDS = {"off", "0", "false", "no", "disabled"}


def headed_mode() -> bool:
    """hermes browser_tool_cloud._is_headed_mode, env-shaped: the browser
    window opens VISIBLE by default (owner 2026-09-07: 'in front of users
    eyes'); PULSEAI_BROWSER_HEADED=off restores hermes' headless default."""
    raw = os.environ.get("PULSEAI_BROWSER_HEADED", "").strip().lower()
    if raw in _OFF_WORDS:
        return False
    if raw in _ON_WORDS:
        return True
    return True


_recording_lock = threading.Lock()
_RECORDING_SESSIONS: set[str] = set()  # hermes _recording_sessions shape


def recording_enabled() -> bool:
    """hermes gates on browser.record_sessions (default False); pulse defaults
    ON per the owner's visible-testing direction. PULSEAI_BROWSER_RECORD=off
    restores hermes' posture."""
    raw = os.environ.get("PULSEAI_BROWSER_RECORD", "").strip().lower()
    if raw in _OFF_WORDS:
        return False
    if raw in _ON_WORDS:
        return True
    return True


def recordings_dir() -> Path:
    """hermes: <hermes_home>/browser_recordings, cleaned at 72h. Pulse: under
    the home dot-dir, with an env override for desktop installs."""
    override = os.environ.get("PULSEAI_BROWSER_RECORDINGS_DIR", "").strip()
    base = Path(override) if override else Path.home() / ".pulseai" / "browser_recordings"
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
    end is pulse's closest equivalent of session close."""
    return stop_browser_recording(_session_name(thread_id))


def _command_env(session_name: str) -> Dict[str, str]:
    env = dict(os.environ)
    env["AGENT_BROWSER_SOCKET_DIR"] = _session_socket_dir(session_name)
    # Daemon-side idle self-termination (agent-browser 0.24+), mirroring hermes'
    # janitor, unless the operator set the knob explicitly.
    if "AGENT_BROWSER_IDLE_TIMEOUT_MS" not in env:
        env["AGENT_BROWSER_IDLE_TIMEOUT_MS"] = str(_inactivity_timeout_s() * 1000)
    return env


def _command_timeout() -> int:
    return DEFAULT_COMMAND_TIMEOUT


def _open_timeout(*, first_open: bool) -> int:
    """Floors for `open`: cold daemon + first Chromium launch can exceed the
    generic timeout on slow hosts (hermes MIN_OPEN_TIMEOUT family)."""
    base = _command_timeout()
    return max(base, MIN_FIRST_OPEN_TIMEOUT if first_open else MIN_OPEN_TIMEOUT)


def build_session_args(session: str) -> List[str]:
    """hermes browser_tool_session (:589-591): local sessions ride
    `--session <name>`, plus `--headed` when the window should be visible
    (hermes _is_headed_mode; pulse default ON — owner visible-testing)."""
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
        return {"success": False,
                "error": f"Non-JSON output from agent-browser for '{command}': {raw}"}
    if isinstance(parsed, dict) and "success" in parsed:
        return parsed
    return {"success": True, "data": parsed if isinstance(parsed, dict) else {"result": parsed}}


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
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd_parts, capture_output=True, text=True, timeout=timeout,
            shell=False, env=_command_env(session),
        )
    except subprocess.TimeoutExpired:
        invalidate_cli_cache()
        return {"success": False,
                "error": f"Browser command '{command}' timed out after {timeout}s. "
                         "The daemon may be wedged; retry once, then report to the user."}
    except OSError as exc:
        invalidate_cli_cache()
        return {"success": False, "error": f"Failed to launch agent-browser: {exc}"}
    if proc.returncode != 0:
        # A nonzero rc from a previously-cached path can mean the binary vanished
        # (npm re-link) — drop the cache so the next call re-resolves (hermes).
        invalidate_cli_cache()
    return _interpret_output(command, proc.stdout or "", proc.stderr or "", proc.returncode)


# ---------------------------------------------------------------------------
# URL floors — hermes browser_tool._secret_url_error / _is_always_blocked_url
# ---------------------------------------------------------------------------
def _secret_url_error(url: str) -> Optional[Dict[str, Any]]:
    if _SECRET_PREFIX_RE.search(url):
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


# ---------------------------------------------------------------------------
# Shared response shaping — hermes browser_tool
# ---------------------------------------------------------------------------
def _snapshot_fields(result: Dict[str, Any]) -> Dict[str, Any]:
    """`snapshot` + `element_count`; oversized snapshots truncate at line
    boundaries and the full tree is stored for read_file paging (hermes)."""
    data = result.get("data", {}) or {}
    snapshot_text = data.get("snapshot", "") or ""
    refs = data.get("refs") or {}
    full_path: Optional[str] = None
    if len(snapshot_text) > DEFAULT_SNAPSHOT_THRESHOLD:
        cut = snapshot_text.rfind("\n", 0, DEFAULT_SNAPSHOT_THRESHOLD)
        if cut < MIN_SNAPSHOT_THRESHOLD:
            cut = DEFAULT_SNAPSHOT_THRESHOLD
        try:
            snap_dir = Path(tempfile.gettempdir()) / "pulseai-browser-snapshots"
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
    return {"snapshot": snapshot_text, "element_count": len(refs) if refs else 0}


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
# Descriptions are the teaching; only references to tools pulse lacks are
# adapted (web_extract -> web_fetch; the vision-tool sentence in get_images),
# per the port rule: the block never names a tool the runtime lacks.
# ---------------------------------------------------------------------------
@tool
def browser_navigate(url: str, config: RunnableConfig = None) -> str:
    """Navigate to a URL in the browser. Initializes the session and loads the page. Must be called before other browser tools. The browser opens VISIBLE on the user's screen and the session is recorded to a .webm — when the user asks to 'test', 'verify', or 'try' an app, THIS is what they want to watch: these browser tools, live, not a scripted playwright/puppeteer run hidden inside the terminal. For simple information retrieval, prefer web_search or web_fetch (faster, cheaper). For plain-text endpoints — URLs ending in .md, .txt, .json, .yaml, .yml, .csv, .xml, raw.githubusercontent.com, or any documented API endpoint — prefer curl via the terminal tool or web_fetch; the browser stack is overkill and much slower for these. Use browser tools when you need to interact with a page (click, fill forms, dynamic content) or to verify that a web app you built actually renders and works. Returns a compact page snapshot with interactive elements and ref IDs — no need to call browser_snapshot separately after navigating."""
    session = _session_from_config(config)
    policy_error = _url_policy_error(url)
    if policy_error is not None:
        return _dumps(policy_error)
    recording_path = maybe_start_recording(session)
    result = run_browser_command(session, "open", [url], timeout=_open_timeout(first_open=True))
    if not result.get("success"):
        return _failed_response(result, "Navigation failed")
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
def browser_snapshot(full: bool = False, config: RunnableConfig = None) -> str:
    """Get a text-based snapshot of the current page's accessibility tree. Returns interactive elements with ref IDs (like @e1, @e2) for browser_click and browser_type. full=false (default): compact view with interactive elements. full=true: complete page content. Snapshots over 15000 chars are truncated; when that happens the complete snapshot is saved to a file and the output includes its path so you can page through the rest with read_file. Requires browser_navigate first. Note: browser_navigate already returns a compact snapshot — use this to refresh after interactions that change the page, or with full=true for complete content."""
    session = _session_from_config(config)
    result = run_browser_command(session, "snapshot", [] if full else ["-c"])
    if not result.get("success"):
        return _failed_response(result, "Failed to get snapshot")
    return _dumps({"success": True, **_snapshot_fields(result)})


@tool
def browser_click(ref: str, config: RunnableConfig = None) -> str:
    """Click on an element identified by its ref ID from the snapshot (e.g., '@e5'). The ref IDs are shown in square brackets in the snapshot output. Requires browser_navigate and browser_snapshot to be called first."""
    session = _session_from_config(config)
    ref = _at_ref(ref)
    result = run_browser_command(session, "click", [ref])
    return _tool_response(result, {"clicked": ref}, f"Failed to click {ref}")


@tool
def browser_type(ref: str, text: str, config: RunnableConfig = None) -> str:
    """Type text into an input field identified by its ref ID. Clears the field first, then types the new text. Requires browser_navigate and browser_snapshot to be called first."""
    session = _session_from_config(config)
    ref = _at_ref(ref)
    result = run_browser_command(session, "fill", [ref, text])
    if result.get("success"):
        return _dumps({"success": True, "typed": text, "element": ref})
    return _failed_response(result, f"Failed to type into {ref}")


@tool
def browser_scroll(direction: str, config: RunnableConfig = None) -> str:
    """Scroll the page in a direction. Use this to reveal more content that may be below or above the current viewport. Requires browser_navigate to be called first."""
    if direction not in {"up", "down"}:
        return _dumps(_err(f"Invalid direction '{direction}'. Use 'up' or 'down'."))
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
def browser_press(key: str, config: RunnableConfig = None) -> str:
    """Press a keyboard key. Useful for submitting forms (Enter), navigating (Tab), or keyboard shortcuts. Requires browser_navigate to be called first."""
    session = _session_from_config(config)
    result = run_browser_command(session, "press", [key])
    return _tool_response(result, {"pressed": key}, f"Failed to press {key}")


@tool
def browser_console(clear: bool = False, expression: str = "", config: RunnableConfig = None) -> str:
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
        return _dumps({"success": True, "result": parsed,
                       "result_type": type(parsed).__name__})
    clear_args = ["--clear"] if clear else []
    console_result = run_browser_command(session, "console", clear_args)
    errors_result = run_browser_command(session, "errors", clear_args)
    messages = [
        {"type": msg.get("type", "log"), "text": msg.get("text", ""), "source": "console"}
        for msg in ((console_result.get("data", {}) or {}).get("messages", []) or [])
    ] if console_result.get("success") else []
    errors = [
        {"message": err.get("message", ""), "source": "exception"}
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
        return _dumps({"success": True, "images": images, "count": len(images)})
    except json.JSONDecodeError:
        return _dumps({"success": True, "images": [], "count": 0,
                       "warning": "Could not parse image data"})


@tool
def browser_screenshot(name: str = "page", config: RunnableConfig = None) -> str:
    """Capture a screenshot of the current page and save it to <workspace>/screenshots/<name>.png, with a visual-quality receipt. Use after browser_snapshot to leave visual proof of what rendered. Requires browser_navigate to be called first.

    Not a hermes SCHEMA — hermes reaches this agent-browser command only
    inside browser_vision (`screenshot [--full] <path>`, hermes
    _capture_vision_screenshot). Pulse keeps it as its own tool because the
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
