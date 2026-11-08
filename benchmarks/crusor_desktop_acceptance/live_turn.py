"""P0.6.5 — live desktop turn: readiness, submission and correlation.

This module is the part the P0.6.4 harness was missing. It does not run the
engine itself: it drives the REAL Electron window over CDP (focus, type, press
Enter), then reads the evidence the actual application wrote while serving that
turn (turn manifest, financial ledger, mutation ledger, acceptance ledger).

Correlation is done on identifiers produced by the application:

    (run_id, session_id, turn_id, workspace_id)

`run_id` comes from the acceptance env; the other three come from the turn
manifest that the bridge's own runtime wrote. A record is only accepted when
its identifiers agree AND the bridge PID in the acceptance ledger is the PID of
the python child of the Electron utility process.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmarks.crusor_desktop_acceptance.cdp_client import CdpClient, CdpError

ENGINE_STATUS_SELECTOR = ".crusorai-engine-status"
READY_TEXT = "Crusor ready"
COMPOSER_SELECTOR = "textarea.crusorai-composer-input"


# ---------------------------------------------------------------------------
# acceptance environment
# ---------------------------------------------------------------------------

def build_acceptance_env(
    *,
    run_id: str,
    evidence_dir: Path,
    max_dispatches: int = 5,
    budget_inr: float = 5.00,
) -> dict[str, str]:
    """Environment the REAL app (worker + bridge) must inherit."""
    home = (evidence_dir / "home").resolve()
    return {
        "CRUSORAI_ACCEPTANCE_RUN_ID": run_id,
        "CRUSORAI_ACCEPTANCE_MAX_DISPATCHES": str(int(max_dispatches)),
        "CRUSORAI_ACCEPTANCE_EVIDENCE_PATH": str((evidence_dir / "acceptance_dispatch.json").resolve()),
        "CRUSORAI_HOME": str(home),
        "CRUSORAI_EVIDENCE_DIR": str((home / "evidence").resolve()),
        "CRUSORAI_TURN_COST_BUDGET_INR": f"{budget_inr:.2f}",
        "CRUSORAI_SESSION_COST_BUDGET_INR": f"{budget_inr:.2f}",
        "CRUSORAI_RESERVE_BUDGET_INR": "0.50",
        "CRUSORAI_COST_GOVERNANCE": "on",
        "CRUSORAI_MEMORY": "off",
        # The bridge's own watchdog: a turn that wedges prints every thread's
        # stack after 60 s, which is the only way to see WHERE it is stuck.
        "CRUSORAI_BRIDGE_DIAGNOSTICS": "1",
        # Auxiliary model calls (session auto-title) must not claim acceptance
        # dispatches: they are not task work and no task FinOps reservation can
        # settle them (P0.6.8 live finding).
        "CRUSORAI_AUTOTITLE": "off",
        # The engine executes the task's tests with this interpreter. Pinning it
        # keeps the workspace's pytest resolution out of the guessing game when
        # the desktop bridge runs under a launcher shim.
        "CRUSORAI_TEST_PYTHON": sys.executable,
    }


def prompt_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# engine readiness
# ---------------------------------------------------------------------------

def engine_status(client: CdpClient) -> dict[str, Any]:
    expr = (
        "(() => { const el = document.querySelector(%r);"
        " if (!el) { return {present: false}; }"
        " return {present: true, text: (el.textContent || '').trim(),"
        "   cls: String(el.className || '')}; })()" % ENGINE_STATUS_SELECTOR
    )
    try:
        return client.evaluate(expr) or {"present": False}
    except CdpError as exc:
        return {"present": False, "error": str(exc)}


def composer_present(client: CdpClient) -> bool:
    try:
        return bool(client.evaluate(
            "(() => Boolean(document.querySelector('textarea.crusorai-composer-input')))()"
        ))
    except CdpError:
        return False


def chip_present(client: CdpClient) -> bool:
    try:
        return bool(client.evaluate(
            "(() => Boolean(document.querySelector('.crusorai-engine-status')))()"
        ))
    except CdpError:
        return False


def ensure_panel_open(client: CdpClient, *, timeout_s: float = 90.0, reopen=None) -> dict[str, Any]:
    """Keep the Crusor panel open until it is stable.

    The workbench restores the panel, then ``CrusorAutoHideContribution`` closes
    it at AfterRestored (~3 s in). Sampling once right after load sees a panel
    that is about to disappear — that is exactly how P0.6.4.1's screenshots
    showed "Engine starting" while the engine was actually coming up behind a
    closed view. This routine re-opens the view and only reports success after
    the composer is present in two consecutive samples.
    """
    from benchmarks.crusor_desktop_acceptance.renderer_observer import focus_crusor_panel

    reopen = reopen or (lambda: focus_crusor_panel(client, wait_s=4.0))
    deadline = time.monotonic() + timeout_s
    attempts: list[dict[str, Any]] = []
    stable = 0
    while time.monotonic() < deadline:
        if composer_present(client) and chip_present(client):
            time.sleep(1.2)
            if composer_present(client) and chip_present(client):
                stable += 1
                if stable >= 2:
                    return {"ok": True, "attempts": attempts, "stable_samples": stable}
        else:
            stable = 0
            try:
                attempts.append({"at": round(time.monotonic(), 2), "reopen": reopen()})
            except Exception as exc:  # noqa: BLE001 - a failed re-open must not wedge the gate
                attempts.append({"at": round(time.monotonic(), 2), "error": str(exc)})
        time.sleep(0.5)
    return {"ok": False, "attempts": attempts, "stable_samples": stable}


def wait_for_engine_ready(
    client: CdpClient,
    *,
    timeout_s: float = 120.0,
    on_missing=None,
) -> dict[str, Any]:
    """Wait for the panel's own status chip to say "Crusor ready".

    That chip is rendered from the engine service state, which only becomes
    Ready after the bridge answers `hello` with the matching protocol version.
    An enabled composer is NOT treated as readiness.

    ``on_missing`` (optional) is called when the chip disappears, so a view
    that auto-hides mid-wait is re-opened instead of failing the gate.
    """
    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {"present": False}
    missing_streak = 0
    while time.monotonic() < deadline:
        last = engine_status(client)
        samples.append({"at": round(time.monotonic(), 3), **last})
        if last.get("present") and str(last.get("text") or "").strip().startswith(READY_TEXT):
            return {"ready": True, "state": last, "samples": samples[-10:]}
        if not last.get("present"):
            missing_streak += 1
            if on_missing is not None and missing_streak >= 4:
                missing_streak = 0
                try:
                    on_missing()
                except Exception:
                    pass
        else:
            missing_streak = 0
        time.sleep(0.4)
    return {"ready": False, "state": last, "samples": samples[-20:]}


# ---------------------------------------------------------------------------
# genuine UI submission
# ---------------------------------------------------------------------------

def type_prompt(client: CdpClient, prompt: str) -> dict[str, Any]:
    """Focus the real composer and type into it with real input events."""
    focus_expr = (
        "(() => { const el = document.querySelector(%r);"
        " if (!el) { return {focused: false}; }"
        " el.scrollIntoView({block: 'center'}); el.focus();"
        " return {focused: document.activeElement === el,"
        "   disabled: el.disabled === true,"
        "   readonly: el.readOnly === true}; })()" % COMPOSER_SELECTOR
    )
    focused = client.evaluate(focus_expr) or {}
    client.call("Input.insertText", {"text": prompt})
    value_expr = "(() => { const el = document.querySelector(%r); return el ? el.value : null; })()" % COMPOSER_SELECTOR
    typed = client.evaluate(value_expr)
    return {
        "focused": focused,
        "typed_matches_prompt": typed == prompt,
        "typed_length": len(typed or ""),
        "typed_sha256": hashlib.sha256((typed or "").encode("utf-8")).hexdigest(),
    }


def press_enter(client: CdpClient) -> None:
    """Press Enter in the real composer (the product's send gesture).

    ``rawKeyDown`` without ``text`` is deliberate: the composer's keydown
    handler calls ``preventDefault()`` and submits, and omitting ``text`` means
    Chromium does not also insert a newline into the textarea. Sending a
    ``char`` event here produced a literal "\\n" instead of a submission.
    """
    base = {
        "key": "Enter",
        "code": "Enter",
        "windowsVirtualKeyCode": 13,
        "nativeVirtualKeyCode": 13,
    }
    client.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", **base})
    client.call("Input.dispatchKeyEvent", {"type": "keyUp", **base})


def click_send(client: CdpClient) -> dict[str, Any]:
    """Click the composer's real Send button (fallback if Enter is swallowed)."""
    expr = (
        "(() => { const b = document.querySelector('.crusorai-send-button:not(.crusorai-send-stop)');"
        " if (!b || b.disabled) { return {clicked: false}; }"
        " b.scrollIntoView({block: 'center'}); b.click();"
        " return {clicked: true, label: b.getAttribute('aria-label') || ''}; })()"
    )
    return client.evaluate(expr) or {"clicked": False}


def composer_value(client: CdpClient) -> str | None:
    expr = "(() => { const el = document.querySelector(%r); return el ? el.value : null; })()" % COMPOSER_SELECTOR
    try:
        return client.evaluate(expr)
    except CdpError:
        return None


# ---------------------------------------------------------------------------
# turn evidence (written by the real bridge)
# ---------------------------------------------------------------------------

def list_turn_manifests(home: Path) -> set[str]:
    """Every turn manifest the bridge wrote under CRUSORAI_HOME.

    The recorder roots at ``<home>/evidence`` and puts each session in its own
    directory (``<home>/evidence/session-…/turn-….json``); there is no
    intermediate ``turns/`` level. Globbing ``evidence/turns`` missed every
    manifest — the live harness then waited for a turn that had already run.
    """
    root = Path(home) / "evidence"
    if not root.is_dir():
        return set()
    return {str(p) for p in root.rglob("turn-*.json")}


def _verified_manifest(path: Path) -> dict[str, Any] | None:
    sidecar = path.with_suffix(".json.sha256")
    try:
        encoded = path.read_bytes()
        expected = sidecar.read_text(encoding="ascii").split()[0]
        if hashlib.sha256(encoded).hexdigest() != expected:
            return None
        value = json.loads(encoded)
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, ValueError, IndexError):
        return None


def wait_for_turn_manifest(
    home: Path,
    *,
    prompt_sha: str,
    seen_before: set[str],
    timeout_s: float = 900.0,
) -> dict[str, Any]:
    """Wait for the manifest of THIS prompt, verified by its sha256 sidecar."""
    deadline = time.monotonic() + timeout_s
    fallback: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        for path_str in sorted(list_turn_manifests(home)):
            if path_str in seen_before:
                continue
            path = Path(path_str)
            data = _verified_manifest(path)
            if data is None:
                continue
            request = data.get("request") or {}
            candidate = {
                "path": path_str,
                "manifest": data,
                "expected_prompt_sha": prompt_sha,
                "prompt_sha256_matches": request.get("sha256") == prompt_sha,
                "terminal_status": (data.get("terminal") or {}).get("status"),
            }
            if candidate["prompt_sha256_matches"]:
                return candidate
            fallback = fallback or candidate
        time.sleep(0.5)
    if fallback is not None:
        return {**fallback, "matched_by": "newest-manifest-prompt-hash-mismatch"}
    raise TimeoutError("no turn manifest appeared within the timeout")


def turn_is_terminal(candidate: dict[str, Any]) -> bool:
    status = (candidate.get("manifest", {}).get("terminal") or {}).get("status")
    return status in {"completed", "failed", "cancelled", "watchdog", "interrupted"}


def refresh_manifest(candidate: dict[str, Any]) -> dict[str, Any]:
    path = Path(candidate["path"])
    data = _verified_manifest(path)
    if data is None:
        return candidate
    request = data.get("request") or {}
    expected = candidate.get("expected_prompt_sha")
    return {
        **candidate,
        "manifest": data,
        "prompt_sha256_matches": request.get("sha256") == expected,
        "terminal_status": (data.get("terminal") or {}).get("status"),
    }


# ---------------------------------------------------------------------------
# financial ledger (the real cost governor's SQLite)
# ---------------------------------------------------------------------------

def read_orchestration_finops(workspace: str | Path, *, task_id: str = "") -> dict[str, Any]:
    """Read the ORCHESTRATOR's financial state.

    The engine's desktop turn runs through ``EngineeringExecutionOrchestrator``
    → ``ModelExecutionAdapter``, whose governor persists:
      * ``<ws>/.crusorai/finops/<task>_finops.json`` (accounting + reservations)
      * ``<ws>/.crusorai/sessions.db`` (canonical SQLite: reservations + calls)
    P0.6.5 read ``CRUSORAI_HOME/sessions.db`` instead and wrongly concluded no
    settlement had happened. This reads the real one.
    """
    root = Path(workspace) / ".crusorai"
    out: dict[str, Any] = {"available": False, "finops_json": None, "workspace": str(workspace)}
    candidates = sorted((root / "finops").glob("*_finops.json")) if (root / "finops").is_dir() else []
    if task_id:
        preferred = [p for p in candidates if task_id in p.name]
        candidates = preferred or candidates
    data: dict[str, Any] = {}
    if candidates:
        try:
            data = json.loads(candidates[-1].read_text(encoding="utf-8"))
            out["finops_json"] = str(candidates[-1])
            out["available"] = True
        except (OSError, json.JSONDecodeError) as exc:
            out["error"] = str(exc)

    accounting = data.get("accounting") or {}
    settled = data.get("settled_reservations") or {}
    uncertain = data.get("uncertain_reservations") or {}
    active = data.get("active_reservations") or {}

    db_rows: dict[str, Any] = {}
    db = root / "sessions.db"
    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            con.row_factory = sqlite3.Row
            tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            if "financial_reservations" in tables:
                db_rows["reservations"] = [
                    dict(r) for r in con.execute(
                        "select reservation_id, status, estimated_cost_inr, purpose, "
                        "root_session_id, created_at, updated_at from financial_reservations"
                    )
                ]
            if "financial_call_ledger" in tables:
                db_rows["calls"] = [
                    dict(r) for r in con.execute(
                        "select event_id, provider, model, input_tokens, output_tokens, "
                        "actual_cost_inr, cost_known, reservation_id, call_outcome "
                        "from financial_call_ledger"
                    )
                ]
            con.close()
        except sqlite3.Error as exc:
            db_rows["error"] = str(exc)

    out.update({
        "accounting": accounting,
        "settled": settled,
        "uncertain": uncertain,
        "active": active,
        "db": db_rows,
        "db_path": str(db) if db.exists() else None,
    })
    return out


def classify_orchestration_finops(state: dict[str, Any], *, budget_inr: float = 5.00) -> dict[str, Any]:
    """Financial acceptance checks for the orchestrator path."""
    if not state.get("available"):
        return {"ok": False, "reason": state.get("error") or "no orchestrator finops state found"}
    accounting = state.get("accounting") or {}
    settled = state.get("settled") or {}
    uncertain = state.get("uncertain") or {}
    active = state.get("active") or {}
    calls = int(accounting.get("calls_count") or 0)
    spent = float(accounting.get("spent_inr") or 0.0)
    settled_committed = [rid for rid, res in settled.items() if res.get("is_committed")]
    db_reservations = (state.get("db") or {}).get("reservations") or []
    db_settled = [r for r in db_reservations if r.get("status") == "reconciled"]
    checks = {
        "has_settlements": bool(settled_committed),
        "calls_matched_by_settlements": calls == len(settled_committed),
        "no_active_reservations": not active,
        "no_uncertain_reservations": not uncertain,
        "within_budget": spent <= budget_inr,
        "not_breached": not bool(accounting.get("is_breached")),
        "sqlite_reconciled": bool(db_settled) and len(db_settled) >= len(settled_committed),
        "usage_recorded": int(accounting.get("input_tokens") or 0) > 0
        and int(accounting.get("output_tokens") or 0) > 0,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "calls_count": calls,
        "settled_count": len(settled_committed),
        "uncertain_count": len(uncertain),
        "active_count": len(active),
        "spent_inr": round(spent, 6),
        "spent_usd": float(accounting.get("spent_usd") or 0.0),
        "input_tokens": int(accounting.get("input_tokens") or 0),
        "output_tokens": int(accounting.get("output_tokens") or 0),
        "budget_inr": budget_inr,
        "db_settled_rows": len(db_settled),
    }


def read_financial_state(db_path: Path, *, session_id: str, turn_id: str) -> dict[str, Any]:
    if not Path(db_path).exists():
        return {"available": False, "db": str(db_path)}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        reservations = [dict(r) for r in con.execute(
            "SELECT * FROM financial_reservations WHERE session_id = ? OR root_session_id = ?",
            (session_id, session_id),
        )]
        calls = [dict(r) for r in con.execute(
            "SELECT * FROM financial_call_ledger WHERE root_session_id = ? OR child_session_id = ?",
            (session_id, session_id),
        )]
        snapshots = [dict(r) for r in con.execute(
            "SELECT * FROM financial_session_snapshots WHERE session_id = ? OR root_session_id = ?",
            (session_id, session_id),
        )]
    except sqlite3.Error as exc:
        return {"available": False, "db": str(db_path), "error": str(exc)}
    finally:
        con.close()

    calls_for_turn = [c for c in calls if (c.get("turn_id") in (turn_id, None, ""))]
    return {
        "available": True,
        "db": str(db_path),
        "reservations": reservations,
        "calls": calls_for_turn,
        "calls_all": calls,
        "snapshots": snapshots,
    }


def classify_financials(state: dict[str, Any], *, budget_inr: float = 5.00) -> dict[str, Any]:
    if not state.get("available"):
        return {"ok": False, "reason": state.get("error") or "financial db unavailable"}
    reservations = state.get("reservations") or []
    calls = state.get("calls") or []
    settled = [r for r in reservations if str(r.get("status")) not in {"reserved", "in_flight"}]
    total_inr = 0.0
    for call in calls:
        try:
            total_inr += float(call.get("actual_cost_inr") or call.get("estimated_cost_inr") or 0.0)
        except (TypeError, ValueError):
            pass
    return {
        "ok": bool(reservations) and bool(settled) and total_inr <= budget_inr,
        "has_reservation": bool(reservations),
        "all_settled": bool(reservations) and len(settled) == len(reservations),
        "reservation_count": len(reservations),
        "call_count": len(calls),
        "total_cost_inr": round(total_inr, 6),
        "within_budget": total_inr <= budget_inr,
        "pricing_known": all(bool(c.get("cost_known", True)) for c in calls),
    }


# ---------------------------------------------------------------------------
# acceptance ledger + mutation ledger
# ---------------------------------------------------------------------------

def read_acceptance_ledger(path: Path) -> dict[str, Any]:
    if not Path(path).exists():
        return {"available": False, "path": str(path)}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "path": str(path), "error": str(exc)}
    return {"available": True, "path": str(path), **data}


def read_orchestration_lifecycle(workspace: str | Path) -> dict[str, Any]:
    """Read the orchestrator journal for IN-TURN test and repair evidence.

    This is the authoritative record that the engine executed tests inside the
    task, diagnosed failures, spent an authorized repair dispatch, re-executed,
    and evaluated the completion gate — all before the turn ended.
    """
    root = Path(workspace) / ".crusorai"
    journals = sorted(root.rglob("orchestration_journal.jsonl")) if root.exists() else []
    out: dict[str, Any] = {"available": False, "tests": [], "repairs": [],
                           "diagnoses": [], "completion": None, "completion_ok": False,
                           "contract": None, "assignment": None, "plan": None,
                           "cross_file": None, "test_repairs": []}
    if not journals:
        return out
    try:
        lines = journals[-1].read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {**out, "error": str(exc)}
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    for event in events:
        kind = event.get("event_type")
        details = event.get("details") or {}
        if kind in {"TESTS_EXECUTED", "TESTS_REEXECUTED"}:
            out["tests"].append(details.get("run") or {})
            if details.get("evidence"):
                out.setdefault("test_evidence", []).append(details["evidence"])
        elif kind == "FAILURES_CLASSIFIED":
            out["diagnoses"].append(details)
        elif kind == "REPAIR_DISPATCHED":
            out["repairs"].append(details)
        elif kind == "COMPLETION_EVALUATED":
            out["completion"] = details
            out["completion_ok"] = bool(details.get("ok"))
        elif kind == "TASK_DELIVERED":
            out["delivery"] = details
            out["requirement_verification"] = details.get("requirement_verification") or []
        elif kind == "CONTRACT_EXTRACTED":
            out["contract"] = details
        elif kind == "FILES_ASSIGNED":
            out["assignment"] = details
        elif kind == "PLAN_VALIDATED":
            out["plan"] = details
        elif kind == "CROSS_FILE_VALIDATED":
            out["cross_file"] = details
        elif kind == "TEST_REPAIR_APPLIED":
            out["test_repairs"].append(details)
    out["available"] = True
    out["path"] = str(journals[-1])
    out["event_types"] = [e.get("event_type") for e in events]
    out["final_test_run"] = out["tests"][-1] if out["tests"] else None
    return out


def classify_guard(
    ledger: dict[str, Any],
    *,
    run_id: str,
    bridge_pid: int | None = None,
    owned_bridge_pids: list[int] | None = None,
    max_dispatches: int = 5,
) -> dict[str, Any]:
    """Validate the acceptance ledger against the app's own bridge processes.

    The ledger's ``pid`` is the interpreter that imported ``src.bridge``. With a
    venv launcher shim that is a CHILD of the process the utility spawned, so
    acceptance is decided against the whole app-owned bridge set, and the exact
    pid is reported.
    """
    if not ledger.get("available"):
        return {"ok": False, "reason": ledger.get("error") or "acceptance ledger missing"}
    claims = ledger.get("claims") or []
    allowed = set(owned_bridge_pids or ([] if bridge_pid is None else [bridge_pid]))
    ledger_pid = ledger.get("pid")
    pid_ok = True if not allowed else int(ledger_pid or -1) in {int(p) for p in allowed}
    return {
        "ok": (
            ledger.get("run_id") == run_id
            and int(ledger.get("max_dispatches") or 0) == max_dispatches
            and int(ledger.get("attempts_per_dispatch") or 0) == 1
            and len(claims) <= max_dispatches
            and pid_ok
        ),
        "run_id_matches": ledger.get("run_id") == run_id,
        "max_dispatches": ledger.get("max_dispatches"),
        "attempts_per_dispatch": ledger.get("attempts_per_dispatch"),
        "dispatches_used": ledger.get("dispatches_used", len(claims)),
        "pid": ledger_pid,
        "owned_bridge_pids": sorted(allowed),
        "bridge_pid": bridge_pid,
        "pid_matches_bridge": pid_ok,
        "claims": claims,
    }


def read_mutation_ledger(workspace: Path) -> list[dict[str, Any]]:
    root = Path(workspace) / ".crusorai" / "tenants"
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return out
    for path in root.rglob("ledger/*_ledger.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        records = data if isinstance(data, list) else data.get("records") or data.get("changes") or []
        for record in records:
            if isinstance(record, dict):
                out.append({"tenant_ledger": str(path), **record})
    return out
