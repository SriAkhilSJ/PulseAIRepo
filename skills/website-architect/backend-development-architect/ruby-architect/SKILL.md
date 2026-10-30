---
name: ruby-architect
description: Architect-level Ruby guidance — application layering beyond fat models and controllers, service and query object boundaries, ActiveRecord usage limits, background job and connection-pool discipline, and the concurrency reality of a Ruby service. Use when designing or reviewing a Ruby (Rails or Rack) backend.
license: MIT
compatibility: Ruby 3.2+; Rails 7/8 or Sinatra/Rack
metadata:
  crusor-domain: website-architect
  crusor-path: backend-development-architect/ruby-architect
  crusor-origin: original
  crusor-sources: "guides.rubyonrails.org; api.rubyonrails.org; shopify.github.io/ruby-style-guide"
  crusor-triggers: "ruby, rails, activerecord, sidekiq, rack, ruby on rails, service objects"
  crusor-verified-on: "2026-10-30"
---

# Ruby Architect

Ruby's flexibility is the risk: without explicit boundaries, business logic
dissolves into models, controllers and callbacks.

## When to use

- Rails product development, internal tools, API backends.
- Existing Ruby codebase whose models have 900 lines.

## When NOT to use

- CPU-bound services or high-concurrency fan-out (Ruby's thread model and GVL
  make other runtimes cheaper).
- Edge/serverless workloads with cold-start constraints.

## Decision 1 — Layering

```
app/controllers/    params, auth, response codes
  app/services/     use-cases, transactions
    app/queries/    read paths (query objects)
      app/models/   persistence + small domain behaviour
```

- A service object takes plain arguments, returns a result, raises typed errors.
- Controllers never contain business rules; models never call external APIs.
- Callbacks are for persistence invariants only — anything else is a hidden
  action that will surprise someone.
- `concerns/` only for genuinely shared behaviour; it is the most common hiding
  place for coupling.

## Decision 2 — ActiveRecord discipline

- Scopes for reusable filters; never build queries in views or controllers.
- Eager-load (`includes`/`preload`) deliberately; N+1 is the default failure.
- Keep transactions in services, short; no HTTP calls inside them.
- `find_by` with explicit nil handling; avoid `rescue nil` and `try` chains that
  hide state.
- Migrations reversible or explicitly forward-only; no data logic in schema
  migrations.

## Decision 3 — Concurrency and runtime

- Puma workers × threads sized to the DB pool — the pool is the real limit.
- Assume the GVL: CPU-heavy work belongs in a job or a separate process.
- Background jobs (Sidekiq) are idempotent and safe to retry; no job depends on
  a transient in-memory state.
- Timeouts: DB statement timeout, HTTP client timeouts, job timeout.
- Memory bloat: monitor RSS; long-running processes need restart policies.

## Decision 4 — Testing and quality

- Request specs for boundaries, model/unit specs for rules; avoid testing Rails
  itself.
- Factories produce the minimum valid object; no shared mutable global state.
- RuboCop for style, `brakeman` for security, `bundler-audit` for dependencies,
  all in CI.

## Failure modes at scale

- N+1 queries discovered in production on the busiest page.
- A callback that sends email inside a transaction.
- Job retries creating duplicate side effects.
- Threads > DB pool → connection timeouts under load.
- A 1,500-line model with 40 public methods used nowhere else.

## Verification receipts

1. Query count per endpoint (no N+1) in request specs.
2. Transaction duration on the busiest write path.
3. Puma threads vs pool size documented and load-tested.
4. Job idempotency test: run twice, one effect.
5. Brakeman + bundler-audit clean in CI.
