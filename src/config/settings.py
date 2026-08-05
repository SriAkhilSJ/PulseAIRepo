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

# Optional hard override of the model's context window (tokens). When set,
# it wins over the live provider probe AND the built-in table. Leave unset
# to let the engine discover the window dynamically.
LLM_CONTEXT_WINDOW: str | None = os.getenv("LLM_CONTEXT_WINDOW")

# Provider input safety limit (tokens). Trim messages before sending if over.
# OmniRouter's auto-combo tier 503s on oversized requests; keep the payload
# under this cap so the pre-send guard can avoid the rejection.
#   > 0 : explicit cap (safe default for free/combo tiers)
#   = 0 : AUTO — trust the dynamically discovered model window instead.
#         Use this on paid/unlimited tiers to unlock the full context window;
#         both the ContextEngine budget and the RetryLLMProxy guard resolve
#         the identical number, so they can never disagree.
PROVIDER_SAFE_LIMIT: int = int(os.getenv("PROVIDER_SAFE_LIMIT", "6000"))

# =========================================================
# EMBEDDING (for semantic context, dedup, memory, and scoring)
# =========================================================
EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "local")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DEVICE: str = os.getenv("EMBEDDING_DEVICE", "cpu")

