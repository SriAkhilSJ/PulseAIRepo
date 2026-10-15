import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
import uvicorn

# Import builder (durable SqliteSaver graph stays for bridge; we recompile with MemorySaver for AG-UI async)
from src.graphs.chat_graph import builder

_CHECKPOINT_DB = os.path.join(os.path.expanduser("~"), ".crusorai", "sessions.db")
os.makedirs(os.path.dirname(_CHECKPOINT_DB), exist_ok=True)

from langgraph.checkpoint.memory import MemorySaver
app = FastAPI()

# Async-compatible checkpointer for AG-UI (InMemory - use AsyncSqliteSaver with proper async context for production durability later)
async_memory = MemorySaver()

# Create graph with async-compatible checkpointer
async_graph = builder.compile(checkpointer=async_memory)

from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import LangGraphAGUIAgent

add_langgraph_fastapi_endpoint(
    app=app,
    agent=LangGraphAGUIAgent(
        name="crusor_agent",
        description="Crusor autonomous coding agent - single Crusor Agent for the IDE.",
        graph=async_graph,
    ),
    path="/",
)

def main() -> None:
    # Bind guard (AGUI_A2UI_PLAN.md Phase 1): loopback by default; a
    # non-loopback bind without CRUSORAI_DASHBOARD_TOKEN is refused.
    from src.agui.bind import resolve_bind

    decision = resolve_bind()
    if not decision.ok:
        raise SystemExit(decision.error)
    uvicorn.run(
        "src.server:app",
        host=decision.host,
        port=decision.port,
        reload=False,
    )

if __name__ == "__main__":
    main()
