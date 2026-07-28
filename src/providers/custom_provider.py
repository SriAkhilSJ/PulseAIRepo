from langchain_openai import ChatOpenAI
from openai.types.responses import response
from http import client
from src.config.settings import(
    CUSTOM_API_KEY,
    CUSTOM_BASE_URL
)

llm= ChatOpenAI(
    api_key=CUSTOM_API_KEY,
    model="auto/cheap"
)
