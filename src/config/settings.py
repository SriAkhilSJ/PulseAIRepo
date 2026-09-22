from dotenv import load_dotenv, find_dotenv
from pathlib import Path
import os
import sys

# Hermes does NOT cwd-guess — it resolves HERMES_HOME/.env and cli-config.yaml.
# CrusorAI must also be path-stable when the desktop spawns the bridge with
# cwd=engineRoot (resolveEngineDirectory) or when pytest runs from repo subdir.
# Load in order: (1) explicit engine package .env (PulseAIRepo/.env),
# (2) dotenv walk from cwd (find_dotenv), both with override=True so env export
# always wins over file.
_engine_env = Path(__file__).resolve().parents[2] / ".env"
if _engine_env.is_file():
    load_dotenv(dotenv_path=_engine_env, override=True)
load_dotenv(override=True)
# Also honor find_dotenv for nested launches (e.g. lab workspaces)
_found = find_dotenv(usecwd=True)
if _found:
    load_dotenv(dotenv_path=_found, override=True)
try:
    print(f"[settings] loaded: LLM_PROVIDER={os.getenv('LLM_PROVIDER')!r} LLM_MODEL={os.getenv('LLM_MODEL')!r} CRUSORAI_MEMORY={os.getenv('CRUSORAI_MEMORY')!r} CUSTOM_BASE_URL={os.getenv('CUSTOM_BASE_URL','')[:32]!r}", file=sys.stderr, flush=True)
except Exception:
    pass


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

    Routes to the cheap tier by default (provider="cheap" triggers
    CRUSORAI_CHEAP_API_KEY / CRUSORAI_CHEAP_BASE_URL / CRUSORAI_CHEAP_MODEL
    in factory.get_llm). Override via AUX_LLM_PROVIDER / AUX_LLM_MODEL.
    """
    provider = os.getenv("AUX_LLM_PROVIDER", "cheap")
    model = os.getenv("AUX_LLM_MODEL") or os.getenv("CRUSORAI_CHEAP_MODEL", "qwen/qwen3.7-flash")
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
# REASONING / EXTENDED THINKING
# =========================================================
# Controls provider-side extended thinking (reasoning tokens sent before the
# visible answer).  Valid levels: "none", "low", "medium", "high", "xhigh",
# "max", "ultra".  "none" disables thinking entirely; unset or empty falls
# back to the provider default (medium for Anthropic, off for most others).
#
# Anthropic (Claude 4.6+): sends adaptive thinking + output_config.effort.
# OpenAI (o-series, GPT-5): sends reasoning_effort in the request body.
# DeepSeek: sends reasoning_content via streaming delta (already handled by
# StreamingPump — this knob only affects the *budget* hint on endpoints that
# support one).
REASONING_EFFORT: str = os.getenv("REASONING_EFFORT", "").strip()

# =========================================================
# EMBEDDING (for semantic context, dedup, memory, and scoring)
# =========================================================
EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "local")
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DEVICE: str = os.getenv("EMBEDDING_DEVICE", "cpu")

