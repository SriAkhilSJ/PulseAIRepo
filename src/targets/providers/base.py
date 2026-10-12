"""Provider base class and host-aware command helpers.

A provider answers four questions about one build target:

1. **Is this workspace that target?** (``detect``)
2. **What is the plan?** (``plan`` → ordered stages, tokens, requirements)
3. **Did it actually work?** (``interpret`` → the evidence receipt)
4. **Can this host even do it?** (``host_support``)

Adding a platform must never require touching the graph, the gate or the
prompt: register a provider and the tools (`src/tools/target_tools.py`) pick it
up. That is the whole point of the abstraction.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.targets.contract import (
    KIND_BUILD,
    KIND_CLEANUP,
    KIND_INSTALL,
    KIND_LAUNCH,
    KIND_PROBE,
    KIND_TEST,
    Artifact,
    RunPlan,
    Stage,
    TargetReceipt,
)
from src.targets.detect import TargetCandidate
from src.targets.runner import RunOutcome, TargetRequest, receipt_from
from src.targets.toolchain import ALL_HOSTS, host_platform


class PlanUnavailable(RuntimeError):
    """The provider cannot build a plan on this workspace/host (with a reason)."""


def tool_path(tool_id: str, fallback: str = "") -> str:
    """Resolve an executable at plan time, honouring the ``CRUSORAI_*`` override.

    Resolving here (instead of hardcoding a name in argv) is what makes a
    custom SDK path, a container image or a CI cache work without a second
    configuration surface.
    """
    from src.targets.toolchain import TOOLS_BY_ID, sdk_candidates

    spec = TOOLS_BY_ID.get(tool_id)
    if spec is None:
        return fallback or tool_id
    override = os.environ.get(spec.env_override, "").strip() if spec.env_override else ""
    for candidate in ([override] if override else []) + list(spec.commands):
        if candidate and os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    # Android tooling is routinely installed without touching PATH (Android Studio
    # on Windows especially): resolve it out of the SDK root before giving up, so the
    # plan runs the same binary the doctor reported.
    for candidate in sdk_candidates(spec):
        if Path(candidate).exists():
            return candidate
    return fallback or (spec.commands[0] if spec.commands else tool_id)


def node_bin(name: str) -> str:
    """Resolve a Node CLI the way the host actually spells it (``npm.cmd``)."""
    return tool_path(name, fallback=name)


def gradle_argv(workspace: str | Path, *args: str) -> list[str]:
    """Prefer the committed wrapper (reproducible Gradle) over a global one."""
    root = Path(workspace)
    for wrapper in ("gradlew.bat", "gradlew"):
        candidate = root / wrapper
        if candidate.is_file():
            if wrapper.endswith(".bat") and os.name != "nt":
                return ["cmd", "/c", str(candidate), *args]
            return [str(candidate), *args]
    return [tool_path("gradle", fallback="gradle"), *args]


def package_manager_argv(workspace: str | Path) -> list[str]:
    """The project's own package manager, or npm."""
    from src.targets.detect import package_manager

    name, _lockfile = package_manager(Path(workspace))
    if name == "npm":
        return [node_bin("npm")]
    if name == "bun":
        return [tool_path("bun", fallback="bun")]
    return [tool_path(name, fallback=name)]


def npm_run_argv(workspace: str | Path, script: str, *extra: str) -> list[str]:
    manager = package_manager_argv(workspace)
    if Path(manager[0]).name.startswith("npm"):
        return [*manager, "run", script, *extra]
    if Path(manager[0]).name.startswith("bun"):
        return [*manager, "run", script, *extra]
    return [*manager, "run", script, *extra]


def npx_argv(*args: str) -> list[str]:
    return [node_bin("npx"), *args]


class TargetProvider:
    """Base class every target provider implements."""

    id: str = ""
    label: str = ""
    kind: str = "platform"                 # platform | framework
    requires: tuple[str, ...] = ()
    recommended: tuple[str, ...] = ()
    host_platforms: tuple[str, ...] = ALL_HOSTS

    # ---- host ----------------------------------------------------------- #

    def host_support(self, host: str | None = None) -> tuple[bool, str]:
        resolved = host_platform(host)
        if resolved in self.host_platforms:
            return True, ""
        return False, (
            f"{self.label} needs {'/'.join(self.host_platforms)} on the machine running "
            f"the agent; this host is {resolved}."
        )

    # ---- detection ------------------------------------------------------ #

    def detect(self, workspace: str | Path) -> list[TargetCandidate]:
        return []

    def default_app_id(self, workspace: str | Path) -> str:
        for candidate in self.detect(workspace):
            if candidate.app_id:
                return candidate.app_id
        return ""

    # ---- planning ------------------------------------------------------- #

    def plan(self, workspace: str | Path, request: TargetRequest) -> RunPlan:
        raise NotImplementedError

    def requirements(self, workspace: str | Path, request: TargetRequest) -> tuple[str, ...]:
        return self.requires

    # ---- interpretation ------------------------------------------------ #

    def interpret(
        self, workspace: str | Path, request: TargetRequest, outcome: RunOutcome,
    ) -> TargetReceipt:
        receipt = receipt_from(
            outcome, provider=self.id, target=outcome.plan.target,
            device=outcome.tokens.get("device", ""),
            app_id=outcome.tokens.get("app_id", "") or outcome.plan.app_id,
            platform=host_platform(),
        )
        return receipt

    # ---- shared stage builders ----------------------------------------- #

    def build_stage(self, name: str, argv: Sequence[str], **kwargs: Any) -> Stage:
        kwargs.setdefault("kind", KIND_BUILD)
        return Stage(name=name, argv=tuple(argv), **kwargs)

    def install_stage(self, name: str, argv: Sequence[str], **kwargs: Any) -> Stage:
        kwargs.setdefault("kind", KIND_INSTALL)
        return Stage(name=name, argv=tuple(argv), **kwargs)

    def launch_stage(self, name: str, argv: Sequence[str], **kwargs: Any) -> Stage:
        kwargs.setdefault("kind", KIND_LAUNCH)
        return Stage(name=name, argv=tuple(argv), **kwargs)

    def probe_stage(self, name: str, argv: Sequence[str] = (), **kwargs: Any) -> Stage:
        kwargs.setdefault("kind", KIND_PROBE)
        return Stage(name=name, argv=tuple(argv), **kwargs)

    def test_stage(self, name: str, argv: Sequence[str], **kwargs: Any) -> Stage:
        kwargs.setdefault("kind", KIND_TEST)
        return Stage(name=name, argv=tuple(argv), **kwargs)

    def cleanup_stage(self, name: str, argv: Sequence[str] = (), **kwargs: Any) -> Stage:
        kwargs.setdefault("kind", KIND_CLEANUP)
        kwargs.setdefault("required", False)
        return Stage(name=name, argv=tuple(argv), **kwargs)

    def handler_stage(self, name: str, handler: str, kind: str = KIND_PROBE,
                      args: Mapping[str, Any] | None = None, **kwargs: Any) -> Stage:
        kwargs.setdefault("required", False)
        env = tuple(sorted({str(k): str(v) for k, v in dict(args or {}).items()}.items()))
        return Stage(name=name, argv=(), kind=kind, handler=handler, env=env, **kwargs)


def newest_file(workspace: str | Path, patterns: Sequence[str], *, suffixes: Sequence[str] = ()) -> str:
    """Absolute path of the newest file matching any glob (build outputs)."""
    root = Path(workspace)
    hits: list[Path] = []
    for pattern in patterns:
        try:
            hits.extend(path for path in root.glob(pattern) if path.is_file())
        except (OSError, ValueError):
            continue
    if suffixes:
        wanted = tuple(suffix.lower() for suffix in suffixes)
        hits = [path for path in hits if path.suffix.lower() in wanted]
    if not hits:
        return ""
    return str(max(hits, key=lambda path: path.stat().st_mtime if path.exists() else 0))


def evidence_path(outcome: RunOutcome, name: str) -> Path:
    return Path(outcome.artifacts_dir) / name


def read_evidence(outcome: RunOutcome, name: str, *, limit: int = 2_000_000) -> str:
    path = evidence_path(outcome, name)
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def artifact_for_evidence(outcome: RunOutcome, name: str, kind: str) -> Artifact | None:
    from src.targets.evidence import artifact_for

    path = evidence_path(outcome, name)
    if not path.exists() or path.stat().st_size == 0:
        return None
    return artifact_for(path, kind=kind)


def current_host() -> str:
    return host_platform(sys.platform)


__all__ = [
    "PlanUnavailable", "TargetProvider", "artifact_for_evidence", "current_host",
    "evidence_path", "gradle_argv", "newest_file", "npm_run_argv", "node_bin",
    "npx_argv", "package_manager_argv", "read_evidence", "tool_path",
]
