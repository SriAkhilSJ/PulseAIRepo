"""P0.6.4 desktop acceptance harness orchestration.

Runs three independent evidence lanes under ONE immutable run id and writes an
append-only ledger plus a report:

1. **Electron lane** — launch the real ``CrusorAI.exe``, prove the process
   facts, prove the debugging port is loopback-only, attach over CDP to the
   real renderer, confirm the page belongs to the app, locate the composer,
   capture renderer console/exception state and a screenshot.
2. **Bridge lane** — drive the real ``python -m src.bridge`` over its shipped
   protocol (handshake, session mint, workspace binding, clean shutdown) with
   a frame allowlist that makes a paid provider frame impossible.
3. **Governance lane** — offline budget arithmetic, retry/failover posture,
   FinOps state read, and Code OSS Invariant 7 drift.

No prompt is entered, no turn is submitted, and no provider is called.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.crusor_desktop_acceptance.bridge_probe import (
    BridgeProbe,
    BridgeProbeError,
    validate_probe_frames,
)
from benchmarks.crusor_desktop_acceptance.cdp_client import (
    CdpClient,
    CdpError,
    parse_targets,
    pick_page_target,
)
from benchmarks.crusor_desktop_acceptance.correlation import (
    Correlator,
    RunContext,
    utc_now_iso,
    workspace_id,
)
from benchmarks.crusor_desktop_acceptance.desktop_launcher import (
    LaunchError,
    allocate_loopback_port,
    capture_identity,
    crash_signature,
    launch_app,
    read_argv_config_override,
    read_devtools_active_port,
    read_product,
    stop_app,
    wait_for_cdp,
    wait_for_devtools,
    wait_for_page_target,
)
from benchmarks.crusor_desktop_acceptance.invariant7 import check_invariant7
from benchmarks.crusor_desktop_acceptance.processes import collect_tree
from benchmarks.crusor_desktop_acceptance.provider_finops import (
    preflight_estimate,
    provider_retry_configuration,
)
from benchmarks.crusor_desktop_acceptance.renderer_observer import (
    COMPOSER_SELECTOR,
    collect_console,
    observe_composer,
    observe_renderer,
    save_screenshot,
)


@dataclass
class HarnessOptions:
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    evidence_dir: Path | None = None
    workspace: Path | None = None
    # 0 = allocate a free loopback port per launch (preferred). A fixed value is
    # still accepted for reproducing an existing environment.
    port: int = 0
    launch_timeout_s: float = 120.0
    bridge_timeout_s: float = 120.0
    skip_desktop: bool = False
    skip_bridge: bool = False
    keep_app_running: bool = False
    max_output_tokens: int = 2048
    budget_inr: float = 5.00

    def resolved_evidence_dir(self) -> Path:
        if self.evidence_dir:
            return Path(self.evidence_dir).resolve()
        return (Path(self.repo_root) / "diagnostics" / "p0_6_4").resolve()


def git_info(repo_root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            completed = subprocess.run(
                ["git", *args], cwd=str(repo_root), capture_output=True, text=True, timeout=120,
            )
            return completed.stdout.strip() if completed.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""

    return {
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "head": run("rev-parse", "HEAD"),
        "head_short": run("rev-parse", "--short", "HEAD"),
        "dirty_entries": len([line for line in run("status", "--porcelain").splitlines() if line.strip()]),
        "desktop_vscode_dirty_entries": len([
            line for line in run("status", "--porcelain", "--", "desktop/vscode").splitlines() if line.strip()
        ]),
    }


def _desktop_requirements() -> dict[str, list[tuple[str, str]]]:
    return {
        "1. real Electron executable running": [("electron", "electron.launch"), ("electron", "electron.identity")],
        "2. actual CDP connection to renderer": [
            ("renderer", "cdp.version"),
            ("renderer", "cdp.target"),
            ("renderer", "renderer.identity"),
        ],
        "3. composer textarea.crusorai-composer-input located": [
            ("renderer", "renderer.workbench_ready"),
            ("renderer", "composer.found"),
        ],
        "4. prompt entered through composer": [("renderer", "ui.submit")],
        "5. UI submission action triggered": [("renderer", "ui.submit")],
        "6. worker + bridge handled same session": [("worker", "worker.launch"), ("bridge", "bridge.handshake")],
        "7. provider request belongs to same turn": [("provider", "provider.dispatch")],
        "8. artifact belongs to same execution": [("mutation", "mutation.receipt")],
        "9. final response rendered in panel": [("renderer", "render.response")],
        "10. renderer console: zero unhandled exceptions": [("renderer", "renderer.console")],
    }


class DesktopAcceptanceHarness:
    def __init__(self, options: HarnessOptions | None = None) -> None:
        self.options = options or HarnessOptions()
        self.repo_root = Path(self.options.repo_root).resolve()
        self.vscode_root = self.repo_root / "desktop" / "vscode"
        evidence_dir = self.options.resolved_evidence_dir()
        workspace = self.options.workspace or Path(
            tempfile.mkdtemp(prefix="crusor_p0_6_4_workspace_")
        )
        self.workspace = Path(workspace).resolve()
        self.ctx = RunContext(
            evidence_dir,
            phase="P0.6.4",
            workspace=str(self.workspace),
        )
        self.logs_dir = evidence_dir / "logs"
        self.screens_dir = evidence_dir / "screenshots"
        self.errors: list[str] = []

    # -- lane 1: process + renderer ---------------------------------------

    def _record_console(self, pid: int, console: dict[str, Any], *, kind: str) -> None:
        self.ctx.record(
            "renderer", kind,
            {
                "installed": console.get("installed"),
                "unhandled_errors": len(console.get("errors") or []),
                "unhandled_rejections": len(console.get("rejects") or []),
                "console_errors": len(console.get("consoleErrors") or []),
                "console_warnings": len(console.get("consoleWarns") or []),
                "samples": {
                    "errors": (console.get("errors") or [])[:5],
                    "rejects": (console.get("rejects") or [])[:5],
                    "consoleErrors": (console.get("consoleErrors") or [])[:5],
                },
            },
            pid=pid,
        )

    def _desktop_lane(self) -> dict[str, Any]:
        result: dict[str, Any] = {"attempted": True, "ok": False}
        app = None
        client = None
        port = int(self.options.port) or allocate_loopback_port()
        result["requested_port"] = port
        portable_dir = self.ctx.evidence_dir / "portable"
        try:
            # Root-cause evidence: the per-user argv.json that VS Code re-applies.
            self.ctx.record(
                "electron", "electron.argv_config",
                {"user_override": read_argv_config_override(),
                 "acceptance_portable_dir": str(portable_dir),
                 "requested_port": port},
            )
            app = launch_app(
                vscode_root=self.vscode_root,
                workspace=self.workspace,
                port=port,
                logs_dir=self.logs_dir,
                user_data_dir=self.ctx.evidence_dir / "user-data",
                portable_dir=portable_dir,
            )
            result["pid"] = app.pid
            self.ctx.record(
                "electron", "electron.launch",
                {"exe": str(app.exe), "args": app.args, "workspace": str(self.workspace),
                 "debug_port": app.port, "started_at": app.started_at,
                 "stdout_log": app.stdout_path, "stderr_log": app.stderr_path},
                pid=app.pid,
                workspace=str(self.workspace),
            )

            listener = wait_for_devtools(app, timeout_s=self.options.launch_timeout_s)
            self.ctx.record("electron", "electron.debug_port", listener, pid=app.pid)
            effective_port = int(listener.get("port") or app.port)

            version = wait_for_cdp(effective_port, timeout_s=self.options.launch_timeout_s)
            identity = capture_identity(app, self.vscode_root)
            self.ctx.record("electron", "electron.identity", identity, pid=app.pid)

            targets_raw = wait_for_page_target(effective_port, timeout_s=self.options.launch_timeout_s)
            target = pick_page_target(
                parse_targets(json.dumps(targets_raw)),
                prefer_title=str((read_product(self.vscode_root).get("nameLong") or "")),
            )
            self.ctx.record(
                "renderer", "cdp.version",
                {"browser": version.get("Browser"), "protocol_version": version.get("Protocol-Version"),
                 "target_count": len(targets_raw), "effective_port": effective_port,
                 "requested_port": app.port},
                pid=app.pid,
            )
            self.ctx.record("renderer", "cdp.target", target.to_dict(), pid=app.pid)

            client = CdpClient(target.websocket_url)
            client.connect()
            client.call("Runtime.enable")
            client.call("Page.enable")
            client.call("Log.enable")

            observation = observe_renderer(
                client,
                expected_name=str(read_product(self.vscode_root).get("nameShort") or "CrusorAI"),
                screenshot_dir=self.screens_dir,
            )
            result["observation"] = observation.to_dict()
            result["belongs_to_crusor"] = observation.belongs_to_crusor
            self.ctx.record(
                "renderer", "renderer.identity_failed" if not observation.belongs_to_crusor else "renderer.identity",
                {"page": observation.page_identity, "belongs": observation.belongs_to_crusor,
                 "reason": observation.belongs_reason, "workbench_ready": observation.workbench_ready},
                pid=app.pid,
            )
            if observation.workbench_ready:
                self.ctx.record(
                    "renderer", "renderer.workbench_ready",
                    {"selector": ".monaco-workbench", "title": observation.page_identity.get("title"),
                     "url": observation.page_identity.get("url")},
                    pid=app.pid,
                )
            self.ctx.record(
                "renderer", "composer.inspect",
                {"selector": COMPOSER_SELECTOR, "snapshot": observation.composer,
                 "focus_attempts": observation.focus_attempts,
                 "screenshots": observation.screenshots},
                pid=app.pid,
                workspace=str(self.workspace),
            )
            if int(observation.composer.get("count") or 0) > 0:
                self.ctx.record(
                    "renderer", "composer.found",
                    {"selector": COMPOSER_SELECTOR,
                     "visible": observation.composer.get("visible"),
                     "enabled": observation.composer.get("enabled"),
                     "placeholder": observation.composer.get("placeholder")},
                    pid=app.pid,
                    workspace=str(self.workspace),
                )
            # The console buckets are drained by observe_renderer; record THAT
            # snapshot (it is the evidence for the install/focus window) rather
            # than an empty re-read.
            self._record_console(app.pid, observation.console, kind="renderer.console")
            result["console"] = observation.console

            # Post-focus screenshot of the real panel, when the composer exists.
            if observation.screenshots:
                result["screenshot"] = observation.screenshots[-1]
            if int(observation.composer.get("count") or 0) > 0:
                try:
                    shot = save_screenshot(client, self.screens_dir / "renderer-composer.png")
                    observation.screenshots.append(str(shot))
                    result["screenshot"] = str(shot)
                    self.ctx.record(
                        "renderer", "renderer.screenshot",
                        {"path": str(shot), "selector": COMPOSER_SELECTOR,
                         "composer_count": observation.composer.get("count")},
                        pid=app.pid,
                    )
                except CdpError as exc:
                    self.errors.append(f"screenshot failed: {exc}")

            # Worker/bridge process evidence from the live app's own tree.
            tree = collect_tree(app.pid)
            python_procs = tree.find("python")
            worker_modules = tree.find("crusorAI")
            self.ctx.record(
                "worker", "worker.process_tree",
                {
                    "root_pid": app.pid,
                    "descendants": [proc.to_dict() for proc in tree.descendants],
                    "python_processes": [proc.to_dict() for proc in python_procs],
                    "engine_module_processes": [proc.to_dict() for proc in worker_modules],
                    "captured_at": tree.captured_at,
                },
                pid=app.pid,
            )
            if python_procs:
                self.ctx.record(
                    "worker", "worker.launch",
                    {"bridge_pids": [proc.pid for proc in python_procs],
                     "command_lines": [proc.command_line for proc in python_procs]},
                    pid=app.pid,
                )
            result["python_descendants"] = [proc.to_dict() for proc in python_procs]

            # Tail console (anything raised between focus and now).
            tail = collect_console(client)
            result["console_tail"] = tail
            self._record_console(app.pid, tail, kind="renderer.console_tail")
            result["ok"] = bool(observation.belongs_to_crusor and int(observation.composer.get("count") or 0) > 0)
        except (LaunchError, CdpError, OSError, ValueError) as exc:
            self.errors.append(f"desktop lane: {type(exc).__name__}: {exc}")
            exit_code = None
            if app is not None and app.process is not None:
                exit_code = app.process.poll()
            self.ctx.record(
                "electron", "electron.launch_failed",
                {
                    "error": f"{type(exc).__name__}: {exc}",
                    "exit_code": exit_code,
                    "requested_port": port,
                    "devtools_active_port": read_devtools_active_port(app.user_data_dir) if app is not None else None,
                    "stderr_signature": crash_signature(app.stderr_path) if app is not None else {},
                },
                pid=app.pid if app is not None else None,
            )
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["exit_code"] = exit_code
        finally:
            if client is not None:
                client.close()
            if app is not None and not self.options.keep_app_running:
                shutdown = stop_app(app)
                self.ctx.record("electron", "electron.stop", shutdown, pid=app.pid)
                result["shutdown"] = shutdown
        return result

    # -- lane 2: bridge ----------------------------------------------------

    def _bridge_lane(self) -> dict[str, Any]:
        result: dict[str, Any] = {"attempted": True, "ok": False}
        probe = BridgeProbe(self.repo_root)
        try:
            probe_result = probe.run_lifecycle(str(self.workspace))
            validation = validate_probe_frames(probe_result)
            payload = probe_result.to_dict()
            payload["validation"] = validation
            result["probe"] = payload
            result["ok"] = bool(validation.get("passed"))

            self.ctx.record(
                "bridge", "bridge.launch",
                {"python": probe_result.python_executable, "python_version": probe_result.python_version,
                 "engine_root": probe_result.engine_root, "pid": probe_result.pid,
                 "command": [probe_result.python_executable, "-m", "src.bridge"]},
                pid=probe_result.pid,
                workspace=str(self.workspace),
            )
            self.ctx.record(
                "bridge", "bridge.handshake",
                {"frame": probe_result.handshake, "validation": validation["checks"]},
                pid=probe_result.pid,
                workspace=str(self.workspace),
            )
            self.ctx.record(
                "bridge", "bridge.session",
                {"session": probe_result.session, "workspace_bound": probe_result.workspace_bound},
                session_id=str((probe_result.session or {}).get("session_id") or ""),
                pid=probe_result.pid,
                workspace=str(self.workspace),
            )
            self.ctx.record(
                "bridge", "bridge.frames",
                {"frames_in": probe_result.frames_in,
                 "frames_out": probe_result.frames_out,
                 "paid_frames_sent": 0},
                pid=probe_result.pid,
            )
            self.ctx.record(
                "bridge", "bridge.shutdown",
                {"exit_code": probe_result.exit_code,
                 "runtime_seconds": round(probe_result.ended_at - probe_result.started_at, 3)
                 if probe_result.ended_at else None,
                 "stderr_tail": probe_result.stderr_lines[-20:]},
                pid=probe_result.pid,
            )
            # The bridge itself is the authority on whether the compiled panel
            # matches the pulled sources. Record its verdict verbatim instead
            # of inferring freshness from mtimes.
            stale_lines = [line for line in probe_result.stderr_lines if "STALE" in line.upper()]
            fresh_lines = [
                line for line in probe_result.stderr_lines
                if "desktop ui:" in line.lower() and "stale" not in line.lower()
            ]
            self.ctx.record(
                "bridge", "bridge.workbench_freshness",
                {
                    "stale": bool(stale_lines),
                    "stale_lines": stale_lines[:3],
                    "fresh_lines": fresh_lines[:3],
                },
                pid=probe_result.pid,
            )
            result["workbench_stale"] = bool(stale_lines)
            result["workbench_freshness_lines"] = stale_lines[:3] or fresh_lines[:3]
        except (BridgeProbeError, OSError) as exc:
            self.errors.append(f"bridge lane: {type(exc).__name__}: {exc}")
            self.ctx.record("bridge", "bridge.launch_failed", {"error": f"{type(exc).__name__}: {exc}"})
            result["error"] = f"{type(exc).__name__}: {exc}"
            probe.terminate()
        return result

    # -- lane 3: governance ----------------------------------------------

    def _governance_lane(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        git = git_info(self.repo_root)
        result["git"] = git
        self.ctx.record("acceptance", "acceptance.git", git)

        invariant = check_invariant7(self.repo_root, vscode_root=self.vscode_root)
        result["invariant7"] = invariant.to_dict()
        self.ctx.record("acceptance", "acceptance.invariant7", invariant.to_dict())

        retry = provider_retry_configuration()
        result["retry"] = retry
        self.ctx.record("provider", "provider.retry_posture", retry)

        from src.config.settings import LLM_MODEL, LLM_PROVIDER, CUSTOM_API_KEY

        estimate = preflight_estimate(
            prompt="P0.6.4 offline observability preflight (no dispatch)",
            provider=LLM_PROVIDER,
            model=LLM_MODEL,
            max_output_tokens=self.options.max_output_tokens,
            budget_inr=self.options.budget_inr,
        )
        estimate["credential_present"] = bool(CUSTOM_API_KEY)
        result["preflight"] = estimate
        self.ctx.record("finops", "finops.preflight", estimate)

        result["provider_dispatches_this_run"] = len([
            rec for rec in self.ctx.records if rec.kind == "provider.dispatch"
        ])
        self.ctx.record(
            "acceptance", "acceptance.offline_assertion",
            {"provider_dispatches": result["provider_dispatches_this_run"],
             "paid_frames_sent": 0,
             "prompt_submitted": False},
        )
        return result

    # -- entry -------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        started = time.time()
        self.ctx.record(
            "acceptance", "acceptance.start",
            {"workspace": str(self.workspace), "workspace_id": workspace_id(str(self.workspace)),
             "phase": "P0.6.4", "started_at": utc_now_iso()},
            workspace=str(self.workspace),
        )
        governance = self._governance_lane()
        desktop = {} if self.options.skip_desktop else self._desktop_lane()
        bridge = {} if self.options.skip_bridge else self._bridge_lane()

        correlator = Correlator(self.ctx.records)
        classification = correlator.classify(self.ctx.run_id, _desktop_requirements())

        summary = {
            "run_id": self.ctx.run_id,
            "phase": "P0.6.4",
            "evidence_dir": str(self.ctx.evidence_dir),
            "workspace": str(self.workspace),
            "workspace_id": workspace_id(str(self.workspace)),
            "started_at": started,
            "finished_at": time.time(),
            "duration_seconds": round(time.time() - started, 3),
            "git": governance.get("git", {}),
            "preflight": governance.get("preflight", {}),
            "retry_posture": governance.get("retry", {}),
            "invariant7": governance.get("invariant7", {}),
            "desktop_lane": desktop,
            "bridge_lane": bridge,
            "provider_dispatches": governance.get("provider_dispatches_this_run", 0),
            "criteria": classification,
            "errors": self.errors,
            "records": [rec.to_dict() for rec in self.ctx.records],
        }
        self.ctx.write_json("evidence.json", summary)
        (self.ctx.evidence_dir / "report.md").write_text(self._render_report(summary), encoding="utf-8")
        return summary

    # -- report ------------------------------------------------------------

    def _render_report(self, summary: dict[str, Any]) -> str:
        criteria = summary.get("criteria", {})
        desktop = summary.get("desktop_lane", {}) or {}
        bridge = summary.get("bridge_lane", {}) or {}
        preflight = summary.get("preflight", {}) or {}
        invariant = summary.get("invariant7", {}) or {}
        observation = (desktop.get("observation") or {})
        composer = observation.get("composer", {}) or {}
        console = observation.get("console", {}) or {}
        console_errors = len(console.get("errors") or [])
        console_rejects = len(console.get("rejects") or [])
        console_cerrors = len(console.get("consoleErrors") or [])

        lines = [
            f"# P0.6.4 — Desktop Observability & Acceptance Harness",
            "",
            f"- **Run ID:** `{summary['run_id']}`",
            f"- **Evidence dir:** `{summary['evidence_dir']}`",
            f"- **Git HEAD:** `{summary['git'].get('head_short', '?')}` on `{summary['git'].get('branch', '?')}`",
            f"- **Workspace id:** `{summary['workspace_id']}`",
            f"- **Provider dispatches this run:** {summary['provider_dispatches']}",
            "",
            "## Electron lane",
            "",
            f"- launched: `{bool(desktop.get('pid'))}`  pid: `{desktop.get('pid')}`",
            f"- renderer belongs to Crusor: `{desktop.get('belongs_to_crusor')}`",
            f"- composer `{COMPOSER_SELECTOR}` count: `{composer.get('count')}` "
            f"visible: `{composer.get('visible')}` enabled: `{composer.get('enabled')}`",
            f"- screenshots: {', '.join(observation.get('screenshots', [])) or '(none)'}",
            f"- unhandled errors: {console_errors} / rejections: {console_rejects}"
            f" / console errors: {console_cerrors}",
            "",
            "## Bridge lane",
            "",
            f"- handshake: `{(bridge.get('probe') or {}).get('handshake', {}).get('engine')}` "
            f"protocol `{(bridge.get('probe') or {}).get('handshake', {}).get('protocol')}` "
            f"version `{(bridge.get('probe') or {}).get('handshake', {}).get('engine_version')}`",
            f"- session id: `{((bridge.get('probe') or {}).get('session') or {}).get('session_id')}`",
            f"- exit code: `{(bridge.get('probe') or {}).get('exit_code')}`",
            f"- validation passed: `{((bridge.get('probe') or {}).get('validation') or {}).get('passed')}`",
            f"- compiled workbench stale vs sources: `{bridge.get('workbench_stale')}`"
            f" {('— ' + bridge['workbench_freshness_lines'][0][:220]) if bridge.get('workbench_freshness_lines') else ''}",
            "",
            "## Governance",
            "",
            f"- pricing verified: `{preflight.get('pricing_verified')}` "
            f"(in ${preflight.get('input_price_per_1m_usd')}/1M, out ${preflight.get('output_price_per_1m_usd')}/1M)",
            f"- max request cost: INR `{preflight.get('max_cost_inr')}` / USD `{preflight.get('max_cost_usd')}` "
            f"— fits ₹{preflight.get('budget_inr')}: `{preflight.get('fits_budget')}`",
            f"- retry posture: `{summary.get('retry_posture')}`",
            f"- Invariant 7 maintained: `{invariant.get('maintained')}` "
            f"(drift: {invariant.get('drift_files')}, undeclared: {invariant.get('undeclared_changes')})",
            "",
            "## Acceptance criteria (P0.6.4 = observability only)",
            "",
            "| Criterion | Evidence |",
            "| --- | --- |",
        ]
        for name, value in criteria.items():
            lines.append(f"| {name} | {value} |")
        if self.errors:
            lines += ["", "## Errors", ""]
            lines += [f"- {err}" for err in self.errors]
        lines.append("")
        return "\n".join(lines)
