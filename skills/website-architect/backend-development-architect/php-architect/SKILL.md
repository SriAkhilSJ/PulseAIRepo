---
name: php-architect
description: Architect-level PHP guidance — framework and layering choices, request lifecycle and shared-nothing deployment, autoloading and dependency injection, database and session boundaries, and the operational reality of PHP-FPM. Use when designing or reviewing a PHP backend.
license: MIT
compatibility: PHP 8.2+; Laravel / Symfony / plain PSR-15
metadata:
  crusor-domain: website-architect
  crusor-path: backend-development-architect/php-architect
  crusor-origin: original
  crusor-sources: "php.net/manual; laravel.com/docs; symfony.com/doc/current; php-fig.org/psr"
  crusor-triggers: "php, laravel, symfony, php-fpm, composer, psr, eloquent, blade"
  crusor-verified-on: "2026-10-30"
---

# PHP Architect

PHP's defining property is **shared-nothing**: each request starts clean. That is
a strength — until someone reintroduces hidden global state.

## When to use

- Content platforms, e-commerce, internal apps with a PHP team.
- Laravel/Symfony projects needing boundaries beyond "everything in controllers".
- Migrating legacy PHP into a maintained structure.

## When NOT to use

- Long-running, stateful services (websockets, workers) — possible, but other
  runtimes fit better.

## Decision 1 — Structure

```
public/index.php     front controller, nothing else
  src/Http/          controllers, requests/validation
    src/Domain/      entities, value objects, rules
      src/Application/ services, use-cases
        src/Infrastructure/ repositories, external clients
```

- PSR-4 autoloading; one class per file; `composer` owns the autoloader.
- Framework code stays in `Http`/`Infrastructure`; the domain has no framework
  imports.
- Dependency injection via the container, constructor injection only; no service
  locators inside domain code.

## Decision 2 — Request lifecycle

| Concern | Rule |
|---|---|
| validation | at the edge (FormRequest/Validator), typed DTO inward |
| auth | middleware/guard; authorization policies per resource |
| sessions | server-side store, regenerated on login |
| output | escaped by default (Blade/Twig); raw output requires a sanitiser |
| errors | one handler → JSON envelope, never a stack trace |

- Shared-nothing means no static caches surviving a request — use the cache
  backend, not a static property.
- Config from environment, validated at boot; `env()` outside config files is a
  bug.

## Decision 3 — Data access

- Eloquent/Doctrine are fine in `Infrastructure`; the domain sees repository
  interfaces.
- Eager-load relations (`with()`), otherwise N+1 is guaranteed on list pages.
- Migrations versioned and reversible; no manual DDL in production.
- Transactions in services; no email/HTTP calls inside a transaction.

## Decision 4 — Runtime and operations

- PHP-FPM pool sized to CPU and DB connections; `pm.max_children` is the real
  concurrency limit.
- Opcache enabled in production; `preload` only after measuring.
- Queues (Horizon/Worker) for anything slow; jobs idempotent.
- Deploy: build artefacts, `composer install --no-dev --optimize-autoloader`,
  cache warm-up, then release — no `composer update` on the production box.

## Failure modes at scale

- Business logic in Blade templates.
- `env()` called in application code (breaks once config is cached).
- N+1 on the product listing page.
- Unbounded FPM children exhausting DB connections.
- A deploy that runs migrations and code changes at the same instant, with no
  rollback path.

## Verification receipts

1. Query count on the busiest list page (eager loading proven).
2. Config cache + opcache verified in production.
3. FPM children vs DB max_connections documented.
4. Queue job idempotency test.
5. Static analysis (PHPStan/Psalm) and `composer audit` clean in CI.
