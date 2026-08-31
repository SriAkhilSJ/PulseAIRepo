"""Task-classification vocabulary for the context engine.

P9: extracted from ``context_engine.py`` so the layer-policy module
(``layer_policy.py``) can share the ``TaskType`` members — which key
the relevance map — without an import cycle: the engine imports the
policy at module top, and a policy-side import of the engine would hit
a partially-initialized module (TaskType sits in the engine below the
import block).

``context_engine.py`` re-exports ``TaskType`` via a plain import, so
every existing ``from src.context.context_engine import TaskType``
keeps working unchanged.
"""

from enum import Enum


class TaskType(Enum):
    EXPLORE = "explore"
    DEBUG = "debug"
    CREATE = "create"
    REFACTOR = "refactor"
    TEST = "test"
    EXPLAIN = "explain"
    CHAT = "chat"
    PLAN = "plan"
    RECOVERY = "recovery"
