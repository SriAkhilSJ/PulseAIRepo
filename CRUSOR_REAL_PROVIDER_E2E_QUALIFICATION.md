# Crusor Real-Provider E2E Qualification

**Date:** 2026-11-11
**Branch:** `feat/prompt-cache-stabilization`, HEAD `fb5bd528b40933346c4004a1490154683dc0d40e` (no commit)
**Spend cap authorised:** ₹50 (user-confirmed). **Actual spend: ₹0.1430.**
**Verdict: FAIL.** Real inference is proven; the engineering capability is not.

---

## 1. OpenCode architecture comparison

Delivered separately in `OPENCODE_EXECUTION_ARCHITECTURE_COMPARISON.md`.

Summary of the source study, and why it matters here: the file paths named in the mission
(`packages/opencode/src/session/{message,processor,session}.ts`) do not exist on `dev`.
The repository was restructured; the real equivalents are
`packages/schema/src/session-message.ts`, `packages/core/src/session/{message-updater,projector,history}.ts`
and the split `runner/{llm,step,publish-llm-event}.ts` (there is no `processor.ts`).
Read from the live tree (`12,463` entries), not assumed.

The one property worth carrying into this report: OpenCode persists **one ordered array of
tagged parts** and mutates it only by append plus addressed update, with stream deltas
declared ephemeral and durable boundaries carrying full values. Crusor's event journal and
card projection are a superset of that model, and the live timeline task already brought the
renderer to parity. **Nothing in that comparison explains the failure recorded below** — the
failure is upstream of rendering, in the planning contract gate.

Crusor source was not changed as a result of the comparison.

---

## 2. Provider and model configuration (verified, no secrets printed)

| Field | Value | How verified |
|---|---|---|
| Provider ID | `custom` | `settings.LLM_PROVIDER` |
| Model ID | `z-ai/glm-5.3-flash` | `settings.LLM_MODEL` |
| Base URL | `https://velona.in/v1` | `settings.CUSTOM_BASE_URL` |
| Credential | present, 50 chars, not printed | `settings.CUSTOM_API_KEY` length check |
| Model availability | `GET /v1/models` → **200**, 382 models, configured model present | direct probe with the configured browser User-Agent |
| Cloudflare note | without `CRUSORAI_HTTP_USER_AGENT` the endpoint returns **403 / Error 1010** | probe without the header |
| Aux model | `qwen/qwen3.7-flash` | `settings.AUX_LLM_MODEL` |
| Pricing (custom → glm-5.3-flash) | in $0.05/M, cached $0.01/M, out $0.20/M | `src/finops/pricing_registry.py:169-173` |
| Pricing (aux) | in $0.08/M, cached $0.01/M, out $0.24/M | `pricing_registry.py:174` |
| USD→INR | 86.0 | `settings.CRUSORAI_USD_INR` |
| Cost governance | ON, unknown-pricing policy `token_limited` | settings |
| Retry policy | SDK retries disabled (`max_retries=0`); `RetryLLMProxy` owns a bounded attempt budget | `src/llm/factory.py:494-509`, `acceptance_guard.py:183` |
| Run-time budget | session ₹50, turn ₹50, task ₹20 | harness env |

### 2.1 Mock / scripted seams: all off for the run

- `scripted_model_active()` → **False**; `CRUSORAI_TEST_MODE` **unset** (both are required for
  the scripted seam, `src/llm/scripted_model.py:169`, `factory.py:1267`).
- `CRUSORAI_ORCHESTRATOR_MOCK` **unset** (`chat_graph.py:5373`).
- `CRUSORAI_ACCEPTANCE_RUN_ID`, `CRUSORAI_OFFLINE_MODE`, `PYTEST_CURRENT_TEST` **unset**.
- No fake executor / deterministic adapter / mock event injection was enabled. The app log
  confirms the bridge loaded `LLM_PROVIDER='custom'` and the real `.env`.

---

## 3. Was real inference used? Yes — and it is proven by the ledger, not the UI

Two provider invocations were **settled** during Test B. Both carry non-zero tokens, a real
cost, a usage receipt and `mode: "provider"`.

| # | Invocation ID | Purpose | Input | Output | Cached | Cost (USD) | Cost (INR) | Status | Attempts | Finish |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `inv-9c04786f6ecf4079` | `node_task_req_001_module` | 3,130 | 5,904 | 0 | 0.001338 | **0.123738** | settled | 1 | stop |
| 2 | `inv-5fe62175fe294eda` | `node_task_req_003_module` | 3,134 | 255 | 0 | 0.000208 | **0.019236** | settled | 1 | stop |

Reconciled totals: **6,264 input / 6,159 output / 0 cached**, **₹0.142974 ($0.001546)**,
**0 retries, 0 fallbacks, 0 errors, 0 unknown-cost calls**. `usage_receipt_present: true` on
both. Reservation and settlement IDs match per call (`res_*`).

Ledger file: `%TEMP%\CrusorLiveE2E\appdata\finops\provider_invocations.jsonl`
(copied to `evidence/ledger-all.json`).

**Critical attribution correction.** These two calls belong to **Test B**, not Test A.
`started_at` decodes to 16:34:49 and 16:34:53, i.e. after Test A had already terminated at
16:34:47, and Test A's own ledger delta was **0 rows**. Test A therefore never reached the
provider at all. Both calls were in flight when the run was stopped on request, so they are
evidence of *dispatch*, not of completed engineering work.

---

## 4. Test A — multi-file `divide()` implementation

**Prompt sent verbatim through the real panel** (composer → bridge → canonical runtime):

> "Implement a divide(a, b) function in the existing mini_math package. Division by zero must
> raise ZeroDivisionError. Export the function from the package, add appropriate tests … run
> the complete test suite. Preserve the existing functions."

**What happened:** the turn ended in **8.6 s** with no plan, no tool call, no approval and no
file write. The assistant text was:

```
Planning changes
RUNNING
0%
Engineering execution failed: plan rejected before dispatch: contract ambiguity:
no public symbol is specified for the requested function
```

**DOM observed (authoritative, from the live section):**

| Signal | Result |
|---|---|
| Activity card | 1 (`Planning changes`) |
| Plan card | **0** (no plan ever dispatched) |
| Tool rows | **0** |
| File-change cards | **0** |
| Approval cards / dock | **0** |
| Test-result cards | **0** |
| Streaming assistant prose | none beyond the terminal error string |
| Order | `card:activity → text` |

**Files changed: none.** Hashes before/after are identical; the fixture suite still reports
`9 passed` **because nothing was touched**, which is not evidence of agent work.

### 4.1 Root cause (reproduced in source)

`src/orchestration/contract.py:311-315` extracts a symbol only when the name follows the
literal token `def` or `function`:

```python
re.finditer(r"\b(?:def|function)\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", text)
```

The prompt uses the ordinary English order — *"a divide(a, b) function"* — so the pattern
does not match, `fields["symbols"]` is empty, and line 522 rejects the plan:

```python
if re.search(r"\b(?:public\s+)?function\b", prompt, re.IGNORECASE) and not fields["symbols"]:
    ambiguities.append("no public symbol is specified for the requested function")
```

So the gate fires on the very phrasing the task mandates. This is a deterministic product
defect, reproducible without any provider call, and it blocks the entire qualification before
the capability under test is exercised.

**Test A verdict: FAIL.**

---

## 5. Test B — multi-turn context retention

**Status: NOT COMPLETED (stopped on request).** The prompt was submitted at 16:34:49 and the
run was terminated at ~16:36 at the user's instruction. Two implementation-node generations
had dispatched (see §3); no plan card, no tool activity, no file change and no assistant
answer were ever rendered.

**Test B verdict: INCONCLUSIVE.** The observable evidence is that the runtime dispatched real
implementation calls — not that it retained context, edited files or ran tests.

---

## 6. Test C — regression diagnosis and repair

**Status: NOT RUN.** The controlled `multiply()` regression was never injected, because the
session never reached Test C. No manual repair was performed and no agent repair was claimed.

**Test C verdict: NOT EXECUTED.**

---

## 7. Changed files in the disposable fixture

```
%TEMP%\CrusorLiveE2E\workspace\mini_math\
  src/mini_math/ops.py        sha256 c1804f2f… 371 B   (unchanged)
  src/mini_math/__init__.py   sha256 388d31e6… 153 B   (unchanged)
  tests/test_ops.py           sha256 1eed3bb8… 653 B   (unchanged)
  README.md                   sha256 50ebdcce… 520 B   (unchanged)
```

No file was created, modified or deleted by the agent. Baseline and post-run suites are
identical (`9 passed`), which proves the fixture is clean, not that the agent worked.

No writes occurred outside the disposable workspace and the isolated app-data/log roots: the
Crusor repository dirty-entry count was unchanged (214 entries, zero deletions) and no
fixture artefact appeared in the repo.

---

## 8. Test and verification outcomes

| Check | Result |
|---|---|
| Baseline fixture suite (pre-run) | `9 passed` |
| Agent-modified files | 0 |
| Independent post-run suite | `9 passed` — same code, so not a verification of agent output |
| Verification card / delivery receipt for a real task | none produced (no task completed) |
| FinOps accounting | operational: 2 settled rows, real cost, receipts present |
| Ledger ↔ usage reconciliation | consistent (reservation/settlement/usage IDs match per call) |

## 9. Identity inconsistency found

The UI turn id was `turn-0abccf5553864a47ad0bada7d8f8e231`; the ledger rows carry
`turn_id = turn_turn-57463918e7474896816ab66eff3ad5f7` (a nested `turn_turn-…` prefix, and a
different id because it belongs to a different turn). Two consequences:

1. Per-turn cost attribution from the ledger cannot be joined to the rendered turn without a
   mapping step.
2. `task_id` is literally `"turn_" + turn_id`, so the `turn_turn-` duplication is a naming
   bug, not just a display artefact.

Also: `latency_ms` is **null** in both rows. Latency must be derived from
`started_at`/`completed_at` (61.3 s and 3.4 s), which means the ledger does not currently
carry the latency field the qualification requires.

## 10. Electron screenshots

`%TEMP%\CrusorLiveE2E\evidence\`

| File | Content |
|---|---|
| `00-agent-ready.png` | engine ready, real provider configured |
| `A-01-running.png` | Test A running: single activity card, no plan |
| `A-02-finished.png` | Test A terminal state: contract-rejection error |
| `B-01-running.png` | Test B dispatched, run stopped shortly after |

These are the evidence that the UI produced **no plan, no tools, no file change and no test
result** for the task. They are not a demonstration of the agentic experience.

## 11. Session restoration

**Not performed.** The run was terminated before the restart/rehydration phase. The prior
provider-free acceptance (`PASS 40/40`, three turns, reload, repeated hydration, full restart)
remains the only restoration evidence, and it is deterministic evidence, not real-provider
evidence.

## 12. Token, latency and cost analysis

| Metric | Value |
|---|---|
| Paid requests | **2** (both Test B; Test A = 0) |
| Test A cost | ₹0.00 |
| Test B cost (partial) | ₹0.143 |
| Per-call latency | 61.3 s and 3.4 s (derived; `latency_ms` null) |
| Total token consumption | 6,264 in / 6,159 out / 0 cached |
| Retries / fallbacks | 0 / 0 |
| Cost certainty | provider-agnostic **local pricing** applied to provider-reported token counts; `provider_reported_cost` is null |
| Session total | **₹0.143 of the ₹50 cap (0.29 %)** |
| Cost per successful engineering task | **not computable** — zero tasks succeeded |

Provider-reported usage vs local estimate: the endpoint returned no `usage.cost`, so all INR
figures are local pricing × provider token counts. Token counts themselves are
provider-reported. No extrapolation to a 24-hour figure is offered; two calls with no
completed task carry no predictive value.

## 13. Failures and limitations

1. **Blocking defect (product).** `parse_prompt_contract` does not recognise
   *"a divide(a, b) function"*, so the contract gate rejects a fully specified request with
   "no public symbol is specified". Reproduced read-only in `contract.py:311-315` and `:522`.
   Effect: no dispatch, no plan, no tool use, no edits, no tests — for a prompt that names the
   function, its parameters, its error behaviour, the files, the tests and the docs.
2. **UI streaming not acceptable** (user judgement, consistent with the capture). During the
   only turn that ran, the user saw one activity stage and a terminal error string: no plan
   card, no tool rows, no file-change card, no test-result card. Whatever streaming exists is
   not showing the work.
3. **Tests B and C not executed**, so multi-turn retention, real editing, test execution,
   diagnosis and repair are **unproven**, not failed-and-proven.
4. **Identity mismatch** between UI turn id and ledger `turn_id`, plus the `turn_turn-`
   duplication; per-turn cost joins need a mapping.
5. **`latency_ms` is null** in the ledger; timing is only derivable from start/end timestamps.
6. **Cost certainty is local pricing**, not provider-reported.
7. **Cloudflare 403** on `/v1/models` without the configured browser User-Agent — an
   environment trap for any future preflight that omits it.

## 14. Overall verdict

**FAIL.**

- **Real provider path:** **PASS** in the narrow sense — the configured model was reached
  through the real Electron app, bridge, canonical runtime and gateway, with settled ledger
  rows, real tokens and real cost. No mock, no scripted seam, no fake executor was active.
- **Engineering capability:** **FAIL** — the first task never reached the provider because a
  deterministic contract gate rejected an unambiguous request, and the second task was
  stopped before it produced any work. Repository understanding, multi-file implementation,
  multi-turn retention, test execution, diagnosis and repair are **not demonstrated**.
- **UI:** **FAIL** for this run — no plan, no tools, no file change, no test results; streaming
  judged unacceptable by the user.

Deterministic evidence and real-provider evidence are kept separate throughout: §3 is
real-provider evidence; §8 defines deterministic evidence; nothing here is inferred from a
model's claim of completion.

## 15. What has to be true before re-running

1. Fix the symbol extraction so *"implement a divide(a, b) function"* yields `divide`
   (accept name-first phrasing; add a regression test for it). This is a one-line pattern
   problem with a large blast radius, and it is the reason this qualification failed before
   inference.
2. Make the ledger `latency_ms` real and fix the `turn_turn-` / UI-turn-id mismatch so
   per-turn cost and timing attribute correctly.
3. Re-run Tests A–C with a fresh ₹50 cap only after (1) and (2). Spend so far (₹0.143) is
   consumed; the authorisation for this run is now closed.
