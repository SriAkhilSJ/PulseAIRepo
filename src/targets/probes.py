"""Deterministic Python probes used as plan stages.

Some stages are not commands: "is the dev server answering?", "did the desktop
window actually open a document?", "is the captured screenshot a real UI or a
black rectangle?", "is the app process still alive 20 seconds in?". Those are
cheap, exact checks — exactly the kind of thing a model should never spend a
turn on.

A handler receives a context mapping and returns ``(exit_code, text)``:

    workspace, artifacts_dir, request, plan, stage, index, args

``args`` comes from ``Stage.env`` (a plan-time string mapping). Tokens
``{workspace}``, ``{artifacts}``, ``{app_id}``, ``{device}`` and ``${ENV}``
references are substituted before the handler runs.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

DEFAULT_HTTP_TIMEOUT_S = 45.0
_POLL_INTERVAL_S = 0.7


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def substitute(text: str, ctx: Mapping[str, Any]) -> str:
    """Resolve ``{workspace}``-style and ``${ENV}``-style references in args."""
    request = ctx.get("request")
    plan = ctx.get("plan")
    # Resolved-at-run-time tokens (the real device serial, the newest APK) fill
    # the gaps; an explicitly requested device/app id always wins.
    values = {str(key): str(value) for key, value in dict(ctx.get("tokens") or {}).items()}
    explicit = {
        "device": str(getattr(request, "device", "") or getattr(plan, "device", "") or ""),
        "app_id": str(getattr(request, "app_id", "") or getattr(plan, "app_id", "") or ""),
        "url": str(getattr(request, "url", "") or ""),
    }
    values.update({key: value for key, value in explicit.items() if value})
    values["workspace"] = str(ctx.get("workspace") or "")
    values["artifacts"] = str(ctx.get("artifacts_dir") or "")
    out = str(text)
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return os.path.expandvars(out)


def _args(ctx: Mapping[str, Any]) -> dict[str, str]:
    raw = ctx.get("args") or {}
    return {str(key): substitute(str(value), ctx) for key, value in dict(raw).items()}


def _flag(args: Mapping[str, str], name: str, default: str = "") -> str:
    return str(args.get(name, default) or default)


def _seconds(args: Mapping[str, str], name: str, default: float) -> float:
    try:
        return max(0.0, float(args.get(name, default)))
    except (TypeError, ValueError):
        return default


def _background_records(ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    path = Path(str(ctx.get("artifacts_dir"))) / "background-pids.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _process_alive(pid: int) -> bool:
    """True only for a *running* process.

    ``os.kill(pid, 0)`` also succeeds for a zombie, which would report a crashed
    GUI app as healthy; the process table is consulted for the real state.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=15, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return True
        return f'"{pid}"' in (proc.stdout or "")
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True,
            timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    state = (proc.stdout or "").strip()
    return bool(state) and not state.startswith("Z")


def _log_tail(record: Mapping[str, Any], lines: int = 25) -> str:
    path = str(record.get("log") or "")
    if not path:
        return ""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


# --------------------------------------------------------------------------- #
# handlers
# --------------------------------------------------------------------------- #


def sleep(ctx: Mapping[str, Any]) -> tuple[int, str]:
    """Settle a UI: ``args={"seconds": "2"}``."""
    seconds = _seconds(_args(ctx), "seconds", 2.0)
    time.sleep(min(seconds, 120.0))
    return 0, f"slept {seconds:.1f}s"


def http_ready(ctx: Mapping[str, Any]) -> tuple[int, str]:
    """Poll a URL until it answers 2xx/3xx (dev servers, health endpoints)."""
    args = _args(ctx)
    url = _flag(args, "url") or str(getattr(ctx.get("request"), "url", "") or "")
    if not url:
        return 1, "http_ready needs a url (stage arg 'url' or request.url)"
    budget = _seconds(args, "timeout_s", DEFAULT_HTTP_TIMEOUT_S)
    expect_status = _flag(args, "expect_status")
    expect_text = _flag(args, "expect_text")
    deadline = time.monotonic() + budget
    last = "no attempt made"
    while True:
        last = _http_probe(url, expect_status=expect_status, expect_text=expect_text)
        if last.startswith("ok"):
            return 0, f"HTTP READY {url}\n{last}"
        if time.monotonic() >= deadline:
            return 1, f"HTTP NOT READY after {budget:.0f}s: {url}\n{last}"
        time.sleep(_POLL_INTERVAL_S)


def _http_probe(url: str, *, expect_status: str = "", expect_text: str = "") -> str:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - explicit operator URL
            status = int(getattr(response, "status", 0) or 0)
            body = response.read(4096)
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return f"http {exc.code}: {exc.reason}"
    except (urllib.error.URLError, ValueError, OSError) as exc:
        return f"unreachable: {exc}"
    text = body.decode("utf-8", "replace")
    if expect_status and str(status) != expect_status:
        return f"status {status} != expected {expect_status}"
    if expect_text and expect_text.lower() not in text.lower():
        return f"status {status} but body does not contain {expect_text!r}"
    title = ""
    match = re.search(r"<title[^>]*>([\s\S]{0,200}?)</title>", text, re.IGNORECASE)
    if match:
        title = match.group(1).strip()
    preview = re.sub(r"\s+", " ", text)[:220]
    return (
        f"ok status={status} type={content_type or 'unknown'}"
        + (f" title={title!r}" if title else "")
        + f"\nbody: {preview}"
    )


def cdp_ready(ctx: Mapping[str, Any]) -> tuple[int, str]:
    """Prove a desktop app window is debuggable AND has opened a real document.

    Works for Electron (``--remote-debugging-port``), Tauri on Windows
    (``WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS``) and any Chromium host. A live
    port with zero page targets means the window never opened — the failure a
    green build hides.
    """
    args = _args(ctx)
    port = _flag(args, "port", "9222")
    budget = _seconds(args, "timeout_s", 30.0)
    require_page = _flag(args, "require_page", "1") not in ("0", "false", "no")
    deadline = time.monotonic() + budget
    last = "no attempt made"
    while True:
        version = _get_json(f"http://127.0.0.1:{port}/json/version")
        if isinstance(version, dict):
            browser = str(version.get("Browser") or version.get("browser") or "unknown")
            targets = _get_json(f"http://127.0.0.1:{port}/json/list")
            pages = [t for t in targets if isinstance(t, dict) and t.get("type") == "page"] \
                if isinstance(targets, list) else []
            titled = [p for p in pages if str(p.get("title") or "").strip()]
            if pages and (titled or not require_page):
                shown = [
                    f"- {str(p.get('title') or '(untitled)')[:80]} :: {str(p.get('url') or '')[:120]}"
                    for p in pages[:6]
                ]
                return 0, (
                    f"CDP READY port={port} browser={browser} pages={len(pages)}\n"
                    + "\n".join(shown)
                )
            last = f"cdp port {port} answered ({browser}) but no titled page target yet"
        else:
            last = str(version)
        if time.monotonic() >= deadline:
            return 1, f"CDP NOT READY after {budget:.0f}s on port {port}: {last}"
        time.sleep(_POLL_INTERVAL_S)


def _get_json(url: str) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - loopback only
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        return f"unreachable: {exc}"


def process_alive(ctx: Mapping[str, Any]) -> tuple[int, str]:
    """Verify a background stage (desktop app, dev server, metro) stayed up."""
    args = _args(ctx)
    budget = _seconds(args, "timeout_s", 15.0)
    name_filter = _flag(args, "name")
    records = [
        record for record in _background_records(ctx)
        if not name_filter or str(record.get("name")) == name_filter
    ]
    if not records:
        return 1, "no background process was started by this plan"
    deadline = time.monotonic() + budget
    while True:
        alive = [(r, _process_alive(int(r.get("pid") or 0))) for r in records]
        if all(state for _record, state in alive):
            pids = ", ".join(str(int(r.get("pid") or 0)) for r, _ in alive)
            return 0, f"PROCESS ALIVE ({len(alive)}): pids {pids}"
        died = [(r, state) for r, state in alive if not state]
        if time.monotonic() >= deadline:
            details = "\n".join(
                f"- {record.get('name')} pid={record.get('pid')} died\n{_log_tail(record)}"
                for record, _state in died
            )
            return 1, f"process exited before {budget:.0f}s elapsed:\n{details}"
        time.sleep(_POLL_INTERVAL_S)


def screenshot_quality(ctx: Mapping[str, Any]) -> tuple[int, str]:
    """Reject near-blank captures of a real device/app window."""
    from src.targets.evidence import screenshot_quality as _quality

    args = _args(ctx)
    path = _flag(args, "file")
    if not path:
        return 1, "screenshot_quality needs a file argument"
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(str(ctx.get("artifacts_dir"))) / candidate
    if not candidate.exists():
        return 1, f"screenshot missing: {candidate}"
    quality = _quality(candidate)
    if quality.get("passed"):
        return 0, f"SCREENSHOT {candidate.name}: {quality.get('reason')} ({_metrics(quality)})"
    return 1, f"SCREENSHOT {candidate.name} rejected: {quality.get('reason')} ({_metrics(quality)})"


def _metrics(quality: Mapping[str, Any]) -> str:
    return (
        f"{quality.get('width', '?')}x{quality.get('height', '?')} "
        f"dominant={quality.get('dominant_ratio')} luma_stddev={quality.get('luma_stddev')} "
        f"edge_density={quality.get('edge_density')}"
    )


def file_contains(ctx: Mapping[str, Any]) -> tuple[int, str]:
    """Assert a workspace/evidence file exists and contains a marker."""
    args = _args(ctx)
    path = _flag(args, "file")
    needle = _flag(args, "contains")
    if not path:
        return 1, "file_contains needs a file argument"
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path(str(ctx.get("workspace"))) / candidate
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return 1, f"could not read {candidate}: {exc}"
    if needle and needle.lower() not in text.lower():
        return 1, f"{candidate.name} does not contain {needle!r}"
    return 0, f"{candidate.name}: {len(text)} chars" + (f", contains {needle!r}" if needle else "")


def wait_for_file(ctx: Mapping[str, Any]) -> tuple[int, str]:
    """Poll for a build output (an APK, a bundle) up to ``timeout_s``."""
    args = _args(ctx)
    pattern = _flag(args, "file")
    budget = _seconds(args, "timeout_s", 20.0)
    if not pattern:
        return 1, "wait_for_file needs a file pattern"
    root = Path(str(ctx.get("workspace")))
    deadline = time.monotonic() + budget
    while True:
        matches = sorted(root.glob(pattern))
        if matches:
            newest = max(matches, key=lambda p: p.stat().st_mtime if p.exists() else 0)
            return 0, f"FOUND {newest.relative_to(root).as_posix()}"
        if time.monotonic() >= deadline:
            return 1, f"no file matched {pattern!r} under {root} after {budget:.0f}s"
        time.sleep(_POLL_INTERVAL_S)


HANDLERS = {
    "sleep": sleep,
    "http_ready": http_ready,
    "cdp_ready": cdp_ready,
    "process_alive": process_alive,
    "screenshot_quality": screenshot_quality,
    "file_contains": file_contains,
    "wait_for_file": wait_for_file,
}


__all__ = list(HANDLERS) + ["HANDLERS", "substitute"]
