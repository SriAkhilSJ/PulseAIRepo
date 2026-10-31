# ShopZone — Amazon-style E-commerce Platform

A full-stack, production-style storefront with a real relational database
(SQLite), a JSON REST API, customer accounts, cart & checkout with server-side
price/stock enforcement, order history, and an admin/vendor hub. Zero external
dependencies — Python 3.11 standard library only.

## Quickstart

```bash
python server.py
# → ShopZone running at http://localhost:8000
```

Open http://localhost:8000 in a browser.

## Demo accounts

| Role      | Email                | Password  |
|-----------|----------------------|-----------|
| Admin     | admin@shopzone.demo  | admin123  |
| Customer  | demo@shopzone.demo   | demo1234  |

New customers can also self-register from the UI.

## Feature map

**Customer storefront** — live search, category / rating / price filters,
sorting, pagination, product detail with reviews, cart drawer with
server-recomputed pricing, login/register, checkout with stock validation,
idempotency, order history.

**Admin hub** (`Store Admin` menu) — revenue/orders/low-stock stats, product
CRUD, restock, order status management, soft-delete catalog control.

## API overview (all JSON, prefix `/api`)

| Method | Path                          | Auth    | Purpose                        |
|--------|-------------------------------|---------|--------------------------------|
| GET    | /health                       | —       | liveness                       |
| POST   | /auth/register                | —       | create account → token         |
| POST   | /auth/login                   | —       | login → token                  |
| POST   | /auth/logout                  | bearer  | revoke session                 |
| GET    | /auth/me                      | bearer  | current user                   |
| GET    | /products                     | —       | search/filter/sort/paginate    |
| GET    | /products/<id>                | —       | detail + reviews               |
| POST   | /products/<id>/reviews        | bearer  | add review, updates rating     |
| POST   | /cart/quote                   | —       | server-priced cart snapshot    |
| POST   | /checkout                     | bearer  | place order (atomic, idempotent) |
| GET    | /orders                       | bearer  | my orders                      |
| POST   | /products                     | admin   | create product                 |
| PUT    | /products/<id>                | admin   | update product                 |
| DELETE | /products/<id>                | admin   | soft delete (deactivate)       |
| POST   | /products/<id>/restock        | admin   | add stock                      |
| GET    | /admin/orders                 | admin   | all orders                     |
| POST   | /admin/orders/<id>/status     | admin   | update order status            |
| GET    | /admin/stats                  | admin   | dashboard metrics              |

Errors use one envelope: `{"error": {"code", "message"}}` with 400/401/403/404/409/422.

## Tests

```bash
python -m unittest discover -s tests -v
```

Boots the real app on an ephemeral port against a throwaway database and
exercises auth, catalog, cart math, atomic checkout, idempotency, and admin
authorization.

## Design notes

- Money is stored/computed in **integer cents**; the server is the source of
  truth for all totals (client-quoted prices are never trusted).
- Checkout runs in a single `BEGIN IMMEDIATE` transaction: stock is checked
  and decremented, then the order is written — no overselling.
- An `idempotency_key` on checkout makes retries safe (unique index; a replay
  returns the original order).
- SQLite runs in WAL mode with per-request connections (threaded server).
- Product images are generated SVG tiles (hue + emoji), so the catalog renders
  offline; swap `productImage()` in `frontend/app.js` for real photo URLs.
