from langchain_openai import ChatOpenAI
from src.config.settings import NVIDIA_API_KEY

llm=ChatOpenAI(
        api_key=NVIDIA_API_KEY,
        model="z-ai/glm-5.2",
        base_url="https://integrate.api.nvidia.com/v1"
)
