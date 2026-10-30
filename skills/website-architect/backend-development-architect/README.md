# backend-development-architect

Server-side architecture branch. One architect skill per language, and one per
framework/method beneath it — the agent selects by task, not by preference.

```
backend-development-architect/
└── python-architect/            # language-level decisions + leaf map
    ├── flask-architect/         # WSGI, factory + blueprints, sync workers
    ├── fastapi-architect/       # ASGI, pydantic contracts, DI, lifespans
    └── django-architect/        # apps, ORM/migrations, DRF, admin
```

## Planned

| Language | Framework leaves |
|---|---|
| `nodejs-architect` (see react branch) | `express-architect`, `nestjs-architect`, `fastify-architect` |
| `java-architect` | `spring-boot-architect`, `quarkus-architect` |
| `go-architect` | `gin-architect`, `fiber-architect`, `net-http-architect` |
| `rust-architect` | `axum-architect`, `actix-architect` |
| `dotnet-architect` | `aspnet-core-architect` |
| `ruby-architect` | `rails-architect`, `sinatra-architect` |
| `php-architect` | `laravel-architect`, `symfony-architect` |

Each leaf answers: when to choose this over its siblings, canonical structure,
boundaries, failure modes, verification receipts.
