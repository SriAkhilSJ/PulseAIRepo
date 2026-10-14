"""Deterministic plan execution: the part a model must never improvise.

``execute_plan`` owns the mechanical sequence for every target — resolve the
device, run the build, install, launch, capture, clean up — and returns one
:class:`RunOutcome` whose stage results are the receipt's spine. Providers
describe *what* to run; this module decides *how* a plan is trusted:

* a required stage that fails stops the plan (no install onto a failed build);
* optional stages (``required=False``) record their failure and continue;
* every stage's full output is persisted next to the screenshots;
* a timeout is a failure with an explicit reason, never an empty success;
* background launches (dev servers, GUI apps) are tracked and reaped.
"""
from __future__ import annotations

import importlib
import json
import os
import shlex
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.targets.contract import (
    KIND_CLEANUP,
    Artifact,
    RunPlan,
    Stage,
    StageResult,
    TargetReceipt,
)
from src.targets.evidence import artifact_for, collect_artifacts

MAX_OUTPUT_CHARS = 6000
DEFAULT_TIMEOUT_MULTIPLIER = 1.0


@dataclass
class TargetRequest:
    """What the agent asked for, in one object every provider understands."""

    mode: str = "verify"                     # build | run | verify | test
    device: str = ""
    app_id: str = ""
    url: str = ""
    assertions: tuple[tuple[str, str], ...] = ()
    start_emulator: bool = True
    keep_running: bool = False
    no_cleanup: bool = False
    timeout_multiplier: float = DEFAULT_TIMEOUT_MULTIPLIER
    extra_args: tuple[str, ...] = ()
    workdir: str = ""

    def wants(self, *modes: str) -> bool:
        return self.mode in modes


@dataclass
class RunOutcome:
    plan: RunPlan
    results: list[StageResult] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    artifacts_dir: str = ""
    workspace: str = ""
    notes: list[str] = field(default_factory=list)
    failure_stage: str = ""
    failure_reason: str = ""
    dry_run: bool = False
    background: list[dict[str, Any]] = field(default_factory=list)
    #: Live Popen handles for background stages (never serialized).
    handles: list[Any] = field(default_factory=list, repr=False)
    #: Token values resolved while running (``device``, ``apk``, ...). Providers
    #: read this to name the real device in the receipt instead of guessing.
    tokens: dict[str, str] = field(default_factory=dict)

    def result(self, name: str) -> StageResult | None:
        for item in self.results:
            if item.stage.name == name:
                return item
        return None

    def output_of(self, *names: str) -> str:
        for name in names:
            item = self.result(name)
            if item is not None:
                return item.output
        return ""

    def all_output(self) -> str:
        return "\n".join(item.output for item in self.results)

    @property
    def blocked(self) -> bool:
        return bool(self.failure_reason)


# --------------------------------------------------------------------------- #
# Token resolution
# --------------------------------------------------------------------------- #

ResolverFn = Callable[[Path, "TargetRequest", Mapping[str, str]], str]
HandlerFn = Callable[[Mapping[str, Any]], "tuple[int, str]"]
_RESOLVER_CACHE: dict[str, Any] = {}


def load_resolver(dotted: str) -> Any:
    """Import ``module:function`` (cached); a broken reference returns None."""
    if dotted in _RESOLVER_CACHE:
        return _RESOLVER_CACHE[dotted]
    module_name, _, attribute = dotted.partition(":")
    try:
        module = importlib.import_module(module_name)
        target = getattr(module, attribute)
    except (ImportError, AttributeError, ValueError):
        return None
    _RESOLVER_CACHE[dotted] = target
    return target


class TokenResolutionError(RuntimeError):
    pass


def resolve_tokens(
    argv: Sequence[str],
    *,
    workspace: Path,
    request: TargetRequest,
    plan: RunPlan,
    artifacts_dir: Path,
    resolvers: Mapping[str, str] | None = None,
    sink: dict[str, str] | None = None,
) -> list[str]:
    """Substitute ``{tokens}`` in a stage's argv (or fail loudly)."""
    tokens: dict[str, str] = {
        "workspace": str(workspace),
        "artifacts": str(artifacts_dir),
        "app_id": request.app_id or plan.app_id,
        "device": request.device or plan.device,
        "url": request.url,
    }
    table = dict(resolvers or {})
    out: list[str] = []
    for part in argv:
        rendered = part
        for _ in range(4):  # resolvers may themselves reference resolved tokens
            names = _tokens_in(rendered)
            if not names:
                break
            progress = False
            for name in names:
                if tokens.get(name):
                    rendered = rendered.replace("{" + name + "}", tokens[name])
                    progress = True
                    continue
                dotted = table.get(name)
                if not dotted:
                    raise TokenResolutionError(
                        f"stage references {{{name}}} but the provider supplied no resolver"
                    )
                resolver = load_resolver(dotted)
                if resolver is None:
                    raise TokenResolutionError(f"resolver {dotted} could not be imported")
                try:
                    value = str(resolver(workspace, request, tokens) or "")
                except Exception as exc:  # resolver failures are plan failures
                    raise TokenResolutionError(f"resolving {{{name}}} failed: {exc}") from exc
                if not value:
                    raise TokenResolutionError(f"{{{name}}} resolved to nothing")
                tokens[name] = value
                if sink is not None:
                    sink[name] = value
                rendered = rendered.replace("{" + name + "}", value)
                progress = True
            if not progress:
                break
        out.append(rendered)
    return out


def _tokens_in(text: str) -> list[str]:
    names: list[str] = []
    index = 0
    while True:
        start = text.find("{", index)
        if start == -1:
            return names
        end = text.find("}", start)
        if end == -1:
            return names
        name = text[start + 1:end].strip()
        if name and all(ch.isalnum() or ch in "_-" for ch in name):
            names.append(name)
        index = end + 1


def shlex_join(argv: Sequence[str]) -> str:
    try:
        return shlex.join(list(argv))
    except AttributeError:  # pragma: no cover - very old Pythons
        return " ".join(argv)


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #


def evidence_dir(workspace: Path, target: str, *, base: str | os.PathLike[str] | None = None) -> Path:
    override = str(base or os.environ.get("CRUSORAI_TARGET_EVIDENCE_DIR") or "").strip()
    root = Path(override) if override else Path(workspace) / ".crusorai" / "target-evidence"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    directory = root / f"{target}-{stamp}"
    for attempt in (directory, Path(workspace) / ".crusorai" / "target-evidence" / f"{target}-{stamp}-{os.getpid()}"):
        try:
            attempt.mkdir(parents=True, exist_ok=True)
            return attempt
        except OSError:
            continue
    return Path(workspace)


def _stage_env(stage: Stage, base: Mapping[str, str] | None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update({str(key): str(value) for key, value in stage.env})
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CI", "1")
    return env


def _truncate(text: str) -> str:
    text = text or ""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    head = text[: MAX_OUTPUT_CHARS // 2]
    tail = text[-MAX_OUTPUT_CHARS // 2:]
    return f"{head}\n... [{len(text) - MAX_OUTPUT_CHARS} chars elided] ...\n{tail}"


def execute_plan(
    plan: RunPlan,
    request: TargetRequest,
    *,
    workspace: str | Path,
    resolvers: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
) -> RunOutcome:
    """Run every stage in order; stop at the first required failure."""
    root = Path(workspace).resolve()
    artifacts = evidence_dir(root, plan.target)
    outcome = RunOutcome(
        plan=plan, workspace=str(root), artifacts_dir=str(artifacts),
        notes=list(plan.notes), dry_run=dry_run,
    )
    multiplier = max(0.25, float(request.timeout_multiplier or 1.0))
    halted = False
    try:
        for index, stage in enumerate(plan.stages, start=1):
            if halted and stage.kind != KIND_CLEANUP:
                outcome.results.append(StageResult(
                    stage=stage, exit_code=None, output="skipped: earlier required stage failed",
                    skipped=True, resolved_argv=stage.argv,
                ))
                continue
            timeout = int(max(5, stage.timeout_s * multiplier))
            if dry_run:
                # A preview must never need a device, an emulator or a build
                # output: show the raw argv exactly as the provider wrote it.
                rendered = shlex_join(list(stage.argv)) or f"[handler {stage.handler}]"
                outcome.results.append(StageResult(
                    stage=stage, exit_code=0, output=f"[dry-run] {rendered}",
                    resolved_argv=tuple(stage.argv),
                ))
                continue
            try:
                argv = resolve_tokens(
                    stage.argv, workspace=root, request=request, plan=plan,
                    artifacts_dir=artifacts, resolvers=resolvers, sink=outcome.tokens,
                ) if stage.argv else []
            except TokenResolutionError as exc:
                outcome.results.append(StageResult(
                    stage=stage, exit_code=None, output=f"plan error: {exc}",
                    resolved_argv=stage.argv,
                ))
                if stage.required:
                    halted = True
                    outcome.failure_stage = stage.name
                    outcome.failure_reason = str(exc)
                continue

            result = _run_stage(
                stage, argv, workspace=root, artifacts_dir=artifacts, index=index,
                env=env, timeout=timeout, request=request, plan=plan,
                outcome=outcome, tokens=outcome.tokens,
            )
            outcome.results.append(result)
            outcome.artifacts.extend(result.artifacts)
            if not result.ok and stage.required:
                halted = True
                if not outcome.failure_reason:
                    outcome.failure_stage = stage.name
                    outcome.failure_reason = (
                        f"stage '{stage.name}' timed out after {timeout}s"
                        if result.timed_out else
                        f"stage '{stage.name}' exited {result.exit_code} "
                        f"({shlex_join(argv[:3])}{'...' if len(argv) > 3 else ''})"
                    )
    finally:
        if not request.keep_running:
            _reap_background(outcome)
    return outcome


def _run_stage(
    stage: Stage,
    argv: Sequence[str],
    *,
    workspace: Path,
    artifacts_dir: Path,
    index: int,
    env: Mapping[str, str] | None,
    timeout: int,
    request: TargetRequest,
    plan: RunPlan,
    outcome: RunOutcome,
    tokens: Mapping[str, str] | None = None,
) -> StageResult:
    if stage.handler:
        return _run_handler(
            stage, workspace=workspace, artifacts_dir=artifacts_dir, index=index,
            request=request, plan=plan, tokens=tokens or {},
        )
    if stage.background:
        return _start_background(
            stage, argv, workspace=workspace, artifacts_dir=artifacts_dir,
            index=index, env=env, outcome=outcome,
        )
    return _run_foreground(
        stage, argv, workspace=workspace, artifacts_dir=artifacts_dir,
        index=index, env=env, timeout=timeout,
    )


def _run_foreground(
    stage: Stage,
    argv: Sequence[str],
    *,
    workspace: Path,
    artifacts_dir: Path,
    index: int,
    env: Mapping[str, str] | None,
    timeout: int,
) -> StageResult:
    stage_env = _stage_env(stage, env)
    cwd = (workspace / stage.cwd).resolve() if stage.cwd not in ("", ".") else workspace
    started = time.monotonic()
    timed_out = False
    exit_code: int | None = None
    output = ""
    if not cwd.exists():
        return StageResult(
            stage=stage, exit_code=None, output=f"working directory does not exist: {cwd}",
            resolved_argv=tuple(argv),
        )
    if stage.stdout_file:
        return _capture_binary(stage, argv, cwd=cwd, env=stage_env, artifacts_dir=artifacts_dir,
                               index=index, started=started, timeout=timeout)
    try:
        proc = subprocess.run(
            list(argv), cwd=str(cwd), env=stage_env, capture_output=True,
            text=True, timeout=timeout, check=False,
        )
        exit_code = proc.returncode
        output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        output = f"TIMEOUT after {timeout}s\n{partial}"
    except FileNotFoundError:
        output = f"executable not found: {argv[0]} (install it, or set the tool's CRUSORAI_* path override)"
    except OSError as exc:
        output = f"could not run {argv[0]}: {exc}"

    result = StageResult(
        stage=stage, exit_code=exit_code, output=_truncate(output),
        duration_s=time.monotonic() - started, timed_out=timed_out,
        resolved_argv=tuple(argv),
    )
    _persist_log(artifacts_dir, index, stage, argv, result)
    for pattern in stage.artifact_globs:
        result.artifacts.extend(
            collect_artifacts(workspace, (pattern,), kind=f"{stage.kind}-artifact")
        )
    return result


def _capture_binary(
    stage: Stage,
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    artifacts_dir: Path,
    index: int,
    started: float,
    timeout: int,
) -> StageResult:
    """Stream raw stdout (a PNG, a tarball) into the evidence directory."""
    target = Path(stage.stdout_file)
    if not target.is_absolute():
        target = artifacts_dir / target
    target.parent.mkdir(parents=True, exist_ok=True)
    timed_out = False
    exit_code: int | None = None
    try:
        with open(target, "wb") as handle:
            proc = subprocess.run(
                list(argv), cwd=str(cwd), env=env, stdout=handle,
                stderr=subprocess.PIPE, timeout=timeout, check=False,
            )
        exit_code = proc.returncode
        stderr = (proc.stderr or b"").decode("utf-8", "replace")
        size = target.stat().st_size if target.exists() else 0
        output = f"raw stdout -> {target.name} ({size} bytes)\n{stderr}".strip()
    except subprocess.TimeoutExpired:
        timed_out = True
        output = f"TIMEOUT after {timeout}s while capturing {target.name}"
    except FileNotFoundError:
        output = f"executable not found: {argv[0]}"
    except OSError as exc:
        output = f"could not capture {target.name}: {exc}"
    result = StageResult(
        stage=stage, exit_code=exit_code, output=output,
        duration_s=time.monotonic() - started, timed_out=timed_out,
        resolved_argv=tuple(argv),
    )
    if target.exists() and target.stat().st_size > 0:
        result.artifacts.append(artifact_for(target, kind=stage.name or "binary"))
    _persist_log(artifacts_dir, index, stage, argv, result)
    return result


def _start_background(
    stage: Stage,
    argv: Sequence[str],
    *,
    workspace: Path,
    artifacts_dir: Path,
    index: int,
    env: Mapping[str, str] | None,
    outcome: RunOutcome,
) -> StageResult:
    stage_env = _stage_env(stage, env)
    cwd = (workspace / stage.cwd).resolve() if stage.cwd not in ("", ".") else workspace
    log_path = artifacts_dir / f"{index:02d}-{stage.name.replace('/', '-')}.log"
    started = time.monotonic()
    try:
        handle = open(log_path, "wb")
    except OSError as exc:
        return StageResult(stage=stage, exit_code=1,
                           output=f"could not open background log: {exc}",
                           resolved_argv=tuple(argv))
    options: dict[str, Any] = {}
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        options["start_new_session"] = True
    try:
        proc = subprocess.Popen(  # noqa: S603 - argv list, never a shell string
            list(argv), cwd=str(cwd), env=stage_env,
            stdout=handle, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **options,
        )
    except (OSError, ValueError) as exc:
        handle.close()
        return StageResult(stage=stage, exit_code=1, output=f"could not start {argv[0]}: {exc}",
                           resolved_argv=tuple(argv))
    record = {
        "name": stage.name, "pid": proc.pid, "argv": list(argv),
        "log": str(log_path), "started": time.time(),
    }
    outcome.background.append(record)
    outcome.handles.append(proc)
    _write_pid_file(artifacts_dir, outcome.background)
    return StageResult(
        stage=stage, exit_code=0,
        output=f"started background pid={proc.pid}: {shlex_join(argv)}\nlog: {log_path.name}",
        duration_s=time.monotonic() - started, resolved_argv=tuple(argv),
    )


def _write_pid_file(artifacts_dir: Path, records: Sequence[Mapping[str, Any]]) -> None:
    try:
        (artifacts_dir / "background-pids.json").write_text(
            json.dumps(list(records), indent=2), encoding="utf-8",
        )
    except OSError:
        return


def _run_handler(
    stage: Stage,
    *,
    workspace: Path,
    artifacts_dir: Path,
    index: int,
    request: TargetRequest,
    plan: RunPlan,
    tokens: Mapping[str, str] | None = None,
) -> StageResult:
    handler: HandlerFn | None = load_resolver(stage.handler)
    started = time.monotonic()
    if handler is None:
        return StageResult(stage=stage, exit_code=1,
                           output=f"handler {stage.handler} could not be imported")
    context = {
        "workspace": workspace, "artifacts_dir": artifacts_dir,
        "request": request, "plan": plan, "stage": stage, "index": index,
        "args": dict(stage.env), "tokens": dict(tokens or {}),
    }
    try:
        exit_code, output = handler(context)  # type: ignore[misc]
    except Exception as exc:  # a broken handler is a failed stage, never a crash
        exit_code, output = 1, f"handler {stage.handler} raised {type(exc).__name__}: {exc}"
    result = StageResult(
        stage=stage, exit_code=int(exit_code), output=_truncate(str(output)),
        duration_s=time.monotonic() - started, resolved_argv=(stage.handler,),
    )
    _persist_log(artifacts_dir, index, stage, (stage.handler,), result)
    for pattern in stage.artifact_globs:
        result.artifacts.extend(
            collect_artifacts(workspace, (pattern,), kind=f"{stage.kind}-artifact")
        )
    return result


def _reap_background(outcome: RunOutcome) -> None:
    tree_stopped: set[int] = set()
    for record in list(outcome.background):
        pid = int(record.get("pid") or 0)
        if pid <= 0:
            continue
        try:
            if os.name == "nt":
                result = subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True, check=False, timeout=20,
                )
                if result.returncode == 0:
                    tree_stopped.add(pid)
            else:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                time.sleep(0.3)
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except OSError:
                    pass
                tree_stopped.add(pid)
        except (OSError, subprocess.SubprocessError):
            # The process may already have exited, or the platform tree-kill
            # utility may be unavailable. The owned Popen handle below is the
            # portable last-resort for the direct child.
            pass

    stopped = set(tree_stopped)
    # Reap our own children so a killed app is really gone (a zombie still
    # answers os.kill(pid, 0) and would look "alive" to the next probe). On
    # Windows, taskkill can fail or race with process startup; terminate the
    # owned child directly if it is still running, then always wait for it.
    for handle in outcome.handles:
        pid = int(getattr(handle, "pid", 0) or 0)
        try:
            if handle.poll() is None:
                try:
                    handle.kill()
                except OSError:
                    pass
            handle.wait(timeout=5)
            if handle.poll() is not None and pid > 0:
                stopped.add(pid)
        except (subprocess.SubprocessError, OSError, ValueError):
            continue

    for record in outcome.background:
        if int(record.get("pid") or 0) in stopped:
            record["stopped"] = True
    if outcome.background and outcome.artifacts_dir:
        _write_pid_file(Path(outcome.artifacts_dir), outcome.background)


def _persist_log(
    artifacts_dir: Path, index: int, stage: Stage, argv: Sequence[str], result: StageResult,
) -> None:
    name = f"{index:02d}-{stage.name.replace('/', '-')}.log"
    header = (
        f"$ {shlex_join(argv)}\n"
        f"# kind={stage.kind} required={stage.required} exit={result.exit_code} "
        f"timeout={result.timed_out} duration={result.duration_s:.2f}s\n\n"
    )
    try:
        (artifacts_dir / name).write_text(header + (result.output or ""), encoding="utf-8")
        result.artifacts.append(artifact_for(artifacts_dir / name, kind="log"))
    except OSError:
        return


def read_tail(path: str | Path, *, lines: int = 60) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"could not read {path}: {exc}"
    return "\n".join(text.splitlines()[-lines:])


def receipt_from(
    outcome: RunOutcome,
    *,
    provider: str,
    target: str,
    device: str = "",
    app_id: str = "",
    platform: str = "",
    notes: Sequence[str] = (),
) -> TargetReceipt:
    """Fold a RunOutcome into the receipt shape the verification gate understands."""
    receipt = TargetReceipt(
        target=target, provider=provider, device=device, app_id=app_id,
        platform=platform, stages=list(outcome.results),
        artifacts=list(outcome.artifacts), artifacts_dir=outcome.artifacts_dir,
        notes=[*outcome.notes, *notes],
    )
    if outcome.failure_reason:
        receipt.failed(outcome.failure_stage, outcome.failure_reason)
    return receipt


__all__ = [
    "MAX_OUTPUT_CHARS", "RunOutcome", "TargetRequest", "TokenResolutionError",
    "evidence_dir", "execute_plan", "load_resolver", "read_tail", "receipt_from",
    "resolve_tokens", "shlex_join",
]
