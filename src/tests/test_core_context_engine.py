"""Tests for src.context.core package and core.context_engine."""

import pytest
from src.context.core import (
    ContextBuilder,
    ContextEngine,
    ContextState,
    HASHED_STATE_KEYS,
    TaskClassifier,
    hash_state,
    wire_dicts_to_messages,
    workspace_exceeds_budget,
)
from src.context.context_engine import ContextEngine as FacadeContextEngine
from src.context.task_types import TaskType


def test_core_package_exports():
    assert ContextEngine is not None
    assert TaskClassifier is not None
    assert ContextState is not None
    assert ContextBuilder is not None
    assert "workspace" in HASHED_STATE_KEYS


def test_facade_subclasses_core():
    assert issubclass(FacadeContextEngine, ContextEngine)


def test_task_classifier_heuristics():
    clf = TaskClassifier()
    assert clf.classify("fix the crash and broken traceback") == TaskType.DEBUG
    assert clf.classify("create a new file for database models") == TaskType.CREATE
    assert clf.classify("run pytest and verify the test cases") == TaskType.TEST
    assert clf.classify("where is the configuration defined") == TaskType.EXPLORE


def test_core_context_engine_lifecycle():
    eng = ContextEngine(max_tokens=8000, model="gpt-4o", probe_window=False)
    status = eng.get_status()
    assert isinstance(status, dict)
    assert status.get("model") == "gpt-4o"
