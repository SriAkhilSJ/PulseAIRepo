---
name: grpc-architect
description: Architect-level gRPC guidance — proto as the service contract, message evolution and compatibility rules, streaming mode selection, deadlines and retries, and the operational reality of running gRPC between services or to browsers. Use when designing service-to-service APIs.
license: MIT
compatibility: gRPC (HTTP/2), protobuf 3; grpc-web for browsers
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/api-development-architect/grpc-architect
  crusor-origin: original
  crusor-sources: "grpc.io/docs; protobuf.dev/programming-guides/proto3; grpc.io/docs/guides/deadlines"
  crusor-triggers: "grpc, protobuf, proto3, streaming, grpc-web, service mesh, rpc"
  crusor-verified-on: "2026-10-30"
---

# gRPC Architect

gRPC is **typed contracts plus streaming over HTTP/2**. It is excellent between
services you control and awkward everywhere else.

## When to use

- Service-to-service calls with strict contracts and generated clients.
- Low-latency, high-volume internal traffic.
- Streaming (server, client, bidirectional) or binary payloads.

## When NOT to use

- Public APIs consumed by arbitrary clients (use REST).
- Browser-first consumers, unless you accept grpc-web proxying.
- Small systems where a JSON API and one HTTP client suffice.

## Decision 1 — Proto is the contract

- `.proto` files are versioned, reviewed, and owned by the service that serves
  them.
- Package naming: `company.service.v1` — the version lives in the package, not
  the method name.
- One service per bounded context; RPCs are verbs on that service.
- Generate both server stubs and clients in CI; hand-written clients defeat the
  purpose.

## Decision 2 — Evolution rules

| Change | Compatibility |
|---|---|
| add field (new number) | safe |
| add optional message field | safe |
| rename field | safe on the wire, breaks generated code — keep the number |
| change type | **breaking** |
| reuse a deleted field number | **breaking** |
| remove RPC | breaking — reserve and deprecate |

- Never reuse or renumber tags; `reserved` them when removing.
- Unknown fields must be preserved and ignored, not rejected.
- Breaking changes ship as `v2` in a new package.

## Decision 3 — Streaming modes

| Mode | Use |
|---|---|
| unary | request/response, the default |
| server streaming | feeds, logs, large results |
| client streaming | uploads, batching |
| bidirectional | realtime, interactive sessions |

- Streaming is not a substitute for queues: no delivery guarantees, no replay.
- Every stream has a deadline on the client and a cancel path on the server.
- Backpressure: the server must respect flow control, not buffer unboundedly.

## Decision 4 — Failure semantics

- Deadlines are mandatory; a gRPC call without one can hang forever.
- Retries only for idempotent calls, with backoff and a retry budget; servers
  implement idempotency where they accept retries.
- Status codes carry meaning: `INVALID_ARGUMENT`, `NOT_FOUND`,
  `PERMISSION_DENIED`, `UNAVAILABLE`, `DEADLINE_EXCEEDED`.
- Error details (`google.rpc.Status`) instead of string-only errors.

## Decision 5 — Operations

- Load balancing: L7/mesh (not naive client-side round-robin over long-lived
  connections).
- mTLS or token-based auth between services; identity in metadata.
- Reflection off in production; health checking via the standard service.
- Browsers: grpc-web through a proxy (Envoy), with CORS and auth handled there.

## Failure modes at scale

- Tag numbers reused after a field deletion → silent data corruption.
- No deadlines → thread pool exhaustion under a slow dependency.
- Long-lived streams pinned to one backend, defeating load balancing.
- Proto contracts drifting from the served implementation (stale generated code).
- Retries without idempotency → duplicate writes.

## Verification receipts

1. Compatibility check (`buf breaking`) in CI.
2. Deadline + retry test against a slow dependency.
3. Streaming test with a slow consumer (backpressure honoured).
4. Auth test between services (unauthenticated call rejected).
5. Generated-code freshness check in the build.
