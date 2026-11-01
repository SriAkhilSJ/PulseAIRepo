# E2E Agent Core Test — GLM 5.3, first real MVP

**Date:** 2026-11-01 · **Model:** `z-ai/glm-5.3-flash` (Velona gateway, `custom` provider)
**Branch:** `arena/0348f25c-pulseairepo` · **Tracking issue:** #28 (verdict posted per run)

---

## 1. Headline

| | Result |
| :--- | :--- |
| Final run | [`41282122129`](https://github.com/SriAkhilSJ/PulseAIRepo/actions/runs/41282122129) @ `04fb9c29` |
| Invariants | **5 / 5 PASS** |
| Turn outcome | `completed` — `decided_by=none->completed`, `unverified=False` |
| Deliverable | **PASS (independent)** — 4 tests OK, live `HTTP 200 {"status":"ok"}` |
| Spend, this turn | **$0.013856** — 3/3 rows priced, 86,153 in / 1,866 out, cache reported 3/3 |
| Spend, whole campaign | **≈ $0.2832** — 14 real turns, 1,784,110 tokens |
| Cost source | `https://velona.in/gateway/v1/models` — 386 priced entries; GLM 5.3 = $0.15/1M in, $0.50/1M out |

The MVP is no longer a claim in a log. It is a stdlib HTTP server that a fresh
runner starts and probes:

```
agent test file: python mvp/test_server.py -> exit 0    Ran 4 tests … OK
mvp/server.py      present (70 lines)   server.py parses
mvp/index.html     present (28 lines)   references /api/health: 1 · id=health: 1
mvp/styles.css     present (58 lines)
mvp/test_server.py present (54 lines)
live HTTP /api/health -> 200   body: {"status": "ok"}   LIVE CONTRACT: PASS
DELIVERABLE VERDICT: PASS (independent)
```

The runner's workspace is uploaded with the evidence
(`e2e-glm53-evidence` → `ws/mvp/**`), so the artifact survives the runner
instead of being deleted with it.

---

## 2. The bug ladder — why a green run kept reporting itself as failed

Every fix below was found by a real run failing, not by reading code. That is
the point of the exercise: the graph was green in unit tests and dishonest
end-to-end.

| # | Symptom (run) | Root cause | Fix | Evidence it worked |
| :-- | :--- | :--- | :--- | :--- |
| 1 | 5 requests, 0 tokens, `Connection error.` (`41277871983`) | `CUSTOM_API_KEY` secret had a trailing newline (len 51 vs 50) → httpx `LocalProtocolError` → SDK reported a network error | `settings._cred()` strips at import; workflow normalises + reports `raw_len`/`clean_len` | `41278204959`: `key len=50 …6af4`, **SDK PROBE OK**, 6 requests, real tokens |
| 2 | `Cost: $0.000000` on a billed run (`41278204959`) | Rate card empty → `estimate_cost_usd()` returns `None`; report collapsed `None` to `0.0` | Rows counted as *priced* only when a rate resolved; unpriced ⇒ **UNKNOWN** + `RATE CARD GAP`, never `$0` | `I3` reads `priced_rows=N/M`; governor abstains honestly |
| 3 | `unverified=True` with a green artifact (`41278424864`) | `python mvp/test_server.py` matched **no** verification token (`" test"` demanded a leading space) | `_is_verification_command()` shared by all three call sites; recognises `test_*.py`, `*_test.py`, `tests/**` | `## Commands the agent ran` now marks the run as a check |
| 4 | A stdlib server was required to pass a browser test (`41278424864`) | The word “page” made `_looks_like_ui_task` true, so `navigate` + `rendered` were required; the prompt never asked for a browser | `test_suite_ask` recognises `unittest`/`pytest`/`test_*.py` — a named test suite is the channel | `missing=none` on the verify domain; unnamed UI tasks still owe browser proof (regression test) |
| 5 | Two green test runs, still `unverified` (`41279653910`) | An exploratory `python -c "…/api/health"` probe failed and minted a debt clearable **only** by re-running that exact one-liner | **Green evidence generous, red debt narrow**: only stable targets (test file, runner, build/lint/typecheck) can create a blocking debt | `unresolved_check_debts=0` while remaining green evidence untouched |
| 6 | `missing=['integrity']` on a correct page (`41279904524`) | `/styles.css` resolved against the workspace root, but the page is served **from** `mvp/` — the audit punished the contract the prompt specified | Root-absolute refs resolve against every ancestor document root; genuinely missing assets still report | `missing=none`; both directions pinned by tests |
| 7 | `verification=passed … exec_status=failed` (`41280335964`) | `state.get("task_completed") is False` sat in the failure chain — but that is the **turn-start default**; it is *derived* at finalize and never set True mid-turn | Removed from the outcome chain and the mirrored verdict; every deliberate failure already names itself in `task_status` | `decided_by=none->completed` |
| 8 | Rate card empty for a model the gateway prices (`41281037034`) | `pricing.provider_config()` read the raw env, so the newline came back and urllib raised `Invalid header value`; the async refresh swallowed it in a daemon thread | `.strip()` in `provider_config()`; probe runs `refresh()` synchronously so failures surface | `[card] entries=386`, `Cost $0.013820 (3/3 rows priced)` |

Steps 3–7 are one theme: **the gate knew the artifact was fine and still refused
to say so** — for a different reason each time. Step 8 is the mirror image: the
cost leg abstained correctly for eleven runs, and the reason was a credential
that had already been "fixed" one layer up.

---

## 3. Final invariant table (verbatim from the verdict)

| # | Check | Result | Detail |
| :-- | :--- | :--- | :--- |
| 1 | I1 terminal reason recorded | ✅ PASS | `frame=turn_done run_outcome='completed' trace_row='completed'` |
| 2 | I2 trace has a terminal node | ✅ PASS | `nodes={'ai': 3, 'tools': 2, 'finalize': 1, 'turn_terminal': 1}` |
| 3 | I3 spend measured in USD | ✅ PASS | `llm_requests=3 priced_rows=3/3 cost=$0.013820` |
| 4 | I4 no silent stall | ✅ PASS | `completed=True reason_present=True` |
| 5 | I5 turn completed (strict) | ✅ PASS | `completed=True` |

And the outcome is explainable by one line, which is the whole point:

```
[turn] finalize decision: exec_status=completed run_outcome=completed
  failure_reason=None decided_by=none->completed | signals: trailing_failed=False
  no_work_done=False ended_mid_task=False budget_cut=False unverified=False
  verified_ok=True task_completed=False task_status='in_progress' failed_steps=0
```

---

## 4. Spend, measured (rate card now populated)

| Run | Input | Output | Est. USD | Outcome |
| :--- | ---: | ---: | ---: | :--- |
| `41278204959` | 168,417 | 9,362 | 0.0299 | budget_exhausted |
| `41278424864` | 144,560 | 4,033 | 0.0237 | failed (unverified) |
| `41279458317` | 187,896 | 5,751 | 0.0311 | budget_exhausted |
| `41279653910` | 203,646 | 3,106 | 0.0321 | failed (dead debt) |
| `41279904524` | 259,959 | 4,559 | 0.0413 | failed (integrity) |
| `41280080898` | 86,321 | 2,259 | 0.0141 | failed (task_completed) |
| `41280335964` | 86,050 | 1,957 | 0.0139 | failed (task_completed) |
| `41280526792` … `41282122129` | 602,642 | 13,592 | **0.0981** | **completed ×7** |
| **Total** | **1,739,491** | **44,619** | **≈ 0.2832** | 14 turns |

Two token caps were also wrong on the way: `AGENT_TOKEN_BUDGET` was dead
(a 600k env var beside a 150k CLI wall, which wins), and the E2E workflow did
not trigger on `src/**` at all — a test whose trigger excludes its subject.

A completed MVP turn now costs **≈ $0.014** and ~86k tokens, and the last run reports cache splits on 3/3 calls. The earlier
150k wall was cutting healthy builds at iteration 6 of 20.

---

## 5. What is still open

| # | Item | Why it matters | Suggested action |
| :-- | :--- | :--- | :--- |
| 1 | **Rotate `CUSTOM_API_KEY`** | Run `41281037034` printed the key with its trailing newline into a **public** issue comment (urllib quotes the header value in its error). The comment is now redacted, and a scrubber step redacts any future leak — but redaction cannot un-publish a value. | Rotate in the gateway + update the `CUSTOM_API_KEY` secret |
| 2 | ~~Shape-glob false positive~~ — verified, not a bug | The fingerprint line prints the literal glob `key_live_*`. A naive substring count flags it, but the scrubber's `key_live_[A-Za-z0-9_]+` needs at least one character after the underscore, so the glob is never "redacted" and no real key is missed. | none |
| 3 | Two stale finalize tests | `test_finalize_chat_turn.py` expects `task_completed=True` for a work run that never verified; the contract correctly derives `False` while `task_status="completed"` | Decide which is canonical, then fix the losing side |
| 4 | `task_status="completed"` vs `task_completed=False` | Two fields can disagree on the same turn | Make `task_status` derive from the same contract |
| 5 | 50 pre-existing offline failures | Same set before and after this work (29 in `test_task_classifier_skip.py`, telemetry-key drift) | Separate cleanup |
| 6 | `gh run download` returns EOF | Evidence must be read from the issue verdict | Unrelated to the core |

Offline suite after this work: **3107 passed / 50 failed**, against a baseline of
**3099 passed / 51 failed** on the same tree — the one extra pass is the stale
`check_velona_keys` test that this work corrected. No regressions.

---

## 6. Files that carry the fixes

| File | Change |
| :--- | :--- |
| `src/graphs/gates.py` | `_is_verification_command()`, `_is_debt_eligible_command()`, test-suite channel detection, gate names its missing domains |
| `src/graphs/chat_graph.py` | `task_completed is False` removed from the outcome chain; finalize prints the deciding branch and the gap |
| `src/context/workspace_integrity.py` | Root-absolute references resolve against the served directory |
| `src/telemetry/pricing.py` | Credential stripped at the header boundary |
| `scripts/e2e_core_report.py` | Priced-vs-unpriced rows; "Commands the agent ran"; verification channel; token cap |
| `.github/workflows/e2e-core.yml` | Credential normalise → SDK probe → pricing probe → turn → independent re-test → verdict → redact → artifact (`ws/mvp/**`) |
| `src/tests/test_verification_channel_detection.py` | **24** tests pinning every item above, including both directions of each widening |

---

## 7. Honest caveats

- The E2E proves **one** bounded MVP task, not general competence. It is a
  regression harness for honesty (did the run explain itself?) and deliverable
  reality (does the thing serve?), not a benchmark.
- The six consecutive completions use the same prompt. Repetition is not
  robustness.
- Cache reporting is 3/3 only on the very last run; the two before it were
  2/3, so cache economics are measured but not yet consistently.
- The `$0.2694` campaign figure uses the rate card's list price. It is an
  estimate of spend, not a vendor invoice.
