"""Inline completion provider for PulseAI — ghost text suggestions.

This module provides fast, context-aware inline completions similar to
GitHub Copilot. It uses the existing context engine to gather relevant
code context and calls the LLM for short completion suggestions.

The completions are served via the bridge protocol as a new event type
and rendered as ghost text in the VS Code editor.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from src.config.settings import LLM_PROVIDER, LLM_MODEL


@dataclass
class CompletionRequest:
    """A request for inline completion at a specific cursor position."""
    resource: str
    language_id: str
    line: int
    column: int
    prefix: str
    suffix: str
    context_lines: int = 30
    max_tokens: int = 128


@dataclass
class CompletionItem:
    """A single inline completion suggestion."""
    text: str
    range_start_line: int
    range_start_column: int
    range_end_line: int
    range_end_column: int
    confidence: float = 0.0
    stop_reason: str = ""


class InlineCompletionProvider:
    """Provides inline completions by calling the LLM with surrounding context.
    
    Uses a lightweight, fast path — NOT the full context engine. For
    completions we need sub-200ms latency, so we skip the expensive
    16-layer context assembly and instead use a focused prompt with
    just the surrounding code.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._debounce_ms = int(os.environ.get("PULSEAI_COMPLETION_DEBOUNCE_MS", "150"))
        self._max_tokens = int(os.environ.get("PULSEAI_COMPLETION_MAX_TOKENS", "128"))
        self._enabled = os.environ.get("PULSEAI_INLINE_COMPLETIONS", "1").strip().lower() in {
            "1", "true", "yes", "on",
        }
        self._cache: dict[str, list[CompletionItem]] = {}
        self._cache_max = 64

    @property
    def enabled(self) -> bool:
        return self._enabled

    def compute_completions(self, request: CompletionRequest) -> list[CompletionItem]:
        """Compute inline completions for a given cursor position.
        
        This is a synchronous method designed to be called from the bridge
        event loop. It builds a minimal prompt and calls the LLM.
        """
        if not self._enabled:
            return []

        cache_key = self._cache_key(request)
        with self._lock:
            if cache_key in self._cache:
                return self._cache[cache_key]

        # Build the completion prompt — minimal, fast, focused
        prompt = self._build_prompt(request)
        
        try:
            items = self._call_llm(prompt, request)
        except Exception:
            items = []

        # Cache the result (bounded)
        with self._lock:
            if len(self._cache) >= self._cache_max:
                # Evict oldest entries
                keys = list(self._cache.keys())
                for k in keys[: self._cache_max // 2]:
                    del self._cache[k]
            self._cache[cache_key] = items

        return items

    def invalidate(self, resource: str) -> None:
        """Invalidate cached completions for a resource (called on edit)."""
        with self._lock:
            to_remove = [k for k in self._cache if k.startswith(resource)]
            for k in to_remove:
                del self._cache[k]

    def _cache_key(self, request: CompletionRequest) -> str:
        # Key on resource + prefix hash for stable cache
        prefix_hash = hash(request.prefix[-500:]) if len(request.prefix) > 500 else hash(request.prefix)
        return f"{request.resource}:{request.line}:{request.column}:{prefix_hash}"

    def _build_prompt(self, request: CompletionRequest) -> str:
        """Build a minimal prompt for inline completion.
        
        Format: <prefix> ... cursor ... <suffix>
        The model completes what's between prefix and suffix.
        """
        # Extract surrounding context (up to context_lines lines before/after)
        prefix_lines = request.prefix.split("\n")
        suffix_lines = request.suffix.split("\n")

        # Take last N lines of prefix
        prefix_context = "\n".join(prefix_lines[-request.context_lines:])
        # Take first N lines of suffix
        suffix_context = "\n".join(suffix_lines[:request.context_lines // 2])

        # Language hint from VSCode language ID
        lang_hint = request.language_id or "code"

        prompt = f"""Complete the code at the cursor position. Return ONLY the completion text, no explanations.

Language: {lang_hint}

Code before cursor:
```
{prefix_context}
```

Code after cursor:
```
{suffix_context}
```

Continue from the cursor position. Return only the code that should be inserted:"""

        return prompt

    def _call_llm(self, prompt: str, request: CompletionRequest) -> list[CompletionItem]:
        """Call the LLM for a completion. Uses the fastest available provider."""
        from src.llm.factory import get_llm

        try:
            llm = get_llm(LLM_PROVIDER, LLM_MODEL)
            # Use a short timeout for completions — we need speed
            response = llm.invoke(
                [{"role": "user", "content": prompt}],
            )
            text = getattr(response, "content", "") or ""
            text = self._clean_completion(text)
            if not text:
                return []

            # Calculate cursor position from prefix
            prefix_lines = request.prefix.split("\n")
            start_line = request.line
            start_column = request.column
            text_lines = text.split("\n")

            if len(text_lines) == 1:
                end_line = start_line
                end_column = start_column + len(text)
            else:
                end_line = start_line + len(text_lines) - 1
                end_column = len(text_lines[-1])

            return [CompletionItem(
                text=text,
                range_start_line=start_line,
                range_start_column=start_column,
                range_end_line=end_line,
                end_column=end_column,
                confidence=0.8,
                stop_reason="stop",
            )]
        except Exception:
            return []

    @staticmethod
    def _clean_completion(text: str) -> str:
        """Clean up the LLM completion output."""
        # Remove markdown code fences
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (fences)
            if lines[-1].strip() == "```":
                lines = lines[1:-1]
            elif lines[0].strip().startswith("```"):
                lines = lines[1:]
            text = "\n".join(lines)

        # Remove common prefixes the model might add
        for prefix in ["The completion is:", "Here is the completion:", "Code:", "```"]:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()

        return text.strip()


# Singleton
_inline_completion_provider: InlineCompletionProvider | None = None
_inline_completion_lock = threading.Lock()


def get_inline_completion_provider() -> InlineCompletionProvider:
    global _inline_completion_provider
    if _inline_completion_provider is None:
        with _inline_completion_lock:
            if _inline_completion_provider is None:
                _inline_completion_provider = InlineCompletionProvider()
    return _inline_completion_provider
