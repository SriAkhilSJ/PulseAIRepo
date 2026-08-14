"""Pins for D35 (§47): the hermes prompt-pattern steal — adapted, never
pasted. Two gaps closed (finish-the-job, batch calls), one pattern
consciously NOT doubled (anti-fabrication — already covered), one
anti-batch sentence REMOVED (it suppressed the behavior D34's gate was
built to serve), kill-switch restores byte-identical legacy.
"""

from __future__ import annotations

import inspect

import pytest

from src.prompts.claude_persona import (
    CLAUDE_SYSTEM_PERSONA,
    _D35_FINISH_JOB,
    _D35_GROUNDING,
    _D35_LEGACY_BATCH_SENTENCE,
    system_persona,
)
import src.graphs.chat_graph as chat_graph


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("PULSEAI_PERSONA_GUIDANCE", raising=False)
    yield


# ------------------------------------------------------------ on-mode

def test_d35_legacy_constant_never_mutated():
    """The frozen constant is sacred: on-mode must not edit it."""
    assert _D35_LEGACY_BATCH_SENTENCE in CLAUDE_SYSTEM_PERSONA


def test_d35_on_kills_the_anti_batch_sentence():
    p = system_persona()
    assert _D35_LEGACY_BATCH_SENTENCE not in p, (
        "the persona told the model to NEVER batch — D34's gate exists "
        "to execute batches safely; the sentence must be replaced, and "
        "this pin screams if persona drift ever breaks the replace"
    )
    # hermes PARALLEL_TOOL_CALL_GUIDANCE pattern: batch independent calls
    # (reads AND disjoint writes) into one turn; only serialize true
    # dependencies. D8 measured 30 round trips for 30 tools because the
    # old sentence told the model to keep writes one-at-a-time.
    assert "Parallel tool calls" in p
    assert "request them together in a single response" in p
    assert "Only serialize when a later call genuinely depends" in p
    assert "write_file / " in p, "writes must be batchable too (D34 orders conflicts)"


def test_d35_batch_sentence_is_d34_truthful():
    p = system_persona()
    assert "concurrently" in p and "conflicting" in p, (
        "the batch line must state the REAL D34 contract: safe batches "
        "concurrent, conflicting ones ordered — never overclaim"
    )


def test_d35_finish_job_patterns_present():
    p = system_persona()
    for marker in (
        "working artifact backed by real tool output",
        "Never end a turn with a promise of future action",
        "blocked, say so",
    ):
        assert marker in p, f"finish-the-job pattern missing: {marker!r}"


def test_d35_anti_fabrication_deliberately_not_doubled():
    """hermes' third block is already covered by the legacy persona
    ("Never invent file contents..."). One coverage, zero paste."""
    assert CLAUDE_SYSTEM_PERSONA.count("Never invent file contents") == 1
    assert system_persona().count("Never invent file contents") == 1, (
        "if this ever reads 2, someone pasted hermes over our coverage"
    )


def test_d35_growth_bound():
    """Token-budget guard: the steal is tight guidance, not hermes'
    3,111-line corpus. The D40 (D9) round added the hermes
    TOOL_USE_ENFORCEMENT block (~650 chars, qwen-gated upstream; our
    model IS qwen) — the D9 transcript showed the model promising
    actions, stalling on ask_user, and declaring Finished on a broken
    app, which is exactly what that block forbids. Ceiling sized for
    batch guidance + finish-job + enforcement; any further paste breaks
    it loudly.

    P0-C raised the ceiling: the Programmatic-Tool-Calling default block
    (~1.5k chars) is the single highest-leverage efficiency instruction —
    it is what stops the 1-call-1-tool collapse by teaching a concrete
    execute_code script pattern. ~4.2k growth for a constant, cache-safe
    (Law #1) prefix that pays back the first time a task avoids 4+
    round-trips is a deliberate, bounded trade.

    D36 raised it again (~1.0k): the Grounding block ported the hermes
    OPENAI_MODEL_EXECUTION_GUIDANCE grounding patterns — mandatory tool
    use for facts (math/time/system/file/git/web), missing-context
    handling (lookup first, ask only when no tool can retrieve, label
    assumptions), and a compact pre-finalize verification checklist.
    This closes the remaining qwen failure mode: answering facts from
    memory instead of tools."""
    growth = len(system_persona()) - len(CLAUDE_SYSTEM_PERSONA)
    assert growth < 6200, f"persona grew by {growth} chars — too fat"


# ------------------------------------------------------------ kill-switch

def test_d35_killswitch_restores_byte_identical_legacy(monkeypatch):
    monkeypatch.setenv("PULSEAI_PERSONA_GUIDANCE", "off")
    assert system_persona() is CLAUDE_SYSTEM_PERSONA or (
        system_persona() == CLAUDE_SYSTEM_PERSONA
    ), "off must return the exact legacy persona, byte for byte"


def test_d35_finish_job_section_isolated():
    """The appended block is one contiguous tail, so 'off' cannot leak
    fragments of it."""
    assert _D35_FINISH_JOB.startswith("\n\n## Execution Discipline")
    assert "## Finishing the Job" not in CLAUDE_SYSTEM_PERSONA
    assert "## Execution Discipline" not in CLAUDE_SYSTEM_PERSONA


# ------------------------------------------------------------ P0-C: PTC default

def test_p0c_ptc_default_block_present_on_mode():
    """P0-C: the composed persona teaches execute_code as the DEFAULT for
    multi-step work, with a concrete worked script (not just an abstract
    mention). This is what stops the 1-call-1-tool collapse on weak models."""
    p = system_persona()
    assert "Programmatic Tool Calling = your default" in p, (
        "PTC must be framed as the DEFAULT, not an option"
    )
    # A copy-pasteable script example is the actual lever (abstract advice
    # already existed and did not change behavior).
    assert "read_file(p)" in p, "the worked example must call a real tool"
    assert "ONE round-trip" in p, (
        "the cost framing (each call resends the conversation) must be stated"
    )


def test_p0c_ptc_default_absent_from_legacy_constant():
    """The PTC block is composed ON, never baked into the frozen constant —
    so the kill-switch stays a true byte-identical restore."""
    assert "Programmatic Tool Calling = your default" not in CLAUDE_SYSTEM_PERSONA


def test_p0c_killswitch_drops_ptc_block(monkeypatch):
    monkeypatch.setenv("PULSEAI_PERSONA_GUIDANCE", "off")
    p = system_persona()
    assert "Programmatic Tool Calling = your default" not in p, (
        "off-mode leaked the PTC block — kill-switch must restore legacy only"
    )


# ------------------------------------------------------------ wiring

def test_d35_graph_consumes_persona_via_function():
    src = inspect.getsource(chat_graph)
    assert "system_persona()" in src, "chat_graph must call the switch-point"
    assert "SystemMessage(content=CLAUDE_SYSTEM_PERSONA)" not in src, (
        "raw constant must not be consumed directly — it would bypass "
        "the kill-switch"
    )


# ------------------------------------------------------------ D36: grounding

def test_d36_grounding_present_on_mode():
    p = system_persona()
    for marker in (
        "Never answer facts from memory",
        "Missing context",
        "label the",
        "Before finalizing, verify",
    ):
        assert marker.lower() in p.lower(), f"grounding pattern missing: {marker!r}"


def test_d36_grounding_absent_from_legacy():
    """Grounding is composed ON — never baked into the frozen constant."""
    assert "Facts from memory" not in CLAUDE_SYSTEM_PERSONA
    assert _D35_GROUNDING not in CLAUDE_SYSTEM_PERSONA


def test_d36_mandatory_tool_use_lists_concrete_tools():
    """The block must name the actual PulseAI tools (no phantom tools)."""
    p = system_persona()
    for tool in ("run_terminal", "read_file", "search_code", "web_search", "execute_code"):
        assert tool in p, f"grounding block must name real tool {tool!r}"


def test_d36_grounding_composed_after_ptc():
    """Composition order: legacy ∪ finish-job ∪ ptc ∪ grounding."""
    p = system_persona()
    assert p.index("Programmatic Tool Calling") < p.index("Grounding"), (
        "grounding must append after the PTC block"
    )


def test_d36_killswitch_drops_grounding(monkeypatch):
    monkeypatch.setenv("PULSEAI_PERSONA_GUIDANCE", "off")
    p = system_persona()
    assert p == CLAUDE_SYSTEM_PERSONA, "off-mode must restore legacy only"
    assert "Grounding" not in p, "off-mode leaked the grounding block"
