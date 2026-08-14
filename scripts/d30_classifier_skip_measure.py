"""D30 measurement (§46): how much of a REAL session's classification
traffic does the quick path absorb for free?

A labeled corpus of realistic follow-up messages (the kind coding-agent
sessions are actually made of). Every message the quick path classifies
is one aux-LLM call NOT spent; every message it declines pays exactly
what it paid before D30. Asserts: every quick-fired label is CORRECT
(no misroutes), and reports the skip rate.

Run:  python scripts/d30_classifier_skip_measure.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graphs.chat_graph import _quick_task_decision

TASK = "build a login page with email/password auth"

# (message, expected action) — expected is what a GOOD classification is;
# None = "needs the aux LLM" (ambiguous by design).
CORPUS: list[tuple[str, str | None]] = [
    # slam-dunk acks (continue with unchanged task)
    ("ok", "continue"), ("okk", "continue"), ("okkk", "continue"),
    ("yes!", "continue"), ("yess go", "continue"), ("yahh", "continue"),
    ("go", "continue"), ("do it", "continue"), ("sure", "continue"),
    ("sounds good", "continue"), ("looks good bro", "continue"),
    ("go for it", "continue"), ("ok go", "continue"), ("yes please", "continue"),
    ("thanks", "continue"), ("perfect 👍", "continue"), ("great 🔥", "continue"),
    ("nice", "continue"), ("bet", "continue"), ("lgtm", "continue"),
    ("roger that".replace(" that", ""), "continue"), ("aight", "continue"),
    ("alright then", "continue"), ("✅", "continue"), ("cool", "continue"),
    ("y", "continue"),
    # explicit resets (new task)
    ("new task: add OAuth to the API", "new"),
    ("new task build a discord bot", "new"),
    ("start over with a CLI tool", "new"),
    ("forget the previous task, move to docker setup", "new"),
    ("scrap that, do a terraform module", "new"),
    ("forget this task", "new"),
    ("different task: fix the navbar", "new"),
    # ambiguous — must still pay the aux call (None expected)
    ("actually can you refactor the auth instead", None),
    ("no, change the button color to red", None),
    ("explain how the login flow works", None),
    ("why did the test fail?", None),
    ("now add OAuth support to what you built", None),
    ("hmm maybe use sessions instead of JWT", None),
    ("the navbar looks broken on mobile", None),
    ("ok but remove the sidebar", None),
    ("yes, wait", None),
    ("yes", None),            # plan-approval word: never reaches D30
    ("proceed", None),        # plan-approval word
    ("go ahead", None),       # plan-approval word
    ("can you also handle password reset emails", None),
    ("what's the best way to store tokens here", None),
    ("make the form prettier and add validation", None),
    ("ok\nnow add tests for it", None),
    ("new taskbar styling in the editor", None),
    ("that output file seems wrong to me", None),
    ("use better variable names in auth.py", None),
    ("how much did this session cost so far", None),
]


def main() -> None:
    free = llm = 0
    misroutes = []
    for msg, expected in CORPUS:
        got = _quick_task_decision(TASK, msg)
        if expected is None:
            llm += 1
            if got is not None:
                misroutes.append((msg, "expected LLM, got quick", got))
        else:
            free += 1
            if got is None or got[0] != expected:
                misroutes.append((msg, f"expected {expected}", got))

    total = len(CORPUS)
    print(f"corpus: {total} realistic follow-up messages")
    print(f"  classified FREE by quick path : {free}/{total} "
          f"({100*free/total:.0f}% of this corpus)")
    print(f"  still paying the aux LLM      : {llm}/{total} "
          f"(includes plan-approval words already free pre-D30)")
    if misroutes:
        print("MISROUTES (must be empty):")
        for m in misroutes:
            print("  ✗", m)
        sys.exit(1)
    print("  misroutes: 0 (every quick-fired label is correct)")


if __name__ == "__main__":
    main()
