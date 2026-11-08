# P0.6.9 — Findings

## 1. Final verdict

**`P0.6.9_ACCEPTANCE_FAILED`.**

The engineering task passed end-to-end, and the auxiliary title call was enabled,
claimed and reserved before dispatch. It did **not settle**: the bridge finalized
the evidence manifest before running the governed title call, the harness treated
the manifest as turn-terminal and stopped the app, killing the call mid-flight.
One reservation remained `in_flight`; the title was empty.

That is precisely the condition this milestone forbids — a physical provider
claim without a settlement — so the run is failed, not converted to a pass.

| Summary | Value |
| --- | --- |
| Run / turn | `p0_6_5_20261107T221000_edc9f5de` / `turn-b140891f…` |
| Prompt | exact P0.6.7 prompt (SHA `a887a669…`) |
| Contract | hash `06a61371…`, 2 components, no ambiguities |
| Plan | 2 work units, demand 2 |
| In-turn tests | 10/10, exit 0 |
| Engineering dispatches | 2, settled, ₹0.092296 |
| Auxiliary title | 1 claim, reservation `res_2f16815efba3`, **in_flight**, ₹0 settled |
| Guard claims | 3 (2 task + 1 auxiliary) |
| Offline suite | **309 passed, 0 failed** |

## 2. Original P0.6.8 accounting failure

P0.6.8's task passed 10/10, but the auto-title call used
`qwen/qwen3.7-flash` through `RetryLLMProxy` with no FinOps reservation: 3 guard
claims, 2 settlements. The transport counted the call; the financial system did
not. P0.6.8's mitigation disabled auto-title in acceptance, which hid the gap.

## 3. Provider inventory

`PROVIDER_INVENTORY.md` lists every call site (orchestrator implementation/
repair, session titling, chat graph, summarizer, compaction, self-curation,
planner helpers, one-shot runner, inline completions, basic graph, tool test,
embeddings, retries). The accepted desktop path (engineering + repair + titling)
is governed; legacy/management lanes are inventoried and fail closed in
acceptance without a reservation.

## 4. Unified accounting architecture

- `src/finops/invocation_context.py`: one invocation scope (subsystem,
  reservation id, provider/model, task) and one workspace ledger
  (`provider_invocations.jsonl`) carrying run/session/turn/workspace ids,
  reservation/settlement ids, usage, cost and status.
- `src/finops/governed.py`: `GovernedProviderGateway` for auxiliary/background
  calls — verified pricing, conservative bound, reserve, one attempt, output
  ceiling, authentic usage, actual cost, settle. Unpriced/unauthorized calls
  never dispatch; ambiguity stays uncertain.
- `RetryLLMProxy.invoke` refuses any acceptance-mode call without a reservation
  scope, before request preparation.
- The task adapter keeps its existing FinOps path, adds the scope and writes
  the same ledger record.
- Session titling uses a session-scoped governor (₹0.50 auxiliary budget) and
  is enabled during acceptance.

## 5. Auxiliary invocation changes

`_maybe_autotitle_session` now:

1. resolves its own accounting scope (`subsystem=session_titling`);
2. resolves provider/model (`cheap` / `qwen/qwen3.7-flash`);
3. reserves a conservative maximum;
4. invokes once (`max_attempts=1`) with a 64-token ceiling through the gateway;
5. captures authentic usage, calculates actual cost, settles;
6. writes an invocation record;
7. falls back to an explicit **local** title only when accounting refuses or the
   model returns no usable text — never as a fake successful model call.

The call runs synchronously in acceptance, and after the post-live fix, **before
the evidence manifest is finalized**.

## 6. Acceptance guard changes

- The guard still counts every physical claim at the proxy.
- The harness now reads the invocation ledger plus all FinOps files and requires:
  guard claims == settled invocation records == aggregate calls; ≥2 settled
  engineering and ≥1 settled `session_titling` record with provider/model/cost;
  a non-empty title; ledger cost == aggregate settled cost (1e-6); no
  uncertain/active holds; aggregate ≤ ₹5.
- After the live failure, `finish()` waits up to 90 s for a terminal auxiliary
  record before stopping the app.

## 7. Offline qualification

**309 passed, 0 failed, 0 skipped** (257.45 s). 15 new P0.6.9 tests cover the
gateway lifecycle, unpriced refusal, uncertain holds, releases, distinct
settlements, proxy fail-closed/accounted calls, ledger attribution, aggregate
FinOps, bridge titling, local fallback and the wait helper. All prior P0.6.6–
P0.6.8 suites and bridge/renderer/stability tests pass.

## 8. Live acceptance evidence

Passed: Electron submission, workbench, worker/bridge ownership, prompt SHA,
contract extraction, role-aware assignment, plan validation, cross-file
consistency, source/test generation, 10/10 in-turn pytest, independent smoke,
requirement verification, truthful `COMPLETED` turn, task FinOps reconciliation,
no unauthorised mutations.

Failed: automatic title generation never settled; the title is empty; the
auxiliary invocation has no usage record or settlement.

## 9. Dispatch and attempt counts

- 3 physical claims, 1 attempt each (guard max 5).
- 2 settled engineering dispatches.
- 1 auxiliary claim (qwen) with a reservation but no settlement.
- No retries, no failover, no duplicate settlement.

## 10. Actual financial cost

- Task: **₹0.092296** (1201 input / 4693 output tokens).
- Auxiliary: **₹0** settled; **₹0.014149** reserved and left in flight.
- Aggregate settled: ₹0.092296; outstanding hold ₹0.014149; budget ₹5 not
  breached.

## 11. Task vs auxiliary breakdown

| Subsystem | Claims | Settled | Cost |
| --- | ---: | ---: | ---: |
| engineering | 2 | 2 | ₹0.092296 |
| session_titling | 1 | **0** | ₹0 |
| **total** | **3** | **2** | **₹0.092296 settled + ₹0.014149 held** |

## 12. SQLite/JSON reconciliation

- Task ledger: 2/2 settled, SQLite and JSON agree.
- Auxiliary: reservation exists in JSON and canonical store; no usage/commit,
  so no reconciliation is possible. It is not represented as free.
- Aggregate does not reconcile because one physical call is unresolved.

## 13. Invariant 7

**Maintained** — 0 changed files in `desktop/vscode`, 0 drift, 0 undeclared.

## 14. Secret scan

0 real hits across changed files. Reviewed false positives: env-variable names
in `api_key=GROQ_API_KEY` etc., the contextvar `token = _CURRENT_SCOPE.set(...)`,
and the approval token variable.

## 15. Remaining defects

1. **Live ordering fix is unproven.** The bridge now settles the title before
   the manifest and the harness waits, but no second live run was authorized.
2. **Legacy lanes remain ungoverned outside acceptance** (chat graph,
   summarizer, compaction, self-curation, planner helpers, one-shot, inline
   completions). They are refused in acceptance; production coverage remains a
   gap.
3. **Auxiliary provider latency/behavior** was not characterized: the live call
   never returned before shutdown, so its normal duration is unknown.
4. **No OS-level network sandbox.**

## 16. Commit map

| Commit | Content |
| --- | --- |
| `048fabb3` | invocation context/ledger, governed gateway, proxy boundary, adapter records, titling gateway |
| `bea5e5df` | 15 accounting tests + P0.6.9 gate updates |
| `c68ccc7c` | harness ledger/aggregate readers + P0.6.9 verdict |
| `6e216ded` | inventory, baseline, coverage, first offline qualification (308) |
| `f3ad118f` | post-live fix: title before manifest + harness wait (309 offline) |
| this docs commit | this report, matrix, financial reconciliation, live9 evidence, checksums |

Branch `feat/prompt-cache-stabilization`; local HEAD == origin verified after
push.

## 17. Final authorized re-acceptance (live10)

One additional bounded live run was authorized and executed after the two
lifecycle fixes. It failed **before testing or titling**: the source provider
output hit the 8192-token ceiling (`finish_reason='length'`) and the fail-closed
adapter refused to mutate `src/duration.py`. The turn ended `failed`; no
auxiliary provider call was made.

- Run `p0_6_5_20261107T224903_ddf70775`, turn `turn-894b79c8...`.
- Contract `82b51fcd...`, 2 components, plan 2 work units, validated.
- 2 physical claims (source + tests), both settled; INR 0.164152; 0 active/uncertain.
- No title, no auxiliary claim; the harness waited 90 s and honestly timed out.
- Offline preflight: 309 passed; Invariant 7 maintained; live9 checksums 24/24.

Full detail: `FINAL_REACCEPTANCE.md`. No further paid run was performed.
