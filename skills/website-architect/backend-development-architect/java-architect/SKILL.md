---
name: java-architect
description: Architect-level Java guidance — module and package layering, DI container discipline, JVM memory and thread-pool sizing, exception and transactional boundaries, and the build/runtime shape of a Java service. Use when designing or reviewing a Java backend.
license: MIT
compatibility: Java 21+ (LTS); Spring Boot / Quarkus / plain JVM
metadata:
  crusor-domain: website-architect
  crusor-path: backend-development-architect/java-architect
  crusor-origin: original
  crusor-sources: "docs.oracle.com/en/java; spring.io/guides; quarkus.io/guides"
  crusor-triggers: "java, jvm, spring, spring boot, maven, gradle, virtual threads, hibernate"
  crusor-verified-on: "2026-10-30"
---

# Java Architect

The JVM gives you **threads, memory and a long-lived process**. Most production
incidents are pool exhaustion, heap pressure, or a transaction held too long.

## When to use

- Enterprise integration, large teams, long-lived services.
- Strong typing, mature ecosystem, and observability tooling matter.
- Existing Java estate or JVM-dependent libraries.

## When NOT to use

- Tiny services where startup time and footprint dominate (see `go-architect`).
- Scripting and glue work.

## Decision 1 — Layering

```
web/ (controllers, DTOs)     request/response only
  service/ (use cases)       transactions, orchestration
    repository/ (persistence) entities, queries
      domain/ (model)        no framework annotations
```

- Framework annotations stay out of the domain model.
- DTOs at the boundary; entities never serialised directly to clients.
- Package-by-feature over package-by-layer once the codebase grows past a
  handful of domains.

## Decision 2 — Dependency injection

- Constructor injection only; no field injection (untestable, hides cycles).
- Singletons are the default and must be **stateless**; per-request state lives
  in a request-scoped bean or a method parameter.
- Configuration validated at startup (`@ConfigurationProperties` +
  validation), fail fast on missing values.
- Avoid a `@Component` in every class: clear boundaries beat annotation
  convenience.

## Decision 3 — Concurrency and pools

| Pool | Sizing rule |
|---|---|
| request threads | platform threads for blocking stacks; virtual threads for I/O fan-out (Java 21+) |
| DB connections | sized to the database, not to request concurrency |
| executors | bounded queue + rejection policy, never unbounded |

- Never block a virtual thread on a `synchronized` block held by another.
- Timeouts on every outbound call; a missing timeout is a thread leak.
- `CompletableFuture` chains need an explicit executor and exception handling.

## Decision 4 — Transactions and exceptions

- `@Transactional` at the service boundary, short, no remote calls inside.
- Checked exceptions for recoverable contract failures; runtime exceptions for
  programming errors; map both to API errors in one place.
- Never swallow exceptions; log once at the boundary that handles them.
- Optimistic locking for contended rows; retries at the right layer, not
  everywhere.

## Decision 5 — Build and runtime

- Reproducible builds with a wrapper (`./mvnw`, `./gradlew`) and a lock of
  plugin versions.
- Heap and container limits aligned (`-XX:MaxRAMPercentage`), not a hard-coded
  `-Xmx` from 2015.
- Graceful shutdown enabled; readiness reflects dependencies.
- JFR/actuator metrics available before you need them.

## Failure modes at scale

- Connection pool smaller than the request pool → requests queue silently.
- A `@Transactional` method calling an external API → locks held for seconds.
- Field-injected singletons with mutable state serving two tenants.
- Unbounded executor queues turning overload into OOM.
- Startup slower than the orchestrator's probe window → crash loop.

## Verification receipts

1. Pool sizes documented against DB limits and load-tested.
2. Transaction duration measured on the busiest write path.
3. Stateless-singleton audit (no mutable fields).
4. Startup time + readiness probe timing recorded.
5. Heap/GC behaviour under peak load (JFR or metrics).
