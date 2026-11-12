# Financial & Performance Visibility Spec

Status: **DRAFT FOR APPROVAL** · 2026-11-12 · Owner: founder · Builds on existing `src/finops/` + `src/telemetry/pricing.py`.

---

## 1. Why this exists

Three decisions depend on this system, and today none can be answered:

| Question | Can you answer it today? |
| --- | --- |
| What does one successful task cost me? | **No** — receipts are dead (`src/observability/` shadowing) |
| Which provider/model gives the best cost per success? | **No** — no per-task outcome joined to cost |
| What is my monthly burn vs. revenue? | **No** — no consolidated ledger |

This system is also a **product feature**, not just internal tooling: cost per successful task is the
claim no competitor publishes (see `03-COMPETITIVE-BENCHMARK.md` §2).

---

## 2. Architecture (deliberately small)

```
agent turn ──► TurnReceipt (JSONL append)  ──►  ledger.sqlite  ──►  rollups (SQL views)  ──►  dashboard page
                    │                                                   │
                    └── existing finops/accounting.py (token truth)      └── monthly export CSV
```

- **Source of truth for tokens:** provider-reported usage already implemented in `src/finops/accounting.py`
  (idempotent, priced via `src/telemetry/pricing.py`). Do not re-estimate tokens where the provider reports them.
- **Storage:** one append-only JSONL per day + SQLite for queries. No Kafka, no Prometheus, no Grafana.
- **Currency:** configurable; keep the repo's ₹ convention for internal reports, display USD for public claims.
- **Retention:** 90 days raw, monthly rollups kept forever. (Also addresses the 937 MB checkpoint DB problem —
  retention applies to checkpoints too.)

---

## 3. Event schema (TurnReceipt v0)

| Field | Type | Notes |
| --- | --- | --- |
| `receipt_id` | uuid | idempotency key |
| `task_id` | uuid | groups all turns of one user task |
| `turn_index` | int | 0-based |
| `ts_start`, `ts_end` | iso8601 | wall clock, UTC |
| `workspace_id` | hash | never a raw path (privacy) |
| `provider`, `model` | string | as routed, not as requested |
| `profile` | enum | beginner / developer / enterprise |
| `autonomy_mode` | enum | allow / ask / deny resolution used |
| `tokens_in`, `tokens_out`, `tokens_cache_read`, `tokens_cache_write` | int | provider-reported |
| `cost_usd` | decimal | priced at request time; store the rate-card version |
| `tool_calls` | int | count, plus `tools[]` names |
| `approvals_requested` / `approvals_denied` | int | autonomy health |
| `tests_run`, `tests_passed`, `tests_failed` | int | from the test tool |
| `outcome` | enum | `success` / `failed` / `blocked` / `cancelled` |
| `outcome_evidence` | string | e.g. `pytest exit 0`, never a self-assessment |
| `retry_count` | int | provider retries |
| `error_class` | enum | rate_limit / auth / context_overflow / tool_error / model_error |
| `checkpoint_bytes` | int | feeds the DB-growth metric |

**Rule that matters:** `outcome` is set by evidence (exit code, test result), never by the model saying
"done". This is the F-09 audit finding, and it is the difference between a metric and a mood.

---

## 4. Metric definitions (no vanity metrics)

| Metric | Definition | Formula |
| --- | --- | --- |
| Task completion rate | Tasks reaching `success` | `success / (success+failed+blocked)` |
| **First-attempt success rate** | Tasks succeeding with `turn_index = 0` and `retry_count = 0` | `first_attempt_success / tasks` |
| Test pass rate | Post-task test runs green | `tests_passed / (passed+failed)` |
| **Cost per successful task** | Fully loaded: all attempts, retries, failures, then divided by successes | `Σ cost(all tasks) / successes` |
| Tokens per task | Mean across tasks, split in/out/cache | `Σ tokens / tasks` |
| Recovery rate | Failures that still ended in success | `recovered / failures` |
| Intervention rate | Human approvals + manual retries per task | `Σ interventions / tasks` |
| Execution time | p50 / p95 wall clock per task | percentile |
| Escape rate | Unapproved mutations or sandbox violations | count, target 0 |
| Provider efficiency | Cost per success **and** success rate per provider/model | ratio table |
| Monthly burn | Provider invoices + infra + tooling | `Σ invoices` |
| Unit margin | Revenue − (burn attributable to served tasks) | per tier |

Two definitions to defend in every review:
**cost per successful task includes failures** (otherwise it flatters), and **success requires evidence**
(otherwise it lies).

---

## 5. Dashboard — three views, one page

### View 1 — Operations (daily, you)
- Today: tasks, success rate, interventions, spend.
- 7/30-day trend: cost per successful task (the north-star line).
- Alerts panel: budget threshold, error-class spike, checkpoint DB growth, receipt gaps.

### View 2 — Providers (weekly, you)
Grid: rows = provider/model, columns = tasks, success %, p95 time, tokens/task, cost/task, cost/success.
Sortable. This is the only honest way to choose a default model.

### View 3 — Business (monthly, you + future investor)
Monthly table: provider spend, infra spend, tooling, total burn; installs, active users, tasks, revenue, margin.
Plus 3 published numbers for the launch page: median task cost, first-attempt success, p95 time.

---

## 6. Guardrails and alerts

| Guardrail | Threshold | Action |
| --- | --- | --- |
| Monthly provider budget | user-set (existing budget governor) | warn 70%, hard-stop at 100% unless overridden |
| Per-task cost | p95 × 3 | warn in-app before the next turn |
| Receipt gap | any task without a receipt | fail the build (`CI` gate) — receipts are a correctness feature |
| Checkpoint DB size | > 2 GB | prompt retention purge |
| Error-class spike | >20% of turns in 1h | surface to user, suggest provider switch |
| Escape | any unapproved mutation | log as incident, never silent |

---

## 7. Build plan

| Stage | Work | Effort | Gate |
| --- | --- | --- | --- |
| v0 (two-day milestone) | Fix shadowing; emit receipt per task to JSONL; print cost on completion | 1.5d | Included in Deliverable 4 (A4/A5) |
| v1 (P0-C / P1) | SQLite ledger + 3 SQL views + `/ops` page on the existing Flask dashboard | 2d | After v0 |
| v2 (P3) | User-facing usage page + monthly CSV export + provider comparison | 4d | After F1/F2 |
| v3 | Public benchmark page fed by the same ledger | 3d | Before launch |

**Reuse, do not rebuild:** the Flask dashboard at `:8080` already serves SSE + approvals; add `/ops` there
rather than standing up a new stack. The finops accounting layer already prices requests; do not duplicate it.

---

## 8. What not to measure

- Lines of code, commits, "agent actions" — all gameable.
- Model self-reported confidence.
- Tokens saved by context engineering (interesting, unprovable today) — measure *task success*, not tokens saved.
- Number of installed skills/tools — a proxy for nothing.
- Any number you cannot trace to a receipt row.
