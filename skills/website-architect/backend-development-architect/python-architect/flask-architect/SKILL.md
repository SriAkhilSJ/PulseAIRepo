---
name: flask-architect
description: Architect-level Flask guidance — app factory and blueprint boundaries, WSGI and sync concurrency model, extension configuration, request/application context discipline, error handlers, and when Flask is the right choice over FastAPI or Django. Use when designing or reviewing a Flask service.
license: MIT
compatibility: Flask 3.x, WSGI (gunicorn/uWSGI)
metadata:
  crusor-domain: website-architect
  crusor-path: website-architect/backend-development-architect/python-architect/flask-architect
  crusor-origin: original
  crusor-sources: "flask.palletsprojects.com; wsgi.readthedocs.io"
  crusor-triggers: "flask, wsgi, blueprints, app factory, jinja, gunicorn"
  crusor-verified-on: "2026-10-30"
---

# Flask Architect

Flask is a **library, not a platform**: it gives you routing and a request cycle,
and you decide everything else. Architecture here is mostly about what you refuse
to put in the app.

## When to use

- Small/medium service or internal API with explicit control over the stack.
- Server-rendered pages with Jinja and light interactivity.
- A WSGI deployment that must stay simple (no async requirement).
- Prototypes that will grow — provided the factory/blueprint discipline below is
  in place from day one.

## When NOT to use

- Many concurrent I/O waits (see `fastapi-architect`; Flask's sync model bounds
  you to worker processes).
- A product with admin, auth, and a large ORM surface (see `django-architect`).
- OpenAPI-first contract delivery — FastAPI makes that native.

## Decision 1 — App factory + blueprints

```python
def create_app(config: Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config)
    app.register_blueprint(api_v1, url_prefix="/v1")
    return app
```

- **No module-level `app`.** The factory is what makes tests, workers and
  multiple configs possible.
- One blueprint per bounded context (`auth`, `orders`, `billing`), not per file.
- Extensions initialised in the factory, bound to `app.extensions`, never as
  import-time singletons.
- Config is an object with typed fields; secrets come from the environment.

## Decision 2 — Layering inside a WSGI app

```
wsgi.py            create_app()
  blueprints/      routes: parse, validate, status codes
    services/      use-cases (no flask imports)
      repositories/ DB access
        models/    SQLAlchemy or plain dataclasses
```

- A service function never imports `request`, `g`, or `current_app`.
- Validation happens at the blueprint edge; services take typed arguments.
- `g` is per-request scratch space, not a container for business objects.

## Decision 3 — Contexts and error handling

- Application context for startup resources; request context for request data.
  Do not stash request state on the app object.
- One `register_error_handler` per error class; return the same envelope shape
  everywhere.
- 404/405/500 handled explicitly — a default HTML traceback is a security leak.
- Teardown hooks close sessions/connections deterministically.

## Decision 4 — Concurrency and deployment

- WSGI = one request per worker at a time. Scale with worker **processes**.
- Blocking external calls need timeouts; without them a slow upstream consumes
  the worker.
- Shared state (rate limits, caches) belongs outside the process; memory dies
  with the worker and is not shared.
- Behind a proxy: trust exactly one hop of `X-Forwarded-*`
  (`ProxyFix`), and set secure cookie flags.

## Failure modes at scale

- Module-level `app` + import-time extension init → can't test, can't scale.
- Business logic inside view functions → duplicated across blueprints.
- `app.config` used as a global registry for runtime state.
- One worker configuration for CPU-bound and I/O-bound paths.
- Sessions/cookies used as a data store.

## Verification receipts

1. App created twice in one process (tests) without shared state.
2. Error handlers verified for 400/404/405/500 with a consistent envelope.
3. Load test at expected concurrency: worker saturation and queue time visible.
4. Teardown test: connections closed, no leaked sessions.
5. Config audit: no secret in code, debug off in production.
