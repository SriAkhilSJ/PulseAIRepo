---
name: rust-architect
description: Architect-level Rust guidance — crate and module boundaries, ownership decisions that shape the design, async runtime and task discipline, error taxonomy with thiserror/anyhow, and the compile-time cost trade-offs of a Rust service. Use when designing or reviewing a Rust backend, CLI or service.
license: MIT
compatibility: Rust 2021+; tokio/axum or actix
metadata:
  crusor-domain: website-architect
  crusor-path: backend-development-architect/rust-architect
  crusor-origin: original
  crusor-sources: "doc.rust-lang.org/book; tokio.rs/tokio/tutorial; rust-lang.github.io/api-guidelines"
  crusor-triggers: "rust, cargo, tokio, axum, ownership, borrow checker, async rust, cli in rust"
  crusor-verified-on: "2026-10-30"
---

# Rust Architect

Rust makes **data ownership explicit at compile time**. Architecture here is
deciding who owns what before writing the type — the compiler enforces the
decision.

## When to use

- Latency-critical or resource-constrained services; edge, proxies, CLIs.
- Code where correctness under concurrency matters more than delivery speed.
- Replacing a component where GC pauses or memory safety are the risk.

## When NOT to use

- CRUD products with a small team and a deadline: the borrow checker is a real
  cost, and Go/TypeScript may deliver sooner.
- Prototyping, where iteration speed dominates.

## Decision 1 — Crate and module layout

```
src/main.rs        wiring, config, shutdown
src/lib.rs         public surface (testable without the binary)
  domain/          pure types and rules; no async, no I/O
  adapters/        http, db, queue
  application/     use-cases, orchestration
```

- Binary is thin; logic lives in the library so it can be tested and reused.
- Own types at boundaries; don't leak `sqlx::Row` or framework types into the
  domain.
- Prefer composition over trait-object soup; `dyn Trait` only where runtime
  polymorphism is genuinely required.
- Newtypes for IDs and units (`OrderId(Uuid)`), not bare primitives.

## Decision 2 — Async discipline

- One runtime; `tokio` unless the ecosystem forces otherwise.
- Never block in an async context: CPU work goes to `spawn_blocking`, long CPU
  to a separate task pool.
- `Clone` on handles (clients, pools) — share `Arc` only for genuinely shared
  mutable state.
- Every spawn has a supervisor: an error must not vanish into a detached task.
- Structured concurrency: join or cancel children; no orphan tasks on shutdown.

## Decision 3 — Errors

| Layer | Crate |
|---|---|
| library/domain | `thiserror` — typed, exhaustive |
| application/binary | `anyhow` — context-rich, opaque |

- Convert at boundaries; HTTP mapping in one place (`IntoResponse`).
- No `unwrap`/`expect` on input-derived values; `?` with context instead.
- Panics are for bugs; a `panic = "abort"` policy is a deliberate choice, not a
  default.

## Decision 4 — Performance reality

- Measure with `criterion`; don't optimise what the borrow checker already made
  fast.
- Allocation is the usual hotspot; reuse buffers, avoid `clone()` in loops.
- Compile time is a team cost: workspace splitting, `--release` profile tuning,
  and CI caching are architecture decisions.

## Failure modes at scale

- Blocking call inside an async handler stalling a worker thread.
- `Rc<RefCell<…>>` everywhere to dodge ownership — single-threaded design in a
  server.
- 40-minute clean builds because everything is one crate.
- `unwrap()` on network responses taking down the process.
- Trait objects for everything, losing the type safety you paid for.

## Verification receipts

1. `cargo clippy -- -D warnings` and `cargo test` clean.
2. Blocking-in-async audit (`spawn_blocking` used where needed).
3. Shutdown test: in-flight requests complete, tasks cancelled.
4. Panic audit: no `unwrap` on external input.
5. Build time recorded; CI cache effective.
