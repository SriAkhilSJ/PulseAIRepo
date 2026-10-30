---
name: event-schema-architect
description: Architect-level event schema design — event naming and payload shape, schema registry and compatibility modes, versioning and deprecation, ownership across producers and consumers, and the contract tests that stop a producer from breaking a consumer silently. Use when many systems exchange events.
license: MIT
compatibility: Avro/Protobuf/JSON Schema, Confluent Schema Registry, Buf
metadata:
  crusor-domain: data-engineering-architect
  crusor-path: data-engineering-architect/event-streams-architect/event-schema-architect
  crusor-origin: original
  crusor-sources: "docs.confluent.io/platform/current/schema-registry/fundamentals; buf.build/docs; cloudevents.io"
  crusor-triggers: "event schema, schema registry, avro, protobuf, compatibility mode, event versioning, cloudevents, contract test, event contract"
  crusor-verified-on: "2026-10-30"
---

# Event Schema Architect

An event schema is **a public API with an audience you cannot enumerate**. Treat
every field as if a stranger depends on it — usually one does.

## When to use

- Multiple producers and consumers exchange events.
- Schema changes have broken consumers.
- Designing an event-driven integration between teams.

## When NOT to use

- A single internal topic with one consumer in the same deploy.
- Request/response APIs — that is an API contract, not an event.

## Decision 1 — Event shape

- Name in the past tense: `OrderPlaced`, `InvoicePaid` — events are facts.
- Envelope: id, type, version, occurred_at, producer, trace/correlation id, key.
- Payload: only what the event means, plus ids consumers need to fetch more.
- Never put a full mutable entity dump in an event; consumers will depend on fields
  that change for unrelated reasons.

## Decision 2 — Registry and compatibility

| Mode | Allows |
|---|---|
| backward | consumers on new schema read old data |
| forward | old consumers read new data (new fields optional) |
| full | both |
| none | chaos |

- Backward-compatible by default for data topics; full for shared/platform topics.
- Additive optional fields with defaults are safe; removing, renaming, or changing
  types is not.
- Schema ids travel with the payload; consumers must resolve by id, not by guessing.

## Decision 3 — Versioning

- A major version (`v2` field or topic suffix) for breaking changes, with both live
  during migration.
- Deprecate fields explicitly with a date and a consumer list; silent removal is an
  outage scheduled for later.
- Document the "blueprint": event name, fields, meaning, owner, retention.
- Keep a compatibility test in CI that fails on a breaking change.

## Decision 4 — Ownership

- One producer owns the schema; consumers register their interest.
- A schema change requires: compatibility check, consumer test, migration plan for
  breaking changes.
- Platform teams own the registry and compatibility policy, not the event semantics.

## Decision 5 — Contract tests

- Producer side: validate the serialised event against the registered schema.
- Consumer side: run the consumer against a recorded sample of real events (new and
  old) in CI.
- Replay a month-old sample after a schema change — that is the test that catches
  reality.

## Failure modes at scale

- Field renamed with the same type; consumers silently get nulls.
- Registry in `none` mode; a breaking change merged on a Friday.
- Enum added without a default; old consumers crash on unknown value.
- Events carrying full entity snapshots; every producer change ripples.
- No contract test; discovery happens in production at 3 a.m.

## Verification receipts

1. Event catalogue with name, envelope, owner, version.
2. Registry compatibility mode configured per subject.
3. CI check rejecting a deliberately breaking schema change.
4. Consumer replay test against a month-old event sample.
5. Deprecation record with dates and affected consumers.
