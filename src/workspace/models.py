"""
src/workspace/models.py - Workspace Discipline & Change Management Data Models.

Phase 11.3: Workspace Discipline & Change Management.
Provides deterministic data structures for:
1. File ownership categories (clean user, modified user, staged user, untracked user, agent-owned).
2. Workspace change operations (CREATE, MODIFY, DELETE, RENAME, MOVE).
3. Risk classifications and approval states.
4. Workspace baselines, change ledger entries, change plans, and transaction journals.
"""

from __future__ import annotations

import enum
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple


class WorkspaceOperationType(str, enum.Enum):
    """Operation types supported by the Central Workspace Mutation Broker."""
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    RENAME = "RENAME"
    MOVE = "MOVE"
    DIRECTORY_CREATE = "DIRECTORY_CREATE"
    DIRECTORY_REMOVE = "DIRECTORY_REMOVE"


class FileOwnershipCategory(str, enum.Enum):
    """
    Categorizes the ownership and baseline provenance of every file in the workspace.
    Distinguishes pre-existing user work from agent-generated modifications.
    """
    EXISTING_USER_CLEAN = "EXISTING_USER_CLEAN"
    EXISTING_USER_MODIFIED = "EXISTING_USER_MODIFIED"
    EXISTING_USER_STAGED = "EXISTING_USER_STAGED"
    EXISTING_USER_UNTRACKED = "EXISTING_USER_UNTRACKED"
    AGENT_CREATED = "AGENT_CREATED"
    AGENT_MODIFIED = "AGENT_MODIFIED"
    AGENT_DELETED = "AGENT_DELETED"
    AGENT_RENAMED = "AGENT_RENAMED"
    USER_SUPERSEDED_AGENT = "USER_SUPERSEDED_AGENT"  # User edited agent-created file


class RiskLevel(str, enum.Enum):
    """Risk tier of planned or requested workspace modifications."""
    LOW_RISK = "LOW_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    HIGH_RISK = "HIGH_RISK"
    PROHIBITED = "PROHIBITED"


class JournalState(str, enum.Enum):
    """State of an operation within the workspace transaction journal."""
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class WorkspaceBaseline:
    """Snapshot of workspace and Git state captured prior to any task modification."""
    workspace_root: str
    git_root: Optional[str]
    branch: Optional[str]
    commit_hash: Optional[str]
    clean_files: Dict[str, str] = field(default_factory=dict)       # rel_path -> sha256
    modified_files: Dict[str, str] = field(default_factory=dict)    # rel_path -> sha256
    staged_files: Dict[str, str] = field(default_factory=dict)      # rel_path -> sha256
    untracked_files: Dict[str, str] = field(default_factory=dict)   # rel_path -> sha256
    ignored_files: List[str] = field(default_factory=list)
    captured_timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkspaceBaseline:
        return cls(**data)


@dataclass
class ChangeRecord:
    """Immutable audit record of an agent-driven workspace change."""
    task_id: str
    workspace_id: str
    operation_id: str
    file_path: str  # workspace-relative normalized path
    operation_type: WorkspaceOperationType
    original_hash: Optional[str]
    new_hash: Optional[str]
    original_existence: bool
    change_reason: str
    related_requirement_ids: List[str] = field(default_factory=list)
    related_architecture_decisions: List[str] = field(default_factory=list)
    approval_ref: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    status: JournalState = JournalState.APPLIED
    verification_status: str = "PENDING"
    ownership_category: FileOwnershipCategory = FileOwnershipCategory.AGENT_CREATED
    destination_path: Optional[str] = None  # for rename/move

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["operation_type"] = self.operation_type.value
        d["status"] = self.status.value
        d["ownership_category"] = self.ownership_category.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ChangeRecord:
        data_c = dict(data)
        data_c["operation_type"] = WorkspaceOperationType(data_c["operation_type"])
        data_c["status"] = JournalState(data_c["status"])
        data_c["ownership_category"] = FileOwnershipCategory(data_c["ownership_category"])
        return cls(**data_c)


@dataclass
class ChangePlanItem:
    """Specific file change declared in a ChangePlan."""
    file_path: str
    operation: WorkspaceOperationType
    reason: str
    related_requirements: List[str] = field(default_factory=list)
    related_decisions: List[str] = field(default_factory=list)
    destination_path: Optional[str] = None


@dataclass
class ChangePlan:
    """Declared engineering change plan constructed before executing mutations."""
    plan_id: str
    task_id: str
    intended_outcome: str
    items: List[ChangePlanItem] = field(default_factory=list)
    expected_dependencies: List[str] = field(default_factory=list)
    risk_classification: RiskLevel = RiskLevel.LOW_RISK
    required_approvals: List[str] = field(default_factory=list)
    expected_tests: List[str] = field(default_factory=list)
    expected_cleanup: List[str] = field(default_factory=list)
    status: str = "DRAFT"  # DRAFT, APPROVED, IN_EXECUTION, COMPLETED, ABANDONED
    created_at: float = field(default_factory=time.time)
    revised_at: Optional[float] = None
    revisions: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def files_to_create(self) -> List[str]:
        return [item.file_path for item in self.items if item.operation == WorkspaceOperationType.CREATE]

    @property
    def files_to_modify(self) -> List[str]:
        return [item.file_path for item in self.items if item.operation == WorkspaceOperationType.MODIFY]

    @property
    def files_to_delete(self) -> List[str]:
        return [item.file_path for item in self.items if item.operation == WorkspaceOperationType.DELETE]

    @property
    def files_to_rename(self) -> List[Tuple[str, str]]:
        return [(item.file_path, item.destination_path or "") for item in self.items if item.operation in (WorkspaceOperationType.RENAME, WorkspaceOperationType.MOVE)]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["risk_classification"] = self.risk_classification.value
        d["items"] = [
            {
                "file_path": item.file_path,
                "operation": item.operation.value,
                "reason": item.reason,
                "related_requirements": item.related_requirements,
                "related_decisions": item.related_decisions,
                "destination_path": item.destination_path,
            }
            for item in self.items
        ]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ChangePlan:
        data_c = dict(data)
        data_c["risk_classification"] = RiskLevel(data_c["risk_classification"])
        data_c["items"] = [
            ChangePlanItem(
                file_path=i["file_path"],
                operation=WorkspaceOperationType(i["operation"]),
                reason=i["reason"],
                related_requirements=i.get("related_requirements", []),
                related_decisions=i.get("related_decisions", []),
                destination_path=i.get("destination_path"),
            )
            for i in data_c.get("items", [])
        ]
        return cls(**data_c)


@dataclass
class TransactionJournalEntry:
    """Atomic multi-file transaction journal entry for crash-safe rollback."""
    tx_id: str
    task_id: str
    operations: List[ChangeRecord] = field(default_factory=list)
    state: JournalState = JournalState.PLANNED
    start_time: float = field(default_factory=time.time)
    finish_time: Optional[float] = None
    rollback_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tx_id": self.tx_id,
            "task_id": self.task_id,
            "operations": [op.to_dict() for op in self.operations],
            "state": self.state.value,
            "start_time": self.start_time,
            "finish_time": self.finish_time,
            "rollback_error": self.rollback_error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TransactionJournalEntry:
        return cls(
            tx_id=data["tx_id"],
            task_id=data["task_id"],
            operations=[ChangeRecord.from_dict(op) for op in data.get("operations", [])],
            state=JournalState(data["state"]),
            start_time=data["start_time"],
            finish_time=data.get("finish_time"),
            rollback_error=data.get("rollback_error"),
        )

