---
name: django-architect
description: Architect-level Django guidance — app boundaries and project layout, ORM and migration discipline, settings/environment split, auth and permissions, DRF API layering, admin as an internal surface, and the queries that make Django slow. Use when designing or reviewing a Django/DRF product.
license: MIT
compatibility: Django 4.2/5.x, Django REST Framework, PostgreSQL
metadata:
  crusor-domain: website-architect
  crusor-path: backend-development-architect/python-architect/django-architect
  crusor-origin: original
  crusor-sources: "docs.djangoproject.com; www.django-rest-framework.org"
  crusor-triggers: "django, drf, django orm, django migration, django admin, django-rest-framework"
  crusor-verified-on: "2026-10-30"
---

# Django Architect

Django is a **product framework**: it ships the ORM, auth, admin and migrations.
Architecture is about respecting its grain — apps as boundaries, the ORM as the
only data path — rather than fighting it.

## When to use

- Product web app with users, auth, admin and a relational core.
- Content/catalog/CRM-style domains where CRUD is the bulk of the work.
- A team that benefits from convention over assembly.

## When NOT to use

- A small service or single-purpose API (see `flask-architect`,
  `fastapi-architect`).
- Async-heavy or realtime-first workloads — Django works, but the async story is
  secondary.
- A polyglot microservice where the ORM's coupling is unwanted.

## Decision 1 — Apps as bounded contexts

```
project/            settings, urls, asgi/wsgi
  apps/<context>/   models, services, api, admin, migrations
    services/       use-cases; transactions live here
      selectors/    read queries (query objects)
```

- One app per business context, not per technical layer.
- Cross-app imports go through a service/selector, never into another app's
  models.
- `core`/`common` stays tiny; a big shared app is coupling with a nicer name.

## Decision 2 — ORM discipline

- Views/serializers do not build complex queries; selectors do, and they are
  tested.
- `select_related`/`prefetch_related` are part of the design, not an optimisation
  pass — N+1 is the default failure.
- Write paths use `transaction.atomic()` in the service, not the view.
- No raw SQL without a documented reason and a parameterised query.
- Model `save()` stays dumb; side effects belong to services/signals you can see.

## Decision 3 — Migrations

- Every schema change is a migration, reviewed like code.
- Data migrations separate from schema migrations.
- Backwards-compatible sequence for zero-downtime: add → backfill → switch →
  remove (never rename in place on a live table).
- `makemigrations --check` in CI so drift cannot merge.

## Decision 4 — Settings and environments

- `settings/base.py` + `dev.py` + `prod.py`; environment-specific values from env
  vars (`django-environ`/`pydantic-settings`).
- `DEBUG=False` by default; a missing secret must fail at boot, not fall back.
- `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, secure cookies and HSTS set explicitly
  in production.
- Static/media served by the proxy/object store, never by Django in production.

## Decision 5 — API layer (DRF)

- Serializers validate input and shape output; they are not business logic.
- ViewSets only for genuinely resourceful endpoints; explicit APIViews for
  actions with rules.
- Permissions are declared per view and tested; object-level checks in the
  service or permission class.
- Pagination, filtering and ordering are global defaults, not per-view
  reinvention.
- Throttling at the edge; heavy exports/imports go to background jobs.

## Decision 6 — Admin and auth

- Admin is an internal operational surface: restrict by staff, audit actions,
  never expose it as the customer UI.
- Custom user model from day one (`AUTH_USER_MODEL`) — retrofitting it is a
  migration project.
- Session vs token auth chosen per surface; API tokens scoped and revocable.

## Failure modes at scale

- Fat views + fat serializers; no service layer, rules duplicated.
- N+1 in list endpoints discovered only in production.
- Migrations locked in a deploy; long transactions blocking the table.
- Signals causing hidden writes that nobody can trace.
- Settings drift between environments; prod is the only place it breaks.

## Verification receipts

1. `manage.py check --deploy` clean; `makemigrations --check` in CI.
2. Query-count test on the hottest list endpoint (`assertNumQueries`).
3. Permission matrix tests per endpoint (owner / other user / staff / anon).
4. Migration plan reviewed for a live table change (expand/contract).
5. Load test on the two heaviest read and write paths.
