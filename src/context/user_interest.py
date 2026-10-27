"""Bounded user-interest state for Agent Core.

The main model should decide meaning from the user's actual words.  This module
therefore does *not* add a second model/classifier call or rewrite the request
into an invented goal.  It keeps the initial objective and newest steering
source-faithfully (within explicit bounds), records conservative routing signals,
and carries explicit constraint/evidence excerpts across retries and context
compaction.

Design lineage:
- Codex keeps model context separate from the real user request and retains the
  newest unanswered request.
- OpenCode checkpoints Objective, Requirements, Decisions, and Work State.
- Gemini CLI distinguishes directives from inquiries and treats later hints as
  scope-preserving corrections.
- Cline retains the initial task and latest user messages during truncation.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re
from typing import Any, Literal, Mapping


SCHEMA_VERSION = 1
MAX_OBJECTIVE_CHARS = 2_400
MAX_INSTRUCTION_CHARS = 1_600
MAX_STEERING_ITEMS = 3
MAX_STEERING_CHARS = 600
MAX_CONSTRAINTS = 6
MAX_OUTCOME_ITEMS = 4
MAX_EVIDENCE_ITEMS = 4
MAX_EXCERPT_CHARS = 240
MAX_FOCUS_CHARS = 3_600

InterestMode = Literal["act", "answer", "social", "undetermined"]
ChangePolicy = Literal["changes_requested", "no_changes", "unspecified"]
TaskRelationship = Literal[
    "new",
    "continue",
    "corrects",
    "replaces",
    "unrelated",
    "undetermined",
    "cancelled",
]

# A narrow, explicit command vocabulary.  These expressions decide only the
# routing hint; the main model still sees the source request and owns semantic
# interpretation.  Whole-word matching avoids bugs such as "address" matching
# "add" or "explain" accidentally becoming an execution request.
_ACTION_VERBS = (
    "add|apply|build|change|commit|configure|create|delete|deploy|edit|execute|"
    "fix|implement|install|migrate|move|optimize|push|refactor|remove|rename|"
    "repair|replace|run|test|touch|update|verify|write"
)
_MUTATION_VERBS = (
    "add|apply|build|change|commit|configure|create|delete|deploy|edit|fix|"
    "implement|install|migrate|move|optimize|push|refactor|remove|rename|"
    "repair|replace|touch|update|write"
)
_COMMAND_RE = re.compile(
    rf"(?im)^\s*(?:[-*]\s*)?(?:(?:now|only|just)\s+)?(?:please\s+)?"
    rf"(?:{_ACTION_VERBS})\b"
)
_POLITE_ACTION_RE = re.compile(
    rf"(?i)\b(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:{_ACTION_VERBS})\b"
)
_EXPLICIT_ACTION_RE = re.compile(
    rf"(?i)\b(?:i\s+(?:want|need|would\s+like)\s+you\s+to|please|go\s+ahead\s+and)\s+"
    rf"(?:{_ACTION_VERBS})\b"
)
_ACTION_CLAUSE_RE = re.compile(
    rf"(?i)\b(?:and|then|also)\s+(?:please\s+)?(?:{_ACTION_VERBS})\b"
)
_MUTATION_RE = re.compile(rf"(?i)\b(?:{_MUTATION_VERBS})\b")
# Mutation words inside an explicit prohibition are constraints, not positive
# authorization.  Keep the original clause in the contract, but remove its
# mutation verbs from the cheap routing hint before deciding change policy.
_NEGATED_MUTATION_RE = re.compile(
    rf"(?i)\b(?:do\s+not|don't|dont|never|avoid)\s+"
    rf"(?:(?:attempt(?:ing)?|try(?:ing)?)\s+to\s+)?"
    rf"(?:{_MUTATION_VERBS})\b"
    rf"(?:\s+(?:anything|something|files?|code|software|packages?|dependencies))?"
    rf"(?:\s+(?:or|and)\s+(?:{_MUTATION_VERBS})\b"
    rf"(?:\s+(?:anything|something|files?|code|software|packages?|dependencies))?)*"
)
_INQUIRY_RE = re.compile(
    r"(?is)^\s*(?:please\s+)?(?:"
    r"what|why|how|when|where|which|who|whose|is|are|am|was|were|do|does|did|"
    r"tell\s+me|explain|analy[sz]e|assess|review|compare|evaluate|summari[sz]e"
    r")\b"
)
_READ_ONLY_RE = re.compile(
    r"(?i)(?:"
    r"\b(?:do\s+not|don't|dont)\s+(?:make|modify|change|edit|write|implement|"
    r"code|touch)\b|"
    r"\bwithout\s+(?:making|modifying|changing|editing|writing|implementing|"
    r"coding|touching)\b|"
    r"\b(?:no|avoid)\s+(?:code|coding|changes?|edits?|implementation|mutation)\b|"
    r"\b(?:only|just)\s+(?:analy[sz]e|assess|inspect|review|explain|report|"
    r"discuss|tell\s+me)\b"
    r")"
)
_CONSTRAINT_RE = re.compile(
    r"(?i)\b(?:must|mustn't|mustnt|required|require(?:d|s)?|only|exactly|never|"
    r"do\s+not|don't|dont|do\s+nothing\s+else|nothing\s+else|"
    r"that(?:'s|\s+is)\s+all|without|avoid|exclude|except|at\s+least|at\s+most|"
    r"no\b|stick\s+to|scope|preserve|keep)\b"
)
_OUTCOME_RE = re.compile(
    r"(?i)\b(?:add|answer|analy[sz]e|build|change|compare|create|deliver|edit|"
    r"explain|fix|implement|output|produce|provide|refactor|remove|repair|"
    r"report|replace|return|review|run|save|test|update|verify|write|"
    r"app|application|artifact|code|document|file|patch|plan)\b"
)
_EVIDENCE_RE = re.compile(
    r"(?i)\b(?:test(?:s|ed|ing)?|verify|verified|verification|validate|validation|"
    r"evidence|prove|proof|screenshot|benchmark|typecheck|lint|exit\s+code)\b"
)

_EXPLICIT_REPLACEMENT_RE = re.compile(
    r"(?is)^\s*(?:"
    r"(?:new|different|another|fresh)\s+task\b|"
    r"start\s+over\b|"
    r"(?:forget|abandon)\s+(?:the\s+)?(?:previous|current|old|this|that)?\s*task\b|"
    r"scrap\s+(?:that|this|everything|(?:the\s+)?(?:previous|current|old)\s+task)\b"
    r")"
)
_EXPLICIT_CORRECTION_RE = re.compile(
    r"(?is)^\s*(?:actually\b|correction\s*[:\-]|to\s+clarify\b|"
    r"instead\b|but\b|however\b|only\b|"
    r"(?:change|adjust|correct|revise)\s+(?:that|it|the\s+(?:task|scope|request))\b)"
    r"|\b(?:instead\s+of|rather\s+than)\b"
)
_CORRECTION_PREFIX_RE = re.compile(
    r"(?is)^\s*(?:actually|correction|to\s+clarify|instead|but|however)\b"
    r"\s*[:;,\-–—]?\s*"
)

_PHATIC_WORDS = frozenset(
    "hi hey hello yo hiya howdy thanks thank thx ty ok okay kk cool nice great "
    "perfect awesome sure yes yeah yup nope yep sorry welcome bye gm gn bro".split()
)
_PHATIC_FILLER = frozenset("there you are friend man buddy all it its just so and".split())
_AUTHORIZATION_PHRASES = frozenset({
    "approve", "approved", "continue", "do it", "execute plan", "go ahead",
    "proceed", "run plan",
})


def _bounded(value: object, limit: int) -> str:
    """Normalize whitespace and make truncation explicit while keeping both ends."""
    text = " ".join(str(value or "").split()).strip()
    if len(text) <= limit:
        return text
    marker = " [... truncated ...] "
    room = max(0, limit - len(marker))
    head = room // 2
    return text[:head].rstrip() + marker + text[-(room - head):].lstrip()


def _dedupe_bounded(
    values: list[str] | tuple[str, ...], *, count: int, chars: int
) -> tuple[str, ...]:
    """Keep the newest unique excerpts, returned in chronological order."""
    newest: list[str] = []
    seen: set[str] = set()
    for raw in reversed(values):
        value = _bounded(raw, chars)
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        newest.append(value)
        if len(newest) >= count:
            break
    newest.reverse()
    return tuple(newest)


def _segments(text: str) -> list[str]:
    """Split user text into bounded, source-faithful sentence/bullet excerpts."""
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    pieces: list[str] = []
    for line in normalized.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if not line:
            continue
        # Sentence splitting is intentionally conservative: paths, versions,
        # and abbreviations stay intact unless punctuation is followed by
        # whitespace and a likely new clause.
        pieces.extend(re.split(r"(?<=[!?])\s+|(?<=\.)\s+(?=[A-Z])", line))
    return [piece.strip() for piece in pieces if piece.strip()]


def _extract(text: str, pattern: re.Pattern[str], maximum: int) -> tuple[str, ...]:
    return _dedupe_bounded(
        [piece for piece in _segments(text) if pattern.search(piece)],
        count=maximum,
        chars=MAX_EXCERPT_CHARS,
    )


def _is_social(text: str) -> bool:
    tokens = [
        token
        for token in re.findall(r"[a-z]+", str(text).lower())
        if token not in _PHATIC_FILLER
    ]
    if not tokens or len(tokens) > 5:
        return False

    def matches(token: str) -> bool:
        if token in _PHATIC_WORDS:
            return True
        stem = token
        while len(stem) >= 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem in _PHATIC_WORDS

    return all(matches(token) for token in tokens)


def _is_authorization(text: str) -> bool:
    normalized = " ".join(str(text or "").casefold().split()).strip(" .!…~")
    return normalized in _AUTHORIZATION_PHRASES


def _unwrap_routing_quotes(text: str) -> str:
    """Remove one balanced UI/report quote wrapper for routing only.

    Desktop bridges and copied prompts sometimes preserve the whole directive
    as ``"Run ..."``.  The quotes are formatting, not semantic uncertainty.
    The source string remains untouched in :class:`UserInterest`; only the
    deterministic routing view is unwrapped.
    """
    value = str(text or "").strip()
    pairs = {'"': '"', "'": "'", "“": "”", "‘": "’"}
    closing = pairs.get(value[:1])
    if closing and len(value) >= 2 and value.endswith(closing):
        inner = value[1:-1].strip()
        if inner:
            return inner
    return value


def _instruction_payload(text: str) -> str:
    """Drop routing labels while preserving the full text in the contract."""
    payload = _unwrap_routing_quotes(text)
    for pattern in (_EXPLICIT_REPLACEMENT_RE, _CORRECTION_PREFIX_RE):
        match = pattern.search(payload)
        if match:
            remainder = payload[match.end():].lstrip(" \t:,-–—")
            if remainder:
                payload = remainder
    return payload


def _positive_mutation_requested(text: str) -> bool:
    """Whether the instruction positively authorizes a workspace mutation."""
    without_prohibitions = _NEGATED_MUTATION_RE.sub("", text)
    return bool(_MUTATION_RE.search(without_prohibitions))


def decide_interest_mode(instruction: str) -> tuple[InterestMode, ChangePolicy, str]:
    """Return a conservative routing decision without pretending certainty.

    Explicit no-change language independently constrains mutation. An
    imperative or polite action request is an ``act`` turn. Questions and
    inquiries are ``answer`` turns. Everything else remains ``undetermined``
    for the main model rather than being guessed from a broad keyword list.
    """
    text = _instruction_payload(str(instruction or "").strip())
    if not text:
        return "undetermined", "unspecified", "empty"
    authorization = _is_authorization(text)
    if _is_social(text) or authorization:
        basis = "authorization_only" if authorization else "social_only"
        return "social", "unspecified", basis

    action = bool(
        _COMMAND_RE.search(text)
        or _POLITE_ACTION_RE.search(text)
        or _EXPLICIT_ACTION_RE.search(text)
        or _ACTION_CLAUSE_RE.search(text)
    )
    no_changes = bool(_READ_ONLY_RE.search(text))
    positive_mutation = _positive_mutation_requested(text)
    if action:
        # A scoped prohibition does not cancel an explicit delivery request:
        # "build the app; do not modify the tests" authorizes application
        # changes while protecting one artifact. Only a no-change directive
        # with no independent positive mutation keeps the whole turn read-only.
        if no_changes and not positive_mutation:
            return "act", "no_changes", "explicit_action_no_change"
        changes: ChangePolicy = (
            "changes_requested" if positive_mutation else "unspecified"
        )
        return "act", changes, "explicit_action"
    if no_changes:
        return "answer", "no_changes", "explicit_no_change"
    if _INQUIRY_RE.search(text) or "?" in text:
        return "answer", "unspecified", "inquiry"
    return "undetermined", "unspecified", "main_model_decides"


def infer_explicit_followup_relationship(instruction: str) -> TaskRelationship:
    """Recognize only user-explicit replacement/correction language.

    Semantic relatedness remains the main model's job (or the optional task
    classifier's job).  This free path records strong wording such as "new
    task" and "actually ... instead" without turning vague prose into a
    fabricated relationship.
    """
    text = _unwrap_routing_quotes(str(instruction or "").strip())
    if not text:
        return "undetermined"
    if _EXPLICIT_REPLACEMENT_RE.search(text):
        return "replaces"
    if _EXPLICIT_CORRECTION_RE.search(text):
        return "corrects"
    return "undetermined"


@dataclass(frozen=True)
class UserInterest:
    """Versioned, JSON-safe contract describing the user's active interest."""

    schema_version: int = SCHEMA_VERSION
    objective: str = ""
    latest_instruction: str = ""
    latest_substantive_instruction: str = ""
    steering: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    requested_outcomes: tuple[str, ...] = ()
    requested_evidence: tuple[str, ...] = ()
    mode: InterestMode = "undetermined"
    change_policy: ChangePolicy = "unspecified"
    relationship: TaskRelationship = "undetermined"
    decision_basis: str = "main_model_decides"
    fingerprint: str = ""

    def to_state(self) -> dict[str, Any]:
        data = asdict(self)
        for key in (
            "steering", "constraints", "requested_outcomes", "requested_evidence"
        ):
            data[key] = list(data[key])
        return data

    @classmethod
    def from_state(cls, value: object) -> "UserInterest | None":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            return None
        try:
            mode = str(value.get("mode") or "undetermined")
            if mode not in {"act", "answer", "social", "undetermined"}:
                mode = "undetermined"
            change_policy = str(value.get("change_policy") or "unspecified")
            if change_policy not in {
                "changes_requested", "no_changes", "unspecified"
            }:
                change_policy = "unspecified"
            relationship = str(value.get("relationship") or "undetermined")
            if relationship not in {
                "new", "continue", "corrects", "replaces", "unrelated",
                "undetermined", "cancelled",
            }:
                relationship = "undetermined"
            return cls(
                schema_version=SCHEMA_VERSION,
                objective=_bounded(value.get("objective"), MAX_OBJECTIVE_CHARS),
                latest_instruction=_bounded(
                    value.get("latest_instruction"), MAX_INSTRUCTION_CHARS
                ),
                latest_substantive_instruction=_bounded(
                    value.get("latest_substantive_instruction"),
                    MAX_INSTRUCTION_CHARS,
                ),
                steering=_dedupe_bounded(
                    list(value.get("steering") or []),
                    count=MAX_STEERING_ITEMS,
                    chars=MAX_STEERING_CHARS,
                ),
                constraints=_dedupe_bounded(
                    list(value.get("constraints") or []),
                    count=MAX_CONSTRAINTS,
                    chars=MAX_EXCERPT_CHARS,
                ),
                requested_outcomes=_dedupe_bounded(
                    list(value.get("requested_outcomes") or []),
                    count=MAX_OUTCOME_ITEMS,
                    chars=MAX_EXCERPT_CHARS,
                ),
                requested_evidence=_dedupe_bounded(
                    list(value.get("requested_evidence") or []),
                    count=MAX_EVIDENCE_ITEMS,
                    chars=MAX_EXCERPT_CHARS,
                ),
                mode=mode,  # type: ignore[arg-type]
                change_policy=change_policy,  # type: ignore[arg-type]
                relationship=relationship,  # type: ignore[arg-type]
                decision_basis=_bounded(value.get("decision_basis"), 80)
                or "main_model_decides",
                fingerprint=_bounded(value.get("fingerprint"), 64),
            )
        except Exception:
            return None

    def focus_text(self) -> str:
        """Text used for task classification and relevant-context retrieval."""
        if self.relationship == "unrelated" and self.latest_instruction:
            return _bounded(self.latest_instruction, MAX_FOCUS_CHARS)
        if self.mode == "social" and self.objective:
            return _bounded(self.objective, MAX_FOCUS_CHARS)
        latest = self.latest_substantive_instruction
        if latest and latest.casefold() != self.objective.casefold():
            return _bounded(
                f"{self.objective}\n\nLatest user direction: {latest}",
                MAX_FOCUS_CHARS,
            )
        return _bounded(latest or self.objective or self.latest_instruction, MAX_FOCUS_CHARS)


def _with_fingerprint(interest: UserInterest) -> UserInterest:
    data = interest.to_state()
    data.pop("fingerprint", None)
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return replace(interest, fingerprint=hashlib.sha256(encoded).hexdigest()[:16])


def resolve_user_interest(
    *,
    previous: object = None,
    objective: str,
    latest_instruction: str,
    relationship: TaskRelationship = "undetermined",
) -> UserInterest:
    """Resolve the bounded contract for one turn.

    ``new``/``replaces`` reset inherited steering. ``continue``, ``corrects``,
    and ``undetermined`` keep the objective while carrying substantive
    steering. ``unrelated`` preserves active-task requirements but marks the
    current turn so context selection can answer it without replacing the task.
    """
    prior = UserInterest.from_state(previous)
    objective_text = _bounded(objective, MAX_OBJECTIVE_CHARS)
    instruction = _bounded(latest_instruction, MAX_INSTRUCTION_CHARS)
    mode, change_policy, basis = decide_interest_mode(instruction)

    explicit_relationship = infer_explicit_followup_relationship(instruction)
    if prior is not None and relationship in {"continue", "undetermined"}:
        if explicit_relationship in {"corrects", "replaces"}:
            relationship = explicit_relationship
        elif prior.mode == "social" and mode not in {"social", "undetermined"}:
            # A greeting is conversational setup, not a durable mission.  The
            # first substantive answer/action after "hello" therefore becomes
            # the objective without paying the optional relationship
            # classifier.  Desktop evidence bd057959 showed the old merge as
            # `hello Latest user direction: Create ...`, contradicting the
            # report's claim that the greeting had been cleanly replaced.
            relationship = "replaces"
    if (
        prior is not None
        and relationship == "replaces"
        and objective_text.casefold() == prior.objective.casefold()
    ):
        objective_text = _bounded(
            _instruction_payload(instruction), MAX_OBJECTIVE_CHARS
        )

    if relationship == "cancelled":
        return _with_fingerprint(UserInterest(
            objective="",
            latest_instruction=instruction,
            mode=mode,
            change_policy="no_changes",
            relationship="cancelled",
            decision_basis=basis,
        ))

    reset = relationship in {"new", "replaces"} or prior is None
    if reset:
        substantive = "" if mode == "social" else instruction
        source = "\n".join(part for part in (objective_text, substantive) if part)
        return _with_fingerprint(UserInterest(
            objective=objective_text or substantive,
            latest_instruction=instruction,
            latest_substantive_instruction=substantive or objective_text,
            constraints=_extract(source, _CONSTRAINT_RE, MAX_CONSTRAINTS),
            requested_outcomes=_extract(
                source, _OUTCOME_RE, MAX_OUTCOME_ITEMS
            ),
            requested_evidence=_extract(
                source, _EVIDENCE_RE, MAX_EVIDENCE_ITEMS
            ),
            mode=mode,
            change_policy=change_policy,
            relationship=relationship,
            decision_basis=basis,
        ))

    if relationship == "unrelated":
        return _with_fingerprint(replace(
            prior,
            latest_instruction=instruction,
            mode=mode,
            change_policy=change_policy,
            relationship="unrelated",
            decision_basis=basis,
            fingerprint="",
        ))

    # A pure acknowledgement/approval authorizes continuation but must not
    # replace the most recent substantive steering with "ok" / "proceed".
    if mode == "social":
        restored_mode = prior.mode
        restored_policy = prior.change_policy
        restored_basis = basis
        if prior.relationship == "unrelated":
            active_text = prior.latest_substantive_instruction or prior.objective
            restored_mode, restored_policy, restored_basis = decide_interest_mode(
                active_text
            )
            if restored_mode in {"social", "undetermined"}:
                restored_mode, restored_policy, restored_basis = decide_interest_mode(
                    prior.objective
                )
            restored_basis = "resume_after_unrelated"
        return _with_fingerprint(replace(
            prior,
            objective=objective_text or prior.objective,
            latest_instruction=instruction,
            mode=restored_mode,
            change_policy=restored_policy,
            relationship=relationship,
            decision_basis=restored_basis,
            fingerprint="",
        ))

    steering = list(prior.steering)
    old_latest = prior.latest_substantive_instruction
    if old_latest and old_latest.casefold() not in {
        prior.objective.casefold(), instruction.casefold()
    }:
        steering.append(old_latest)

    constraints = list(prior.constraints) + list(
        _extract(instruction, _CONSTRAINT_RE, MAX_CONSTRAINTS)
    )
    requested_outcomes = list(prior.requested_outcomes) + list(
        _extract(instruction, _OUTCOME_RE, MAX_OUTCOME_ITEMS)
    )
    requested_evidence = list(prior.requested_evidence) + list(
        _extract(instruction, _EVIDENCE_RE, MAX_EVIDENCE_ITEMS)
    )
    return _with_fingerprint(UserInterest(
        objective=objective_text or prior.objective,
        latest_instruction=instruction,
        latest_substantive_instruction=instruction or old_latest,
        steering=_dedupe_bounded(
            steering, count=MAX_STEERING_ITEMS, chars=MAX_STEERING_CHARS
        ),
        constraints=_dedupe_bounded(
            constraints, count=MAX_CONSTRAINTS, chars=MAX_EXCERPT_CHARS
        ),
        requested_outcomes=_dedupe_bounded(
            requested_outcomes,
            count=MAX_OUTCOME_ITEMS,
            chars=MAX_EXCERPT_CHARS,
        ),
        requested_evidence=_dedupe_bounded(
            requested_evidence,
            count=MAX_EVIDENCE_ITEMS,
            chars=MAX_EXCERPT_CHARS,
        ),
        mode=mode,
        change_policy=change_policy,
        relationship=relationship,
        decision_basis=basis,
    ))


def _human_texts(messages: object) -> list[str]:
    """User-authored rows from a legacy checkpoint, oldest to newest."""
    if not isinstance(messages, (list, tuple)):
        return []
    texts: list[str] = []
    for message in messages:
        if getattr(message, "type", "") != "human":
            continue
        content = getattr(message, "content", "")
        if isinstance(content, list):
            text_parts = [
                str(block.get("text", ""))
                for block in content
                if isinstance(block, Mapping) and block.get("type") == "text"
            ]
            content = " ".join(part for part in text_parts if part)
        text = str(content or "").strip()
        if text:
            texts.append(text)
    return texts


def interest_from_state(state: Mapping[str, Any]) -> UserInterest:
    """Load a contract, or derive one for callers predating schema v1.

    Old checkpoints may have neither ``user_interest`` nor
    ``latest_instruction``. In that one migration case the newest human row
    is the current objective; a stale first-turn ``current_task`` must not win.
    """
    stored = UserInterest.from_state(state.get("user_interest"))
    if stored is not None:
        return stored
    objective = str(state.get("current_task") or "")
    latest = str(state.get("latest_instruction") or "")
    relationship: TaskRelationship = "undetermined"
    if not latest:
        human_texts = _human_texts(state.get("messages"))
        latest = human_texts[-1] if human_texts else ""
        # One-row states often use a shortened chat message alongside a more
        # precise current_task. Only a genuinely later row (or no objective)
        # is allowed to replace that legacy label.
        if latest and (
            not objective
            or (len(human_texts) > 1 and latest.casefold() != objective.casefold())
        ):
            objective = latest
            relationship = "new"
    return resolve_user_interest(
        objective=objective,
        latest_instruction=latest,
        relationship=relationship,
    )


def render_user_interest(interest: UserInterest) -> str:
    """Render the compact decision contract consumed by the main model."""
    mode_labels = {
        "act": "ACT — the user explicitly requested an action",
        "answer": "ANSWER — analyze or explain; do not invent an implementation request",
        "social": "CONTINUE — acknowledgement/authorization; preserve the active objective",
        "undetermined": "DECIDE — infer from the quoted request; do not guess missing scope",
    }
    change_labels = {
        "changes_requested": "workspace changes explicitly requested",
        "no_changes": "NO workspace changes requested",
        "unspecified": "not explicitly specified",
    }
    lines = [
        "=== CURRENT TASK / USER INTEREST CONTRACT (schema v1) ===",
        "This is a bounded routing view of user-authored text. The quoted text is the source of truth.",
        f"Decision: {mode_labels[interest.mode]}",
        f"Change policy: {change_labels[interest.change_policy]}",
        f"Relationship to active objective: {interest.relationship}",
    ]
    if interest.objective:
        lines.append(f"Overall goal: {interest.objective}")
    if interest.latest_instruction:
        lines.append(f"Latest instruction: {interest.latest_instruction}")
    if (
        interest.latest_substantive_instruction
        and interest.latest_substantive_instruction.casefold()
        not in {
            interest.objective.casefold(),
            interest.latest_instruction.casefold(),
        }
    ):
        lines.append(
            "Latest substantive direction (quoted): "
            + interest.latest_substantive_instruction
        )
    if interest.steering:
        lines.append("Earlier steering still in scope (oldest to newest):")
        lines.extend(f"- {item}" for item in interest.steering)
    if interest.constraints:
        lines.append("Explicit constraint-bearing excerpts (newest conflict wins):")
        lines.extend(f"- {item}" for item in interest.constraints)
    if interest.requested_outcomes:
        lines.append("Requested deliverable/outcome excerpts:")
        lines.extend(f"- {item}" for item in interest.requested_outcomes)
    if interest.requested_evidence:
        lines.append("Requested verification/evidence excerpts:")
        lines.extend(f"- {item}" for item in interest.requested_evidence)
    lines.extend([
        "Operating rule: later explicit user corrections override conflicting older ones; unaffected requirements remain active.",
        "Operating rule: do not convert an inquiry into edits, drop requirements during retries, or claim completion without requested evidence.",
        "Operating rule: when missing information would materially change execution, ask one focused clarification; otherwise proceed without inventing it.",
        f"Interest fingerprint: {interest.fingerprint}",
    ])
    return "\n".join(lines)


__all__ = [
    "SCHEMA_VERSION",
    "UserInterest",
    "decide_interest_mode",
    "infer_explicit_followup_relationship",
    "interest_from_state",
    "render_user_interest",
    "resolve_user_interest",
]
