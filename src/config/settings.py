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

# LLM_PROVIDER / LLM_MODEL are the single source of truth for model selection.
# Set them in .env; code should import these settings instead of hardcoding models.

LLM_PROVIDER: str = os.getenv(
    "LLM_PROVIDER",
    "groq",
)

LLM_MODEL: str = os.getenv(
    "LLM_MODEL",
    "qwen/qwen3.6-27b",
)

# =========================================================
# CONTEXT / TOKEN COUNTING
# =========================================================

# Model name used by the ContextEngine/token counter.
# Defaults to the active LLM model so context accounting follows .env settings.
CONTEXT_MODEL: str = os.getenv(
    "CONTEXT_MODEL",
    LLM_MODEL,
)

# =========================================================
# EMBEDDING (for semantic context, dedup, memory, and scoring)
# =========================================================
EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "local")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DEVICE: str = os.getenv("EMBEDDING_DEVICE", "cpu")

