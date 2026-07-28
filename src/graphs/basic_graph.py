from unittest import result
from openai.types.responses import response
from typing import TypedDict
from src.llm.factory import get_llm
from langgraph.graph import StateGraph, START,END

class AgentState(TypedDict):
    message: str
    response: str

llm = get_llm(
    provider="groq",
    model="qwen/qwen3.6-27b"
)
    

def ai_node(state: AgentState):
    message= state["message"]
    result =llm.invoke(message)

    return {
        "response":result.content
    }
builder = StateGraph(AgentState)
builder.add_node("ai",ai_node)
builder.add_edge(START, "ai")
builder.add_edge("ai", END)
graph =builder.compile()
result = graph.invoke({
    "message": "Who is Monkey D. Luffy?",
    "response": ""
})

print(result["response"])