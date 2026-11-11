"""Request-scoped mutation authorizations for graph tool execution.

SafeToolNode mints a scoped, digest-bound ``APPV-`` token only after the
human approval lifecycle (or an explicit session policy) has resolved. The
token travels with the tool invocation through ``RunnableConfig`` and is
consumed by the WorkspaceMutationBroker at the write edge.

Nothing here is a second approval system: the token is the existing
``RiskApprovalGate`` token, the queue is the existing ``ApprovalQueue``, and
the broker is the existing ``WorkspaceMutationBroker``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

_CONFIG_KEY = "mutation_authorizations"


@dataclass(frozen=True)
class MutationAuthorization:
    """One approved workspace operation, bound to path + digest + token."""

    tool_call_id: str
    path: str
    operation: str
    token: str
    digest: str
    approval_id: str = ""
    task_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "path": self.path,
            "operation": self.operation,
            "token": self.token,
            "digest": self.digest,
            "approval_id": self.approval_id,
            "task_id": self.task_id,
        }


def attach_mutation_authorizations(config, authorizations: Iterable[MutationAuthorization]):
    """Return a copy of ``config`` carrying the per-call authorizations.

    A copy is used so a parallel/sequential batch cannot mutate another
    caller's config, and so LangGraph checkpoint state never sees tokens.
    """
    auths = [a.as_dict() if isinstance(a, MutationAuthorization) else dict(a)
             for a in (authorizations or ())]
    if not auths:
        return config
    cloned = dict(config or {})
    configurable = dict(cloned.get("configurable") or {})
    configurable[_CONFIG_KEY] = auths
    cloned["configurable"] = configurable
    return cloned


def find_mutation_authorization(config, path: str, operation: str | None = None) -> dict | None:
    """Find the authorization for ``path`` (and optional operation)."""
    configurable = (config or {}).get("configurable", {}) or {}
    wanted = str(path or "").replace("\\", "/")
    for item in configurable.get(_CONFIG_KEY) or ():
        if str(item.get("path") or "").replace("\\", "/") != wanted:
            continue
        if operation and str(item.get("operation") or "").upper() != str(operation).upper():
            continue
        return dict(item)
    return None


def graph_requires_approval_token(config) -> bool:
    """True when this invocation belongs to the canonical desktop runtime.

    The canonical bridge sets ``canonical_runtime``; direct library/tool
    callers keep the historical broker semantics (ownership + risk checks)
    without a mandatory token.
    """
    configurable = (config or {}).get("configurable", {}) or {}
    if "canonical_runtime" in configurable:
        return bool(configurable.get("canonical_runtime"))
    return False
