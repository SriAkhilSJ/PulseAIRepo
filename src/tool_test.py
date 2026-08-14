from langchain_core.messages import HumanMessage

from src.config.settings import LLM_MODEL, LLM_PROVIDER
from src.llm.factory import get_llm
from src.tools.math_tools import add


llm = get_llm(
    provider=LLM_PROVIDER,
    model=LLM_MODEL,
)

llm_with_tools = llm.bind_tools([add])

response = llm_with_tools.invoke([
    HumanMessage(
        content="Use the add tool to calculate 928 + 716."
    )
])

print(response.tool_calls[0])
