"""
run_state_ledger.py - Deterministic Run State Ledger for CrusorAI / PulseAI Core.

Maintains an immutable, persistent state ledger that survives context
compaction and token truncation:
- Objective & pinned acceptance criteria
- Workspace revision ledger
- Context residency map (file hashes currently resident in active window)
- Tool execution history & state deltas
- Verification debt set (hashes of failing checks)
- Recovery checkpoints
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Any


@dataclass
class ToolExecutionRecord:
    sequence: int
    tool_name: str
    target: str
    revision_before: int
    revision_after: int
    timestamp: float = field(default_factory=time.time)
    exit_code: Optional[int] = None
    state_mutated: bool = False
    new_information_provided: bool = True
    output_digest: str = ""
    # Bounded hashed line observations for advisory overlap detection only.
    observation_path: str = ""
    observation_start: int = 0
    observation_line_digests: tuple[str, ...] = ()


@dataclass
class AgentRunState:
    session_id: str
    objective: str = ""
    current_revision: int = 0
    # path -> content_hash of files verified resident in active prompt
    active_context_files: Dict[str, str] = field(default_factory=dict)
    # Set of hashes of failing verification checks / tests
    verification_debt: Set[str] = field(default_factory=set)
    execution_history: List[ToolExecutionRecord] = field(default_factory=list)
    actions_since_last_progress: int = 0
    checkpoints: Dict[str, Any] = field(default_factory=dict)

    def record_tool_call(
        self,
        tool_name: str,
        target: str,
        state_mutated: bool = False,
        new_info: bool = True,
        exit_code: Optional[int] = None,
        output_text: str = "",
        observation_path: str = "",
        observation_start: int = 0,
        observation_line_digests: tuple[str, ...] = (),
    ) -> ToolExecutionRecord:
        """Record a tool execution and update revision & progress counters."""
        rev_before = self.current_revision
        if state_mutated:
            self.current_revision += 1
            self.actions_since_last_progress = 0
        elif new_info:
            self.actions_since_last_progress = 0
        else:
            self.actions_since_last_progress += 1

        output_hash = (
            hashlib.sha256(output_text.encode("utf-8", errors="ignore")).hexdigest()[:12]
            if output_text
            else ""
        )

        record = ToolExecutionRecord(
            sequence=len(self.execution_history) + 1,
            tool_name=tool_name,
            target=target,
            revision_before=rev_before,
            revision_after=self.current_revision,
            exit_code=exit_code,
            state_mutated=state_mutated,
            new_information_provided=new_info,
            output_digest=output_hash,
            observation_path=observation_path,
            observation_start=observation_start,
            observation_line_digests=observation_line_digests,
        )
        self.execution_history.append(record)
        return record

    def update_file_residency(self, file_path: str | Path, content_hash: str) -> None:
        """Mark a file hash as resident in the active context window."""
        resolved = str(Path(file_path).resolve())
        self.active_context_files[resolved] = content_hash

    def evict_file_residency(self, file_path: str | Path) -> None:
        """Evict a file from residency (e.g. after context compaction)."""
        resolved = str(Path(file_path).resolve())
        self.active_context_files.pop(resolved, None)

    def is_file_resident(
        self, file_path: str | Path, current_hash: str, active_prompt_text: str = ""
    ) -> bool:
        """Check if file content is confirmed resident in active prompt context."""
        resolved = str(Path(file_path).resolve())
        if resolved not in self.active_context_files:
            return False
        if self.active_context_files[resolved] != current_hash:
            return False
        if active_prompt_text:
            fname = Path(file_path).name
            short_h = current_hash[:8]
            # Must have either filename or hash fingerprint physically present in text
            if fname not in active_prompt_text and short_h not in active_prompt_text:
                return False
        return True

    def add_verification_debt(self, check_identifier: str) -> None:
        """Record a failing test or assertion check."""
        digest = hashlib.sha256(check_identifier.encode("utf-8")).hexdigest()[:16]
        self.verification_debt.add(digest)

    def resolve_verification_debt(self, check_identifier: str) -> None:
        """Clear a resolved test or assertion check."""
        digest = hashlib.sha256(check_identifier.encode("utf-8")).hexdigest()[:16]
        self.verification_debt.discard(digest)

    def snapshot(self, label: str) -> None:
        """Create a lightweight recovery checkpoint."""
        self.checkpoints[label] = {
            "revision": self.current_revision,
            "debt_count": len(self.verification_debt),
            "history_len": len(self.execution_history),
            "timestamp": time.time(),
        }


# Global session registry for state ledgers
_LEDGERS: Dict[str, AgentRunState] = {}


def get_run_state_ledger(session_id: str, objective: str = "") -> AgentRunState:
    """Retrieve or initialize the deterministic run state ledger for a session."""
    if session_id not in _LEDGERS:
        _LEDGERS[session_id] = AgentRunState(session_id=session_id, objective=objective)
    return _LEDGERS[session_id]
