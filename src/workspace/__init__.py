"""
src/workspace/__init__.py - Workspace Discipline & Change Management Subsystem.

Phase 11.3: Workspace Discipline & Change Management.
Exports:
- WorkspaceBaseline, WorkspaceBaselineManager, compute_file_sha256
- WorkspaceChangeLedger, ChangeRecord, FileOwnershipCategory
- WorkspaceMutationBroker, ConcurrencyConflictError, MutationAuthorizationError
- PathSafetyValidator, PathSecurityViolation
- ChangePlan, ChangePlanItem, ChangePlanEngine
- RiskApprovalGate, RiskLevel, WorkspaceOperationType, JournalState
- WorkspaceJournalManager, TransactionJournalEntry
- CleanlinessChecker
- TerminalSafetyBroker
- GitDisciplineManager
"""

from src.workspace.models import (
    ChangePlan,
    ChangePlanItem,
    ChangeRecord,
    FileOwnershipCategory,
    JournalState,
    RiskLevel,
    TransactionJournalEntry,
    WorkspaceBaseline,
    WorkspaceOperationType,
)
from src.workspace.path_safety import (
    PathSafetyValidator,
    PathSecurityViolation,
)
from src.workspace.baseline import (
    WorkspaceBaselineManager,
    compute_file_sha256,
)
from src.workspace.ledger import (
    WorkspaceChangeLedger,
)
from src.workspace.risk_policy import (
    RiskApprovalGate,
)
from src.workspace.journal import (
    WorkspaceJournalManager,
)
from src.workspace.change_planner import (
    ChangePlanEngine,
)
from src.workspace.cleanliness import (
    CleanlinessChecker,
)
from src.workspace.terminal_discipline import (
    TerminalSafetyBroker,
)
from src.workspace.git_discipline import (
    GitDisciplineManager,
)
from src.workspace.mutation_broker import (
    ConcurrencyConflictError,
    MutationAuthorizationError,
    WorkspaceMutationBroker,
)

__all__ = [
    "ChangePlan",
    "ChangePlanItem",
    "ChangeRecord",
    "FileOwnershipCategory",
    "JournalState",
    "RiskLevel",
    "TransactionJournalEntry",
    "WorkspaceBaseline",
    "WorkspaceOperationType",
    "PathSafetyValidator",
    "PathSecurityViolation",
    "WorkspaceBaselineManager",
    "compute_file_sha256",
    "WorkspaceChangeLedger",
    "RiskApprovalGate",
    "WorkspaceJournalManager",
    "ChangePlanEngine",
    "CleanlinessChecker",
    "TerminalSafetyBroker",
    "GitDisciplineManager",
    "WorkspaceMutationBroker",
    "ConcurrencyConflictError",
    "MutationAuthorizationError",
]

