# Can the agent survive a long session?

**Asked:** can the agent run without stoppage, even for a long session?
**Tested:** 2026-11-01, GLM 5.3 (`z-ai/glm-5.3-flash`) through the real bridge and graph.
**Short answer: it never crashes, hangs or corrupts — but no, it cannot currently run a long session without stopping.** Two hard limits stop it, and neither is a model failure.

---

## 1. Why this had never been tested

Every harness in this repo mints a fresh session per run — `scripts/run_bridge_turn.py`
says so in its own docstring ("creates a UNIQUE session, never reuse ids — durable
checkpoint pollution"). So **every green result in this repo is a first turn**, with an
empty history and a cold context. A long session is a different risk surface:

- the transcript grows every turn, so **every prompt grows every turn**;
- iteration/token/cost budgets are **turn-scoped**, so a long session is bounded by
  **context and compaction**, not by the valves that reset;
- compaction, checkpointing and memory only matter from turn 2 onward.

New in this work: `scripts/run_long_session.py` (one bridge, **one** `session_create`,
N prompts down the same session id), `tests/e2e/prompts_session.txt` (7 checkable turns
on one MVP), and `.github/workflows/long-session.yml`.

---

## 2. What actually happened

### Run A — `41284413469` (funded): ran every turn, but stopped finishing work

| Turn | Frame | Completed | LLM calls | History in | Tools | Wall | New tokens |
| ---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: |
| 1 | turn_done | yes | 3 | 2 msgs | 5 | 18.5s | 86,500 |
| 2 | turn_done | yes | 15 | 2 msgs | 16 | 44.2s | 337,735 |
| 3 | turn_done | yes | 12 | 18 msgs | 11 | 9.2s | 113,698 |
| 4 | turn_done | yes | 15 | 25 msgs | 17 | 20.4s | 275,084 |
| 5 | turn_done | **cut** | 24 | 41 msgs | 26 | 38.7s | 627,486 |
| 6 | turn_done | **cut** | 16 | 15 msgs | 16 | 49.3s | 642,639 |
| 7 | turn_done | **cut** | 19 | 116 msgs | 18 | 48.9s | 638,625 |

The session ran all seven turns in **229s** and every one returned a well-formed frame.
But from turn 5 the turn was cut:

```
[budget] exhausted: tokens 617,579/600,000 (328,064 cached) >= cap, spend $0.0943
[grace] Run budget reached [iterations 14/20, tokens 617,579/600,000, 328,064 cached,
        spend $0.0943, tripped: tokens]
```

**The mechanism:** history grew 2 → 116 messages, so a single turn's token cost grew
**86k → ~640k**. The cap is **per turn** and fixed at 600k. From turn 5 onward one turn
*needed* more than the whole cap, so every later turn was truncated mid-work — with 6
iterations still unused.

The artifact survived: 6 tests passing after all seven turns. But `mvp/README.md`
(turn 7's deliverable) was never written, and **`python mvp/server.py` no longer served**
(every endpoint answered `000`) after turn 6 refactored the server into a
`create_server(port)` factory — while all six unit tests stayed green, because they call
the factory directly. *A green suite hid a broken entry point.*

### Run B — `41284812787`: stopped at turn 4, no credit left

| Turn | Frame | Completed | History in | Wall | New tokens |
| ---: | :--- | :--- | ---: | ---: | ---: |
| 1 | turn_done | yes | 2 msgs | 15.5s | 85,852 |
| 2 | turn_done | yes | 2 msgs | 11.7s | 103,086 |
| 3 | turn_done | yes | 7 msgs | 78.0s | 141,568 |
| 4 | turn_failed | **NO** | 9 msgs | 46.9s | 0 |
| 5–7 | turn_failed | **NO** | 14 msgs | ~0.6s | 0 |

### Run D — `41285437596`: the halt path, verified live (still no credit)

| Turn | Frame | Completed | LLM calls | New tokens | Error |
| ---: | :--- | :--- | ---: | ---: | :--- |
| 1–7 | turn_failed | **NO** | 1–7 | 0 | `Error code: 402 - Balance ₹0.00. Top up from ₹10 at https://velona.in/wallet` |

**→ The gateway balance is exhausted.** The run stops being a test of the agent and
becomes a test of the account. Topping up (₹10 minimum) is the only fix.

Re-run after the fixes, to check that a dead wallet now *stops the session* instead of
burning the remaining turns:

| Turn | Frame | Completed | LLM calls | Wall | New tokens | Error |
| ---: | :--- | :--- | ---: | ---: | ---: | :--- |
| 1 | turn_failed | **NO** | 1 | 6.2s | 0 | `402 — Balance ₹0.00. Top up from ₹10…` |
| 2 | `session-halted-provider-balance` | **NO** | 0 | 0s | 0 | — (6 turns not attempted) |

Total session wall clock **7.5s**, versus seven identical 0.6s failures before. Verdict:
**"0/7 turns genuinely completed — HALTED — provider balance exhausted after turn 1; 6
turn(s) not attempted"**, `session_exit=1`. The halt works; the wallet is still empty.

---

## 3. The four bugs this exposed (all fixed)

| # | Bug | Receipt | Fix |
| :-- | :--- | :--- | :--- |
| 1 | **The harness overstated survival.** A budget-cut turn still emits `turn_done`, so the driver counted 3 truncated turns as full survivals and printed "7/7 SURVIVED". | Run A's own report, contradicted by its `[budget] exhausted` lines | `summarize()` derives the verdict only from `completed` / `run_outcome`; "SURVIVED" now requires every turn to have said so; exit code is non-zero when any turn is cut |
| 2 | **A dead wallet was classified as retryable.** `classify_api_error` returned `unknown, retryable=True` for Velona's 402, so the agent retried a terminal failure across every remaining turn. | Run C: 7 turns, each failing in 0.6s | Added "top up from", zero-balance patterns and a currency-aware `_ZERO_BALANCE_RE`; **seven** copy-pasted call sites now route through one `_is_billing_message`; the 402 now classifies `billing`, `retryable=False`. The harness halts the session instead of spending turns |
| 4 | **The CI job was green regardless of the result.** `set +e` around the session is right (the re-test and the verdict must still run), but nothing read `SESSION_EXIT`, so run `41285437596` showed a ✅ while its own report said "0/7 turns genuinely completed". | Same run: job `success`, `session_exit=1` | A gate *after* the evidence upload: the job now fails if the session did not survive or the re-test failed, so the check mark means what a human thinks it means |
| 3 | **The harness could read another turn's frames.** The bridge forwards `event_bus` traffic, and `event_bus` *replays* retained history to a new subscriber, so a turn could conclude on a stale terminal frame. | Code path, `subscribe(thread_id=None)` | Driver drains the queue to silence before each prompt and ignores terminal frames whose `turn_id` it has already concluded |

**A fourth false green, found while verifying the fix:** the CI job for run
`41285437596` finished **green** — all 11 steps "success" — while the session it ran had
exited 1 and printed "0/7 turns". `set +e` around the session step is deliberate (the
re-test, the verdict comment and the artifact upload must still run when the session
fails), but nothing downstream ever read `SESSION_EXIT`. The check mark a human trusts
was decoupled from the result. A gate step now runs *after* the evidence upload and fails
the job when the session did not survive or the re-test failed.

**Correction to my own earlier claim:** I first attributed run B's 0.6s failures to
replayed frames. The error capture proved they were `402`s. The drain/`turn_id` guards are
still correct hardening — but they were not the cause, and I should not have called them
a diagnosis.

---

## 4. So what would make a long session survivable?

The barriers are ranked by what actually bites first.

| Priority | Barrier | Why it bites | Fix |
| :-- | :--- | :--- | :--- |
| 1 | **Provider balance** | Hard stop; nothing runs | Top up. And now it fails *loudly and immediately* instead of retrying |
| 2 | **Per-turn token cap vs growing history** | A mature turn needs >cap, so every later turn is truncated with iterations unused | Size the cap against history, not a constant: the meaningful guard once pricing works is `AGENT_COST_BUDGET` (money). Keep tokens as a generous backstop (the clamp already allows 2M) and make the cost leg the binding one |
| 3 | **Entry point rot** | Turns 6 reshaped `server.py` and broke `python mvp/server.py` while tests stayed green | Every delivery turn must re-assert the *documented launch command*, not just the unit suite — the long-session verify step now runs a boot matrix (`python mvp/server.py`, `-m mvp.server`) and names the one that serves |
| 4 | **Compaction pacing** | History still reached 116 messages; it fired (`context_engine_lines=4`, history dropped 18→15 mid-run) but not enough to keep a turn under the cap | Compact against the *per-turn budget*, not only the context window |

None of these is "the model gave up". In three runs and 21 turns the agent never hung,
never lost the workspace, and never ended a turn without a recorded reason — which is
the property the earlier invariants were built for. Stamina is limited by **money,
budget arithmetic, and its own refactors**, not by instability.

---

## 5. Reproduce

```bash
python scripts/run_long_session.py \
  --workspace /tmp/ws --prompts-file tests/e2e/prompts_session.txt \
  --turns 7 --timeout-s-per-turn 480 --max-session-minutes 45 \
  --max-llm-calls 20 --max-input-tokens 600000 --results-root /tmp/results
```

Or push (`.github/workflows/long-session.yml` runs it and posts the verdict to issue #28).
Runs cost roughly **$0.10–0.15** for seven turns; the per-turn cost grows with history,
so later turns dominate the bill.
