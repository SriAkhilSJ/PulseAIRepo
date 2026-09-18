"""Regression: OpenRouter-style reasoning deltas survive langchain conversion.

Field 2026-09-17: velona.in (OpenRouter-style) streams the model's thinking
as ``delta.reasoning`` (+ ``delta.reasoning_details``) and carries
``message.reasoning`` on buffered responses. Stock ChatOpenAI documentedly
drops both — the token pump never saw a reasoning frame and the desktop's
Thinking card never painted. ReasoningAwareOpenAI lifts them into
``additional_kwargs['reasoning_content']`` on BOTH paths, the carrier
_AgentTokenPump already reads.
"""

from __future__ import annotations

from src.llm.factory import ReasoningAwareOpenAI


def _llm() -> ReasoningAwareOpenAI:
    return ReasoningAwareOpenAI(model="test-model", api_key="test-key")


def test_stream_chunk_lifts_reasoning_into_message_kwargs():
    llm = _llm()
    chunk = {
        "choices": [
            {"delta": {"role": "assistant", "content": "", "reasoning": "We need 17*23"}}
        ]
    }
    gc = llm._convert_chunk_to_generation_chunk(chunk, None, None)
    assert gc is not None
    assert gc.message.additional_kwargs.get("reasoning_content") == "We need 17*23"


def test_stream_chunk_lifts_reasoning_content_variant():
    llm = _llm()
    chunk = {
        "choices": [
            {"delta": {"role": "assistant", "content": "", "reasoning_content": "step 1"}}
        ]
    }
    gc = llm._convert_chunk_to_generation_chunk(chunk, None, None)
    assert gc.message.additional_kwargs.get("reasoning_content") == "step 1"


def test_stream_chunk_keeps_structured_reasoning_details():
    llm = _llm()
    details = [{"type": "text", "text": "detail"}]
    chunk = {
        "choices": [
            {
                "delta": {
                    "role": "assistant",
                    "content": "",
                    "reasoning": "think",
                    "reasoning_details": details,
                }
            }
        ]
    }
    gc = llm._convert_chunk_to_generation_chunk(chunk, None, None)
    assert gc.message.additional_kwargs.get("reasoning_details") == details
    assert gc.message.additional_kwargs.get("reasoning_content") == "think"


def test_plain_content_chunk_stays_clean():
    llm = _llm()
    chunk = {"choices": [{"delta": {"role": "assistant", "content": "hello"}}]}
    gc = llm._convert_chunk_to_generation_chunk(chunk, None, None)
    assert not gc.message.additional_kwargs.get("reasoning_content")
    assert not gc.message.additional_kwargs.get("reasoning_details")


def test_buffered_result_lifts_message_reasoning():
    llm = _llm()
    resp = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "391", "reasoning": "17*23 = 391"},
                "finish_reason": "stop",
            }
        ]
    }
    result = llm._create_chat_result(resp)
    msg = result.generations[0].message
    assert msg.content == "391"
    assert msg.additional_kwargs.get("reasoning_content") == "17*23 = 391"


def test_buffered_result_without_reasoning_is_untouched():
    llm = _llm()
    resp = {
        "choices": [
            {
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "stop",
            }
        ]
    }
    result = llm._create_chat_result(resp)
    msg = result.generations[0].message
    assert msg.content == "hi"
    assert not msg.additional_kwargs.get("reasoning_content")
