"""Pins for the server-side auto-titler (Hermes ``session.title`` parity).

Rule (field 2026-09-28): history titles are CREATED (model-written), FIXED
(set once), and UNIQUE within the workspace. Nothing captures the first
message verbatim.
"""

from __future__ import annotations

from src.runtime.session_titling import (
    TITLE_MAX_CHARS,
    ensure_unique_title,
    generate_session_title,
    shorten_title,
)


class _FakeStore:
    def __init__(self, titles):
        self._titles = list(titles)

    def list_sessions_rich(self, workspace=None, limit=2000):
        assert limit >= len(self._titles)
        return [{"title": title} for title in self._titles]


def test_model_title_is_cleaned_to_one_line():
    seen = {}

    def fake(prompt):
        seen["prompt"] = prompt
        return '  "Fix the login redirect," \nSecond line ignored  '

    assert generate_session_title("login broken", "fixed it", invoke=fake) == "Fix the login redirect"
    assert "login broken" in seen["prompt"]
    assert "fixed it" in seen["prompt"]


def test_model_title_caps_length_and_strips_session_word_rules():
    long_title = "word " * 40
    assert generate_session_title("x", "y", invoke=lambda prompt: long_title).endswith("…")
    assert len(generate_session_title("x", "y", invoke=lambda prompt: long_title)) <= TITLE_MAX_CHARS


def test_generate_returns_empty_without_calling_on_bad_input_or_failure():
    calls = []

    def fake(prompt):
        calls.append(prompt)
        raise RuntimeError("provider down")

    assert generate_session_title("", "reply", invoke=fake) == ""
    assert generate_session_title("   ", "reply", invoke=fake) == ""
    assert generate_session_title("hi", "hello", invoke=fake) == ""
    assert len(calls) == 1, "only the real attempt may call the model"


def test_generate_accepts_langchain_message_shapes():
    class _Msg:
        content = [{"type": "text", "text": "  Deploy checklist. "}, {"type": "text", "text": ""}]

    assert generate_session_title("deploy", "done", invoke=lambda prompt: _Msg()) == "Deploy checklist"


def test_unique_title_suffixes_on_collision_case_insensitive():
    store = _FakeStore(["Deploy checklist", "deploy checklist (2)", "Other"])
    assert ensure_unique_title(store, "/ws", "Deploy checklist") == "Deploy checklist (3)"
    assert ensure_unique_title(store, "/ws", "DEPLOY CHECKLIST") == "DEPLOY CHECKLIST (3)"
    assert ensure_unique_title(store, "/ws", "Fresh idea") == "Fresh idea"
    assert ensure_unique_title(store, "/ws", "   ") == ""


def test_shorten_title_collapses_and_caps_goals():
    assert shorten_title("  line one\nline two  ") == "line one"
    assert shorten_title("x" * 200).endswith("…")
    assert len(shorten_title("x" * 200)) <= TITLE_MAX_CHARS
    assert shorten_title("") == ""
