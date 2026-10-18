"""Task-scoped runtime posture for the broad Scope IDE agent.

The product is not a coding-only agent.  It can research, inspect and create
workspace artifacts, operate tools/processes, browse UIs, and write/verify code.
The model should not pay for every capability on every request, though.

This module is the single, pure resolver from (task, client config) to an
immutable RuntimeProfile.  Tool binding, prompt guidance, telemetry, and the IDE
bridge can all consume the same object instead of independently re-classifying
work.  Deterministic capability order is part of the prompt-cache contract.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable


CAP_WORKSPACE_READ = "workspace_read"
CAP_WORKSPACE_WRITE = "workspace_write"
CAP_EXECUTION = "execution"
CAP_VERIFICATION = "verification"
CAP_RESEARCH = "research"
CAP_BROWSER = "browser"
CAP_DELEGATION = "delegation"
# Multi-platform delivery: the agent builds and PROVES an app on a real
# device/emulator/simulator or as a desktop window (src/targets/). Kept as
# separate capabilities because the tool waist, the prompt guidance and the
# verification gate all differ from browser-only UI work.
CAP_MOBILE_APP = "mobile_app"
CAP_DESKTOP_APP = "desktop_app"

CAPABILITY_ORDER: tuple[str, ...] = (
    CAP_WORKSPACE_READ,
    CAP_WORKSPACE_WRITE,
    CAP_EXECUTION,
    CAP_VERIFICATION,
    CAP_RESEARCH,
    CAP_BROWSER,
    CAP_DELEGATION,
    CAP_MOBILE_APP,
    CAP_DESKTOP_APP,
)
KNOWN_CAPABILITIES = frozenset(CAPABILITY_ORDER)


@dataclass(frozen=True)
class RuntimeProfile:
    """Immutable task posture shared by runtime consumers."""

    name: str
    capabilities: tuple[str, ...]
    reasons: tuple[str, ...] = ()

    def has(self, capability: str) -> bool:
        return capability in self.capabilities


_RESEARCH_PATTERNS = (
    r"\bresearch\b", r"\bsearch (?:the )?web\b", r"\bfind (?:online|sources|documentation)\b",
    r"\bcompare\b", r"\blatest\b", r"\bcurrent\b", r"\bnews\b", r"\bsource(?:s)?\b",
    r"\bmarket analysis\b", r"\bcompetitor(?:s| analysis)?\b", r"\bweb search\b",
)
_BROWSER_PATTERNS = (
    r"\bbrowser\b", r"\bwebsite\b", r"\bweb page\b", r"\bnavigate\b",
    r"\bscreenshot\b", r"\bclick\b", r"\bfill (?:the )?form\b", r"\bui\b",
    r"\buser interface\b", r"\bfrontend\b", r"\bfront-end\b", r"\breact\b",
    r"\bnext\.?js\b", r"\bvue\b", r"\bsvelte\b", r"\bdashboard\b",
    r"\bcomponent\b", r"\bchat app\b", r"\bweb app(?:lication)?\b",
)
# If a prompt names a native target, generic UI/React terms describe that app's
# UI—not a browser session. Only add browser tools to a mixed native+web task
# when it also identifies an actual web surface (including React, but not React
# Native). This keeps the postures separate without blocking explicit hybrids.
_WEB_TARGET_PATTERNS = (
    r"\bweb\b", r"\bbrowser\b", r"\bwebsite\b", r"\bweb page\b",
    r"\bfrontend\b", r"\bfront-end\b", r"\breact\b(?![\s-]+native\b)",
    r"\bnext\.?js\b", r"\bvue\b", r"\bsvelte\b",
)
_CODE_PATTERNS = (
    r"\bcode(?:base)?\b", r"\bbug\b", r"\bdebug\b", r"\brefactor\b",
    r"\bfunction\b", r"\bclass\b", r"\bmethod\b", r"\bmodule\b", r"\bapi\b",
    r"\bendpoint\b", r"\bcompile\b", r"\btypecheck\b", r"\blint\b",
    r"\bpytest\b", r"\bunit tests?\b", r"\bintegration tests?\b", r"\btest suite\b",
    r"\btypescript\b", r"\bjavascript\b", r"\bpython\b", r"\brust\b", r"\bgolang\b",
    r"\b\.py\b", r"\b\.tsx?\b", r"\b\.jsx?\b", r"\bpackage\.json\b",
    r"\bpyproject\.toml\b", r"\bsource file\b", r"\brepository\b", r"\brepo\b",
)
_ARTIFACT_PATTERNS = (
    r"\bcreate\b", r"\bwrite\b", r"\bbuild\b", r"\bgenerate\b", r"\bmake\b",
    r"\bedit\b", r"\bupdate\b", r"\bmodify\b", r"\bconvert\b", r"\bexport\b",
    r"\breport\b", r"\bdocument\b", r"\bpresentation\b", r"\bslides?\b",
    r"\bspreadsheet\b", r"\bworkbook\b", r"\bcsv\b", r"\bpdf\b", r"\bimage\b",
    r"\baudio\b", r"\bvideo\b", r"\bdiagram\b", r"\bfile\b", r"\bdataset\b",
)
_READ_PATTERNS = (
    r"\bread\b", r"\binspect\b", r"\banaly[sz]e\b", r"\bexplain\b",
    r"\breview\b", r"\bsummarize\b", r"\bfind in\b", r"\blocate\b",
    r"\bfolder\b", r"\bdirectory\b", r"\bworkspace\b", r"\bproject\b",
)
# Mobile/desktop vocabulary is deliberately specific: a bare "app" (or "app.py")
# must not turn a web task into a native-build posture. Framework names, device
# tooling and store names are the signals that actually imply a native target.
_MOBILE_PATTERNS = (
    r"\bandroid\b", r"\bapk\b", r"\baab\b", r"\bgradle\b", r"\bkotlin\b",
    r"\bjetpack\b", r"\bcompose\b", r"\bavd\b", r"\badb\b", r"\buiautomator\b",
    r"\bemulator\b", r"\bios\b", r"\biphone\b", r"\bipad\b", r"\bsimulator\b",
    r"\bsimctl\b", r"\bxcode\b", r"\bswiftui?\b", r"\bswift\b", r"\btestflight\b",
    r"\bflutter\b", r"\bdart\b", r"\breact native\b", r"\bexpo\b", r"\bmetro bundler\b",
    r"\bmobile app(?:lication)?\b", r"\bmobile\b", r"\bplay store\b", r"\bapp store\b",
    r"\bmobile ui\b", r"\bmaestro\b", r"\btablet app\b", r"\bapk build\b",
    r"\bmobile test\b",
)
_DESKTOP_PATTERNS = (
    r"\bdesktop app(?:lication)?\b", r"\belectron\b", r"\btauri\b", r"\bwails\b",
    r"\bneutralino\b", r"\bwinui\b", r"\bwpf\b", r"\bwindows forms\b", r"\bmaui\b",
    r"\b\.net desktop\b", r"\bnative window\b", r"\btray app\b", r"\bmenubar app\b",
    r"\binstaller\b", r"\b\.msi\b", r"\b\.dmg\b", r"\bappimage\b", r"\bsnap package\b",
    r"\bwindows app\b", r"\bmacos app\b", r"\blinux app\b", r"\bdesktop\b",
)
_EXECUTION_PATTERNS = (
    r"\brun\b", r"\bexecute\b", r"\binstall\b", r"\bterminal\b", r"\bshell\b",
    r"\bcommand\b", r"\bprocess\b", r"\bserver\b", r"\bport\b", r"\bdeploy\b",
    r"\bscaffold\b", r"\bconfigure\b", r"\bautomation\b", r"\bautomate\b",
)
_COMPLEX_PATTERNS = (
    r"\bmulti[- ]step\b", r"\barchitecture\b", r"\baudit\b", r"\bcomprehensive\b",
    r"\bend[- ]to[- ]end\b", r"\bseveral\b", r"\bmultiple\b", r"\bparallel\b",
)
# Naming the mechanism IS the signal: a user who says "subagent" or
# "delegate" wants delegation even when the job itself is small. The
# complex-task heuristic above cannot hear that, and an unbound
# delegate tool makes the flagship feature silently unavailable.
_DELEGATION_PATTERNS = (
    r"\bsub-?agents?\b", r"\bdelegat\w*\b", r"\bmulti-?agent\b",
)
# Media search/download/generation ride the research capability in
# the tool waist (tools/toolsets.py groups them there): an ask that
# names media is an external-content ask.
_MEDIA_PATTERNS = (
    r"\bimage\b", r"\bpicture\b", r"\bphoto\b", r"\billustration\b",
    r"\bvideo\b", r"\baudio\b", r"\bmedia\b",
)


def _matches(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _client_capabilities(config: Any) -> tuple[str, ...]:
    """Read an optional IDE/client capability extension.

    Accepted locations keep the pure resolver useful with either a LangGraph
    RunnableConfig or a plain dictionary:
      configurable.scope_capabilities
      configurable.capabilities
      scope_capabilities
      capabilities

    Unknown names are ignored: a client may never invent a runtime capability.
    """
    if not isinstance(config, dict):
        return ()
    nested = config.get("configurable")
    sources = [nested] if isinstance(nested, dict) else []
    sources.append(config)
    raw = None
    for source in sources:
        raw = source.get("scope_capabilities")
        if raw is None:
            raw = source.get("capabilities")
        if raw is not None:
            break
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return ()
    selected = {str(item).strip().lower() for item in raw}
    return tuple(cap for cap in CAPABILITY_ORDER if cap in selected)


def _ordered(capabilities: set[str]) -> tuple[str, ...]:
    return tuple(cap for cap in CAPABILITY_ORDER if cap in capabilities)


def _profile_name(capabilities: set[str]) -> str:
    if CAP_MOBILE_APP in capabilities and CAP_DESKTOP_APP in capabilities:
        return "multi_platform_engineering"
    if CAP_MOBILE_APP in capabilities:
        return "mobile_engineering"
    if CAP_DESKTOP_APP in capabilities:
        return "desktop_engineering"
    if CAP_BROWSER in capabilities and CAP_VERIFICATION in capabilities:
        return "ui_engineering"
    if CAP_VERIFICATION in capabilities:
        return "coding"
    if CAP_RESEARCH in capabilities and CAP_WORKSPACE_WRITE in capabilities:
        return "research_artifact"
    if CAP_RESEARCH in capabilities:
        return "research"
    if CAP_WORKSPACE_WRITE in capabilities:
        return "artifact"
    if CAP_EXECUTION in capabilities:
        return "operations"
    if CAP_WORKSPACE_READ in capabilities:
        return "workspace"
    return "general"


def resolve_runtime_profile(task: str, config: Any = None) -> RuntimeProfile:
    """Resolve a broad IDE task into a focused, deterministic posture."""
    text = " ".join((task or "").lower().split())
    explicit = _client_capabilities(config)
    capabilities: set[str] = set(explicit)
    reasons: list[str] = []
    strict = False
    if isinstance(config, dict):
        nested = config.get("configurable")
        strict = bool(
            (nested or {}).get("scope_capabilities_strict", False)
            if isinstance(nested, dict)
            else config.get("scope_capabilities_strict", False)
        )
    if strict:
        return RuntimeProfile(
            name=_profile_name(capabilities),
            capabilities=_ordered(capabilities),
            reasons=("client_strict",),
        )

    research = _matches(text, _RESEARCH_PATTERNS)
    mobile = _matches(text, _MOBILE_PATTERNS)
    desktop = _matches(text, _DESKTOP_PATTERNS)
    browser = _matches(text, _BROWSER_PATTERNS)
    if (mobile or desktop) and not _matches(text, _WEB_TARGET_PATTERNS):
        browser = False
    coding = _matches(text, _CODE_PATTERNS)
    artifact = _matches(text, _ARTIFACT_PATTERNS)
    workspace_read = _matches(text, _READ_PATTERNS)
    execution = _matches(text, _EXECUTION_PATTERNS)
    complex_task = _matches(text, _COMPLEX_PATTERNS) or len(text) > 240

    if research:
        capabilities.add(CAP_RESEARCH)
        reasons.append("research")
    if workspace_read or coding or artifact:
        capabilities.add(CAP_WORKSPACE_READ)
        reasons.append("workspace")
    if artifact:
        capabilities.add(CAP_WORKSPACE_WRITE)
        reasons.append("artifact")
    if execution or artifact or coding:
        capabilities.add(CAP_EXECUTION)
        reasons.append("execution")
    if coding:
        capabilities.update({
            CAP_WORKSPACE_READ,
            CAP_WORKSPACE_WRITE,
            CAP_EXECUTION,
            CAP_VERIFICATION,
        })
        reasons.append("coding")
    if browser:
        capabilities.add(CAP_BROWSER)
        reasons.append("browser")
        # UI engineering needs code verification; a browser-only navigation
        # task does not. Browser terms shared with frontend tasks are split by
        # whether coding/artifact signals are also present.
        if coding or artifact:
            capabilities.update({
                CAP_WORKSPACE_READ,
                CAP_WORKSPACE_WRITE,
                CAP_EXECUTION,
                CAP_VERIFICATION,
            })
    if mobile:
        # A native target is an engineering task, not a browse task: the plan
        # needs the workspace, the shell, and a build/run receipt to be provable.
        capabilities.update({
            CAP_MOBILE_APP, CAP_WORKSPACE_READ, CAP_WORKSPACE_WRITE,
            CAP_EXECUTION, CAP_VERIFICATION,
        })
        reasons.append("mobile")
    if desktop:
        capabilities.update({
            CAP_DESKTOP_APP, CAP_WORKSPACE_READ, CAP_WORKSPACE_WRITE,
            CAP_EXECUTION, CAP_VERIFICATION,
        })
        reasons.append("desktop")
    if complex_task:
        capabilities.add(CAP_DELEGATION)
        reasons.append("complex")
    if _matches(text, _DELEGATION_PATTERNS):
        capabilities.add(CAP_DELEGATION)
        reasons.append("delegation")
    if _matches(text, _MEDIA_PATTERNS):
        capabilities.add(CAP_RESEARCH)
        reasons.append("media")

    # Preserve explicit client additions in the reason trail without allowing
    # their input order to affect the capability order/cache key.
    if _client_capabilities(config):
        reasons.append("client")

    dedup_reasons = tuple(dict.fromkeys(reasons))
    return RuntimeProfile(
        name=_profile_name(capabilities),
        capabilities=_ordered(capabilities),
        reasons=dedup_reasons,
    )


__all__ = [
    "RuntimeProfile",
    "resolve_runtime_profile",
    "KNOWN_CAPABILITIES",
    "CAP_MOBILE_APP",
    "CAP_DESKTOP_APP",
    "CAP_WORKSPACE_READ",
    "CAP_WORKSPACE_WRITE",
    "CAP_EXECUTION",
    "CAP_VERIFICATION",
    "CAP_RESEARCH",
    "CAP_BROWSER",
    "CAP_DELEGATION",
]
