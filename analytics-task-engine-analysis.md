# analytics-task-engine — Research Summary

Target: `c:/Users/Administrator/Downloads/testCRUSOR/analytics-task-engine`

Note: file tools are sandboxed to the PulseAIRepo workspace; findings below were
gathered via read-only shell inspection of the target path.

## Structure
```
analytics-task-engine/
├── .venv/                  # Python 3.11 virtualenv
├── backend/
│   ├── __init__.py         # "Analytics Task Engine — FastAPI backend application package."
│   └── app/
│       ├── config.py       (54 lines) — Settings dataclass; env vars ATE_DB_URL, ATE_JWT_SECRET; PROJECT_ROOT/FRONTEND_DIR/DATA_DIR paths
│       ├── database.py     (51 lines) — SQLAlchemy engine factory (SQLite-tuned: static pool, thread safety), declarative Base
│       ├── models.py       (57 lines) — ORM models: User (auth: username/password_hash/role), Task/TaskQueue (name, JSON payload, status, priority, result, error, timestamps), MetricSample (rps, latency p50/p95, queue depth, cpu, uptime)
│       ├── schemas.py      (89 lines) — Pydantic schemas
│       ├── security.py     (56 lines) — bcrypt hash/verify, JWT create/decode (create_access_token, decode_token, TokenError)
│       ├── deps.py         (71 lines) — FastAPI deps: DB session, HTTPBearer current-user resolution, RBAC role guards
│       ├── worker.py       (288 lines) — task worker engine (largest module, see below)
│       └── routers/        — EMPTY directory
├── frontend/
│   ├── css/                — EMPTY
│   └── src/                — EMPTY
├── scripts/                — EMPTY
├── tests/                  — EMPTY (only __pycache__)
```
No README, requirements.txt, pyproject.toml, package.json, or main.py exists.

## Tech stack (from .venv/Lib/site-packages)
Python 3.11 backend: FastAPI 0.143 + Starlette + Uvicorn, SQLAlchemy 2.x
(Mapped/mapped_column style), Pydantic v2, PyJWT + bcrypt, WebSockets,
python-multipart, python-dotenv, PyYAML, httpx, pytest, OpenTelemetry.
Frontend directories exist but contain no code — backend-only project.

## Main entry points
- No `main.py` / `app = FastAPI()` instance found — the app factory/ASGI entry
  point is missing (routers/ is empty). Uvicorn is referenced only in a
  worker.py docstring ("Runs as a daemon thread inside the uvicorn process").
- `backend/app/worker.py` is the functional core: TaskWorker (threading.Thread)
  polls the task queue, claims tasks (poll_interval 0.25s, max_concurrent 4),
  executes them, writes heartbeats; MetricsHub manages stats + WebSocket client
  broadcasting; TokenBucket rate limiter; WorkerConfig/HubStats dataclasses.

## Purpose
A skeleton/starter for an async analytics task-processing API: authenticated
(RBAC) REST backend that queues prioritized tasks in SQLite, executes them on a
background worker thread, and streams live metrics (RPS, latency percentiles,
queue depth, CPU) over WebSocket. Currently incomplete — entry point, routes,
tests, scripts, and frontend are not yet implemented.
