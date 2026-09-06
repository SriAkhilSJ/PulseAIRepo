"""``clarify`` -- hermes' ask tool, ported from ``tools/clarify_tool.py``.

Structured multiple-choice / open-ended questions to the user. Schema,
validation and a thin dispatcher here; the UI lives in the platform (upstream:
cli.py / gateway / tui_gateway; here: the bridge ``clarify_request`` frame and
the desktop question card, resolved through the ``clarify_reply`` frame).

Pipeline: normalize -> mark the recommended choice -> queue the request (the
turn BLOCKS, exactly like a safety approval) -> the card replies per qid ->
result JSON ``{responses: [...]}`` in question order. Timeout resolves every
unanswered question to the canonical sentinel and flags ``timed_out`` so the
model knows the user walked away and decides for itself.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

MAX_CHOICES = 4  # the UI always appends an "Other (type your answer)" row
MAX_QUESTIONS = 5  # independent questions per batch call
# Canonical timeout sentinel. The blocking layer returns this exact text; the
# tool treats it (like an empty answer) as "the user walked away".
TIMEOUT_RESPONSE = ("The user did not provide a response within the time limit. "
                    "Use your best judgement to make the choice and proceed.")
# Applied to the first choice here (not per-surface) so every surface renders it identically.
RECOMMENDED_LABEL = "(Recommended)"
_UNAVAILABLE = "Clarify tool is not available in this execution context."


def _flatten_choice(c: Any) -> str:
    """Coerce one choice to display text. LLMs sometimes emit dict-shaped choices and ``str(c)``
    would leak the repr onto every surface and back as the answer; unwrap order ``label`` >
    ``description`` > ``text`` > ``title`` (``name``/``value`` excluded: raw component enums,
    not labels). No match -> "" and dropped: no choice beats a garbage label."""
    if isinstance(c, str):
        return c.strip()
    if isinstance(c, dict):
        return next((v.strip() for k in ("label", "description", "text", "title")
                     if isinstance(v := c.get(k), str) and v.strip()), "")
    if isinstance(c, (list, tuple)):
        return " ".join(_flatten_choice(x) for x in c).strip()
    return "" if c is None else str(c).strip()


def mark_recommended(choices: list[str]) -> list[str]:
    """Suffix the first choice (schema says best-first) with RECOMMENDED_LABEL; idempotent,
    and a lone choice is left untouched (nothing to prefer it over)."""
    first = str(choices[0]).strip() if choices else ""
    if len(choices) < 2 or first != strip_recommended(first):
        return choices
    return [f"{first} {RECOMMENDED_LABEL}"] + list(choices[1:])


def strip_recommended(text: str) -> str:
    """Remove the recommendation label so presentation never leaks into ``user_response``."""
    stripped = str(text).strip()
    if stripped.casefold().endswith(RECOMMENDED_LABEL.casefold()):
        return stripped[: -len(RECOMMENDED_LABEL)].strip()
    return stripped


def _json_as(raw: str, kind):
    """``json.loads(raw)`` when it decodes to an instance of ``kind``, else None."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, kind) else None


def _parse_multi_select_response(raw_response: Any) -> list[str]:
    """Parse a list / JSON array / comma-separated reply into stripped non-empty strings."""
    items = raw_response
    if not isinstance(items, list):
        raw = str(items).strip()
        items = _json_as(raw, list) if raw.startswith("[") else None
        if items is None:
            items = raw.split(",")
    return [str(r).strip() for r in items if str(r).strip()]


def _clean_answer(raw: Any, multi: bool):
    """Strip presentation (the label, multi-select JSON) from a locked answer."""
    return [strip_recommended(r) for r in _parse_multi_select_response(raw)] if multi else strip_recommended(raw)


def _clean_choices(choices: list) -> list[str] | None:
    """Flatten, drop empties, cap at MAX_CHOICES; None when nothing survives (open-ended)."""
    cleaned = [s for s in (_flatten_choice(c) for c in choices) if s]
    return cleaned[:MAX_CHOICES] or None


def _is_timeout(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and raw.strip() == TIMEOUT_RESPONSE)


def _normalize_questions(questions: Any) -> tuple:
    """Validate the ``questions`` batch param -> ``(normalized, error)``; an empty list gives
    ``(None, None)`` (fall back to the single-question path). Entries carry ``qid`` (stable
    wire id ``q<index>`` surfaces key answers by; the model's ``id`` is unvalidated text, only
    echoed), ``question``, decorated ``choices``, bare ``choices_offered``, ``multi_select``."""
    if not isinstance(questions, list):
        return None, "questions must be an array of question objects."
    if not questions:
        return None, None
    if len(questions) > MAX_QUESTIONS:
        return None, f"questions supports at most {MAX_QUESTIONS} items."
    normalized = []
    for index, item in enumerate(questions):
        if isinstance(item, str):  # tolerate bare-string items: LLMs sometimes send ["Q1?", "Q2?"]
            item = {"question": item}
        if not isinstance(item, dict):
            return None, f"questions[{index}] must be an object with a 'question'."
        text = str(item.get("question") or "").strip()
        if not text:
            return None, f"questions[{index}].question must be non-empty text."
        choices = item.get("choices")
        if choices is not None:
            if not isinstance(choices, list):
                return None, f"questions[{index}].choices must be a list."
            choices = _clean_choices(choices)
        normalized.append({
            "qid": f"q{index}", "id": str(item.get("id") or "").strip() or None, "question": text,
            "choices": mark_recommended(list(choices)) if choices else None,
            "choices_offered": list(choices) if choices else None,
            "multi_select": bool(item.get("multi_select")) and bool(choices),
        })
    return normalized, None


def _batch_result(normalized: list[dict], answers: dict, timed_out: bool) -> str:
    """Batch result JSON; unanswered -> "". The top-level ``timed_out`` flag (present only when
    true) tells the agent whether blanks are deliberate skips or the user walking away."""
    responses = []
    for entry in normalized:
        raw = answers.get(entry["qid"])
        responses.append({
            **({"id": entry["id"]} if entry["id"] else {}),
            "question": entry["question"], "choices_offered": entry["choices_offered"],
            "user_response": _clean_answer(raw, entry["multi_select"]) if raw else "",
        })
    result: dict[str, Any] = {"responses": responses}
    if timed_out:
        result["timed_out"] = True
    return json.dumps(result, ensure_ascii=False)


def clarify_tool(
    questions: list | None = None, question: str = "", choices: list | None = None,
    multi_select: bool = False, *, callback=None, session_id: str = "default",
    timeout: float = 300.0,
) -> str:
    """Ask one question (``question``/``choices``/``multi_select``) or a batch (``questions``
    wins when non-empty). ``callback`` is platform injected (upstream: cli.py / gateway;
    here: the ClarifyQueue + bridge frames). Returns result JSON."""
    if questions is not None:
        normalized, error = _normalize_questions(questions)
        if error:
            return json.dumps({"error": error}, ensure_ascii=False)
        if normalized:
            if callback is None:
                return json.dumps({"error": _UNAVAILABLE}, ensure_ascii=False)
            try:
                return _run_batch(normalized, callback, session_id=session_id, timeout=timeout)
            except Exception as exc:
                return json.dumps({"error": f"Failed to get user input: {exc}"}, ensure_ascii=False)
        # Empty questions array -> fall through to the single-question path.
    if not question or not question.strip():
        return json.dumps({"error": (
            "No question provided. Pass questions=[{question: '...', "
            "choices?: [...], multi_select?: bool}, ...] -- a single question "
            "is a one-entry array."
        )}, ensure_ascii=False)
    question = question.strip()
    if choices is not None:
        if not isinstance(choices, list):
            return json.dumps({"error": "choices must be a list of strings."}, ensure_ascii=False)
        choices = _clean_choices(choices)
    if callback is None:
        return json.dumps({"error": _UNAVAILABLE}, ensure_ascii=False)
    # The bare list goes back to the agent; the "(Recommended)" label is presentation only.
    shown = mark_recommended(choices) if choices is not None else None
    try:
        raw_response = callback(question, shown, multi_select)
    except Exception as exc:
        return json.dumps({"error": f"Failed to get user input: {exc}"}, ensure_ascii=False)
    return json.dumps({
        "question": question, "choices_offered": choices,
        "user_response": _clean_answer(raw_response, multi_select and choices is not None),
    }, ensure_ascii=False)


def _queue_callback_factory(session_id: str, timeout: float):
    """The platform callback: one batch request through the ClarifyQueue, resolved by
    the bridge ``clarify_reply`` frame (or a Skip / timeout). Batch-capable by
    construction — the whole normalized list rides ONE card, hermes #18450."""
    from src.dashboard.event_bus import clarify_queue, event_bus

    def _callback(question: str, _choices, _multi_select, questions=None):
        if not questions:
            questions = [{
                "qid": "q0", "id": None, "question": question,
                "choices": _choices, "choices_offered": _choices,
                "multi_select": bool(_multi_select),
            }]
        request_id = uuid.uuid4().hex[:16]
        item = clarify_queue.request(request_id, questions, session_id=session_id)
        event_bus.emit("tool.clarify.request", {**item, "title": str(question or "").strip()})

        # Stop must wake a clarify wait immediately rather than leave the
        # bridge blocked for the full timeout (the approval-flow discipline).
        from src.runtime.turn_control import turn_controls

        def _abort_clarify(pending_request=request_id, pending_session=session_id):
            clarify_queue.resolve(
                pending_request, {}, timed_out=True, session_id=pending_session
            )

        turn_controls.register_abort(session_id, _abort_clarify)
        try:
            decision = clarify_queue.wait_for_answers(request_id, timeout=timeout)
        finally:
            turn_controls.unregister_abort(session_id, _abort_clarify)
        if not decision:
            return TIMEOUT_RESPONSE
        if decision.get("timed_out"):
            return TIMEOUT_RESPONSE
        return json.dumps(
            {"answers": decision.get("answers") or {}, "request_id": request_id},
            ensure_ascii=False,
        )

    return _callback


def _run_batch(normalized: list[dict], callback, *, session_id: str, timeout: float) -> str:
    """Dispatch a validated batch. The batch-capable callback gets the whole list once
    and replies ``{"answers": {qid: raw}, "timed_out"?}`` as a dict or JSON string; any
    other falsy/unparseable reply is a cancel-all."""
    raw = callback("", None, False, questions=normalized)
    timed_out = _is_timeout(raw)
    if isinstance(raw, str):
        raw = _json_as(raw, dict)  # the sentinel is not JSON -> None, timed_out stays True
    if isinstance(raw, dict):
        answers = dict(raw.get("answers") or {})
        timed_out = bool(raw.get("timed_out"))
        return _batch_result(normalized, answers, timed_out)
    return _batch_result(normalized, {}, timed_out)


@tool
def clarify(
    questions: list[dict[str, Any]] | None = None,
    question: str = "",
    choices: list[str] | None = None,
    multi_select: bool = False,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """Ask the user one or more questions when you need a decision, clarification, or feedback before proceeding. Pass every question in `questions` (1-5 entries) — a single question is a one-entry array, and several INDEPENDENT questions belong in ONE call (one form beats a chain of clarify calls; if one answer would change another question, ask separately). Per question: single-select (up to 4 choices — put your recommended option FIRST, the UI marks it '(Recommended)' and auto-appends an 'Other' free-text row), multi-select (multi_select=true), or open-ended (omit choices). Options go ONLY in `choices`, never enumerated inside the question text (choices render as pickable rows; options written into the question are dead prose the user can't click). Result: {responses: [...]} in question order (plus timed_out=true if the user stopped part-way). Prefer deciding low-stakes questions yourself; don't use this for dangerous-command confirmation (the terminal tool handles that)."""
    session_id = "default"
    try:
        session_id = str((config or {}).get("configurable", {}).get("thread_id") or "default")
    except Exception:
        pass
    timeout = 300.0
    try:
        import os
        timeout = float(os.environ.get("PULSEAI_CLARIFY_TIMEOUT_S", "").strip() or 300.0)
    except (TypeError, ValueError):
        timeout = 300.0
    callback = _queue_callback_factory(session_id, timeout)
    return clarify_tool(
        questions=questions, question=question, choices=choices,
        multi_select=multi_select, callback=callback, session_id=session_id,
        timeout=timeout,
    )


__all__ = [
    "clarify", "clarify_tool", "MAX_CHOICES", "MAX_QUESTIONS", "TIMEOUT_RESPONSE",
    "RECOMMENDED_LABEL", "mark_recommended", "strip_recommended",
]
