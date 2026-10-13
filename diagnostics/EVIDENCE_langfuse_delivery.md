# Evidence: Langfuse Cloud delivery (`t5-e16ea0e4f4`)

End-to-end OTLP path verified live via `GET /api/public/v2/observations`
(Basic auth, project keys from `.env`):

- **100 observations** in the last 6h window (paginated; more exist).
- **Session `t5-e16ea0e4f4`** (Lena portfolio turn) present with full tree:
  node spans (`node ai`, `node progress`), generations
  (`llm z-ai/glm-5.3-flash` ×25, `llm qwen/qwen3.7-flash` ×1 aux),
  tool spans (`browser_console`, `read_file`, `search_files`, …).
- Path: engine `otel_tracing` → OTLP/HTTP →
  `https://cloud.langfuse.com/api/public/otel/v1/traces` → queryable.
- Note: legacy v1 traces API returns `410 LEGACY_API_UNAVAILABLE` for new
  orgs — v2 observations API is the correct read path.

So the Cloud wiring (`CRUSORAI_OTEL=on` + endpoint + keys) delivers, and
every future turn lands in the Langfuse UI automatically.
