from langchain_groq import ChatGroq

from src.config.settings import GROQ_API_KEY, LLM_MODEL


llm = ChatGroq(
    model=LLM_MODEL,
    api_key=GROQ_API_KEY,
)
