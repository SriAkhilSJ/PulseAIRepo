from pyexpat.errors import messages
from operator import mod
from openai.types.responses import response
from langchain_groq import ChatGroq
from src.config.settings import GROQ_API_KEY

llm =ChatGroq(
    model="qwen/qwen3.6-27b"
    ,api_key=GROQ_API_KEY
)

