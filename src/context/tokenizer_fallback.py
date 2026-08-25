"""Last-resort tokenizer fallback: a turn must never die on tokenization.

tiktoken downloads its BPE files on first use (openaipublic.blob.core.windows.net).
On a fresh machine, offline box, or locked-down proxy that download fails —
and an unguarded failure killed a real turn mid-flight (found by the PBR-002
attribution lane, 2026-08-23). Any encoder-acquisition failure anywhere in
the context path degrades to this ~chars/4 heuristic instead: imprecise but
safe, logged once, never raises.
"""
from __future__ import annotations

import threading

_warned = threading.Event()


class HeuristicEncoder:
    """Duck-types tiktoken encoders: encode() -> list of token ids."""

    def encode(self, text: str) -> list[int]:
        if not text:
            return []
        # ~4 chars/token for English/code; ceil to never report 0 for content.
        return [0] * max(1, (len(text) + 3) // 4)


HEURISTIC_ENCODER = HeuristicEncoder()


def warn_once(context: str, error: BaseException) -> None:
    if _warned.is_set():
        return
    _warned.set()
    print(
        f"[tokenizer] unavailable ({context}): {type(error).__name__}: {error} — "
        "degrading to ~chars/4 heuristic token counts (imprecise, never fatal). "
        "Install/populate the tiktoken cache (one online run) for exact counts.",
        flush=True,
    )
