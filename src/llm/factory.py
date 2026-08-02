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

    def invoke(self, *args, **kwargs):
        last_error = None

        for attempt in range(self._max_attempts):
            try:
                return self._llm.invoke(*args, **kwargs)
            except Exception as error:
                last_error = error

                if not self._is_retryable(error) or attempt == self._max_attempts - 1:
                    raise

                time.sleep(self._retry_delay(error, attempt))

        raise last_error

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
