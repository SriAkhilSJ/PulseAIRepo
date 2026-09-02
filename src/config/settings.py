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
# AUXILIARY (MANAGEMENT-CLASS) MODEL — D21, hermes §29
# =========================================================
# Housekeeping LLM calls (task classification, summaries of giant tool
# outputs, memory maintenance) should bill at janitor rates, never at the
# flagship's — and never share the main conversation's request chain
# (their curator.py:17-18 invariant: aux "never touches the main
# session's prompt cache"). Ours is structural: aux calls are separate
# requests via a dedicated client (factory.get_auxiliary_llm).
_AUX_CHEAP_TABLE: dict[str, str] = {
    "groq": "llama-3.1-8b-instant",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "nvidia": "meta/llama-3.1-8b-instruct",
}


def resolve_aux_llm() -> tuple[str, str]:
    """(provider, model) for management-class calls.

    Env overrides win; else the per-provider cheap table (unknown/custom
    providers fall back to the MAIN model — identical behavior, the safe
    degradation; configure AUX_LLM_MODEL to actually save).
    """
    provider = os.getenv("AUX_LLM_PROVIDER", LLM_PROVIDER)
    model = os.getenv("AUX_LLM_MODEL") or _AUX_CHEAP_TABLE.get(provider, LLM_MODEL)
    return provider, model


AUX_LLM_PROVIDER, AUX_LLM_MODEL = resolve_aux_llm()

# SmartSummarizer stays LLM-free by default (recommended for budget).
# Set SUMMARIZER_LLM=aux to let >8000-char tool outputs be summarized by
# the AUXILIARY model — a real quality win at janitor prices.
SUMMARIZER_LLM: str = os.getenv("SUMMARIZER_LLM", "").strip().lower()

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
# Shipped default is AUTO (0), not a pin. It used to be 6000, which meant the budget
# followed a number nobody asked the provider about: an unresolved window (8,192) times a
# 6,000 cap left ~1,638 tokens of context, and a `hi` turn was refused for "exceeding scan
# budget" on an ordinary repo. Hermes asks the provider and trusts the answer --
# model_budgets now reads the endpoint's own /models metadata -- so the guard and the engine
# both derive from it (RetryLLMProxy._safe_limit), and pinning 6,000 on top of that would
# only re-introduce a second guess. A free or metered tier sets PROVIDER_SAFE_LIMIT=6000
# explicitly; >0 still means exactly what the block above says it means.
PROVIDER_SAFE_LIMIT: int = int(os.getenv("PROVIDER_SAFE_LIMIT", "0"))

# =========================================================
# EMBEDDING (for semantic context, dedup, memory, and scoring)
# =========================================================
EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "local")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DEVICE: str = os.getenv("EMBEDDING_DEVICE", "cpu")

