from langchain_core.messages import HumanMessage

from src.llm.factory import get_llm
from src.tools.math_tools import add


llm = get_llm(
    provider="groq",
    model="qwen/qwen3.6-27b"
)


llm_with_tools = llm.bind_tools([add])


response = llm_with_tools.invoke([
    HumanMessage(
        content="Use the add tool to calculate 928 + 716."
    )
])


print(response.tool_calls[0])