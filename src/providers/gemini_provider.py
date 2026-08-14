from langchain_google_genai import ChatGoogleGenerativeAI

from src.config.settings import GEMINI_API_KEY, LLM_MODEL


llm = ChatGoogleGenerativeAI(
    api_key=GEMINI_API_KEY,
    model=LLM_MODEL,
)
