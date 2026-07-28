from dotenv import load_dotenv
import os

load_dotenv()


# =========================================================
# API KEYS
# =========================================================

OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
NVIDIA_API_KEY: str | None = os.getenv("NVIDIA_API_KEY")

CUSTOM_API_KEY: str | None = os.getenv("CUSTOM_API_KEY")
CUSTOM_BASE_URL: str | None = os.getenv("CUSTOM_BASE_URL")


# =========================================================
# DEFAULT LLM
# =========================================================

LLM_PROVIDER: str = os.getenv(
    "LLM_PROVIDER",
    "groq",
)

LLM_MODEL: str = os.getenv(
    "LLM_MODEL",
    "qwen/qwen3.6-27b",
)