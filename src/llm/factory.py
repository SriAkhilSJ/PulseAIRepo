from src.config.settings import CUSTOM_BASE_URL
from src.config.settings import CUSTOM_API_KEY
from src.config.settings import OPENAI_API_KEY
from src.config.settings import NVIDIA_API_KEY
from langchain_groq import ChatGroq
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from src.config.settings import(
    GEMINI_API_KEY,
    GROQ_API_KEY
)

def get_llm(provider,model):
    if provider == "groq":
        return ChatGroq(model=model,
        api_key=GROQ_API_KEY
    ) 
    if provider =="gemini":
        return ChatGoogleGenerativeAI(
            model=model,
            api_key=GEMINI_API_KEY
        )
    if provider == "nvidia":
        return ChatOpenAI(
            model=model,
            api_key=NVIDIA_API_KEY,
            base_url="https://integrate.api.nvidia.com/v1"
        )
    if provider == "openai":
        return ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=model
        )
    if provider =="custom":
        return ChatOpenAI(
            api_key=CUSTOM_API_KEY,
            base_url=CUSTOM_BASE_URL,
            model=model
        )
    raise ValueError(f"Unknown provider :{provider}")
