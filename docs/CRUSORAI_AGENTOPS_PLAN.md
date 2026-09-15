# CrusorAI — AgentOps Dashboard: Needs Extraction & Build Plan

> **Product name:** CrusorAI (explicitly **not** PulseAI — all new surfaces, branding assets,
> window titles, and API responses must say CrusorAI).
> **Goal:** A dedicated AgentOps dashboard that observes, measures, and operates the CrusorAI
> agent end-to-end: sessions, traces, tokens, cost, tools, context health, errors, approvals,
> evals, and feedback learning.
> **Status:** Plan v0.1 — written from the repository's actual telemetry surfaces.
> ⚠️ **Pending inputs:** the user-supplied **logo** and **requirements PDF** did not arrive in
> the workspace. Sections marked `[PDF-GAP]` are assumptions to be re-validated once the PDF is
> attached; `branding/crusorai-logo.*` is reserved for the logo asset.

---

## 1. What already exists (grounded inventory)

The agent runtime already produces every raw signal an AgentOps product needs. The dashboard's
job is aggregation + presentation, not new instrumentation (except where noted).

| # | Data source | Location | What it gives AgentOps |
|---|-------------|----------|------------------------|
| S1 | **Turn receipts (JSONL)** | `src/observability.py` → `~/.pulseai/observability/turns.jsonl` | One record per turn: session, turn id, model, provider, token buckets (input/output/cache), estimated cost USD, duration, tool-call count + names, execution mode, task type, completed flag, error. Opt-in via `PULSEAI_OBSERVABILITY=on`. |
| S2 | **Durable event journal (SQLite)** | `src/runtime/event_journal.py` → `~/.pulseai/runtime_events.db` (WAL) | Canonical execution timeline: `tool.intent` / `tool.result` rows, event_id uniqueness, session/turn/workspace/tool_call ids, timestamps. This is the trace backbone. |
| S3 | **Context-engine telemetry** | `ContextEngine.get_status()` in `src/context/context_engine.py` | Unified status: model, context window + source, usage %, pressure active, compaction stats, prompt-cache audit, stable-prefix invalidations, micro-compaction, proactive-prune counters, system-prompt char breakdown, context breakdown by layer. |
| S4 | **Latched runtime receipts** | `runtime.cache_break`, `runtime.degraded` (emitted through bridge events) | Once-per-session anomalies: cache-break detection (>5% and >~2000 tokens regression naming the offending layer), degraded scans. |
| S5 | **SSE event stream** | `src/dashboard_server.py` + `src/dashboard/event_bus.py` | Real-time events to a browser: tool approvals (pending/resolved/timed_out), diffs, session ids, statuses. Existing Flask dashboard at `:8080` with optional bearer auth and CORS allowlist. |
| S6 | **Bridge event vocabulary** | `src/bridge/` | `turn_started`, `turn_token_usage`, `turn_done`, `turn_failed`, `tool_call_start`, `tool_call_end`, `tool_failures`, `plan_created/approved/updated/cancelled`, `plan_revision_count`, `plan_wrap_nudges`, `session_create/load/resume/fork`, `runtime_degraded`, `approval_policy`. |
| S7 | **Feedback-learning store** | `src/context/feedback_memory.py` (append-only JSONL) | Per-task outcome attribution: which context layers were used, success flag, learned per-layer relevance weights. Cross-session. |
| S8 | **Cost router** | `src/agents/cost_router.py` | Tier classification (cheap/standard/premium), provider/model routing decisions, dead-provider marks, last-route info. |
| S9 | **Benchmark / eval harness** | `benchmarks/`, `lab/` (`run_eval_*.py`, JSON reports, `retest_evidence_dashboard.html`) | Deterministic scenario contracts, pass/fail grading, evidence artifacts, historical attempt reports. |
| S10 | **Approvals & safety** | `src/dashboard/turn_locks.py`, approval queue in event bus | Fail-closed approval decisions, pending queues, timeouts = deny, cross-session rejection. |
| S11 | **Error surface** | `src/dashboard/error_surface.py` | Classified engine errors for UI display. |
| S12 | **Frontend stacks** | `pulse-webview/` (Vite 8 + React 19 + CopilotKit), `webapp/` (Vite React) | Proven SPA tooling to clone for the dashboard frontend. |

---

## 2. Extracted AgentOps needs

Grouped into 10 capability areas. Priority: **P0** = MVP dashboard, **P1** = second iteration,
**P2** = later / pending PDF confirmation.

### A. Session & Trace Observability (P0)
1. **Session list**: all sessions with status (active/idle/failed), workspace binding, execution
   mode (Agent/Plan/Debug/Ask), started/last-active timestamps, turn counts. *(S2, S5, S6)*
2. **Turn-level trace view**: for one session, the ordered timeline — turn start → plan created →
   tool intents/results → token usage → turn done/failed. Reconstructable from the SQLite journal
   with `event_id`-deduped replay. *(S2, S6)*
3. **Tool-call drill-down**: per call — name, args (redacted), result status, duration, failure
   reason, diff preview for file mutations, paired intent/result. *(S2, S5)*
4. **Plan visibility**: plan steps, revisions (`plan_revision_count`), approvals, wrap nudges. *(S6)*
5. **Live mode**: SSE-driven updates while a session runs (reuse the event bus, add journal-tail
   subscription for crash-safe catch-up). *(S5, S2)*

### B. Token, Cost & Usage Analytics (P0)
6. **Per-turn usage**: input/output/cache token buckets and estimated USD cost from receipts. *(S1)*
7. **Aggregations**: cost & tokens by day/session/model/provider/execution-mode/task-type;
   top-N expensive sessions; burn-rate sparkline. *(S1)*
8. **Cache economics**: cached-token share per turn, prompt-cache hit/miss from `get_status()`,
   cache-break receipts flagged on the timeline. *(S1, S3, S4)*
9. **Routing transparency**: which tier (cheap/standard/premium) each call was routed to and why;
   savings attributed to cheap-tier offload; dead-provider events. *(S8)*
10. **Budgets & alerts** `[PDF-GAP]`: configurable spend/token budgets with threshold alerts.

### C. Context Health (P1)
11. **Context-window gauge**: usage %, pressure-active flag, window source (provider-fetched vs
    fallback), threshold. *(S3)*
12. **Compaction analytics**: compaction events, micro-compaction stats, proactive-prune reclaimed
    tokens, history-shaper counters. *(S3)*
13. **Layer breakdown**: which of the 32 context layers occupied how much of the prompt
    (`context_breakdown`), stable-prefix invalidation count. *(S3)*
14. **Cache-break detection panel**: the latched receipt naming the offending layer. *(S4)*

### D. Errors, Degradation & Reliability (P0)
15. **Error feed**: classified errors (`error_surface`), `turn_failed` events, receipt errors with
    session/turn linkage. *(S11, S6, S1)*
16. **Degradation receipts**: `runtime.degraded` occurrences (truncated scans, heuristic
    fallbacks when embeddings unavailable). *(S4)*
17. **Reliability KPIs**: task completion rate (`completed` flag), failure rate by mode/provider,
    mean turns-to-completion, retry/stall-guard activations. *(S1, S6)*
18. **Health overview**: provider reachability, bridge process status, journal/observability sink
    writability (preflight checks already exist in `src/dashboard/preflight.py`). *(S10/S11 area)*

### E. Approvals & Human-in-the-loop Ops (P1)
19. **Approval queue view**: pending tool approvals with args + diff, approve/deny from the
    dashboard (fail-closed semantics preserved: timeout = deny, cross-session rejected). *(S5, S10)*
20. **Approval analytics**: approval latency, deny rate, always-allow usage, policy per session
    (interactive vs headless benchmark). *(S5, S6)*

### F. Evaluation & Benchmark Ops (P1)
21. **Eval runs list**: lab harness results (`lab/*.json`, bench reports), pass/fail per scenario
    contract, links to evidence artifacts (screenshots, console logs). *(S9)*
22. **Regression board**: attempt history (e.g., Attempts 11/12 immutable FAIL evidence), trend of
    pass rates across runs. *(S9)*
23. **Run-now controls** `[PDF-GAP]`: trigger deterministic echo / benchmark runs from the
    dashboard. *(S9)*

### G. Feedback & Learning Ops (P2)
24. **Layer relevance weights**: learned weights per context layer from the feedback store, with
    record counts and confidence (>=10 records / >=5 attributed). *(S7)*
25. **Outcome attribution explorer**: per task — success flag + layers used. *(S7)*

### H. Performance & Latency (P1)
26. **Turn latency**: duration_s distributions (p50/p95), by model/provider/mode. *(S1)*
27. **Tool latency**: intent→result deltas from the journal. *(S2)*
28. **Throughput**: turns/hour, tokens/minute live charts. *(S1, S5)*

### I. Security & Audit (P1)
29. **Audit trail**: every side-effecting tool run is journal-backed (`tool.intent` before
    execution) — expose as an immutable audit log view. *(S2)*
30. **Secret-redaction visibility**: confirm memory-layer sanitization events; never render raw
    secrets in the dashboard. *(runtime contract)*
31. **Access control**: bearer-token auth (already in `dashboard_server.py`) mandatory for any
    non-loopback deployment; CORS allowlist; audit of dashboard logins. *(S5)*

### J. Product & Branding (P0)
32. **CrusorAI identity everywhere**: title, favicon, splash, about panel. **Logo asset pending —
    user said they sent it; it did not arrive.** Reserved path: `branding/crusorai-logo.svg/png`.
    Until then, use a neutral placeholder mark, never the PulseAI mark.
33. **Dark theme default** (matches PulseAI Dark convention; `[PDF-GAP]` confirm palette from logo).
34. **Zero PulseAI naming leakage** on new surfaces (env var names inside the engine stay as-is —
    renaming runtime env vars is out of scope and would break the desktop integration).

---

## 3. Dashboard architecture

### 3.1 Guiding decisions
- **Reuse, don't re-instrument.** The engine already writes everything (S1–S10). The AgentOps
  layer is a *read model* over the journal DB + receipts JSONL + SSE bus.
- **Separate app, same repo.** New top-level folder `crusorai-agentops/` (frontend) +
  `src/agentops/` (backend). Does not touch the desktop IDE build or the existing chat dashboard.
- **Read-only by default.** Only two write paths in MVP: approval decisions (E19, via existing
  fail-closed queue) and nothing else. Eval triggering (F23) is P2 and gated.
- **Crash-safe.** Journal is WAL SQLite — dashboard tails it read-only (`mode=ro`) so it can never
  corrupt agent state. Receipts JSONL is append-only and debris-tolerant (skip bad lines).

### 3.2 Backend — `src/agentops/` (FastAPI)
```
src/agentops/
  server.py          # FastAPI app, CORS allowlist, bearer auth (mirror dashboard_server policy)
  readers/
    journal.py       # read-only SQLite over runtime_events.db → traces, tool calls, audit log
    receipts.py      # tail/parse turns.jsonl → usage, cost, latency, completion KPIs
    feedback.py      # parse feedback JSONL → layer weights, attribution
    status.py        # live get_status() snapshot via bridge/engine handle (when attached)
  api/
    sessions.py      # GET /api/sessions, /api/sessions/{id}/trace
    usage.py         # GET /api/usage/summary?group_by=day|model|mode, /api/usage/turns
    errors.py        # GET /api/errors, /api/receipts/runtime
    approvals.py     # GET /api/approvals/pending, POST /api/approvals/{id}/resolve
    evals.py         # GET /api/evals (lab JSON reports index)
    stream.py        # GET /api/stream (SSE: journal tail + event bus bridge)
  models.py          # pydantic response schemas (the dashboard's data contract)
```
- **Port:** `8300` (avoids 8080 chat dashboard, 8123 AG-UI agent, 8200 CopilotRuntime, 5173 Vite).
- **Auth:** `CRUSORAI_OPS_TOKEN` bearer env var; required whenever bound off-loopback.
- **Binding:** `0.0.0.0` for preview environments; loopback default for production guidance.

### 3.3 Frontend — `crusorai-agentops/` (Vite + React + TS)
Clone the proven `webapp/` toolchain (Vite, React 19, TypeScript). No CopilotKit needed — this is
an ops console, not a chat surface. Charts: a lightweight lib (e.g., recharts) or hand-rolled SVG
to stay dependency-lean `[PDF-GAP: confirm if the PDF mandates a design system]`.

**Views (left-nav IA):**
1. **Overview** — health tiles (bridge up, provider reachability, sink writable), live KPI strip
   (active sessions, turns today, tokens today, spend today, completion rate, p95 latency),
   sparkline trends, latest errors/receipts ticker.
2. **Sessions** — table + filters (status, mode, workspace); row → Session Detail.
3. **Session Detail / Trace** — vertical timeline of the turn(s): plan card, tool calls with
   expandable args/result/diff, token-usage markers, receipts (`runtime.cache_break` ⚠ chips),
   errors; auto-scroll in live mode via SSE.
4. **Usage & Cost** — cost/token charts grouped by day/session/model/mode/task-type; cache-hit
   ratio; router tier breakdown & savings; budget bar (P1).
5. **Context Health** — per active session: window gauge, compaction/prune counters, layer
   breakdown treemap, cache-break history.
6. **Errors & Reliability** — error feed with classification, degradation receipts, failure-rate
   trends, completion-rate KPI.
7. **Approvals** — pending queue with diff preview + approve/deny (writes via existing fail-closed
   path); decision history & latency stats.
8. **Evals** — benchmark run index from `lab/` JSON reports, pass/fail matrix, evidence links.
9. **Learning** (P2) — feedback store explorer: layer weights, attribution table.
10. **Settings** — token config, sink paths, refresh intervals, about (CrusorAI version/build).

### 3.4 Data flow
```
Agent runtime ──writes──▶ runtime_events.db (S2)      ──read-only tail──▶ ┐
              ──writes──▶ turns.jsonl (S1)            ──parse/aggregate──▶ │ FastAPI :8300
              ──writes──▶ feedback JSONL (S7)         ──parse───────────▶  │  ├ REST (queries)
event_bus / bridge events (S5,S6) ──subscribe─────────────────────────────▶│  └ SSE (live)
                                                                            ▼
                                                          CrusorAI AgentOps SPA (browser)
```

---

## 4. Phased roadmap

### Phase 0 — Branding & skeleton (0.5–1 day)
- Create `crusorai-agentops/` SPA scaffold + `src/agentops/` FastAPI skeleton.
- CrusorAI name, placeholder logo mark, dark theme tokens. **Swap in real logo the moment the
  user re-attaches it** (`branding/crusorai-logo.*`, favicon, header).
- Auth, CORS, port wiring, health endpoint.

### Phase 1 — Core observability MVP (P0 needs: A, B6–8, D15–17, J)
- Journal reader → Sessions list + Session Detail trace + tool drill-down.
- Receipts reader → per-turn usage, cost & token aggregates, completion-rate KPIs, error feed.
- SSE live mode (journal tail + event-bus bridge).
- Overview page with KPI strip and health tiles.

### Phase 2 — Ops depth (P1 needs: C, E, H, I29–31, B9–10)
- Context Health page (get_status snapshots, cache-break panel, layer breakdown).
- Approvals queue with resolve + analytics.
- Latency percentiles, throughput charts.
- Audit-log view; router tier/savings panel; budgets & threshold alerts.

### Phase 3 — Evals, learning & polish (P1 F, P2 G, F23)
- Evals index from `lab/` reports + regression board; optional run-now controls.
- Feedback-learning explorer.
- PDF-driven refinements `[PDF-GAP]`, export (CSV/JSON), saved filters.

### Acceptance criteria (MVP gate)
- [ ] Every view renders real data from S1/S2/S5/S6 with zero new engine instrumentation.
- [ ] Dashboard never blocks or corrupts an agent turn (read-only journal handle; SSE failures
      swallowed; approvals still fail closed).
- [ ] Zero "PulseAI" strings in the new UI; CrusorAI logo/placeholder in header + favicon.
- [ ] Bearer auth enforced off-loopback; CORS allowlist configured.
- [ ] Live trace demonstrated end-to-end: start an agent turn → watch it appear in Session Detail
      within ~1s.

---

## 5. Open questions / pending inputs

| # | Item | Blocker level |
|---|------|---------------|
| 1 | **Logo file not received** — re-attach or drop into repo; until then a neutral placeholder mark is used. | Cosmetic (Phase 0 swap) |
| 2 | **Requirements PDF not received** — this plan's `[PDF-GAP]` items (budgets/alerts, design system, run-now evals) are assumptions to reconcile against it. | Scope validation |
| 3 | Deployment target: local dev tool (loopback) vs hosted team dashboard (auth hardening, multi-user)? | Phase 2+ design |
| 4 | Should the existing `:8080` chat dashboard be replaced/merged, or stay separate from the ops console? | IA decision (default: stay separate) |
| 5 | Retention policy for journal/receipts (rotate, cap size)? | P2 |
