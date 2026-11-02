"""Tests for src.context.budgeting package."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.context.budgeting import (
    ContextBudget,
    ScanLimits,
    ScanReport,
    calibration_factor,
    count_tokens,
    record_sample,
    reset_for_tests,
    trim_messages_to_budget,
)
from src.context.token_budget import count_tokens as facade_count_tokens
from src.context.token_calibration import calibration_factor as facade_calibration_factor
from src.context.bounded_scan import ContextBudget as facade_ContextBudget


def test_budgeting_package_exports():
    assert count_tokens is facade_count_tokens
    assert calibration_factor is facade_calibration_factor
    assert ContextBudget is facade_ContextBudget


def test_count_tokens_and_trim():
    msgs = [
        SystemMessage(content="You are an assistant."),
        HumanMessage(content="Hello world"),
        AIMessage(content="Hi there!"),
    ]
    tokens = count_tokens(msgs)
    assert tokens > 0

    trimmed = trim_messages_to_budget(msgs, max_tokens=1000)
    assert len(trimmed) == 3

    trimmed_tight = trim_messages_to_budget(msgs, max_tokens=15)
    assert len(trimmed_tight) <= len(msgs)


def test_calibration_cycle():
    reset_for_tests()
    model = "test-model"
    assert calibration_factor(model) == 1.0

    record_sample(model, estimated_tokens=1000, actual_tokens=1200)
    record_sample(model, estimated_tokens=1000, actual_tokens=1200)
    factor = record_sample(model, estimated_tokens=1000, actual_tokens=1200)
    assert factor is not None
    assert calibration_factor(model) > 1.0
    reset_for_tests()


def test_context_budget_share():
    cb = ContextBudget(max_files=100, max_bytes=1000)
    slice1 = cb.share(2)
    assert slice1.max_files == 50
    assert slice1.max_bytes == 500

