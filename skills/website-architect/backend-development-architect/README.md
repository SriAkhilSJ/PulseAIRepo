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

## Branches present

| Language | Skill | Framework leaves |
|---|---|---|
| Python | `python-architect` | flask, fastapi, django |
| Node | `nodejs-architect` (in the react branch) | express, nestjs, fastify |
| Go | `go-architect` | leaf map inside |
| Java | `java-architect` | leaf map inside |
| Rust | `rust-architect` | leaf map inside |
| .NET | `dotnet-architect` | leaf map inside |
| Ruby | `ruby-architect` | leaf map inside |
| PHP | `php-architect` | leaf map inside |

Each leaf answers: when to choose this over its siblings, canonical structure,
boundaries, failure modes, verification receipts.
