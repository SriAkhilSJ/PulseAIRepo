"""Target registry: detection, resolution and the one entry point tools call.

Adding a platform means adding a provider here — nothing in the graph, the
verification gate or the prompt engine changes.
"""
from __future__ import annotations

from pathlib import Path

from src.targets.contract import Artifact, RunPlan, TargetReceipt, unavailable
from src.targets.detect import TargetCandidate
from src.targets.providers.android import AndroidProvider
from src.targets.providers.base import PlanUnavailable, TargetProvider
from src.targets.providers.desktop import DesktopProvider
from src.targets.providers.flutter import FlutterProvider
from src.targets.providers.ios import IOSProvider
from src.targets.providers.react_native import ReactNativeProvider
from src.targets.providers.web import WebProvider
from src.targets.providers.base import current_host
from src.targets.runner import TargetRequest, execute_plan, receipt_from
from src.targets.toolchain import requirement_report, missing as missing_tools

#: Every provider the agent can target, in detection precedence order.
PROVIDERS: tuple[TargetProvider, ...] = (
    FlutterProvider(),
    ReactNativeProvider(),
    AndroidProvider(),
    IOSProvider(),
    DesktopProvider(),
    WebProvider(),
)

#: Friendly names the model (or a human) actually types.
ALIASES: dict[str, str] = {
    "android": "android", "apk": "android", "gradle": "android", "kotlin": "android",
    "java-android": "android", "mobile": "android", "phone": "android",
    "ios": "ios", "iphone": "ios", "ipad": "ios", "swift": "ios", "xcode": "ios",
    "simulator": "ios", "ios-simulator": "ios", "ios-device": "ios", "iphone-device": "ios",
    "flutter": "flutter", "dart": "flutter",
    "react-native": "react-native", "rn": "react-native", "expo": "react-native",
    "react_native": "react-native",
    "desktop": "desktop", "electron": "desktop", "tauri": "desktop", "wails": "desktop",
    "neutralino": "desktop", "dotnet": "desktop", "wpf": "desktop", "winui": "desktop",
    "maui": "desktop", "windows": "desktop", "macos": "desktop", "linux": "desktop",
    "web": "web", "webapp": "web", "website": "web", "next": "web", "vite": "web",
    "browser": "web", "pwa": "web",
}


def providers() -> dict[str, TargetProvider]:
    return {provider.id: provider for provider in PROVIDERS}


def provider_ids() -> list[str]:
    return [provider.id for provider in PROVIDERS]


def get_provider(target: str) -> TargetProvider | None:
    """Resolve a user/model target name (with aliases) to a provider."""
    key = str(target or "").strip().lower()
    table = providers()
    if key in table:
        return table[key]
    canonical = ALIASES.get(key, "")
    if canonical:
        return table.get(canonical)
    if ":" in key:                       # flutter:android, react-native:ios
        head = key.split(":", 1)[0]
        return table.get(ALIASES.get(head, head))
    return None


def detect(workspace: str | Path) -> list[TargetCandidate]:
    """All plausible targets for this workspace, best confidence first."""
    root = Path(workspace)
    candidates: list[TargetCandidate] = []
    for provider in PROVIDERS:
        try:
            candidates.extend(provider.detect(root))
        except Exception:  # a broken detector must not hide other targets
            continue
    best: dict[str, TargetCandidate] = {}
    for candidate in candidates:
        current = best.get(candidate.target)
        if current is None or candidate.confidence > current.confidence:
            best[candidate.target] = candidate
    return sorted(best.values(), key=lambda item: (-item.confidence, item.target))


def detect_report(workspace: str | Path) -> str:
    candidates = detect(workspace)
    if not candidates:
        return (
            "No target detected: no Android manifest / Xcode project / Flutter pubspec / "
            "React Native package / desktop shell / web app was found in this workspace."
        )
    lines = [f"Detected {len(candidates)} target(s) — provider, confidence, identity, evidence:"]
    lines.extend("  " + candidate.render() for candidate in candidates)
    return "\n".join(lines)


def resolve_target(
    workspace: str | Path, requested: str = "",
) -> tuple[TargetProvider, list[TargetCandidate]]:
    """Pick the provider to use: explicit request → best detection → error."""
    candidates = detect(workspace)
    if requested.strip():
        provider = get_provider(requested)
        if provider is None:
            raise PlanUnavailable(
                f"unknown target {requested!r}. Known targets: {', '.join(provider_ids())} "
                f"(aliases: {', '.join(sorted(ALIASES))})"
            )
        return provider, [c for c in candidates if c.target == provider.id] or candidates
    if not candidates:
        raise PlanUnavailable(
            "no build target was detected in this workspace — pass target= explicitly "
            f"({', '.join(provider_ids())}) after telling the user what you see"
        )
    top = candidates[0]
    provider = get_provider(top.target)
    if provider is None:  # pragma: no cover - registry/detection drift
        raise PlanUnavailable(f"detected target {top.target!r} has no registered provider")
    return provider, candidates


def build_plan(workspace: str | Path, target: str, request: TargetRequest) -> RunPlan:
    provider, candidates = resolve_target(workspace, target)
    if not request.app_id:
        for candidate in candidates:
            if candidate.target == provider.id and candidate.app_id:
                request.app_id = candidate.app_id
                break
    return provider.plan(workspace, request)


def run(
    workspace: str | Path,
    target: str,
    request: TargetRequest | None = None,
    *,
    dry_run: bool = False,
) -> TargetReceipt:
    """The single entry point: resolve → plan → toolcheck → execute → interpret."""
    request = request or TargetRequest()
    try:
        provider, candidates = resolve_target(workspace, target)
    except PlanUnavailable as exc:
        return unavailable(target or "unknown", "unknown", str(exc))

    host_ok, host_reason = provider.host_support()
    if not host_ok:
        return unavailable(
            provider.id, provider.id, host_reason,
            notes=[f"detected targets: {', '.join(c.target for c in candidates[:4])}"],
        )

    try:
        plan = build_plan(workspace, provider.id, request)
    except PlanUnavailable as exc:
        return unavailable(provider.id, provider.id, str(exc))
    except Exception as exc:  # provider bug: fail closed with the reason
        return unavailable(provider.id, provider.id, f"{type(exc).__name__}: {exc}")

    absent = missing_tools(plan.requires)
    if absent and dry_run:
        # A plan preview is still useful on a machine that cannot run it yet:
        # show the stages and name exactly what is missing.
        plan = RunPlan(
            target=plan.target, provider=plan.provider, stages=plan.stages,
            device=plan.device, app_id=plan.app_id,
            notes=(*plan.notes, "MISSING TOOLCHAIN: " + ", ".join(s.spec.id for s in absent)),
            requires=plan.requires,
        )
    if absent and not dry_run:
        return unavailable(
            plan.target or provider.id, provider.id,
            "missing required toolchain: " + ", ".join(status.spec.id for status in absent)
            + "\n" + requirement_report(plan.requires),
            notes=list(plan.notes),
        )

    outcome = execute_plan(
        plan, request, workspace=workspace,
        resolvers=getattr(provider, "RESOLVERS", None) or {},
        dry_run=dry_run,
    )
    if dry_run:
        # No execution happened, so no evidence exists: return the plan itself
        # instead of an interpreted receipt that would imply observations.
        receipt = receipt_from(
            outcome, provider=provider.id, target=outcome.plan.target,
            app_id=outcome.plan.app_id, platform=current_host(),
            notes=("DRY RUN: this is the plan, nothing was executed",),
        )
        receipt.dry_run = True
        if request.assertions:
            receipt.notes.append(
                "PLANNED ASSERTIONS (checked against the live UI dump at run time): "
                + ", ".join(f"{kind}={value}" for kind, value in request.assertions)
            )
        return receipt
    receipt = provider.interpret(workspace, request, outcome)
    if host_reason:
        receipt.notes.insert(0, host_reason)
    return receipt


def plan_preview(workspace: str | Path, target: str, request: TargetRequest | None = None) -> str:
    """Human-readable plan (used by the dry-run path and by docs/tests)."""
    request = request or TargetRequest()
    receipt = run(workspace, target, request, dry_run=True)
    return receipt.to_text()


def all_artifacts(receipt: TargetReceipt) -> list[Artifact]:
    return list(receipt.artifacts)


__all__ = [
    "ALIASES", "PROVIDERS", "all_artifacts", "build_plan", "detect", "detect_report",
    "get_provider", "plan_preview", "provider_ids", "providers", "resolve_target", "run",
]
