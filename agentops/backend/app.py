"""CrusorAI AgentOps backend — FastAPI app.

Read-only observability console over the agent's existing sinks:
  journal  ~/.pulseai/runtime_events.db   (SQLite WAL, opened mode=ro)
  receipts ~/.pulseai/observability/turns.jsonl

Serves the built website (web/dist) at / in production; the Vite dev server
proxies /api during development. Bearer auth (CRUSORAI_OPS_TOKEN) is enforced
on /api whenever configured — mandatory for any non-loopback deployment.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api.routes import router

WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

app = FastAPI(title="CrusorAI AgentOps", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def bearer_auth(request: Request, call_next):
    tok = config.token()
    if tok and request.url.path.startswith("/api/"):
        supplied = request.headers.get("authorization", "")
        if supplied != f"Bearer {tok}":
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.include_router(router)

if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = WEB_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
else:  # dev: no built SPA yet

    @app.get("/")
    def root():
        return JSONResponse({"hint": "web/dist not built — run: cd agentops/web && npm run build", "api": "/api/health"})


def main() -> None:
    import uvicorn

    host, port = config.host_port()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
