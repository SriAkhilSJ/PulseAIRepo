"""One-receipt UI verification pipelines.

The model decides *what* must be verified once. Deterministic runtime code owns
the mechanical sequence: typecheck, start, readiness, navigate, snapshot,
screenshot-quality check, cleanup. This mirrors Hermes' verify runner and avoids
spending an API call between every predictable operation.
"""
from __future__ import annotations

import re
import time

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool


def _safe_route_name(route: str) -> str:
    token = route.strip().strip("/") or "home"
    return "-".join(part for part in token.replace("_", "-").split("/") if part) or "home"


def _start_ready_server(command: str, config: RunnableConfig) -> tuple[str | None, str]:
    from src.tools.terminal_tools import start_terminal, check_terminal

    started = str(start_terminal.invoke({"command": command}, config=config))
    match = re.search(r"Process ID:\s*([A-Za-z0-9_-]+)", started)
    if not match:
        return None, "failed to start server:\n" + started
    process_id = match.group(1)
    deadline = time.monotonic() + 120
    last = ""
    while time.monotonic() < deadline:
        last = str(check_terminal.invoke({"process_id": process_id, "wait_seconds": 5}))
        low = last.lower()
        if any(marker in low for marker in ("ready in", "listening on", "server running", "local:")):
            return process_id, last
        if "status: completed" in low:
            break
    return process_id, "server never became ready:\n" + last[-3000:]


def _native_javascript_syntax(workspace) -> tuple[bool, str]:
    """Syntax-check authored browser JavaScript as modules, without TypeScript."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        return False, "❌ native JavaScript syntax check requires Node.js, but node was not found."
    skipped = {".git", "node_modules", "vendor", "dist", "build", "out", "coverage"}
    paths = []
    for path in workspace.rglob("*"):
        try:
            relative = path.relative_to(workspace)
            if any(part in skipped for part in relative.parts):
                continue
            if path.is_file() and path.suffix.lower() in {".js", ".mjs", ".cjs"}:
                paths.append(path)
        except OSError:
            continue
    if len(paths) > 200:
        return False, f"❌ native JavaScript syntax check refused {len(paths)} files (limit: 200)."
    for path in sorted(paths):
        try:
            source = path.read_text(encoding="utf-8")
            mode = "commonjs" if path.suffix.lower() == ".cjs" else "module"
            proc = subprocess.run(
                [node, "--check", f"--input-type={mode}"], input=source,
                cwd=str(workspace), capture_output=True, text=True, timeout=10,
            )
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
            return False, f"❌ could not syntax-check {path.relative_to(workspace)}: {exc}"
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "syntax error").strip()
            return False, f"❌ JavaScript syntax failed in {path.relative_to(workspace)}:\n{detail[-2000:]}"
    return True, f"✅ native JavaScript syntax passed ({len(paths)} authored file(s))."


def _verify_source_workspace(config: RunnableConfig) -> tuple[bool, str]:
    """Use tsc when applicable; otherwise audit a native HTML/JS workspace.

    A missing TypeScript setup is not a product failure for plain browser
    projects. Their static prerequisite is complete local HTML/import
    dependencies; the browser stage below then supplies the runtime proof.
    """
    from pathlib import Path
    from src.context.workspace_integrity import audit_workspace
    from src.tools.file_tools import typecheck_workspace

    typecheck = str(typecheck_workspace.invoke({}, config=config))
    if typecheck.startswith("✅"):
        return True, typecheck

    workspace = Path(config["configurable"]["workspace"]).resolve()
    native_web = not (workspace / "tsconfig.json").is_file() and any(workspace.rglob("*.html"))
    if not native_web:
        return False, typecheck

    issues = audit_workspace(workspace)
    if issues:
        details = "\n".join(f"- {issue.describe()}" for issue in issues[:30])
        if len(issues) > 30:
            details += f"\n- ... {len(issues) - 30} more issue(s)"
        return False, (
            f"❌ static web integrity found {len(issues)} unresolved dependency issue(s):\n"
            + details
        )
    syntax_ok, syntax_receipt = _native_javascript_syntax(workspace)
    if not syntax_ok:
        return False, syntax_receipt
    return True, (
        "✅ static web integrity passed: native HTML/JavaScript project has "
        "no unresolved local HTML or module dependencies. " + syntax_receipt
        + " Runtime proof follows."
    )


def _verify_one_url(
    url: str, screenshot_name: str, config: RunnableConfig,
    required_selector: str = "",
) -> tuple[bool, str]:
    from src.tools.browser_mcp import (
        browser_navigate, browser_snapshot, browser_screenshot, browser_evaluate,
    )

    navigate = str(browser_navigate.invoke({"url": url}, config=config))
    if any(marker in navigate.lower() for marker in (
        "failed", "error", "timed out", "internal server error", "status of 500",
    )):
        return False, "navigation failed:\n" + navigate

    snapshot = str(browser_snapshot.invoke({}, config=config))
    normalized = snapshot.replace('\\"', '"')
    has_text = bool(re.search(r'"(?:title|text)":\s*"[^"\n]+', normalized))
    if not has_text:
        return False, "browser snapshot was empty:\n" + snapshot[-3000:]

    selector_receipt = ""
    if required_selector:
        selector = required_selector.replace("\\", "\\\\").replace("'", "\\'")
        script = (
            "JSON.stringify((()=>{const xs=[...document.querySelectorAll('" + selector + "')];"
            "return {count:xs.length,videos:xs.filter(x=>x.tagName==='VIDEO').map(v=>"
            "({autoplay:v.autoplay,muted:v.muted,loop:v.loop,playsInline:v.playsInline," 
            "preload:v.preload,readyState:v.readyState}))}})())"
        )
        selector_receipt = ""
        norm = ""
        # Give remote/video media a bounded chance to reach HAVE_CURRENT_DATA;
        # this is real playback readiness, not merely a <video> tag existing.
        for _ in range(9):
            selector_receipt = str(browser_evaluate.invoke({"script": script}, config=config))
            norm = selector_receipt.replace('\\"', '"')
            if required_selector.lower() != "video" or any(
                int(value) >= 2 for value in re.findall(r'"readyState":(\d+)', norm)
            ):
                break
            time.sleep(1)
        count_match = re.search(r'"count":(\d+)', norm)
        if not count_match or int(count_match.group(1)) < 1:
            return False, f"required selector {required_selector!r} was not rendered:\n" + selector_receipt
        if required_selector.lower() == "video":
            if not all(
                marker in norm for marker in ('"autoplay":true', '"muted":true', '"loop":true', '"playsInline":true')
            ):
                return False, "video element lacks autoplay/muted/loop/playsInline optimization:\n" + selector_receipt
            if not any(int(value) >= 2 for value in re.findall(r'"readyState":(\d+)', norm)):
                return False, "video media never reached playback-ready state:\n" + selector_receipt

    screenshot = str(browser_screenshot.invoke({"name": screenshot_name}, config=config))
    if "visual quality passed" not in screenshot.lower():
        return False, "screenshot quality failed:\n" + screenshot
    selector_line = f"\nSELECTOR: {selector_receipt[-800:]}" if selector_receipt else ""
    return True, (
        f"NAVIGATE: {navigate}\nSNAPSHOT: {snapshot[-1200:]}"
        f"{selector_line}\nSCREENSHOT: {screenshot}"
    )


@tool
def verify_ui_workspace(
    command: str,
    url: str,
    screenshot_name: str,
    config: RunnableConfig,
) -> str:
    """Typecheck and browser-verify one UI page in one deterministic call."""
    from src.tools.terminal_tools import stop_terminal

    source_ok, source_receipt = _verify_source_workspace(config)
    if not source_ok:
        return "❌ UI VERIFICATION FAILED at static source checks:\n" + source_receipt

    process_id, ready = _start_ready_server(command, config)
    if process_id is None or "never became ready" in ready or "failed to start" in ready:
        return "❌ UI VERIFICATION FAILED: " + ready
    try:
        passed, receipt = _verify_one_url(url, screenshot_name or "ui-proof", config)
        if not passed:
            return "❌ UI VERIFICATION FAILED: " + receipt
        return f"✅ UI VERIFICATION PASSED\nSTATIC SOURCE CHECK: {source_receipt}\n{receipt}"
    finally:
        try:
            stop_terminal.invoke({"process_id": process_id})
        except Exception:
            pass


@tool
def verify_ui_routes(
    command: str,
    base_url: str,
    routes: list[str],
    screenshot_prefix: str,
    required_selector: str,
    config: RunnableConfig,
) -> str:
    """Typecheck and browser-verify multiple UI routes in one tool call.

    Starts one server, checks every route sequentially in the same real browser,
    saves one quality-scored screenshot per route, and stops the server. Use for
    multi-page showcases instead of spending a model call per route.
    `required_selector` (for example `video`) must exist on every route; video
    selectors additionally prove autoplay/muted/loop/playsInline attributes.
    """
    from src.tools.terminal_tools import stop_terminal

    clean_routes = list(dict.fromkeys(str(r).strip() for r in routes if str(r).strip()))
    if not clean_routes:
        return "❌ UI ROUTE VERIFICATION FAILED: routes must not be empty."
    if len(clean_routes) > 12:
        return "❌ UI ROUTE VERIFICATION FAILED: at most 12 routes per receipt."

    source_ok, source_receipt = _verify_source_workspace(config)
    if not source_ok:
        return "❌ UI ROUTE VERIFICATION FAILED at static source checks:\n" + source_receipt

    process_id, ready = _start_ready_server(command, config)
    if process_id is None or "never became ready" in ready or "failed to start" in ready:
        return "❌ UI ROUTE VERIFICATION FAILED: " + ready

    receipts: list[str] = []
    try:
        root = base_url.rstrip("/")
        for route in clean_routes:
            path = "/" + route.lstrip("/")
            name = f"{screenshot_prefix or 'ui'}-{_safe_route_name(route)}"
            passed, receipt = _verify_one_url(
                root + path, name, config, required_selector=required_selector,
            )
            if not passed:
                return f"❌ UI ROUTE VERIFICATION FAILED for {path}: {receipt}"
            receipts.append(f"ROUTE {path}\n{receipt}")
        return (
            f"✅ UI ROUTE VERIFICATION PASSED ({len(clean_routes)}/{len(clean_routes)} routes)\n"
            f"STATIC SOURCE CHECK: {source_receipt}\n" + "\n---\n".join(receipts)
        )
    finally:
        try:
            stop_terminal.invoke({"process_id": process_id})
        except Exception:
            pass
