# src/context/token_budget.py
"""
Token Budget Manager
====================

This file makes sure we don't send too many words to the AI.

Every AI has a "token limit" (like a max word count).
If we go over, the AI gets confused or the API rejects us.
"""
import tiktoken

from langchain_core.messages import BaseMessage, SystemMessage
from src.config.settings import CONTEXT_MODEL


def count_tokens(messages: list[BaseMessage], model: str | None = None) -> int:
    """
    Count how many tokens a list of messages uses.

    Think of tokens as "AI words" — roughly 1 token = 0.75 English words.
    """
    model_name = model or CONTEXT_MODEL

    encoder = None
    try:
        # Try to get the right tokenizer for this model. ANY failure (unknown
        # model, unavailable BPE download, offline) degrades to the heuristic
        # encoder — token counting must never kill a turn.
        try:
            encoder = tiktoken.encoding_for_model(model_name)
        except Exception as exc:
            from src.context.tokenizer_fallback import HEURISTIC_ENCODER, warn_once
            warn_once(f"encoding_for_model({model_name!r})", exc)
            encoder = tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        from src.context.tokenizer_fallback import HEURISTIC_ENCODER, warn_once
        warn_once("tiktoken cache lookup", exc)
        encoder = HEURISTIC_ENCODER

    total = 0

    for message in messages:
        # Every message costs some tokens just to exist (formatting overhead)
        total += 4  # Start of message

        # Add tokens for the message content
        if isinstance(message.content, str):
            total += len(encoder.encode(message.content))
        else:
            # Sometimes content is a list (for multimodal), handle safely
            total += len(encoder.encode(str(message.content)))

        # Add tokens for the role name (system/human/ai/tool)
        total += len(encoder.encode(message.type))

        total += 2  # End of message

    # Every reply also has a "prime" cost
    total += 2

    return total


def trim_messages_to_budget(
    messages: list[BaseMessage],
    max_tokens: int,
    model: str | None = None,
) -> list[BaseMessage]:
    """
    Remove old messages until the total is under the token budget.

    Strategy: Keep the MOST RECENT messages, drop the oldest ones.
    Why? Because the AI needs to know what just happened.
    """
    if not messages:
        return []

    # Always keep system messages — they contain instructions
    system_messages = [m for m in messages if isinstance(m, SystemMessage)]
    other_messages = [m for m in messages if not isinstance(m, SystemMessage)]

    # Start with everything
    current = list(messages)

    # While we're over budget, remove the oldest non-system message
    while count_tokens(current, model) > max_tokens and other_messages:
        # Remove the oldest message (first in the list)
        other_messages.pop(0)
        current = system_messages + other_messages

    return current
