# CrusorAI AgentOps

**AgentOps website dashboard for the CrusorAI agent.** One self-contained folder:
FastAPI ops backend + Vite/React website, chrome-on-black branding from
`branding/crusorai-logo.png`. Built on the AgentOps framework of
`docs/references/LLMOps-AgentOps-MLOps-GenAI-Review-IJCATR1407.pdf`
(monitoring · debugging · automation · security) and the plan in
`docs/CRUSORAI_AGENTOPS_PLAN.md`.

The dashboard is a **read-only observer** of the agent's existing sinks:

| Sink | Path (default) | Reads |
|---|---|---|
| Durable event journal (SQLite WAL) | `~/.pulseai/runtime_events.db` | sessions, time-travel traces, tool intent→result, audit trail |
| Turn receipts (JSONL) | `~/.pulseai/observability/turns.jsonl` | tokens, cost (Σ tokens × cost/token), latency, completion, errors |

Journal is opened `mode=ro`; receipts are parsed debris-tolerantly. **The dashboard can
never block or corrupt an agent turn.**

## Quick start — demo mode (no agent needed)

```bash
cd agentops
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # once
cd web && npm install && npm run build && cd ..                      # once

.venv/bin/python scripts/seed_demo.py                                # seed .demo-data/
CRUSORAI_OPS_DATA_DIR=$PWD/.demo-data CRUSORAI_OPS_DEMO=on \
CRUSORAI_OPS_HOST=0.0.0.0 CRUSORAI_OPS_PORT=8300 .venv/bin/python -m backend.app
# optional: .venv/bin/python scripts/sim_live.py   (streams live events into the demo journal)
```

Open `http://localhost:8300` — the UI shows a **DEMO DATA** chip while demo sinks are attached.

## Quick start — live mode (real agent)

Enable the engine's observability sink and point at the real data root (the default):

```bash
export PULSEAI_OBSERVABILITY=on        # engine side: writes turn receipts
.venv/bin/python -m backend.app        # CRUSORAI_OPS_DATA_DIR defaults to ~/.pulseai
```

## Development (hot reload)

```bash
cd web && npm run dev                  # vite :5180, proxies /api → :8300
```

## Environment

| Var | Default | Purpose |
|---|---|---|
| `CRUSORAI_OPS_DATA_DIR` | `~/.pulseai` | data root (journal + observability/) |
| `CRUSORAI_OPS_DEMO` | off | labels UI data source as DEMO |
| `CRUSORAI_OPS_TOKEN` | empty | bearer token for `/api/*` — **set for any non-loopback deployment** |
| `CRUSORAI_OPS_ALLOWED_ORIGINS` | vite dev origins | CORS allowlist |
| `CRUSORAI_OPS_HOST` / `CRUSORAI_OPS_PORT` | `127.0.0.1` / `8300` | bind address |
| `CRUSORAI_OPS_PRICES` | built-in table | JSON price table per 1M tokens: `{"model": [in, out, cache]}` |
| `CRUSORAI_OPS_ENGINE_URL` | empty | live proxy to the engine dashboard (e.g. `http://127.0.0.1:8080`): mirrors approvals over SSE, forwards decisions, proxies context status |
| `CRUSORAI_OPS_ENGINE_TOKEN` | empty | bearer token for the engine dashboard (`PULSEAI_DASHBOARD_TOKEN`) |
| `CRUSORAI_OPS_PROMPTS_DIR` | `<repo>/src/prompts` | prompt corpus root for the registry |

## Views (Phase 1 + Phase 2)

- **Overview** — orchestration control plane: KPI strip w/ deltas + sparklines, live SSE ticker,
  recent sessions, spend-by-day, latest failures, sink health.
- **Sessions** — filterable session table (status/mode/cost/tokens/workspace).
- **Session trace** — time-travel replay scrubber over the journaled timeline, tool intent→result
  drill-down with args/diffs, per-turn receipts, **⏹ kill switch** per session.
- **Context Health** — get_status() snapshots: window gauge + pressure, compaction & prompt-cache
  counters, layer-breakdown bars, usage history; live proxy of the engine's
  `/api/context/status` when `CRUSORAI_OPS_ENGINE_URL` is set.
- **Usage & Cost** — Σ tokens × cost/token aggregates by day/model/provider/mode/task/session,
  cache-hit economics, tool leaderboard, latency percentiles (p50/p95/p99), throughput buckets.
- **Approvals** — human-in-the-loop queue with approve/deny (fail-closed engine semantics
  preserved; live mode forwards to the engine `/api/approve`), decision history + deny/latency stats.
- **Errors & SLOs** — failed turns, latched runtime receipts, SLO panel vs case-study targets,
  **SPC control chart** (X̄ ± A₂R̄) flagging out-of-control spend days.
- **Settings** — data sources, auth posture, env reference, **prompt & policy registry**
  (corpus hash, per-file hashes, turns-by-prompt_id), about.

## Layout

```
agentops/
  backend/            FastAPI ops API (readers/ journal+receipts, api/ routes, pricing, config)
  web/                Vite + React website (views/, components/, chrome-on-black theme)
  scripts/            seed_demo.py, sim_live.py
  requirements.txt    fastapi, uvicorn
```

Roadmap (plan §6): **Phase 2 shipped** (context health, approvals + kill switch, prompt registry,
SPC/SLO alerts, latency percentiles/throughput) · Phase 3 = evals/A-B, learning explorer,
multi-agent tree, drift metrics, compliance export.
