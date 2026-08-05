import re
import time
from typing import Any

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from src.config.settings import (
    CUSTOM_API_KEY,
    CUSTOM_BASE_URL,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    NVIDIA_API_KEY,
    OPENAI_API_KEY,
)


class RetryLLMProxy:
    """Tiny proxy that retries transient LLM rate-limit errors."""

    def __init__(self, llm: Any, max_attempts: int = 5):
        self._llm = llm
        self._max_attempts = max_attempts
        # Explicit model name extraction — do NOT rely on __getattr__
        # fall-through. langchain providers differ: ChatOpenAI/ChatGroq
        # historically exposed model_name (alias "model"), newer versions
        # expose model; ChatGoogleGenerativeAI uses model. Grab whichever
        # exists so count_tokens() always gets a real model string.
        self.model = (
            getattr(llm, "model", None)
            or getattr(llm, "model_name", None)
            or getattr(llm, "model_id", None)
        )

    def invoke(self, *args, **kwargs):
        """
        Invoke with retry logic AND a pre-send token guard.
        If messages exceed the provider's safe limit, trim from the middle
        (preserve system + recent history) before sending.
        """
        last_error = None

        # ------------------------------------------------------------------
        # PRE-SEND TOKEN GUARD (503 mitigation)
        # Guard ONLY the messages arg — never any other positional arg.
        # ------------------------------------------------------------------
        messages_arg = None
        if args:
            messages_arg = args[0]
        elif "messages" in kwargs:
            messages_arg = kwargs["messages"]

        if isinstance(messages_arg, list):
            try:
                from src.config.settings import PROVIDER_SAFE_LIMIT
                from src.context.token_budget import count_tokens
                total_tokens = count_tokens(messages_arg, self.model)
            except Exception as guard_error:
                # NEVER silently disable the guard: a token-counting failure
                # would otherwise zero the limit and ship oversized payloads
                # straight to providers (the 503 the guard exists to prevent).
                print(
                    f"[RetryLLMProxy] Token guard unavailable (model={self.model!r}): "
                    f"{guard_error!r} — sending untrimmed"
                )
                total_tokens = 0
                PROVIDER_SAFE_LIMIT = 0

            if total_tokens > PROVIDER_SAFE_LIMIT:
                trimmed = self._trim_to_limit(messages_arg, PROVIDER_SAFE_LIMIT)
                print(
                    f"[RetryLLMProxy] Trimmed {total_tokens} -> ~{PROVIDER_SAFE_LIMIT} "
                    f"tokens to avoid provider 503"
                )
                if args:
                    args = (trimmed,) + args[1:]
                else:
                    kwargs["messages"] = trimmed

        for attempt in range(self._max_attempts):
            try:
                return self._llm.invoke(*args, **kwargs)
            except Exception as error:
                last_error = error

                if not self._is_retryable(error) or attempt == self._max_attempts - 1:
                    raise

                time.sleep(self._retry_delay(error, attempt))

        raise last_error

    def _trim_to_limit(self, messages: list, limit: int) -> list:
        """
        Trim message list to fit within token limit.
        Strategy: preserve system message (index 0) and the most recent
        messages at the tail. Drop from the middle (oldest history first).
        """
        try:
            from src.context.token_budget import count_tokens
        except Exception:
            return messages

        if not messages:
            return messages

        # Always keep the first message (system prompt).
        keep_head = 1
        head_tokens = count_tokens(messages[:keep_head], self.model)

        # Binary search for how many tail messages we can keep.
        low, high = 0, len(messages) - keep_head
        best = 0
        while low <= high:
            mid = (low + high) // 2
            tail = messages[-mid:] if mid > 0 else []
            t = head_tokens
            if tail:
                try:
                    t = count_tokens(messages[:keep_head] + tail, self.model)
                except Exception:
                    t = head_tokens
            if t <= limit:
                best = mid
                low = mid + 1
            else:
                high = mid - 1

        result = messages[:keep_head]
        if best > 0:
            result.extend(messages[-best:])
        return result

    def bind_tools(self, *args, **kwargs):
        return RetryLLMProxy(
            self._llm.bind_tools(*args, **kwargs),
            max_attempts=self._max_attempts,
        )

    def with_structured_output(self, *args, **kwargs):
        return RetryLLMProxy(
            self._llm.with_structured_output(*args, **kwargs),
            max_attempts=self._max_attempts,
        )

    def __getattr__(self, name: str):
        return getattr(self._llm, name)

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        text = str(error).lower()
        return (
            "rate limit" in text
            or "rate_limit" in text
            or "429" in text
            or "temporarily unavailable" in text
            or "connection error" in text
            or "connecterror" in text
            # OmniRouter returns 503 when an auto-combo backend is unavailable
            # or the request is oversized; retrying (after trimming) may succeed.
            or "503" in text
            or "combo retry limit" in text
            # Some custom auto routers may briefly route to a backend model
            # their OpenAI-compatible endpoint cannot serve. Retrying can select
            # a different backend for the same configured model id.
            or "unsupported model" in text
        )

    @staticmethod
    def _retry_delay(error: Exception, attempt: int) -> float:
        text = str(error)

        # Groq often says: "Please try again in 3.33s" or "405ms".
        seconds_match = re.search(r"try again in ([0-9.]+)s", text, re.IGNORECASE)
        if seconds_match:
            return min(float(seconds_match.group(1)) + 0.5, 30.0)

        millis_match = re.search(r"try again in ([0-9.]+)ms", text, re.IGNORECASE)
        if millis_match:
            return min(float(millis_match.group(1)) / 1000.0 + 0.5, 30.0)

        return min(2.0 * (attempt + 1), 30.0)


def get_llm(provider, model):
    if provider == "groq":
        llm = ChatGroq(
            model=model,
            api_key=GROQ_API_KEY,
        )
        return RetryLLMProxy(llm)

    if provider == "gemini":
        llm = ChatGoogleGenerativeAI(
            model=model,
            api_key=GEMINI_API_KEY,
        )
        return RetryLLMProxy(llm)

    if provider == "nvidia":
        llm = ChatOpenAI(
            model=model,
            api_key=NVIDIA_API_KEY,
            base_url="https://integrate.api.nvidia.com/v1",
        )
        return RetryLLMProxy(llm)

    if provider == "openai":
        llm = ChatOpenAI(
            api_key=OPENAI_API_KEY,
            model=model,
        )
        return RetryLLMProxy(llm)

    if provider == "custom":
        llm = ChatOpenAI(
            api_key=CUSTOM_API_KEY,
            base_url=CUSTOM_BASE_URL,
            model=model,
        )
        return RetryLLMProxy(llm)

    raise ValueError(f"Unknown provider: {provider}")


# =========================================================
# EMBEDDING FACTORY
# =========================================================
class EmbeddingFactory:
    """Singleton embedder — loads once, reused across the agent."""
    _instance: Any = None
    _model: Any = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_model(self):
        if self._model is not None:
            return self._model
        from src.config.settings import EMBEDDING_PROVIDER, EMBEDDING_MODEL, EMBEDDING_DEVICE
        if EMBEDDING_PROVIDER == "local":
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(EMBEDDING_MODEL, device=EMBEDDING_DEVICE)
        elif EMBEDDING_PROVIDER == "openai":
            raise NotImplementedError("OpenAI embeddings not yet implemented")
        else:
            raise ValueError(f"Unknown embedding provider: {EMBEDDING_PROVIDER}")
        return self._model

def get_embedder():
    """Return the shared embedder instance."""
    return EmbeddingFactory().get_model()

