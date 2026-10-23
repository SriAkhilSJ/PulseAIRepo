# Langfuse (self-hosted) for the Crusor agent

> **Status:** optional current diagnostics path, last reviewed 2026-10-23
> against `590fe542`. Traces monitor turns/nodes/model/tool calls; they are
> fail-open and do not authorize a release or replace verification evidence.

`docker-compose.yml` is the **official upstream Langfuse compose** (fetched from
`langfuse/langfuse@main`), unmodified. It runs the full stack locally:
langfuse-web + worker, postgres, clickhouse, redis, minio. Nothing leaves
your machine (the hermes no-upload contract).

## 1. Start it

```bash
cd langfuse
docker compose up -d
# → UI on http://localhost:3000  (first boot: ~1–2 min; create your org/user)
```

For local-only use you may also set `TELEMETRY_ENABLED=false` in the env.

## 2. Create an API key

Langfuse UI → **Settings → API Keys** → create a project key
(`pk-lf-...` public + `sk-lf-...` secret).

## 3. Point the agent at it

```bash
export CRUSORAI_OTEL=on
export CRUSORAI_LANGFUSE_PUBLIC_KEY=pk-lf-...
export CRUSORAI_LANGFUSE_SECRET_KEY=sk-lf-...
# CRUSORAI_OTEL_ENDPOINT defaults to http://127.0.0.1:3000/api/public/otel/v1/traces
```

(or use the `run_crusor_full_stack.bat` / `.ps1` launchers, which set these).

## 4. Watch it

Open http://localhost:3000 → **Tracing**: each agent turn is one trace —

```
turn {session}                     ← root (session.id)
  node.task_manager / planner / ai / finish_gate ...   ← one per graph node
    llm {model}                     ← gen_ai.* attributes + token usage
    tool {name}                     ← execute_tool, redacted args, status
```

Sessions group turns; the dashboards give you cost/latency per model — the
four pillars (success, cost, latency, safety) as native views.

## Why OTel

Spans use OpenTelemetry GenAI semantic conventions. Langfuse is the default
backend, but the same spans can be exported to Phoenix, Grafana Tempo, or any
OTLP endpoint by changing `CRUSORAI_OTEL_ENDPOINT` — no code change.
