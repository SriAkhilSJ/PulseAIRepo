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
    assert "Batch independent read-only tool calls" in p
    assert "DIFFERENT files" in p, "batching is only safe for disjoint reads"


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
        "Never end a turn on a promise of future action",
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
    """Token-budget guard: the steal is two tight paragraphs, not hermes'
    3,111-line corpus. ~1,300 chars growth ceiling (~330 tokens once per
    turn at the stable tier)."""
    growth = len(system_persona()) - len(CLAUDE_SYSTEM_PERSONA)
    assert growth < 1300, f"persona grew by {growth} chars — too fat"


# ------------------------------------------------------------ kill-switch

def test_d35_killswitch_restores_byte_identical_legacy(monkeypatch):
    monkeypatch.setenv("PULSEAI_PERSONA_GUIDANCE", "off")
    assert system_persona() is CLAUDE_SYSTEM_PERSONA or (
        system_persona() == CLAUDE_SYSTEM_PERSONA
    ), "off must return the exact legacy persona, byte for byte"


def test_d35_finish_job_section_isolated():
    """The appended block is one contiguous tail, so 'off' cannot leak
    fragments of it."""
    assert _D35_FINISH_JOB.startswith("\n\n## Finishing the Job")
    assert "## Finishing the Job" not in CLAUDE_SYSTEM_PERSONA


# ------------------------------------------------------------ wiring

def test_d35_graph_consumes_persona_via_function():
    src = inspect.getsource(chat_graph)
    assert "system_persona()" in src, "chat_graph must call the switch-point"
    assert "SystemMessage(content=CLAUDE_SYSTEM_PERSONA)" not in src, (
        "raw constant must not be consumed directly — it would bypass "
        "the kill-switch"
    )
