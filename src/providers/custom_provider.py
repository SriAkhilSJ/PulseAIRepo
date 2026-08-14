from langchain_openai import ChatOpenAI

from src.config.settings import CUSTOM_API_KEY, CUSTOM_BASE_URL, LLM_MODEL


llm = ChatOpenAI(
    api_key=CUSTOM_API_KEY,
    base_url=CUSTOM_BASE_URL,
    model=LLM_MODEL,
)
