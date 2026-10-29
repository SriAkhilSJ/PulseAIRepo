# SprintBoard

A polished, production-minded sprint task board: a Python standard-library backend with SQLite persistence and a browser-native dashboard frontend. **Zero dependencies** — no pip packages, no node modules.

## Features

- **Live statistics** — four cards (Total / Todo / Doing / Done) computed from real API data.
- **Add tasks** with a validated, accessible form (non-blank title + priority of `low` / `medium` / `high`).
- **Status workflow** — move tasks between `todo`, `doing`, and `done` from each card.
- **Filters** — All / Todo / Doing / Done views, with loading, empty, and error states.
- **Delete** tasks with a smooth removal animation.
- **Health indicator** — header badge polling `GET /api/health` every 15 seconds.
- **Responsive design** — dark theme, CSS-variable color system, hover/focus states, subtle animations; works from phones to desktops.

## Architecture

```
┌────────────┐   fetch (REST/JSON)   ┌──────────────┐   sqlite3   ┌──────────┐
│ index.html │ ────────────────────▶ │  server.py   │ ──────────▶ │ tasks.db │
│  app.js    │ ◀──────────────────── │ (ThreadingHTTPServer)     └──────────┘
│ styles.css │                       └──────────────┘
└────────────┘
```

- `server.py` — a `ThreadingHTTPServer` handling both the static site and the JSON API. Threads share SQLite through per-request connections and a write lock (WAL mode enabled).
- `index.html` / `styles.css` / `app.js` — the dashboard. `app.js` is a vanilla-JS IIFE that renders all state from API responses; there are no hardcoded sample tasks.

## Data Model

`tasks` table (SQLite):

| column       | type    | notes                                    |
|--------------|---------|------------------------------------------|
| `id`         | INTEGER | primary key, autoincrement                |
| `title`      | TEXT    | required, non-blank                       |
| `priority`   | TEXT    | `low` \| `medium` \| `high` (default `medium`) |
| `status`     | TEXT    | `todo` \| `doing` \| `done` (default `todo`)   |
| `created_at` | TEXT    | UTC timestamp, set on insert              |

Tasks are returned newest first (descending `id`).

## Launch

```bash
python server.py --host 127.0.0.1 --port 8000
```

Then open http://127.0.0.1:8000. The database file defaults to `tasks.db` beside `server.py`; override it with the `SPRINTBOARD_DB` environment variable:

```bash
SPRINTBOARD_DB=/tmp/demo.db python server.py --host 0.0.0.0 --port 8000
```

## API Routes

| Method   | Route              | Success | Notes                                                          |
|----------|--------------------|---------|----------------------------------------------------------------|
| `GET`    | `/api/health`      | 200     | Returns exactly `{"status": "ok"}`                             |
| `GET`    | `/api/tasks`       | 200     | `{"tasks": [...]}`, newest first                               |
| `POST`   | `/api/tasks`       | 201     | Body: `{"title": "...", "priority": "..."}`; returns `{"task": ...}` |
| `PATCH`  | `/api/tasks/{id}`  | 200     | Body: `{"status": "todo\|doing\|done"}`; returns updated task  |
| `DELETE` | `/api/tasks/{id}`  | 204     | Removes the row                                                |
| `GET`    | `/api/stats`       | 200     | `{"total": n, "todo": n, "doing": n, "done": n}` (integers)    |

Errors are always JSON (`{"error": "..."}`) with an appropriate status code (400 for validation, 404 for unknown tasks/routes); tracebacks are never exposed to clients.

## Verification

```bash
python -m unittest discover -s .acceptance -p 'test_*.py' -v
```

The acceptance suite boots the server against a temporary database (`SPRINTBOARD_DB`) and exercises every route, validation rule, and the required frontend DOM ids.
