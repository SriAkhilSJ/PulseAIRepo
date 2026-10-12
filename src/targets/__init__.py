"""Multi-platform build/run/verify for the Crusor agent (web → Android, iOS, desktop).

Why this package exists
-----------------------
The repo already answers "does the UI work?" for the web with one deterministic
receipt (``verify_ui_workspace``). Mobile and desktop apps need the same
guarantee with different mechanics, and without turning the graph, the prompt or
the verification gate into platform-specific code:

* :mod:`src.targets.contract` — the shared vocabulary (Stage, RunPlan,
  StageResult, Assertion, TargetReceipt). The receipt's ``✅/❌/⛔`` prefixes are
  the contract the existing gate already understands.
* :mod:`src.targets.detect` — bounded workspace fingerprinting (this workspace is
  an Android app / Flutter project / Electron shell / …).
* :mod:`src.targets.toolchain` — which executables each target needs, what is
  installed, and exactly how to install what is missing (the "doctor").
* :mod:`src.targets.runner` — executes a plan deterministically: device
  resolution, background launches, raw screenshot capture, timeouts, cleanup.
* :mod:`src.targets.probes` — deterministic non-command checks: HTTP readiness,
  CDP page existence, screenshot quality, process liveness.
* :mod:`src.targets.evidence` — decodes provider output into hashed artifacts,
  UI assertions and crash findings.
* :mod:`src.targets.providers` — one file per target family (Android, iOS,
  desktop, web) plus framework adapters (Flutter, React Native) that delegate
  their device work to the platform provider.
* :mod:`src.targets.registry` — detection, resolution and the single ``run()``
  entry point the agent tools call.

Design rules (deliberate, and enforced by ``src/tests/test_target_pipeline.py``)
-------------------------------------------------------------------------------
1. **No capability claims without evidence.** A green build is a build, not a
   working app; ``passed`` requires the platform-specific proof (foreground app,
   simulator install, CDP page, live process, non-blank screenshot, clean logs).
2. **Fail closed and loudly.** Missing toolchains, unsupported hosts (iOS on
   Linux), unknown tokens and timeouts produce ⛔/❌ receipts with the exact
   remediation, never a silent skip.
3. **The model decides once.** Plans are cheap, deterministic and reusable: the
   agent picks a target and the runtime owns the mechanical sequence.
4. **Never touch the network or a device at import time.**
"""
from __future__ import annotations

from src.targets.contract import (
    FAIL_PREFIX,
    PASS_PREFIX,
    UNAVAILABLE_PREFIX,
    Assertion,
    Artifact,
    RunPlan,
    Stage,
    StageResult,
    TargetReceipt,
    unavailable,
)
from src.targets.registry import (
    build_plan,
    detect,
    detect_report,
    get_provider,
    plan_preview,
    provider_ids,
    providers,
    resolve_target,
    run,
)
from src.targets.runner import RunOutcome, TargetRequest, execute_plan
from src.targets.toolchain import doctor_report, probe, requirement_report, target_readiness

__all__ = [
    "FAIL_PREFIX", "PASS_PREFIX", "UNAVAILABLE_PREFIX",
    "Assertion", "Artifact", "RunOutcome", "RunPlan", "Stage", "StageResult",
    "TargetReceipt", "TargetRequest",
    "build_plan", "detect", "detect_report", "doctor_report", "execute_plan",
    "get_provider", "plan_preview", "probe", "provider_ids", "providers",
    "requirement_report", "resolve_target", "run", "target_readiness", "unavailable",
]
