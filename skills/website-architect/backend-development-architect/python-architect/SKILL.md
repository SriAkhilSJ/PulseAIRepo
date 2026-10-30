---
name: python-architect
description: Architect-level Python guidance — project and package layout, typing discipline, sync vs async runtime choice, tooling (uv/ruff/mypy/pytest), dependency and boundary rules, and how to pick the framework leaf (flask-architect, fastapi-architect, django-architect). Use first for any Python service, then the framework skill it names.
license: MIT
compatibility: Python 3.11+; uv or pip; ruff + mypy/pyright
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/backend-development-architect/python-architect
  crusor-origin: original
  crusor-sources: "docs.python.org/3; packaging.python.org; docs.astral.sh/uv; docs.pytest.org"
  crusor-triggers: "python, pyproject, uv, ruff, mypy, pytest, asyncio, project layout"
  crusor-verified-on: "2026-10-30"
---

# Python Architect (language entry point)

This skill decides the shape of a Python codebase and names the framework leaf.

## Leaf map

| Need | Skill |
|---|---|
| small/medium HTTP API, sync, explicit control | `flask-architect` |
| async API, typed contracts, OpenAPI-first | `fastapi-architect` |
| product app with ORM, admin, auth built in | `django-architect` |

If the task is a script or data job with no HTTP surface, none of the three
applies — stay here and use the layout/tooling rules below.

## Decision 1 — Project layout

```
pyproject.toml
src/<package>/
  __init__.py          # public surface only
  domain/              # pure rules, no framework imports
  services/            # use-cases; orchestration
  adapters/            # HTTP, DB, queue, third-party
tests/
  unit/  integration/  e2e/
```

- `src/` layout so imports require installation (catches packaging bugs early).
- Framework types never cross into `domain/`; that is what makes tests fast.
- One public API per package (`__init__.py` re-exports), internals private.

## Decision 2 — Sync or async (decide once)

| Workload | Runtime |
|---|---|
| CPU-bound, batch, scripts | sync, processes for parallelism |
| many concurrent I/O waits | async (`asyncio`) |
| mixed | async at the edge, `run_in_executor`/threads for blocking calls |

Mixing is the failure mode: **one blocking call inside an async service stalls
every request**. Pick a model and enforce it with lint/review.

## Decision 3 — Typing

- Public functions have annotated signatures; internals may infer.
- `Protocol` over inheritance for adapters; `TypedDict`/dataclasses for payloads.
- `Any` only at a parse boundary, immediately narrowed.
- Run mypy/pyright in CI; strictness increases per package, never decreases.

## Decision 4 — Tooling floor

- `pyproject.toml` is the single source of deps + tool config.
- `uv` (or pip-tools) with a lockfile; no unpinned ranges in production.
- `ruff` for lint+format; `pytest` with markers for integration.
- Pre-commit runs ruff, type-check, unit tests — not the slow suite.

## Decision 5 — Error and resource contracts

- Domain errors are typed exceptions; adapters translate them to HTTP/queue
  responses in one place.
- Context managers for every resource (files, sessions, connections, locks).
- Timeouts on every network call; retries only on idempotent operations.
- No bare `except`; no swallowing without a stated recovery.

## Failure modes at scale

- Framework objects leaked into domain code → untestable business rules.
- One `utils.py` that everything imports → hidden coupling, import cycles.
- Async endpoint calling a sync DB driver → event loop starvation under load.
- Unpinned dependencies; the build works today and not next month.

## Verification receipts

1. `ruff check`, `mypy`/`pyright`, `pytest -m "not integration"` all green in CI.
2. Import-graph check: `domain/` imports no framework.
3. Lockfile committed and reproducible in a clean environment.
4. A dependency-down test: timeout path returns a typed error, not a hang.
