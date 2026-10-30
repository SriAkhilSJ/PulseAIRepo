---
name: go-architect
description: Architect-level Go guidance — package and module boundaries, interface ownership, goroutine and context discipline, error wrapping contracts, and the concurrency and deployment shape of a Go service. Use when designing or reviewing a Go backend or CLI.
license: MIT
compatibility: Go 1.22+
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/backend-development-architect/go-architect
  crusor-origin: original
  crusor-sources: "go.dev/doc/effective_go; go.dev/blog/context; go.dev/doc/faq"
  crusor-triggers: "go, golang, goroutines, channels, context cancellation, go modules, gin, echo"
  crusor-verified-on: "2026-10-30"
---

# Go Architect

Go makes **concurrency and dependencies explicit**. Architecture is mostly about
not hiding either behind a package that everyone imports.

## When to use

- Services with high concurrency, small binaries, or predictable latency.
- Network infrastructure, CLIs, and sidecars.
- Replacing a runtime where GC pauses or memory footprint matter.

## When NOT to use

- Teams without Go fluency: error handling and cancellation are explicit by
  design, and that discipline is the language.
- CRUD-heavy products where framework conventions save more than they cost.

## Decision 1 — Package boundaries

```
cmd/<binary>/main.go    wiring only, no logic
internal/<domain>/      business rules, exported surface minimal
internal/<adapter>/     http, db, queue
pkg/                    only if genuinely reusable outside the module
```

- `internal/` by default; `pkg/` is a promise to the outside world.
- Import direction is one-way: adapter → domain, never the reverse.
- Interfaces are declared by the **consumer**, small (1–3 methods), next to use.
- A package name describes what it provides, not what it contains (`billing`,
  not `utils`).

## Decision 2 — Concurrency

- Every goroutine has an owner and a way to stop; `context.Context` is the first
  parameter of anything that can block.
- Never start a goroutine from a request handler without bounding it
  (`errgroup`, worker pool).
- Channels for ownership transfer, mutexes for state; buffered channels only
  with a measured reason.
- Propagate cancellation; a cancelled context must abort downstream calls.
- `-race` in CI on the concurrency tests, always.

## Decision 3 — Errors

- Errors are values: wrap with `%w` and context (`fmt.Errorf("load order %s: %w", id, err)`).
- Sentinel/typed errors for control flow (`errors.Is`/`errors.As`), strings for
  humans.
- One place per boundary maps domain errors to HTTP/gRPC status.
- Never `panic` in library code; recover only at a goroutine boundary you own.

## Decision 4 — Runtime and deployment

- Stateless processes; graceful shutdown on `SIGTERM` with `http.Server.Shutdown`.
- Timeouts on the server, the client, and the DB pool; defaults are infinite.
- Connection pools sized to the dependency, not to `GOMAXPROCS`.
- Metrics and structured logs (`slog`) from the start; pprof endpoints never
  public.

## Failure modes at scale

- Goroutine leak per request (a fire-and-forget that never exits).
- A giant `utils` package that every layer imports.
- Context ignored in a DB call → requests that outlive their deadline.
- Interface declared by the producer with 12 methods, so nothing can be faked in
  tests.
- Memory growth from slices retained by long-lived caches.

## Verification receipts

1. `go build ./...`, `go vet`, `go test -race ./...` clean.
2. Goroutine count stable under load (leak check).
3. Cancellation test: client disconnect aborts downstream work.
4. Import graph reviewed: no cycles, no domain → adapter imports.
5. Graceful shutdown under load within the deadline.
