from langchain_openai import ChatOpenAI

from src.config.settings import LLM_MODEL, OPENAI_API_KEY


llm = ChatOpenAI(
    model=LLM_MODEL,
    api_key=OPENAI_API_KEY,
)
