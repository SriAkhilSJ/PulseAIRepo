from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.config.settings import LLM_MODEL, LLM_PROVIDER
from src.llm.factory import get_llm


class AgentState(TypedDict):
    message: str
    response: str


llm = get_llm(
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
)


def ai_node(state: AgentState):
    message = state["message"]
    result = llm.invoke(message)

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
