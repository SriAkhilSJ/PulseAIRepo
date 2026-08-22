"""Pulse Reliability Benchmark v1 contract.

Canonical repository copy (benchmarks/pulse_reliability_v1/contract.py).

- Uses only dependencies already declared by PulseAIRepo (Pydantic v2).
- No import-time I/O, no model calls, no execution side effects.
- Explicit developer actions (load_suite, write_json_schemas) never run on import.

Design drafts and the benchmark contract document live outside the repository.
"""
from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

_TASK_ID = re.compile(r"^PBR-[0-9]{3}$")
_CHECK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Category(str, Enum):
    WORKSPACE = "workspace"
    CONTEXT = "context"
    EDITING = "editing"
    VERIFICATION = "verification"
    LIFECYCLE = "lifecycle"
    SECURITY = "security"


class Risk(str, Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    PROCESS = "process"


class NetworkPolicy(str, Enum):
    DENY = "deny"
    LOCALHOST_ONLY = "localhost-only"
    ALLOWLIST = "allowlist"


class Outcome(str, Enum):
    PASSED = "passed"
    FAILED_FUNCTIONAL = "failed_functional"
    FAILED_VERIFICATION = "failed_verification"
    FAILED_SAFETY = "failed_safety"
    FAILED_HARNESS = "failed_harness"
    CANCELLED_EXPECTED = "cancelled_expected"
    CANCELLED_UNEXPECTED = "cancelled_unexpected"
    TIMEOUT = "timeout"
    ENVIRONMENT_UNAVAILABLE = "environment_unavailable"


class CheckClassification(str, Enum):
    PASSED = "passed"
    FAILED_NEW = "failed_new"
    FAILED_PREEXISTING = "failed_preexisting"
    FAILED_ENVIRONMENTAL = "failed_environmental"
    SKIPPED = "skipped"
    NOT_RUN = "not_run"
    UNKNOWN = "unknown"


CheckType = Literal[
    "command",
    "changed-files",
    "dom",
    "event",
    "process",
    "protocol",
    "context-ranking",
    "workspace-hash",
]

HardFailure = Literal[
    "workspace_escape",
    "secret_disclosure",
    "unapproved_destructive_action",
    "unapproved_network",
    "false_success_claim",
    "orphaned_process",
    "duplicate_mutation_after_replay",
    "concurrent_user_edit_overwritten",
    "checkpoint_restore_failed",
    "evaluator_modified",
]


class WorkspaceSpec(StrictModel):
    fixture: str
    git: bool = False
    line_endings: Literal["preserve", "lf", "crlf"] = "preserve"
    entry_count: int | None = Field(default=None, ge=0)

    @field_validator("fixture")
    @classmethod
    def fixture_is_safe_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError("fixture must be a non-empty safe relative path")
        return value


class CheckSpec(StrictModel):
    id: str
    type: CheckType
    command: tuple[str, ...] | None = None
    expected_exit: int | None = None
    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()
    selector: str | None = None
    event_type: str | None = None
    expected: dict[str, object] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def valid_check_id(cls, value: str) -> str:
        if not _CHECK_ID.fullmatch(value):
            raise ValueError("check id must be lowercase kebab-case")
        return value

    @model_validator(mode="after")
    def command_contract(self) -> "CheckSpec":
        if self.type == "command":
            if not self.command:
                raise ValueError("command checks require a non-empty argv array")
            if self.expected_exit is None:
                raise ValueError("command checks require expected_exit")
        elif self.command is not None or self.expected_exit is not None:
            raise ValueError("only command checks may declare command/expected_exit")
        return self


class TaskManifest(StrictModel):
    id: str
    version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    category: Category
    risk: Risk
    platforms: tuple[Literal["windows", "linux", "macos"], ...]
    timeout_seconds: int = Field(gt=0, le=3600)
    model_calls_allowed: bool
    network_policy: NetworkPolicy
    workspace: WorkspaceSpec
    prompt: str = Field(min_length=1)
    allowed_capabilities: tuple[str, ...]
    forbidden_capabilities: tuple[str, ...]
    checks: tuple[CheckSpec, ...]
    hard_failures: tuple[HardFailure, ...]

    @field_validator("id")
    @classmethod
    def valid_task_id(cls, value: str) -> str:
        if not _TASK_ID.fullmatch(value):
            raise ValueError("task id must match PBR-NNN")
        return value

    @model_validator(mode="after")
    def task_invariants(self) -> "TaskManifest":
        if not self.platforms:
            raise ValueError("at least one platform is required")
        if not self.checks:
            raise ValueError("at least one evaluator-owned check is required")
        check_ids = [item.id for item in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("check ids must be unique within a task")
        overlap = set(self.allowed_capabilities) & set(self.forbidden_capabilities)
        if overlap:
            raise ValueError(f"capabilities cannot be both allowed and forbidden: {overlap}")
        return self


class SuiteManifest(StrictModel):
    schema_id: Literal["pulse-benchmark-manifest/v1"]
    suite_id: Literal["pulse-reliability-v1"]
    version: int = Field(ge=1)
    tasks: tuple[TaskManifest, ...]

    @model_validator(mode="after")
    def unique_task_ids(self) -> "SuiteManifest":
        ids = [task.id for task in self.tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("task ids must be unique")
        if ids != sorted(ids):
            raise ValueError("tasks must be ordered by stable task id")
        return self


class Timing(StrictModel):
    startup: int = Field(default=0, ge=0)
    first_progress: int = Field(default=0, ge=0)
    first_token: int = Field(default=0, ge=0)
    completion: int = Field(default=0, ge=0)
    verification: int = Field(default=0, ge=0)
    shutdown: int = Field(default=0, ge=0)


class Usage(StrictModel):
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float = Field(default=0.0, ge=0)


class CheckResult(StrictModel):
    check_id: str
    classification: CheckClassification
    exit_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    evidence_ids: tuple[str, ...] = ()
    summary: str = ""


class ClaimResult(StrictModel):
    claim: str
    status: Literal["supported", "contradicted", "unverified"]
    evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def supported_claim_has_evidence(self) -> "ClaimResult":
        if self.status == "supported" and not self.evidence_ids:
            raise ValueError("supported claims require evidence ids")
        return self


class ChangeSummary(StrictModel):
    files: tuple[str, ...] = ()
    insertions: int = Field(default=0, ge=0)
    deletions: int = Field(default=0, ge=0)
    outside_scope: tuple[str, ...] = ()


class ProcessLeak(StrictModel):
    owner_type: str
    pid: int = Field(gt=0)
    parent_pid: int | None = Field(default=None, ge=0)
    command_digest: str


class BenchmarkResult(StrictModel):
    schema_id: Literal["pulse-benchmark-result/v1"]
    run_id: str
    task_id: str
    task_version: int = Field(ge=1)
    pulse_commit: str
    outcome: Outcome
    hard_failure: HardFailure | None = None
    timing_ms: Timing = Field(default_factory=Timing)
    usage: Usage = Field(default_factory=Usage)
    changes: ChangeSummary = Field(default_factory=ChangeSummary)
    checks: tuple[CheckResult, ...] = ()
    claims: tuple[ClaimResult, ...] = ()
    human_interventions: int = Field(default=0, ge=0)
    process_leaks: tuple[ProcessLeak, ...] = ()
    artifacts: tuple[str, ...] = ()

    @field_validator("task_id")
    @classmethod
    def valid_result_task_id(cls, value: str) -> str:
        if not _TASK_ID.fullmatch(value):
            raise ValueError("task id must match PBR-NNN")
        return value

    @model_validator(mode="after")
    def result_invariants(self) -> "BenchmarkResult":
        if self.hard_failure is not None and self.outcome == Outcome.PASSED:
            raise ValueError("a hard failure cannot have a passed outcome")
        if self.process_leaks and self.outcome == Outcome.PASSED:
            raise ValueError("process leaks cannot have a passed outcome")
        if any(claim.status == "contradicted" for claim in self.claims) and self.outcome == Outcome.PASSED:
            raise ValueError("contradicted claims cannot have a passed outcome")
        return self


def load_suite(path: str | Path) -> SuiteManifest:
    """Load and validate a suite manifest without executing any task."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return SuiteManifest.model_validate(payload)


def write_json_schemas(directory: str | Path) -> None:
    """Explicit developer action; never runs on import."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.schema.json").write_text(
        json.dumps(SuiteManifest.model_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (root / "result.schema.json").write_text(
        json.dumps(BenchmarkResult.model_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
