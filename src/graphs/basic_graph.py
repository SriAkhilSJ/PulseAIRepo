from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.config.settings import LLM_MODEL, LLM_PROVIDER
from src.llm.factory import get_llm


class AgentState(TypedDict):
    message: str
    response: str


# Field 2026-11-01 (agent-core body checkup): this module used to build its
# client at IMPORT time. Nothing imports it (it is the demo graph), so the only
# effect of that line was to make `import src.graphs.basic_graph` -- and any
# health check or test that walks the package -- fail with a credential error
# on a machine without a key. Building the client lazily keeps the demo
# runnable and makes the package importable with no credentials at all.
_llm = None


def _client():
    global _llm
    if _llm is None:
        _llm = get_llm(provider=LLM_PROVIDER, model=LLM_MODEL)
    return _llm


def ai_node(state: AgentState):
    message = state["message"]
    result = _client().invoke(message)

    return {
        "response": result.content,
    }


builder = StateGraph(AgentState)
builder.add_node("ai", ai_node)
builder.add_edge(START, "ai")
builder.add_edge("ai", END)
graph = builder.compile()


if __name__ == "__main__":
    result = graph.invoke({
        "message": "Who is Monkey D. Luffy?",
        "response": "",
    })

    print(result["response"])
