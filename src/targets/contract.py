"""Platform-neutral build/run/verify contracts for the Crusor agent.

The web pipeline in ``src/tools/ui_verification.py`` proved one thing: the model
should decide *what* must be verified ONCE, and deterministic runtime code owns
the mechanical sequence. That pattern generalizes to every shippable target, but
the mechanics do not:

* an **Android** app is proved by a Gradle build, an install, a launch, a UI
  dump and a crash-free ``logcat`` slice;
* an **iOS** app needs a simulator (``simctl``) or a physical device
  (``pymobiledevice3`` on non-macOS hosts);
* a **desktop** app (Electron / Tauri / WebView2) is proved by a window that
  renders a document the existing CDP browser tools can already read;
* a **Flutter / React Native** project is a *framework* that delegates its real
  device work to one of the three platform providers above.

This module is the contract all of them share. Providers
(``src/targets/providers/``) describe a target as an ordered plan of stages; the
runner executes that plan on the host; the receipt is the only thing the agent
is allowed to call evidence.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

KIND_BUILD = "build"
KIND_INSTALL = "install"
KIND_LAUNCH = "launch"
KIND_PROBE = "probe"
KIND_ASSERT = "assert"
KIND_TEST = "test"
KIND_CLEANUP = "cleanup"

STAGE_KINDS: tuple[str, ...] = (
    KIND_BUILD, KIND_INSTALL, KIND_LAUNCH, KIND_PROBE,
    KIND_ASSERT, KIND_TEST, KIND_CLEANUP,
)

# Host platforms, in the vocabulary of ``sys.platform``-derived names.
HOST_WINDOWS = "windows"
HOST_MACOS = "macos"
HOST_LINUX = "linux"

# Verdict prefixes. The graph's verification gate (``src/graphs/gates.py``)
# reads these prefixes, exactly like the UI verifier's receipts.
PASS_PREFIX = "✅ TARGET VERIFICATION PASSED"
FAIL_PREFIX = "❌ TARGET VERIFICATION FAILED"
UNAVAILABLE_PREFIX = "⛔ TARGET VERIFICATION UNAVAILABLE"
DRY_PREFIX = "🧭 TARGET PLAN (dry run, nothing executed)"


@dataclass(frozen=True)
class Stage:
    """One deterministic command in a target plan.

    ``argv`` entries may contain ``{token}`` placeholders resolved at run time
    by the runner (``{device}``, ``{apk}``, ``{app_id}``, ``{activity}``,
    ``{workspace}``). Placeholders that cannot be resolved fail the stage with
    an explicit reason instead of shelling out something wrong.
    """

    name: str
    argv: tuple[str, ...]
    kind: str = KIND_BUILD
    required: bool = True
    timeout_s: int = 900
    cwd: str = "."
    env: tuple[tuple[str, str], ...] = ()
    artifact_globs: tuple[str, ...] = ()
    note: str = ""
    # ``handler`` runs deterministic Python instead of a subprocess
    # (``module:function``, see ``src/targets/probes.py``) — used for HTTP
    # readiness, CDP discovery, file assertions and process liveness.
    handler: str = ""
    # ``stdout_file`` streams RAW stdout bytes to a file in the evidence
    # directory (adb screencap, binary captures). Implies ``text=False``.
    stdout_file: str = ""
    # ``background`` starts the process and returns immediately (dev servers,
    # GUI apps) so later probe stages can inspect a live target.
    background: bool = False

    def with_env(self, extra: Mapping[str, str]) -> "Stage":
        merged = dict(self.env)
        merged.update({str(k): str(v) for k, v in extra.items()})
        return Stage(
            name=self.name, argv=self.argv, kind=self.kind, required=self.required,
            timeout_s=self.timeout_s, cwd=self.cwd,
            env=tuple(sorted(merged.items())), artifact_globs=self.artifact_globs,
            note=self.note, handler=self.handler, stdout_file=self.stdout_file,
            background=self.background,
        )

    def render(self) -> str:
        return " ".join(self.argv)


@dataclass(frozen=True)
class RunPlan:
    """A provider's ordered answer to "how is this target built and proved?"."""

    target: str
    provider: str
    stages: tuple[Stage, ...]
    device: str = ""
    app_id: str = ""
    notes: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    host_supported: bool = True
    host_reason: str = ""

    def of_kind(self, kind: str) -> tuple[Stage, ...]:
        return tuple(stage for stage in self.stages if stage.kind == kind)


@dataclass
class Artifact:
    """A file a stage produced and that a human (or CI) can inspect."""

    path: str
    kind: str
    size_bytes: int = 0
    sha256: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        size = f"{self.size_bytes} B" if self.size_bytes else "size n/a"
        digest = f" sha256={self.sha256[:12]}" if self.sha256 else ""
        return f"{self.kind}: {self.path} ({size}{digest})"


@dataclass
class StageResult:
    stage: Stage
    exit_code: int | None
    output: str
    duration_s: float = 0.0
    skipped: bool = False
    timed_out: bool = False
    artifacts: list[Artifact] = field(default_factory=list)
    resolved_argv: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return (not self.skipped) and (not self.timed_out) and self.exit_code == 0

    def render(self, width: int = 12) -> str:
        verdict = "skip" if self.skipped else ("timeout" if self.timed_out else f"exit {self.exit_code}")
        argv = " ".join(self.resolved_argv or self.stage.argv)
        if not argv and self.stage.handler:
            argv = f"[deterministic] {self.stage.handler.split(':')[-1]}"
        if len(argv) > 96:
            argv = argv[:93] + "..."
        return (
            f"STAGE {self.stage.name[:width]:<{width}} {verdict:<9} "
            f"{self.duration_s:6.1f}s  {argv}"
        )


@dataclass
class Assertion:
    """A single text/selector expectation checked against the live UI."""

    kind: str          # "text" | "id" | "desc" | "package"
    expected: str
    found: bool
    where: str = ""

    def render(self) -> str:
        mark = "found" if self.found else "MISSING"
        return f"ASSERT {self.kind} {self.expected!r} -> {mark} ({self.where})"


@dataclass
class TargetReceipt:
    """The only shape the agent may present as proof for a non-web target."""

    target: str
    provider: str
    device: str = ""
    app_id: str = ""
    platform: str = ""
    stages: list[StageResult] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)
    crash_findings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    unavailable_reason: str = ""
    failure_reason: str = ""
    failure_stage: str = ""
    visual_quality: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    artifacts_dir: str = ""
    logs: list[str] = field(default_factory=list)
    dry_run: bool = False

    # -- verdict ---------------------------------------------------------- #

    @property
    def available(self) -> bool:
        return not self.unavailable_reason

    @property
    def passed(self) -> bool:
        if self.dry_run or not self.available or self.failure_reason:
            return False
        if any(not result.ok and result.stage.required for result in self.stages):
            return False
        if any(not assertion.found for assertion in self.assertions):
            return False
        if self.crash_findings:
            return False
        if self.visual_quality and self.visual_quality.get("passed") is False:
            return False
        return True

    def failed(self, stage: str, reason: str) -> "TargetReceipt":
        self.failure_stage = stage
        self.failure_reason = reason
        return self

    # -- rendering -------------------------------------------------------- #

    def to_text(self) -> str:
        header = f"{self.provider}:{self.device}" if self.device else self.provider
        if not self.available:
            return f"{UNAVAILABLE_PREFIX}: {self.unavailable_reason}"
        lines: list[str] = []
        if self.dry_run:
            lines.append(DRY_PREFIX)
        elif self.passed:
            lines.append(f"{PASS_PREFIX} ({header})")
        else:
            where = f" at {self.failure_stage}" if self.failure_stage else ""
            why = self.failure_reason or "required evidence is missing"
            lines.append(f"{FAIL_PREFIX}{where}: {why}")
        identity = [f"TARGET: {self.target}", f"PROVIDER: {self.provider}"]
        if self.device:
            identity.append(f"DEVICE: {self.device}")
        if self.app_id:
            identity.append(f"APP: {self.app_id}")
        if self.platform:
            identity.append(f"HOST: {self.platform}")
        lines.append("  ".join(identity))
        for result in self.stages:
            lines.append(result.render())
        for assertion in self.assertions:
            lines.append(assertion.render())
        if self.visual_quality:
            from src.tools.visual_quality import format_quality_receipt

            lines.append("VISUAL " + format_quality_receipt(self.visual_quality))
        if self.crash_findings:
            lines.append(f"CRASH SCAN failed ({len(self.crash_findings)} finding(s)):")
            lines.extend(f"  - {finding}" for finding in self.crash_findings[:8])
        elif any(result.stage.kind == KIND_PROBE and not result.skipped for result in self.stages) \
                and not self.dry_run:
            lines.append("CRASH SCAN clean")
        for artifact in self.artifacts:
            lines.append(f"EVIDENCE {artifact.render()}")
        if self.artifacts_dir:
            lines.append(f"ARTIFACTS DIR {self.artifacts_dir}")
        for note in self.notes:
            lines.append(f"NOTE {note}")
        tail = self._failure_tail()
        if tail and not self.passed:
            lines.append(f"DETAIL {tail}")
        return "\n".join(lines)

    def _failure_tail(self) -> str:
        for result in reversed(self.stages):
            if not result.ok:
                text = (result.output or "").strip()
                if not text:
                    continue
                lines = text.splitlines()
                head = "\n".join(lines[:6])
                tail = "\n".join(lines[-14:]) if len(lines) > 6 else ""
                return f"\n{head}\n...\n{tail}" if tail else f"\n{head}"
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "provider": self.provider,
            "device": self.device,
            "app_id": self.app_id,
            "platform": self.platform,
            "passed": self.passed,
            "dry_run": self.dry_run,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
            "failure_stage": self.failure_stage,
            "failure_reason": self.failure_reason,
            "assertions": [
                {"kind": a.kind, "expected": a.expected, "found": a.found, "where": a.where}
                for a in self.assertions
            ],
            "crash_findings": list(self.crash_findings),
            "visual_quality": dict(self.visual_quality),
            "stages": [
                {
                    "name": r.stage.name,
                    "kind": r.stage.kind,
                    "exit_code": r.exit_code,
                    "skipped": r.skipped,
                    "timed_out": r.timed_out,
                    "duration_s": round(r.duration_s, 3),
                    "argv": list(r.resolved_argv or r.stage.argv),
                }
                for r in self.stages
            ],
            "artifacts": [
                {"path": a.path, "kind": a.kind, "size_bytes": a.size_bytes,
                 "sha256": a.sha256}
                for a in self.artifacts
            ],
            "notes": list(self.notes),
        }


def unavailable(target: str, provider: str, reason: str, *, notes: Iterable[str] = ()) -> TargetReceipt:
    """Build an explicit "cannot prove this here" receipt (never a fake pass)."""
    return TargetReceipt(
        target=target, provider=provider, unavailable_reason=reason,
        notes=list(notes),
    )


def candidate_targets(ids: Sequence[str]) -> str:
    """Human-readable list used in "pick a target" refusals."""
    return ", ".join(dict.fromkeys(str(i) for i in ids if str(i).strip()))
