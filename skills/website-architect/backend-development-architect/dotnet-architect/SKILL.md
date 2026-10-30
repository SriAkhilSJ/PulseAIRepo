---
name: dotnet-architect
description: Architect-level .NET guidance — solution and namespace layering, DI lifetimes and their bugs, async/await discipline, EF Core usage boundaries, and the hosting, configuration and observability shape of an ASP.NET service. Use when designing or reviewing a .NET backend.
license: MIT
compatibility: .NET 8/9; ASP.NET Core; EF Core
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/backend-development-architect/dotnet-architect
  crusor-origin: original
  crusor-sources: "learn.microsoft.com/aspnet/core; learn.microsoft.com/ef/core; learn.microsoft.com/dotnet/standard/asynchronous-patterns"
  crusor-triggers: "dotnet, .net, csharp, asp net core, ef core, dependency injection lifetimes, minimal api"
  crusor-verified-on: "2026-10-30"
---

# .NET Architect

.NET gives you **a container, a lifetime model and an async runtime**. Nearly
every subtle production bug is a lifetime mistake or a blocked thread.

## When to use

- Enterprise services, Windows/Linux mixed estates, Azure-first deployments.
- Strong typing, mature tooling and long support windows matter.
- Existing .NET code or team expertise.

## When NOT to use

- Tiny services where a Go binary or a Node function is simpler and cheaper.

## Decision 1 — Solution structure

```
src/Api/            controllers/minimal endpoints, composition root
  Application/      use-cases; interfaces only
    Domain/         entities, rules, no EF/framework types
      Infrastructure/ EF Core, external clients
tests/              per layer
```

- Dependencies point inward; Domain references nothing.
- One composition root (`Program.cs`) wires everything.
- `internal` by default; public surface is a contract.

## Decision 2 — DI lifetimes (the classic bug)

| Lifetime | Use | Danger |
|---|---|---|
| Singleton | stateless services, caches | capturing scoped services |
| Scoped | per-request: DbContext, unit of work | never in a singleton |
| Transient | lightweight, stateless | pooling pressure |

- A singleton holding a `DbContext` is a correctness bug, not a performance tweak.
- Validate scopes enabled in development (`ValidateScopes = true`) so misuse
  fails at startup.
- `IHttpClientFactory` for outbound HTTP; never `new HttpClient()` per request.

## Decision 3 — Async discipline

- `async` all the way; never `.Result` or `.Wait()` in request paths (deadlocks
  and thread starvation).
- `CancellationToken` threaded through every call that touches I/O.
- `Task.WhenAll` for independent work; sequential awaits for dependent work.
- Background work: `BackgroundService`/queue — not a fire-and-forget task inside
  a request.

## Decision 4 — EF Core boundaries

- Queries in a repository/handler layer; `AsNoTracking()` for reads.
- Projection (`Select`) instead of loading graphs you discard.
- N+1: `Include` deliberately, or project; measure query counts in tests.
- Migrations are explicit and reviewed; `EnsureCreated` is for tests only.
- Keep `DbContext` short-lived (per request/scope); no long-lived caching of
  entities.

## Decision 5 — Hosting and operations

- Configuration: `appsettings` + environment + secret store; validated options.
- Health checks split liveness/readiness; graceful shutdown drains requests.
- Structured logging (`ILogger` scopes with correlation id) and OpenTelemetry.
- Container images: multi-stage build, non-root, no SDK in the runtime image.

## Failure modes at scale

- Singleton capturing `DbContext` → concurrent use exception under load.
- `.Result` in an async controller → thread-pool starvation at peak.
- EF queries without projection → 3 MB payloads per request.
- Migrations applied by every instance at boot → race on startup.
- Secrets in `appsettings.json` committed.

## Verification receipts

1. Lifetime audit: no scoped service captured by a singleton; scope validation on.
2. Query-count test on the busiest endpoint (no N+1).
3. Cancellation test: client abort stops downstream work.
4. Migration applied as a deploy step, once.
5. Health-check behaviour with a dependency down.
