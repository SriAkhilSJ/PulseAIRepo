"""Free conversational openers + terminal output cap (owner latency runs).

Two findings from the owner's instrumented desktop session: (1) '[ai_node]
request ~1.4k tokens' with a 35s wait proved the ENDPOINT is the bottleneck,
so every call we can REMOVE matters -- each chat turn was paying a full
classifier round-trip before hello; (2) `for /d /r` over a 40k-file repo
returned ~5MB of terminal output and the bridge DROPPED the whole frame --
the desktop never saw the result. Pinned: openers classify free (closed
lexicon, exact match), run_terminal caps output at the source, env-driven.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# the free path
# ---------------------------------------------------------------------------

def test_conversational_openers_classify_free():
    from src.graphs.chat_graph import _quick_task_decision

    for opener in ("hi", "hello??", "Hello!", "HEY", "thanks", "who are you",
                   "good morning", "test 123"):
        got = _quick_task_decision("build a login page", opener)
        # D30 ack contract label: 'continue' preserves the active task with
        # NO provider call -- the hermes-aligned mechanism.
        assert got is not None and got[0] == "continue", opener
        assert got[1] == "build a login page"  # active task preserved


def test_anything_beyond_the_opener_still_pays_the_llm():
    from src.graphs.chat_graph import _quick_task_decision

    for message in ("hi can you fix the login page", "hello world program",
                    "thanks, now add OAuth"):
        assert _quick_task_decision("build a login page", message) is None, message


def test_kill_switch_still_bypasses_the_lexicon(monkeypatch):
    from src.graphs.chat_graph import _quick_task_decision

    monkeypatch.setenv("PULSEAI_TASK_CLASSIFIER", "llm")
    assert _quick_task_decision("build a login page", "hi") is None


# ---------------------------------------------------------------------------
# the cap at the source
# ---------------------------------------------------------------------------

def test_run_terminal_caps_monstrous_output(tmp_path):
    from src.tools.terminal_tools import run_terminal

    import sys
    if sys.platform == "win32":
        command = "for /l %i in (1,1,200000) do @echo line-%i"
    else:
        command = "seq 1 200000"

    result = run_terminal.invoke(
        {"command": command},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert len(result) < 40_000, f"output not capped: {len(result)} chars"
    assert "Terminal output truncated" in result
    assert "Total characters" in result  # the limiter's honesty header


def test_output_cap_is_env_driven(tmp_path, monkeypatch):
    import sys

    from src.tools.terminal_tools import run_terminal

    monkeypatch.setenv("PULSEAI_TERMINAL_MAX_OUTPUT_CHARS", "5000")
    command = (
        "for /l %i in (1,1,100000) do @echo line-%i"
        if sys.platform == "win32" else "seq 1 100000"
    )
    result = run_terminal.invoke(
        {"command": command},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert len(result) < 12_000, f"env cap not honored: {len(result)} chars"


def test_small_output_passes_untouched(tmp_path):
    from src.tools.terminal_tools import run_terminal

    result = run_terminal.invoke(
        {"command": "echo hello-from-terminal"},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert "hello-from-terminal" in result
    assert "Terminal output truncated" not in result
