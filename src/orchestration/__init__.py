"""
src/orchestration/__init__.py - Autonomous Engineering Execution Subsystem.

Phase 11.6: Autonomous Engineering Execution.
"""

from src.orchestration.context_manager import AdaptiveContextManager, AuthoritativeTaskContext
from src.orchestration.finops_governor import BudgetExhaustedError, OrchestrationFinOpsGovernor
from src.orchestration.implementation_engine import ControlledImplementationEngine, ScopeDivergenceError
from src.orchestration.journal import DurableOrchestrationJournal
from src.orchestration.lifecycle import LifecycleManager, StageExecutionRecord
from src.orchestration.loop import BoundedAutonomousReasoningLoop, ResourceLimitExceededError
from src.orchestration.models import (
    VALID_TRANSITIONS,
    DeliveryContract,
    EngineeringPlanDAG,
    EngineeringTaskNode,
    ExecutionLimits,
    TaskExecutionState,
    TaskLifecycleStage,
    TaskVerdict,
)
from src.orchestration.orchestrator import EngineeringExecutionOrchestrator
from src.orchestration.planner import EngineeringTaskPlanner, ScopeCreepError
from src.orchestration.scheduler import DependencyAwareScheduler, TaskSchedulingError
from src.orchestration.state_machine import InvalidTransitionError, TaskStateMachine
from src.orchestration.supervision import HumanSupervisionGate, PendingApprovalRequest
from src.orchestration.visibility import DesktopTaskProgressView, DesktopVisibilityReporter

__all__ = [
    "TaskExecutionState",
    "TaskLifecycleStage",
    "TaskVerdict",
    "VALID_TRANSITIONS",
    "ExecutionLimits",
    "EngineeringTaskNode",
    "EngineeringPlanDAG",
    "DeliveryContract",
    "InvalidTransitionError",
    "TaskStateMachine",
    "StageExecutionRecord",
    "LifecycleManager",
    "ScopeCreepError",
    "EngineeringTaskPlanner",
    "TaskSchedulingError",
    "DependencyAwareScheduler",
    "AuthoritativeTaskContext",
    "AdaptiveContextManager",
    "ScopeDivergenceError",
    "ControlledImplementationEngine",
    "ResourceLimitExceededError",
    "BoundedAutonomousReasoningLoop",
    "PendingApprovalRequest",
    "HumanSupervisionGate",
    "DesktopTaskProgressView",
    "DesktopVisibilityReporter",
    "BudgetExhaustedError",
    "OrchestrationFinOpsGovernor",
    "DurableOrchestrationJournal",
    "EngineeringExecutionOrchestrator",
]

