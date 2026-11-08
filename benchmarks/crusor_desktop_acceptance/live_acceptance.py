"""P0.6.5 — one real desktop turn, with a traceable execution chain.

Flow (nothing here calls a model directly):

    Electron UI (real window, CDP)  ->  worker (utility process)
      -> bridge (python child)      ->  orchestrator/chat graph
      -> provider                    ->  WorkspaceMutationBroker
      -> verification               ->  renderer response

Every gate is checked BEFORE the prompt is submitted; a failed gate aborts
without spending provider credits. Evidence is written as it is produced, so a
failure still leaves a usable package.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.crusor_desktop_acceptance.cdp_client import CdpClient, CdpError, parse_targets, pick_page_target
from benchmarks.crusor_desktop_acceptance.correlation import RunContext, utc_now_iso, workspace_id
from benchmarks.crusor_desktop_acceptance.desktop_launcher import (
    allocate_loopback_port,
    launch_app,
    read_devtools_active_port,
    read_product,
    stop_app,
    wait_for_cdp,
    wait_for_devtools,
    wait_for_page_target,
)
from benchmarks.crusor_desktop_acceptance.live_turn import (
    build_acceptance_env,
    classify_financials,
    classify_guard,
    classify_orchestration_finops,
    click_send,
    composer_value,
    ensure_panel_open,
    list_turn_manifests,
    press_enter,
    prompt_sha256,
    read_acceptance_ledger,
    read_all_orchestration_finops,
    read_financial_state,
    read_mutation_ledger,
    read_orchestration_finops,
    read_orchestration_lifecycle,
    read_provider_invocations,
    read_session_title,
    refresh_manifest,
    type_prompt,
    wait_for_engine_ready,
    wait_for_turn_manifest,
    turn_is_terminal,
)
from benchmarks.crusor_desktop_acceptance.processes import discover_engine_processes
from benchmarks.crusor_desktop_acceptance.renderer_observer import (
    COMPOSER_SELECTOR,
    collect_console,
    observe_composer,
    observe_renderer,
    save_screenshot,
    wait_for_workbench,
)

DEFAULT_PROMPT = (
    "Create src/duration.py with exactly one public function parse_duration(value). "
    "It parses a duration string into whole seconds. Supported units: h, m, s. "
    "Input may contain multiple components in any order (for example '1h30m' or "
    "'2m 15s'), optional spaces, and no duplicate units. Return an int. "
    "Raise ValueError for an empty string, unknown units, duplicate units, missing "
    "numbers, or negative values. Do not accept floats. Raise TypeError when value "
    "is not a string. Then create tests/test_duration.py with pytest tests for: "
    "'1h30m' -> 5400, '2m 15s' -> 135, '45s' -> 45, '1h 30m 15s' -> 5415, duplicate "
    "'1h1h' raises ValueError, unknown '1d' raises, empty string raises, '-1h' raises, "
    "non-string raises TypeError. The test file must import the function exactly as "
    "`from src.duration import parse_duration`. Run pytest and make every test pass. "
    "Do not modify unrelated files."
)


@dataclass
class LiveTurnOptions:
    repo_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[2])
    evidence_dir: Path | None = None
    workspace: Path | None = None
    prompt: str = DEFAULT_PROMPT
    max_dispatches: int = 5
    budget_inr: float = 5.00
    launch_timeout_s: float = 120.0
    ready_timeout_s: float = 150.0
    turn_timeout_s: float = 900.0
    #: Validate every gate and type the prompt, but never press Enter.
    stop_before_submit: bool = False

    def resolved_evidence(self) -> Path:
        return (self.evidence_dir or (Path(self.repo_root) / "diagnostics" / "p0_6_5")).resolve()


class AbortedPreflight(RuntimeError):
    """Raised when a mandatory gate fails before the prompt is submitted."""


def _git(*args: str, cwd: Path) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=120)
        return done.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def prepare_workspace(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "acceptance@crusor.local", cwd=root)
    _git("config", "user.name", "Crusor Acceptance", cwd=root)
    (root / "README.md").write_text("# isolated acceptance workspace\n", encoding="utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", "baseline", cwd=root)
    inventory = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
    )
    return {
        "path": str(root),
        "git_status": _git("status", "--porcelain", cwd=root),
        "git_head": _git("rev-parse", "HEAD", cwd=root),
        "inventory": inventory,
    }


class LiveAcceptance:
    def __init__(self, options: LiveTurnOptions | None = None) -> None:
        self.options = options or LiveTurnOptions()
        self.repo_root = Path(self.options.repo_root).resolve()
        self.vscode_root = self.repo_root / "desktop" / "vscode"
        self.run_id = f"p0_6_5_{time.strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.evidence_dir = self.options.resolved_evidence()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.workspace = Path(self.options.workspace or tempfile.mkdtemp(prefix="crusor_p0_6_5_ws_")).resolve()
        self.ctx = RunContext(self.evidence_dir, phase="P0.6.5", run_id=self.run_id, workspace=str(self.workspace))
        self.shots = self.evidence_dir / "screenshots"
        self.shots.mkdir(exist_ok=True)
        self.state: dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": utc_now_iso(),
            "prompt": self.options.prompt,
            "prompt_sha256": prompt_sha256(self.options.prompt),
            "gates": {},
            "stages": {},
        }

    # -- evidence helpers --------------------------------------------------

    def save(self) -> None:
        (self.evidence_dir / "evidence.json").write_text(
            json.dumps(self.state, indent=2, default=str) + "\n", encoding="utf-8"
        )

    def stage(self, name: str, payload: dict[str, Any]) -> None:
        self.state["stages"][name] = {"at": utc_now_iso(), **payload}
        self.save()

    def gate(self, name: str, ok: bool, detail: Any) -> None:
        self.state["gates"][name] = {"ok": bool(ok), "detail": detail, "at": utc_now_iso()}
        self.save()
        if not ok:
            raise AbortedPreflight(f"gate failed: {name}: {detail}")

    # -- main --------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        app = None
        client: CdpClient | None = None
        console_samples: list[dict[str, Any]] = []
        try:
            self.stage("workspace", prepare_workspace(self.workspace))
            self.stage("git", {
                "branch": _git("rev-parse", "--abbrev-ref", "HEAD", cwd=self.repo_root),
                "head": _git("rev-parse", "HEAD", cwd=self.repo_root),
                "desktop_dirty": len(_git("status", "--porcelain", "--", "desktop/vscode", cwd=self.repo_root).splitlines()),
            })

            port = allocate_loopback_port()
            env = build_acceptance_env(
                run_id=self.run_id,
                evidence_dir=self.evidence_dir,
                max_dispatches=self.options.max_dispatches,
                budget_inr=self.options.budget_inr,
            )
            self.state["env_keys"] = sorted(env)

            app = launch_app(
                vscode_root=self.vscode_root,
                workspace=self.workspace,
                port=port,
                logs_dir=self.evidence_dir / "logs",
                user_data_dir=self.evidence_dir / "user-data",
                portable_dir=self.evidence_dir / "portable",
                extra_env=env,
            )
            self.stage("electron_launch", {
                "pid": app.pid,
                "port": port,
                "exe": str(app.exe),
                "argv": app.args,
                "env_keys": sorted(env),
                "portable_dir": app.portable_dir,
            })

            endpoint = wait_for_devtools(app, timeout_s=self.options.launch_timeout_s)
            effective_port = int(endpoint.get("port") or port)
            version = wait_for_cdp(effective_port, timeout_s=self.options.launch_timeout_s)
            targets = wait_for_page_target(effective_port, timeout_s=self.options.launch_timeout_s)
            target = pick_page_target(
                parse_targets(json.dumps(targets)),
                prefer_title=str(read_product(self.vscode_root).get("nameLong") or ""),
            )
            client = CdpClient(target.websocket_url)
            client.connect()
            for method in ("Runtime.enable", "Page.enable", "Log.enable"):
                client.call(method)
            self.stage("cdp", {
                "port": effective_port,
                "requested_port": port,
                "browser": version.get("Browser"),
                "protocol_version": version.get("Protocol-Version"),
                "target": target.to_dict(),
                "loopback_only": endpoint.get("loopback_only"),
            })

            ready = wait_for_workbench(client, timeout_s=self.options.launch_timeout_s)
            obs = observe_renderer(client, expected_name=str(read_product(self.vscode_root).get("nameShort") or "CrusorAI"), screenshot_dir=self.shots)
            console_samples.append(obs.console or {})
            self.gate("renderer_workbench", ready and obs.belongs_to_crusor, {
                "workbench_ready": ready,
                "belongs_to_crusor": obs.belongs_to_crusor,
                "identity": obs.page_identity,
            })

            composer = observe_composer(client)
            self.gate("composer_available", int(composer.get("count") or 0) > 0 and bool(composer.get("enabled")), composer)

            panel = ensure_panel_open(client, timeout_s=60.0)
            self.stage("panel_stability", panel)
            engine = wait_for_engine_ready(
                client,
                timeout_s=self.options.ready_timeout_s,
                on_missing=lambda: ensure_panel_open(client, timeout_s=10.0),
            )
            self.gate("engine_ready", bool(engine.get("ready")), engine)
            save_screenshot(client, self.shots / "01-engine-ready.png")

            # Worker + bridge of THIS app instance, by ancestry.
            procs = discover_engine_processes(app.pid)
            self.stage("processes", procs)
            self.gate("worker_bridge_owned", bool(procs.get("ancestry_ok")) and bool(procs.get("owned_bridge_pids")), {
                "worker_pids": procs.get("worker_pids"),
                "bridge_pids": procs.get("bridge_pids"),
                "owned_bridge_pids": procs.get("owned_bridge_pids"),
                "ancestry_ok": procs.get("ancestry_ok"),
            })
            owned_bridge_pids = procs["owned_bridge_pids"]
            ledger_now = read_acceptance_ledger(self.evidence_dir / "acceptance_dispatch.json")
            guard = classify_guard(
                ledger_now,
                run_id=self.run_id,
                owned_bridge_pids=owned_bridge_pids,
                max_dispatches=self.options.max_dispatches,
            )
            # The interpreter that actually imported src.bridge is the process
            # that owns the guard (with a venv shim it is a child of the process
            # the utility spawned). Prefer the ledger's own pid.
            bridge_pid = int(ledger_now.get("pid") or (owned_bridge_pids[0] if owned_bridge_pids else 0))
            self.gate("acceptance_guard_in_app_bridge", bool(guard.get("ok")), guard)

            # Console carries the bridge's own stderr lines (the app forwards them).
            first_console = collect_console(client)
            console_samples.append(first_console)
            acceptance_line = self._find_acceptance_line(first_console)
            self.stage("guard_console_line", acceptance_line)

            # ---- submit exactly once through the real composer ----
            seen = list_turn_manifests(Path(env["CRUSORAI_HOME"]))
            typed = type_prompt(client, self.options.prompt)
            self.gate("prompt_typed", bool(typed.get("typed_matches_prompt")), typed)
            save_screenshot(client, self.shots / "02-prompt-typed.png")

            if self.options.stop_before_submit:
                self.state["preflight_ok"] = True
                self.state["verdict"] = None
                self.state["stopped_before_submit"] = True
                return self._finalise(app, client, console_samples)

            submit_at = utc_now_iso()
            press_enter(client)
            self.state["submit_at"] = submit_at
            self.save()

            # Confirm the submission took effect: the composer clears on submit.
            method = "enter"
            after_value = composer_value(client)
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline and after_value not in (None, ""):
                time.sleep(0.3)
                after_value = composer_value(client)
            if after_value not in (None, ""):
                # Enter was swallowed (still the exact prompt, no newline):
                # use the real Send button instead. Only when the text is
                # UNCHANGED, so a submission that merely keeps the text cannot
                # be sent twice.
                if after_value == self.options.prompt:
                    clicked = click_send(client)
                    method = "send-button"
                    deadline = time.monotonic() + 4.0
                    while time.monotonic() < deadline and after_value not in (None, ""):
                        time.sleep(0.3)
                        after_value = composer_value(client)
                    self.state["send_button_click"] = clicked

            self.stage("ui_submission", {
                "at": submit_at,
                "method": method,
                "composer_after_submit": after_value,
                "cleared": after_value in (None, ""),
                "typed": typed,
            })
            self.gate("ui_submission_identified", after_value in (None, ""), {
                "composer_after_submit": after_value,
                "method": method,
            })

            try:
                candidate = wait_for_turn_manifest(
                    Path(env["CRUSORAI_HOME"]),
                    prompt_sha=prompt_sha256(self.options.prompt),
                    seen_before=seen,
                    timeout_s=self.options.turn_timeout_s,
                )
            except TimeoutError:
                save_screenshot(client, self.shots / "03-timeout.png")
                raise AbortedPreflight("turn manifest never appeared (UI submission not served)")

            self.stage("turn_manifest", {"path": candidate["path"], "prompt_sha256_matches": candidate.get("prompt_sha256_matches")})
            manifest = candidate["manifest"]
            identity = manifest.get("identity") or {}
            session_id = str(identity.get("session_id") or "")
            turn_id = str(identity.get("turn_id") or "")
            wsid = str(identity.get("workspace_id") or "")
            self.gate("turn_manifest_prompt_match", bool(candidate.get("prompt_sha256_matches")), {
                "expected": prompt_sha256(self.options.prompt),
                "manifest": (manifest.get("request") or {}).get("sha256"),
            })

            # Wait for terminal status.
            deadline = time.monotonic() + self.options.turn_timeout_s
            while time.monotonic() < deadline and not turn_is_terminal(candidate):
                time.sleep(1.0)
                candidate = refresh_manifest(candidate)
                console_samples.append(collect_console(client))
            manifest = candidate["manifest"]
            self.stage("turn_terminal", {
                "status": (manifest.get("terminal") or {}).get("status"),
                "completed": (manifest.get("terminal") or {}).get("completed"),
                "duration_s": (manifest.get("terminal") or {}).get("duration_s"),
                "error": (manifest.get("terminal") or {}).get("error"),
            })
            save_screenshot(client, self.shots / "04-turn-finished.png")

            self.state["correlation"] = {
                "run_id": self.run_id,
                "session_id": session_id,
                "turn_id": turn_id,
                "workspace_id": wsid,
                "main_pid": app.pid,
                "worker_pids": procs.get("worker_pids"),
                "bridge_pid": bridge_pid,
            }
            self.save()

            # Final console drain (renderer health for the whole turn).
            console_samples.append(collect_console(client))
            self.state["renderer_console"] = self._summarise_console(console_samples)
            try:
                save_screenshot(client, self.shots / "05-final-response.png")
            except CdpError:
                pass

            return self.finish(app, client, env, session_id, turn_id, bridge_pid)
        except AbortedPreflight as exc:
            self.state["aborted"] = str(exc)
            self.state["verdict"] = "P0.6.6_PREFLIGHT_ABORTED"
            return self._finalise(app, client, console_samples)
        except Exception as exc:  # noqa: BLE001 - evidence must survive any failure
            self.state["failure"] = f"{type(exc).__name__}: {exc}"
            self.state["verdict"] = "P0.6.6_LIVE_FAILED"
            return self._finalise(app, client, console_samples)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _find_acceptance_line(console: dict[str, Any]) -> dict[str, Any]:
        for bucket in ("consoleWarns", "consoleErrors", "errors", "rejects"):
            for item in console.get(bucket) or []:
                message = str(item.get("message") or "")
                if "[bridge][acceptance]" in message:
                    return {"found": True, "bucket": bucket, "message": message[:400]}
        return {"found": False}

    @staticmethod
    def _summarise_console(samples: list[dict[str, Any]]) -> dict[str, Any]:
        errors = rejects = 0
        warnings: list[str] = []
        for sample in samples:
            errors += len(sample.get("errors") or [])
            rejects += len(sample.get("rejects") or [])
            for item in sample.get("consoleWarns") or []:
                msg = str(item.get("message") or "")
                if len(warnings) < 60:
                    warnings.append(msg[:300])
        return {
            "unhandled_errors": errors,
            "unhandled_rejections": rejects,
            "warnings_sample": warnings,
            "chat_context_error_present": any("chat.contextContributions" in w for w in warnings),
        }

    def finish(self, app, client, env: dict[str, str], session_id: str, turn_id: str, bridge_pid: int) -> dict[str, Any]:
        home = Path(env["CRUSORAI_HOME"])
        # Persist final console + stop the app (the bridge flushes its ledger on exit).
        shutdown = stop_app(app)
        time.sleep(2.0)
        self.state["electron_shutdown"] = shutdown

        ledger = read_acceptance_ledger(self.evidence_dir / "acceptance_dispatch.json")
        guard_final = classify_guard(ledger, run_id=self.run_id, bridge_pid=bridge_pid,
                                     max_dispatches=self.options.max_dispatches)
        self.state["guard_final"] = guard_final

        db = home / "sessions.db"
        if db.exists():
            shutil.copy2(db, self.evidence_dir / "sessions.db")
        fin = read_financial_state(db, session_id=session_id, turn_id=turn_id)
        fin_class = classify_financials(fin, budget_inr=self.options.budget_inr)
        # The desktop turn runs through the orchestrator, whose governor writes
        # into the WORKSPACE, not CRUSORAI_HOME. Read that authoritative state.
        orch_fin = read_orchestration_finops(self.workspace, task_id=f"turn_{turn_id}")
        orch_class = classify_orchestration_finops(orch_fin, budget_inr=self.options.budget_inr)
        self.state["financial"] = {
            "orchestrator": orch_fin,
            "orchestrator_classification": orch_class,
            "cost_governance": {"state": fin, "classification": fin_class},
        }
        self.state["session_financials"] = read_all_orchestration_finops(self.workspace)
        invocations = read_provider_invocations(self.workspace)
        self.state["invocations"] = invocations
        if invocations.get("available"):
            try:
                shutil.copy2(invocations["path"], self.evidence_dir / "provider_invocations.jsonl")
            except OSError:
                pass
        self.state["session_title"] = read_session_title(home / "sessions.db", session_id)

        mutations = read_mutation_ledger(self.workspace)
        self.state["mutations"] = mutations
        self.state["workspace_after"] = {
            "files": sorted(p.relative_to(self.workspace).as_posix()
                            for p in self.workspace.rglob("*")
                            if p.is_file() and ".git" not in p.parts and ".crusorai" not in p.parts),
            "git_status": _git("status", "--porcelain", cwd=self.workspace),
        }

        verification = self._verify_artifacts()
        self.state["verification"] = verification

        # In-turn evidence: the engine must have discovered, executed and (on a
        # natural failure) repaired tests BEFORE the turn ended.
        in_turn = read_orchestration_lifecycle(self.workspace)
        reports = self.workspace / ".crusorai" / "test_reports"
        if reports.exists():
            target = self.evidence_dir / "test_reports"
            target.mkdir(parents=True, exist_ok=True)
            for report in reports.glob("*"):
                if report.is_file():
                    shutil.copy2(report, target / report.name)
            in_turn["evidence_dir"] = str(target)
        self.state["in_turn"] = in_turn
        if in_turn.get("path"):
            try:
                shutil.copy2(in_turn["path"], self.evidence_dir / "orchestration_journal.jsonl")
            except OSError:
                pass
        self.state["verdict"] = self._verdict(guard_final, orch_class, verification)
        return self._finalise(None, None, [])

    def _verify_artifacts(self) -> dict[str, Any]:
        module = self.workspace / "src" / "duration.py"
        tests = self.workspace / "tests" / "test_duration.py"
        out: dict[str, Any] = {
            "module_exists": module.exists(),
            "tests_exist": tests.exists(),
        }
        if module.exists():
            source = module.read_text(encoding="utf-8")
            out["module_sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
            try:
                ast.parse(source, filename=str(module))
                out["ast_ok"] = True
            except SyntaxError as exc:
                out["ast_ok"] = False
                out["ast_error"] = str(exc)
            out["has_parse_duration"] = "def parse_duration" in source
            out["independent_smoke"] = self._independent_smoke(module)
        if tests.exists():
            out["tests_sha256"] = hashlib.sha256(tests.read_bytes()).hexdigest()
            try:
                done = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q", "tests/test_duration.py"],
                    cwd=str(self.workspace), capture_output=True, text=True, timeout=300,
                )
                out["pytest_returncode"] = done.returncode
                out["pytest_tail"] = (done.stdout or done.stderr).strip().splitlines()[-6:]
            except (OSError, subprocess.SubprocessError) as exc:
                out["pytest_error"] = str(exc)
        return out

    @staticmethod
    def _independent_smoke(module_path: Path) -> dict[str, Any]:
        """The harness's own contract check — never the agent's tests."""
        script = (
            "import json, sys\n"
            "from importlib.util import spec_from_file_location, module_from_spec\n"
            f"spec = spec_from_file_location('dur', r'{module_path}')\n"
            "mod = module_from_spec(spec); sys.modules['dur'] = mod; spec.loader.exec_module(mod)\n"
            "fn = mod.parse_duration\n"
            "res = {}\n"
            "res['1h30m'] = fn('1h30m') == 5400\n"
            "res['2m_15s'] = fn('2m 15s') == 135\n"
            "res['45s'] = fn('45s') == 45\n"
            "res['1h_30m_15s'] = fn('1h 30m 15s') == 5415\n"
            "def raises(exc, arg):\n"
            "    try:\n"
            "        fn(arg)\n"
            "    except exc:\n"
            "        return True\n"
            "    except Exception:\n"
            "        return False\n"
            "    return False\n"
            "res['duplicate_valueerror'] = raises(ValueError, '1h1h')\n"
            "res['unknown_valueerror'] = raises(ValueError, '1d')\n"
            "res['empty_valueerror'] = raises(ValueError, '')\n"
            "res['negative_valueerror'] = raises(ValueError, '-1h')\n"
            "res['non_string_typeerror'] = raises(TypeError, 42)\n"
            "print(json.dumps(res))\n"
        )
        try:
            done = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, timeout=120, cwd=str(module_path.parent.parent),
            )
            payload = json.loads((done.stdout or "{}").strip().splitlines()[-1]) if done.stdout.strip() else {}
            return {"ok": bool(payload) and all(payload.values()), "checks": payload,
                    "stderr": (done.stderr or "")[-300:]}
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def _verdict(self, guard: dict[str, Any], fin: dict[str, Any], verification: dict[str, Any]) -> str:
        terminal = (self.state.get("stages", {}).get("turn_terminal") or {})
        renderer_console = self.state.get("renderer_console") or {}
        in_turn = self.state.get("in_turn") or {}
        final_run = (in_turn.get("final_test_run") or {})
        in_turn_tests_ok = (
            bool(in_turn.get("available"))
            and bool(in_turn.get("tests"))
            and int(final_run.get("total") or 0) > 0
            and int(final_run.get("failed") or 0) == 0
            and int(final_run.get("errors") or 0) == 0
            and "pytest" in str(final_run.get("command") or "")
        )
        completion_ok = bool(in_turn.get("completion_ok"))
        contract = in_turn.get("contract") or {}
        assignment = in_turn.get("assignment") or {}
        plan_report = in_turn.get("plan") or {}
        cross = in_turn.get("cross_file") or {}
        components = contract.get("components") or []
        roles = [c.get("role") for c in components]
        req_ids = {
            rid for component in components
            for rid in (component.get("requirement_ids") or [])
        }
        req_map = assignment.get("requirement_map") or {}
        contract_ok = (
            bool(contract.get("contract_hash"))
            and len(components) >= 2
            and "SOURCE" in roles
            and "TEST" in roles
            and bool(req_ids)
            and all(bool(req_map.get(rid)) for rid in req_ids)
            and not (contract.get("ambiguities") or [])
        )
        plan_ok = (
            bool(plan_report.get("ok"))
            and int(plan_report.get("work_units") or 0) == 2
            and int(plan_report.get("demand") or 0) == 2
        )
        cross_ok = bool(cross.get("ok"))

        invocations = self.state.get("invocations") or {}
        summary = invocations.get("summary") or {}
        records = invocations.get("records") or []
        session_fin = self.state.get("session_financials") or {}
        task_settled = [
            r for r in records
            if r.get("subsystem") == "engineering" and r.get("status") == "settled"
        ]
        aux_records = [r for r in records if r.get("subsystem") == "session_titling"]
        aux_settled = [
            r for r in aux_records
            if r.get("status") == "settled"
            and float(r.get("actual_cost_inr") or 0.0) > 0
            and bool(r.get("model"))
            and bool(r.get("provider"))
        ]
        ledger_ok = (
            bool(invocations.get("available"))
            and int(summary.get("total_calls") or 0) > 0
            and int(summary.get("settled_calls") or 0) == int(summary.get("total_calls") or 0)
            and int(summary.get("uncertain_calls") or 0) == 0
            and len(task_settled) >= 2
            and len(aux_settled) >= 1
        )
        dispatches_reconciled = (
            int(guard.get("dispatches_used") or 0)
            == int(summary.get("settled_calls") or 0)
            == int(session_fin.get("calls_count") or 0)
        )
        costs_reconciled = (
            abs(
                float(summary.get("total_cost_inr") or 0.0)
                - float(session_fin.get("spent_inr") or 0.0)
            ) < 1e-6
            and int(session_fin.get("uncertain_count") or 0) == 0
            and int(session_fin.get("active_count") or 0) == 0
            and float(session_fin.get("spent_inr") or 0.0) <= float(self.options.budget_inr)
        )
        title_ok = bool(str(self.state.get("session_title") or "").strip())
        ok = (
            bool(guard.get("ok"))
            and bool(fin.get("ok"))
            and ledger_ok
            and dispatches_reconciled
            and costs_reconciled
            and title_ok
            and contract_ok
            and plan_ok
            and cross_ok
            and bool(verification.get("module_exists"))
            and bool(verification.get("ast_ok"))
            and verification.get("pytest_returncode") == 0
            and bool((verification.get("independent_smoke") or {}).get("ok"))
            and in_turn_tests_ok
            and completion_ok
            and terminal.get("status") == "completed"
            and renderer_console.get("unhandled_errors", 0) == 0
            and bool(self.state.get("correlation"))
        )
        if ok:
            return "P0.6.9_ACCEPTANCE_PASSED"
        completion = in_turn.get("completion") or {}
        if in_turn.get("available") and completion.get("blocked"):
            return "P0.6.9_ACCEPTANCE_BLOCKED"
        return "P0.6.9_ACCEPTANCE_FAILED"

    def _finalise(self, app, client, console_samples) -> dict[str, Any]:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        if app is not None and app.process is not None and app.process.poll() is None:
            self.state["electron_shutdown"] = stop_app(app)
        self.state["finished_at"] = utc_now_iso()
        self.state["records"] = [r.to_dict() for r in self.ctx.records]
        self.save()
        return self.state
