# CrusorAI — AgentOps Dashboard: Needs Extraction & Build Plan

> **Status:** proposed product/build plan, not a shipped dashboard. Raw signals
> listed below should be rechecked against current callers and schemas; the
> current audit is [`AGENT_CORE_CURRENT_STATE.md`](AGENT_CORE_CURRENT_STATE.md).
>
> **Product name:** CrusorAI (explicitly **not** PulseAI — all new surfaces say CrusorAI).
> **Goal:** A dedicated AgentOps website dashboard that observes, measures, and operates the
> CrusorAI agent end-to-end.
> **Inputs received (v0.2):**
> - **Logo** — chrome/silver isometric "CR" monogram on black, from `origin/main @ 9afe945`
>   (`1000083027.png`), now filed at `branding/crusorai-logo.png`.
> - **Requirements/direction PDF** — Joshi, *"LLMOps, AgentOps, and MLOps for Generative AI: A
>   Comprehensive Review"*, IJCATR Vol.14–07, DOI 10.7753/IJCATR1407.1001, now filed at
>   `docs/references/LLMOps-AgentOps-MLOps-GenAI-Review-IJCATR1407.pdf`. Cited below as **[PDF §x]**.
> - **Repo telemetry audit** — 12 live data sources in this repository (S1–S12 below).
> **Placement decision (user):** AgentOps lives in its **own self-contained top-level folder**
> (`agentops/`) as a **website dashboard** — backend + web in one place, independent of the
> desktop IDE build.

---

## 1. What already exists (grounded inventory)

The agent runtime already produces nearly every raw signal AgentOps needs. The dashboard is a
*read model* over these; new instrumentation only where flagged **[GAP]**.

| # | Data source | Location | What it gives AgentOps |
|---|-------------|----------|------------------------|
| S1 | **Turn receipts (JSONL)** | `src/observability.py` → `~/.pulseai/observability/turns.jsonl` | Per turn: session, turn id, model, provider, token buckets (input/output/cache), estimated cost USD, duration, tool-call count + names, execution mode, task type, completed flag, error. Opt-in `PULSEAI_OBSERVABILITY=on`. |
| S2 | **Durable event journal (SQLite, WAL)** | `src/runtime/event_journal.py` → `~/.pulseai/runtime_events.db` | Canonical execution timeline: `tool.intent` → `tool.result` rows, unique event ids, session/turn/workspace/tool_call ids, timestamps. The trace/replay backbone. |
| S3 | **Context-engine telemetry** | `ContextEngine.get_status()` (`src/context/context_engine.py`) | Model, context window + source, usage %, pressure flag, compaction stats, prompt-cache audit, stable-prefix invalidations, micro-compaction, proactive-prune, system-prompt char split, per-layer context breakdown. |
| S4 | **Latched runtime receipts** | `runtime.cache_break`, `runtime.degraded` (bridge events) | Once-per-session anomalies: prompt-cache regression (>5% / >~2000 tok, names offending layer), degraded scans. |
| S5 | **SSE event stream + event bus** | `src/dashboard_server.py`, `src/dashboard/event_bus.py` | Real-time events incl. approval lifecycle (pending/resolved/timed_out), diffs, statuses. Existing Flask chat dashboard at :8080 (stays separate). |
| S6 | **Bridge event vocabulary** | `src/bridge/` | `turn_started`, `turn_token_usage`, `turn_done`, `turn_failed`, `tool_call_start/end`, `tool_failures`, `plan_created/approved/updated/cancelled`, `plan_revision_count`, `plan_wrap_nudges`, `session_create/load/resume/fork`, `runtime_degraded`, `approval_policy`. |
| S7 | **Feedback-learning store (JSONL)** | `src/context/feedback_memory.py` | Per-task outcome attribution: layers used, success flag, learned per-layer relevance weights. |
| S8 | **Cost router** | `src/agents/cost_router.py` | Tier classification (cheap/standard/premium), routing decisions, dead-provider marks, savings attribution. |
| S9 | **Benchmark / eval harness** | `benchmarks/`, `lab/` | Scenario contracts, pass/fail grading, JSON reports, evidence artifacts, historical attempt records. |
| S10 | **Approvals & safety gates** | event-bus approval queue, `src/dashboard/turn_locks.py` | Fail-closed approvals: timeout = deny, cross-session rejected; workspace-safe mutation controls. |
| S11 | **Error surface + preflight** | `src/dashboard/error_surface.py`, `preflight.py` | Classified engine errors; environment/preflight health checks. |
| S12 | **Sub-agent runtime** | `src/agents/sub_agent.py`, `subagent_lifecycle.py` | Sub-agent spawn/lifecycle — basis for multi-agent monitoring **[partially GAP: lifecycle events not journaled]**. |
| S13 | **Prompt corpus** | `src/prompts/` (versioned in git) | Prompt sources for versioning/registry view **[GAP: no prompt-id emitted per turn — add receipt field]**. |

---

## 2. Needs extracted from the reference PDF [PDF]

The paper defines the AgentOps discipline. Every need below is quoted from its structure and
mapped to (a) the CrusorAI dashboard feature that satisfies it, (b) the repo source or gap.

### 2.1 The AgentOps stack [PDF §2.3]
| Need (paper) | Dashboard feature | Source / gap |
|---|---|---|
| Monitoring: real-time metrics, logs, session replays | Live Overview KPIs; Sessions list; Session Replay view (step-through of journaled events with timestamps = time-travel) | S1, S2, S5, S6 |
| Debugging: time-travel debugging, error tracing | Trace detail with per-step replay scrubber; error feed linked to exact turn/tool rows | S2, S11 |
| Debugging: prompt-injection detection | Injection-suspicion flags on tool args / untrusted layer content | **[GAP]** engine sanitizes memory layers; surface a `security.injection_suspect` receipt |
| Automation: deployment pipelines, scaling, rollback | Out of scope for v1 (single-machine agent); eval-run triggers + config versioning are the proxy | S9, S13 |
| Security: audit trails and compliance reporting | Immutable audit log (journal-backed: intent-before-execution), CSV/JSON compliance export | S2 |

### 2.2 LLMOps layer needs [PDF §3.2, §5.2]
| Need | Dashboard feature | Source / gap |
|---|---|---|
| Prompt engineering/management, **prompt versioning**, A/B of prompt variants | Prompt Registry view: prompt file + git hash per turn, variant tags | S13 **[GAP: emit prompt_id per turn]** |
| Hallucination monitoring | Verification-gate outcomes (syntax/type/test/UI-evidence failures) as hallucination-proxy rate | engine verification gates **[GAP: receipt field]** |
| Specialized evaluation metrics | Evals view from lab/benchmark graders | S9 |
| Cost management, cost tracking per API call/token | Usage & Cost view; cost equation below | S1, S8 |
| Observability: performance, latency, token usage | KPI strip + latency percentiles | S1 |

### 2.3 AgentOps differentiators [PDF §5.3, §6]
| Need | Dashboard feature | Source / gap |
|---|---|---|
| Session tracing & replay | Sessions + Trace/Replay views | S2, S6 |
| Multi-agent coordination monitoring | Sub-agent tree per session (parent→children, status, cost attribution) | S12 **[GAP: journal sub-agent lifecycle]** |
| Tool usage analytics | Tool leaderboard: calls, failures, latency, arg patterns per tool | S2 |
| Safety & compliance guardrails; kill switches | Approvals view + **STOP (kill switch)** per session & global; guardrail status tiles | S10 **[GAP: expose cancel via ops API]** |
| Non-determinism / emergent-behavior monitoring | Emergent-behavior flags: `runtime.degraded`, wrap-nudges, stall-guard hits, plan-revision spikes | S4, S6 |
| Continuous learning & adaptation; policy versioning | Learning view (layer weights, attribution); policy/config version from git | S7, S13 |
| Holistic agent-performance evaluation (goal achievement, efficiency, robustness) | Reliability KPIs: completion rate, turns-to-completion, retries, mode-wise success | S1, S6 |
| Reported industry deltas (40% faster debugging, −35% unintended behavior, +50% uptime) | Adopt as dashboard value targets; SLO panel tracks toward them | — |

### 2.4 Challenges → dashboard answers [PDF §7]
1. Data governance/quality → provenance columns (workspace, session, sink path) on every view.
2. Model evaluation/reliability → Evals + reliability KPIs.
3. Scalability/infrastructure → cost & token analytics, tier routing transparency.
4. Security/privacy/ethics → audit trail, redaction guarantees, access control.
5. Observability/**explainability** → "why" panel per decision: context-layer attribution,
   router tier reason, cache-break culprit layer.
6. Adoption/skills → single self-contained folder + README runbook (ops, not ML, vocabulary).

### 2.5 Best practices & integrated framework [PDF §2.4, §8, §9]
- Integrate observability early → dashboard reads existing sinks; zero engine rework for MVP.
- Automated testing/CI-CD for agent updates → link eval runs to git commits (attempt history).
- Continuously monitor cost & performance → Overview KPI strip + alerts.
- Robust error handling & rollback → error feed + journal-backed audit (every mutation reversible
  via recorded diff).
- Guardrails: pre/post filters + human oversight points → Approvals queue (human-in-the-loop).
- A/B testing for agents (architectures, tool configs, prompt strategies) → compare execution
  modes (Agent/Plan/Debug/Ask) and prompt variants in Evals view (P2).
- Three-layer framework (Model Ops / Agent Ops / Orchestration control plane) → dashboard IA
  mirrors it: **Model Ops** = Usage/Cost/Prompt Registry; **Agent Ops** = Sessions/Traces/Errors/
  Context/Learning; **Orchestration** = Overview control plane + Approvals + kill switch.

### 2.6 KPI math to implement [PDF §4.4]
- **Cost:** `Total Cost = Σᵢ tokensᵢ × cost_per_tokenᵢ` → per-model price table (env-configured),
  applied to input/output/cache buckets (cache discounted).
- **Accuracy / Error rate:** `acc = correct/total`, `err = 1 − acc` → completion & failure KPIs.
- **SPC control charts:** `UCL/LCL = X̄ ± A₂·R̄` over daily cost, latency, error-rate → anomaly
  alerts when a day/turn falls outside control limits (this is the budget/anomaly-alert engine).
- **Drift metrics:** KL / Jensen-Shannon / Wasserstein over tool-usage & task-type distributions
  week-over-week → drift panel (P2).
- GenAI output metrics (perplexity, FID, ROUGE/BLEU): not applicable to a coding agent's ops
  console; lab graders cover output quality instead.

### 2.7 Case-study SLO targets to display [PDF §10]
Hallucination-rate −42%, uptime 99.97%, op-cost −35% → SLO panel defaults: **uptime ≥ 99.9%**,
**completion ≥ 90%**, **verification-failure (hallucination proxy) trend ↓**, **cost/task trend ↓**.

---

## 3. Consolidated needs catalog (repo ∪ PDF), prioritized

**P0 = MVP website**, P1 = second iteration, P2 = later.

### A. Sessions, Traces & Replay — P0
1. Session list (status, workspace, mode, turns, timestamps). *(S2, S5, S6)*
2. Trace view: ordered turn timeline — plan, tool intent/result, usage markers, errors. *(S2, S6)*
3. **Session replay / time-travel**: scrub journaled events step-by-step with timestamps. *(S2)* **[PDF §2.3]**
4. Tool-call drill-down: args (redacted), result, duration, failure, diff preview. *(S2, S5)*
5. Plan visibility: steps, revisions, approvals, wrap nudges. *(S6)*
6. Live mode: SSE updates + journal tail catch-up. *(S5, S2)*

### B. Tokens, Cost & Usage — P0
7. Per-turn usage & cost from receipts; **price table implementing Σ tokens × cost/token**. *(S1)* **[PDF §4.4]**
8. Aggregates by day/session/model/provider/mode/task-type; top-N expensive sessions; burn sparkline.
9. Cache economics: cached-token share, prompt-cache audit, cache-break flags. *(S1, S3, S4)*
10. Router transparency: tier per call + why, cheap-tier savings, dead providers. *(S8)*

### C. Context Health — P1
11. Window gauge (usage %, pressure, source), compaction/micro-compaction/prune counters. *(S3)*
12. Layer breakdown treemap; stable-prefix invalidations. *(S3)*
13. Cache-break panel naming offending layer. *(S4)*

### D. Errors, Degradation & Reliability — P0
14. Error feed (classified) linked to session/turn. *(S11, S1, S6)*
15. Degradation receipts; emergent-behavior flags (nudges, stall-guard, revision spikes). *(S4, S6)*
16. Reliability KPIs: completion rate, failure by mode/provider, turns-to-completion. *(S1, S6)*
17. Health tiles: bridge up, provider reachability, sinks writable. *(S11)*
18. Hallucination-proxy: verification-gate failure rate. *(engine gates; [GAP receipt field])* **[PDF §3.2]**

### E. Approvals & Human-in-the-loop — P1
19. Approval queue with diff preview + resolve (fail-closed preserved). *(S5, S10)*
20. Approval analytics: latency, deny rate, always-allow usage. *(S5, S6)*

### F. Evals, A/B & Regression — P1/P2
21. Eval runs index from `lab/` + benchmarks; pass/fail matrix; evidence links. *(S9)*
22. Regression board over attempt history (immutable past FAILs preserved). *(S9)*
23. A/B: compare modes / prompt variants / tool configs (P2). *(S6, S13)* **[PDF §8]**

### G. Learning & Adaptation — P2
24. Layer relevance weights + confidence; outcome attribution explorer. *(S7)* **[PDF §6]**

### H. Performance & Latency — P1
25. Turn latency p50/p95 by model/provider/mode; tool intent→result latency; throughput charts. *(S1, S2)*

### I. Security, Audit & Control — P0/P1
26. Audit log view (journal = intent-before-execution proof) + compliance export (P2). *(S2)* **[PDF §2.3]**
27. **Kill switch**: stop session / stop-all from dashboard (P1). *(engine cancel; [GAP ops API route])* **[PDF §6]**
28. Prompt-injection suspicion flags (P2). **[GAP]** **[PDF §2.3]**
29. Access control: bearer token mandatory off-loopback; CORS allowlist; redaction everywhere. *(S5 pattern)*
30. Secret-safety: dashboard never renders raw secrets; args redacted by policy. *(runtime contract)*

### J. Prompt & Policy Ops — P1
31. Prompt registry: file + git hash + variant per turn; policy/config version. *(S13)* **[GAP: prompt_id]** **[PDF §3.2, §6]**

### K. Anomaly, Drift & SLO Alerting — P1
32. SPC control charts (UCL/LCL) on cost, latency, error rate → alerts. **[PDF §4.4]**
33. SLO panel vs case-study targets (uptime, completion, cost/task ↓). **[PDF §10]**
34. Distribution drift (KL/JS/Wasserstein) on tool/task mixes (P2). **[PDF §4.4]**

### L. Multi-Agent & Orchestration — P2
35. Sub-agent tree per session with cost/status attribution. *(S12; [GAP journal rows])* **[PDF §6]**
36. Overview as orchestration control plane (paper's third layer). **[PDF §9]**

### M. Branding & Product — P0
37. CrusorAI identity: real logo (`branding/crusorai-logo.png`), favicon, splash, about. Dark chrome theme.
38. Zero PulseAI strings in new UI (engine env var names untouched — renaming breaks desktop).
39. Self-contained `agentops/` folder; website dashboard; independent of desktop IDE build.

---

## 4. Branding spec (from the received logo)

- **Mark:** isometric interlocked "C/R" monogram, chrome/silver gradient on pure black.
- **Palette (dark-first, chrome-on-black):**
  - bg `#060607`, panel `#101014`, border `#232329`
  - chrome gradient accent `#f5f5f7 → #b9b9c2 → #7c7c86` (logo chrome) for marks, active nav, KPI numerals
  - text `#eaeaee`, muted `#8f8f98`
  - semantic: success `#3ecf8e`, warn `#f5b84d`, error `#f0564a`, info `#6ea8fe`
- **Type:** Inter/system stack; semibold headings; tabular numerals for KPIs.
- **Wordmark:** monogram + "CrusorAI" (chrome gradient on "Crusor", white "AI").
- Favicon: monogram cropped from the PNG (generate SVG/PNG derivatives in Phase 0).

## 5. Architecture — self-contained `agentops/` folder

```
agentops/                      # everything AgentOps lives here (user decision)
  README.md                    # runbook: dev + prod, env vars, ports
  backend/                     # FastAPI ops API (read-only over engine sinks)
    app.py                     # app factory, CORS allowlist, bearer auth, static-serves web/dist
    readers/
      journal.py               # read-only SQLite (mode=ro) over runtime_events.db → traces, audit
      receipts.py              # tail/parse turns.jsonl → usage, cost, latency, KPIs (debris-tolerant)
      feedback.py              # feedback JSONL → layer weights, attribution
      evals.py                 # index lab/ + benchmarks JSON reports
      status.py                # get_status() snapshots when an engine handle is attached
    api/
      sessions.py  usage.py  errors.py  approvals.py  control.py  evals.py  prompts.py  stream.py
    models.py                  # pydantic response contracts
    pricing.py                 # per-model price table (env) → Σ tokens × cost/token
    spc.py                     # control-limit math (X̄ ± A₂R̄), drift metrics
  web/                         # the website dashboard (Vite + React 19 + TS, clone webapp/ toolchain)
    src/views/  Overview | Sessions | SessionTrace | UsageCost | ContextHealth |
                Errors | Approvals | Evals | Learning | Prompts | Settings
    src/components/ kpi-strip, timeline, replay-scrubber, treemap, control-chart, logo-mark
  scripts/dev.sh               # backend :8300 + vite :5180 (proxy /api → 8300)
```
- **One folder, one product.** Prod: `uv run python -m agentops.backend.app` (or `agentops/serve.py`)
  serves the built SPA + API on **:8300**. Dev: vite :5180 proxies `/api`.
- **Read-only by default.** Writes limited to: approval resolve + cancel/kill-switch (both reuse
  existing fail-closed engine paths). Journal opened `mode=ro`; SSE/receipt failures swallowed —
  the dashboard can never break a turn.
- **Auth:** `CRUSORAI_OPS_TOKEN` bearer; enforced whenever bound off-loopback. Bind `0.0.0.0` in
  preview envs, loopback default documented for personal use.
- Existing `:8080` chat dashboard, `:8123` AG-UI agent, `:8200` CopilotRuntime untouched.

## 6. Phased roadmap

### Phase 0 — Skeleton + brand (≈0.5 d)
Folder scaffold; logo derivatives + chrome-on-black theme; auth/CORS/health; favicon; README runbook.

### Phase 1 — Core observability MVP (A1–6, B7–10, D14–17, I26, M)
Journal reader → Sessions, Trace + **replay scrubber**, tool drill-down, audit log.
Receipts reader → per-turn cost (price table), aggregates, KPI strip, error feed, health tiles.
SSE live mode. Overview control plane.

### Phase 2 — Ops depth (C, E, H, J, K, I27, D18) — ✅ SHIPPED
Context Health; Approvals queue + analytics; latency percentiles; Prompt Registry (needs
`prompt_id` receipt field — the one small engine change, additive + optional);
kill switch; SPC alert engine + SLO panel; verification-failure (hallucination-proxy) rate.
> Implementation notes: live wiring proxies the engine dashboard (`CRUSORAI_OPS_ENGINE_URL`):
> approvals mirrored over its SSE, decisions forwarded to its fail-closed `/api/approve`,
> context status proxied on demand. Demo mode journals `context_status` + approval rows and
> honors operator decisions/kill-switch via sidecar files. Engine `prompt_id` emission remains
> the single open additive gap (registry + per-turn attribution UI already in place).

### Phase 3 — Evals, learning, multi-agent (F, G, L, I28, K34)
Evals index + regression board + A/B compare; Learning explorer; sub-agent tree;
drift metrics; injection-suspicion flags; compliance export.

### MVP acceptance gate
- [ ] All Phase-1 views render real data from S1/S2/S5/S6 with **zero** engine changes.
- [ ] Agent turn never blocked/corrupted by dashboard activity (read-only handles; failures swallowed).
- [ ] Replay: pick any journaled session → step through its events with timestamps.
- [ ] Cost math verified against receipts: Σ buckets × price table = displayed totals.
- [ ] CrusorAI logo + chrome dark theme in header/favicon; zero "PulseAI" strings in new UI.
- [ ] Auth enforced off-loopback; `agentops/` builds and runs standalone (`README` one-liner).

## 7. Open questions (non-blocking)
1. Hosted/team deployment later? (Design stays local-first, auth-ready.)
2. Retention/rotation policy for journal & receipts (P2).
3. Price table defaults per provider/model — confirm preferred currency/granularity.
