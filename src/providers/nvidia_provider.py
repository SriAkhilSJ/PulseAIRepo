from langchain_openai import ChatOpenAI

from src.config.settings import LLM_MODEL, NVIDIA_API_KEY


llm = ChatOpenAI(
    api_key=NVIDIA_API_KEY,
    model=LLM_MODEL,
    base_url="https://integrate.api.nvidia.com/v1",
)
