"""Typed, versioned Agent UI cards derived from canonical turn events.

The bridge remains the only event source. Cards are a presentation projection:
the same event that already drives the transcript may also produce one card,
which the renderer validates again before painting. Model text is untrusted:
cards carry data only, never HTML/JS/CSS, and every string is bounded.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable

CARD_SCHEMA_VERSION = 1
CARD_EVENT_NAME = "agent_card"

CARD_TYPES = frozenset({
    "activity",
    "thinking",
    "read",
    "search",
    "plan",
    "file_change",
    "approval",
    "tool",
    "test_results",
    "verification",
    "delivery",
    "cost",
})

MAX_TEXT = 8_000
MAX_ITEMS = 200
MAX_DIFF = 40_000
MAX_DEPTH = 6

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    text = _CONTROL_RE.sub("", str(value))
    return text if len(text) <= limit else text[:limit] + "…"


def _string_list(value: Any, limit: int = MAX_ITEMS) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item, 500) for item in list(value)[:limit] if item is not None]


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        # NaN/Infinity would serialize to non-standard JSON.
        return value if isinstance(value, int) else (value if value == value and abs(value) != float("inf") else None)
    return _text(value)


def _safe_value(value: Any, depth: int = 0) -> Any:
    """Allow JSON-shaped data only; drop prototypes, callables and markup."""
    if depth > MAX_DEPTH:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return _safe_scalar(value)
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth + 1) for item in list(value)[:MAX_ITEMS]]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_ITEMS:
                break
            name = _text(key, 120)
            if not name or name in {"__proto__", "constructor", "prototype"}:
                continue
            out[name] = _safe_value(item, depth + 1)
        return out
    return None


def normalize_card(
    raw: Any,
    *,
    session_id: str = "",
    turn_id: str = "",
    card_id: str = "",
) -> dict[str, Any] | None:
    """Validate and normalize one card payload. Unknown types fail safe.

    Returns ``None`` only when the envelope itself is unusable. A known
    envelope with an unknown ``card_type`` returns a supported=False card so
    the pane can show a controlled unsupported indicator.
    """
    if not isinstance(raw, dict):
        return None
    version = raw.get("schema_version", CARD_SCHEMA_VERSION)
    if not isinstance(version, int) or version < 1 or version > CARD_SCHEMA_VERSION:
        return None
    declared = _text(raw.get("card_type") or raw.get("type"), 80)
    identifier = _text(card_id or raw.get("card_id"), 200)
    if not identifier:
        return None
    if declared not in CARD_TYPES:
        return {
            "schema_version": CARD_SCHEMA_VERSION,
            "card_type": "unsupported",
            "declared_type": declared or "unknown",
            "supported": False,
            "card_id": identifier,
            "session_id": _text(session_id or raw.get("session_id"), 200),
            "turn_id": _text(turn_id or raw.get("turn_id"), 200),
            "data": {},
        }
    data = _safe_value(raw.get("data"))
    if not isinstance(data, dict):
        data = {}
    if declared == "approval":
        data["diff"] = _text(data.get("diff"), MAX_DIFF)
        data["digest"] = _text(data.get("digest"), 200)
    return {
        "schema_version": CARD_SCHEMA_VERSION,
        "card_type": declared,
        "supported": True,
        "card_id": identifier,
        "session_id": _text(session_id or raw.get("session_id"), 200),
        "turn_id": _text(turn_id or raw.get("turn_id"), 200),
        "data": data,
    }


def _card(card_type: str, card_id: str, data: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any] | None:
    return normalize_card(
        {"schema_version": CARD_SCHEMA_VERSION, "card_type": card_type, "card_id": card_id, "data": data},
        session_id=str(identity.get("session_id") or ""),
        turn_id=str(identity.get("turn_id") or ""),
    )


def _result_object(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _diff_stats(result: Any) -> dict[str, int]:
    record = _result_object(result)
    added = record.get("lines_added", record.get("added"))
    removed = record.get("lines_removed", record.get("removed"))
    if isinstance(added, int) and isinstance(removed, int):
        return {"added": added, "removed": removed}
    return {"added": 0, "removed": 0}


def card_for_frame(frame: dict[str, Any], *, turn_id: str = "") -> dict[str, Any] | None:
    """Project one canonical protocol frame onto an optional UI card."""
    kind = str(frame.get("type") or "")
    identity = {
        "session_id": frame.get("session_id") or "",
        "turn_id": frame.get("turn_id") or turn_id or "",
    }
    suffix = str(frame.get("turn_id") or turn_id or "turn")
    tool_id = _text(frame.get("tool_id"), 200) or "tool"
    name = _text(frame.get("name"), 120) or "tool"

    if kind in {"turn_started", "llm.request"}:
        label = "Understanding request" if kind == "turn_started" else "Waiting on the model"
        return _card("activity", f"{suffix}:activity", {
            "stage": "understanding" if kind == "turn_started" else "generating",
            "label": label,
            "status": "running",
        }, identity)

    if kind == "plan_updated":
        steps = []
        for step in frame.get("steps") or []:
            if not isinstance(step, dict):
                continue
            steps.append({
                "text": _text(step.get("text") or step.get("content") or step.get("step"), 1000),
                "status": _text(step.get("status") or "pending", 40),
            })
            if len(steps) >= MAX_ITEMS:
                break
        return _card("plan", f"{suffix}:plan", {
            "summary": _text(frame.get("summary") or "", 2000),
            "steps": steps,
            "files": _string_list(frame.get("files")),
            "verification": _string_list(frame.get("verification")),
        }, identity)

    if kind == "tool_call_start":
        return _card("tool", f"{suffix}:tool:{tool_id}", {
            "tool_id": tool_id,
            "name": name,
            "description": _text(frame.get("description") or f"Running {name}", 500),
            "status": "running",
        }, identity)

    if kind == "tool_call_end":
        status = _text(frame.get("status") or "completed", 40)
        normalized_status = "succeeded" if status in {"completed", "success", "ok", "passed"} else status
        card = _card("tool", f"{suffix}:tool:{tool_id}", {
            "tool_id": tool_id,
            "name": name,
            "description": _text(f"{name} {status}", 500),
            "status": normalized_status,
            "duration_ms": _safe_scalar(_result_object(frame.get("result")).get("duration_ms")),
        }, identity)
        return card

    if kind == "safety_request":
        diff = frame.get("diff")
        diff_text = json.dumps(diff, ensure_ascii=False, indent=2) if not isinstance(diff, str) else diff
        return _card("approval", f"{suffix}:approval:{tool_id}", {
            "tool_id": tool_id,
            "path": _text(frame.get("path") or _result_object(diff).get("path"), 500),
            "operation": _text(frame.get("operation") or _result_object(diff).get("operation") or "write", 80),
            "diff": _text(diff_text, MAX_DIFF),
            "digest": _text(frame.get("digest") or _result_object(diff).get("digest"), 200),
            "status": "pending",
        }, identity)

    if kind == "verification_updated":
        verified = frame.get("verified_requirements") or frame.get("verified") or []
        unverified = frame.get("unverified_requirements") or frame.get("unverified") or []
        return _card("verification", f"{suffix}:verification", {
            "status": _text(frame.get("status") or frame.get("verification_status") or "unknown", 60),
            "verified": _string_list(verified),
            "unverified": _string_list(unverified),
            "changed_files": _string_list(frame.get("changed_files")),
            "evidence": _string_list(frame.get("evidence_refs") or frame.get("evidence")),
        }, identity)

    if kind == "telemetry":
        return _card("cost", f"{suffix}:cost", {
            "model": _text(frame.get("model"), 200),
            "provider": _text(frame.get("provider"), 120),
            "input_tokens": _safe_scalar(frame.get("input_tokens") or frame.get("input")),
            "output_tokens": _safe_scalar(frame.get("output_tokens") or frame.get("output")),
            "cached_tokens": _safe_scalar(frame.get("cached_tokens") or frame.get("cache")),
            "cost_inr": _safe_scalar(frame.get("cost_inr")),
            "cost_usd": _safe_scalar(frame.get("cost_usd")),
            "certainty": _text(frame.get("cost_certainty") or "unknown", 20),
        }, identity)

    if kind in {"turn_done", "turn_failed"}:
        receipt = frame.get("receipt") if isinstance(frame.get("receipt"), dict) else {}
        delivery = receipt.get("delivery") if isinstance(receipt.get("delivery"), dict) else {}
        usage = receipt.get("usage") if isinstance(receipt.get("usage"), dict) else {}
        tests = receipt.get("tests") if isinstance(receipt.get("tests"), dict) else {}
        status = _text(receipt.get("terminal_status") or ("completed" if kind == "turn_done" else "failed"), 40)
        card = _card("delivery", f"{suffix}:delivery", {
            "verdict": _text(receipt.get("engineering_verdict") or status, 200),
            "status": status,
            "verification": _text(receipt.get("verification_status") or "", 60),
            "files_modified": _string_list(receipt.get("changed_files")),
            "tests_executed": _string_list(tests.get("executed")),
            "tests_passed": _string_list(tests.get("passed")),
            "tests_failed": _string_list(tests.get("failed")),
            "approvals": len(receipt.get("approval_receipts") or []),
            "mutations": len(receipt.get("mutation_receipts") or []),
            "message": _text(receipt.get("message") or frame.get("message"), 2000),
        }, identity)
        return card

    return None


def card_frames_for_frame(frame: dict[str, Any], *, turn_id: str = "") -> list[dict[str, Any]]:
    """Companion cards: one canonical event can project more than one card."""
    cards: list[dict[str, Any]] = []
    card = card_for_frame(frame, turn_id=turn_id)
    if card is not None:
        cards.append(card)
    if str(frame.get("type") or "") == "tool_call_end":
        name = str(frame.get("name") or "").lower()
        identity = {
            "session_id": frame.get("session_id") or "",
            "turn_id": frame.get("turn_id") or turn_id or "",
        }
        suffix = str(frame.get("turn_id") or turn_id or "turn")
        tool_id = _text(frame.get("tool_id"), 200) or "tool"
        if any(token in name for token in ("write", "edit", "create_file", "apply_patch")):
            stats = _diff_stats(frame.get("result"))
            path = _text(_result_object(frame.get("result")).get("path") or frame.get("path"), 500)
            file_card = _card("file_change", f"{suffix}:file:{tool_id}", {
                "path": path,
                "operation": _text("edit" if "edit" in name else "write", 40),
                "added": stats["added"],
                "removed": stats["removed"],
                "status": _text(frame.get("status") or "completed", 40),
            }, identity)
            if file_card is not None:
                cards.append(file_card)
        if any(token in name for token in ("test", "pytest", "vitest", "jest")):
            tests = test_result_card(frame, turn_id=turn_id)
            if tests is not None:
                cards.append(tests)
    if str(frame.get("type") or "") in {"turn_done", "turn_failed"}:
        identity = {
            "session_id": frame.get("session_id") or "",
            "turn_id": frame.get("turn_id") or turn_id or "",
        }
        suffix = str(frame.get("turn_id") or turn_id or "turn")
        receipt = frame.get("receipt") if isinstance(frame.get("receipt"), dict) else {}
        delivery = receipt.get("delivery") if isinstance(receipt.get("delivery"), dict) else {}
        tests = receipt.get("tests") if isinstance(receipt.get("tests"), dict) else {}
        usage = receipt.get("usage") if isinstance(receipt.get("usage"), dict) else {}

        plan_steps = receipt.get("plan") if isinstance(receipt.get("plan"), list) else []
        if plan_steps:
            steps = []
            for step in plan_steps[:MAX_ITEMS]:
                if isinstance(step, str):
                    steps.append({"text": _text(step, 1000), "status": "pending"})
                elif isinstance(step, dict):
                    steps.append({
                        "text": _text(step.get("text") or step.get("description") or step.get("content"), 1000),
                        "status": _text(step.get("status") or "pending", 40),
                    })
            plan_card = _card("plan", f"{suffix}:receipt:plan", {
                "summary": _text(delivery.get("what_was_requested"), 2000),
                "steps": steps,
                "files": _string_list(receipt.get("changed_files")),
                "verification": _string_list(delivery.get("requirement_verification")),
            }, identity)
            if plan_card is not None:
                cards.append(plan_card)

        for index, path in enumerate(_string_list(receipt.get("changed_files"))[:MAX_ITEMS]):
            file_card = _card("file_change", f"{suffix}:receipt:file:{index}", {
                "path": path,
                "operation": "change",
                "added": 0,
                "removed": 0,
                "status": "applied",
            }, identity)
            if file_card is not None:
                cards.append(file_card)

        executed = tests.get("executed") if isinstance(tests.get("executed"), list) else []
        passed = tests.get("passed") if isinstance(tests.get("passed"), list) else []
        failed = tests.get("failed") if isinstance(tests.get("failed"), list) else []
        if executed or passed or failed:
            test_card = _card("test_results", f"{suffix}:receipt:tests", {
                "executed": len(executed),
                "passed": len(passed),
                "failed": len(failed),
                "skipped": 0,
                "failures": _string_list(failed),
            }, identity)
            if test_card is not None:
                cards.append(test_card)

        verification_status = _text(receipt.get("verification_status"), 60)
        if verification_status:
            verification_card = _card("verification", f"{suffix}:receipt:verification", {
                "status": verification_status,
                "verified": _string_list(delivery.get("requirement_verification")),
                "unverified": _string_list(delivery.get("remaining_limitations")),
                "changed_files": _string_list(receipt.get("changed_files")),
                "evidence": [],
            }, identity)
            if verification_card is not None:
                cards.append(verification_card)

        tokens = usage.get("token_usage") if isinstance(usage.get("token_usage"), dict) else {}
        model_invocations = receipt.get("model_invocations") if isinstance(receipt.get("model_invocations"), dict) else {}
        if usage or tokens or model_invocations.get("ids"):
            invocation_ids = []
            for value in model_invocations.get("ids") or []:
                invocation_ids.append(_text(value, 200))
            cost_card = _card("cost", f"{suffix}:receipt:cost", {
                "model": _text(tokens.get("model"), 200),
                "provider": _text(tokens.get("provider"), 120),
                "input_tokens": _safe_scalar(tokens.get("input_tokens")),
                "output_tokens": _safe_scalar(tokens.get("output_tokens")),
                "cached_tokens": _safe_scalar(tokens.get("cached_tokens")),
                "cost_inr": _safe_scalar(usage.get("cost_inr")),
                "cost_usd": _safe_scalar(usage.get("cost_usd")),
                "certainty": "unknown" if (
                    usage.get("cost_unknown") or usage.get("cost_inr") is None
                ) else "actual",
                "invocation_ids": invocation_ids,
            }, identity)
            if cost_card is not None:
                cards.append(cost_card)
    return cards


def test_result_card(frame: dict[str, Any], *, turn_id: str = "") -> dict[str, Any] | None:
    """Test-results card for a test-runner tool result."""
    result = _result_object(frame.get("result"))
    if not result:
        return None
    executed = result.get("executed") or result.get("tests") or result.get("total")
    if executed is None:
        return None
    identity = {"session_id": frame.get("session_id") or "", "turn_id": frame.get("turn_id") or turn_id}
    return _card("test_results", f"{frame.get('turn_id') or turn_id}:tests", {
        "executed": _safe_scalar(executed),
        "passed": _safe_scalar(result.get("passed")),
        "failed": _safe_scalar(result.get("failed")),
        "skipped": _safe_scalar(result.get("skipped")),
        "duration_ms": _safe_scalar(result.get("duration_ms")),
        "failures": _string_list(result.get("failures") or result.get("failure_summary")),
    }, identity)


def card_frame(card: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": CARD_EVENT_NAME,
        "event_id": f"{card['card_id']}:{identity.get('turn_id') or ''}",
        "timestamp": None,
        **identity,
        "session_id": card.get("session_id") or identity.get("session_id"),
        "card": card,
    }
