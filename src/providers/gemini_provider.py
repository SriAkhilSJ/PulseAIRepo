from certifi import contents
from openai.resources.containers.files import content
from openai.types.responses import response
from http import client
from langchain_google_genai import ChatGoogleGenerativeAI
from src.config.settings import GEMINI_API_KEY

llm = ChatGoogleGenerativeAI(api_key=GEMINI_API_KEY,
model="gemini-2.5-flash"
)
