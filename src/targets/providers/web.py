"""Web target provider — the reference implementation, made explicit.

The repo already proves web UIs well (``src/tools/ui_verification.py``: typecheck,
start, navigate, snapshot, screenshot quality, cleanup). This provider does not
replace that; it gives the same *shape* to a dev server so the multi-platform
runner can start it and hand it to the browser pipeline, and so ``detect_targets``
answers "web" for a web workspace alongside the native candidates.

Element-level web proof stays where it is strongest: ``verify_ui_workspace`` /
``verify_ui_routes`` receipts (see ``docs/MULTI_PLATFORM_TARGETS.md``).
"""
from __future__ import annotations

import os
from pathlib import Path

from src.targets.contract import KIND_PROBE, RunPlan, Stage, TargetReceipt
from src.targets.detect import (
    TargetCandidate,
    any_path,
    has_script,
    node_manifest,
    package_manager,
)
from src.targets.providers.base import PlanUnavailable, TargetProvider, npm_run_argv
from src.targets.runner import RunOutcome, TargetRequest

WEB_PORT_ENV = "CRUSORAI_WEB_PORT"
DEFAULT_WEB_PORT = "3000"

_FRAMEWORKS = (
    ("next", "Next.js"),
    ("nuxt", "Nuxt"),
    ("@remix-run/react", "Remix"),
    ("astro", "Astro"),
    ("@sveltejs/kit", "SvelteKit"),
    ("vite", "Vite"),
    ("react-scripts", "Create React App"),
    ("vue", "Vue"),
    ("react", "React"),
)


def web_port() -> str:
    return os.environ.get(WEB_PORT_ENV, DEFAULT_WEB_PORT).strip() or DEFAULT_WEB_PORT


class WebProvider(TargetProvider):
    id = "web"
    label = "Web app (dev server + browser proof)"
    requires = ("node",)
    recommended = ("npm", "pnpm", "yarn", "bun")

    def _framework(self, root: Path) -> str:
        manifest = node_manifest(root)
        deps = {str(key).lower() for key in (
            list((manifest.get("dependencies") or {}).keys())
            + list((manifest.get("devDependencies") or {}).keys())
        )}
        for package, label in _FRAMEWORKS:
            if package in deps:
                return label
        return "Static site" if any_path(root, ("index.html",)) else "Node web app"

    def _dev_script(self, root: Path) -> str:
        manifest = node_manifest(root)
        for script in ("dev", "start", "serve", "preview"):
            if has_script(manifest, script):
                return script
        return ""

    # ---- detection ------------------------------------------------------ #

    def detect(self, workspace: str | Path) -> list[TargetCandidate]:
        root = Path(workspace)
        manifest = node_manifest(root)
        html = any_path(root, ("index.html", "public/index.html", "src/index.html"))
        if not manifest and not html:
            return []
        script = self._dev_script(root)
        confidence = 0.7 if script else 0.45
        if manifest and (root / "tsconfig.json").is_file():
            confidence += 0.05
        details = {
            "framework": self._framework(root),
            "dev_script": script,
            "manager": package_manager(root)[0],
            "has_build": has_script(manifest, "build"),
        }
        return [TargetCandidate(
            target=self.id, label=f"Web app — {details['framework']}", confidence=confidence,
            evidence=tuple(item for item in ("package.json", "index.html", "tsconfig.json",
                                             "vite.config.ts", "next.config.js")
                           if (root / item).exists()),
            framework=str(details["framework"]), app_id="", details=details,
        )]

    # ---- planning ------------------------------------------------------- #

    def plan(self, workspace: str | Path, request: TargetRequest) -> RunPlan:
        root = Path(workspace)
        detected = self.detect(root)
        details = detected[0].details if detected else {}
        script = str(details.get("dev_script") or "")
        stages: list[Stage] = []
        notes: list[str] = [f"framework={details.get('framework', 'unknown')}"]

        if request.mode == "build" or (details.get("has_build") and request.mode == "verify"):
            if details.get("has_build"):
                stages.append(Stage(
                    name="build", kind="build", required=True, timeout_s=1800,
                    argv=tuple(npm_run_argv(root, "build")),
                    note="production build; catches the compile errors a dev server hides",
                ))
        if request.mode != "build":
            if not script:
                raise PlanUnavailable(
                    "no dev/start script in package.json — add one, or use `verify_ui_workspace` with an "
                    "explicit command for a static site"
                )
            port = web_port()
            url = request.url or f"http://127.0.0.1:{port}"
            stages.extend([
                Stage(name="dev_server", kind=KIND_PROBE, background=True, required=True, timeout_s=120,
                      argv=tuple(npm_run_argv(root, script)), env=(("PORT", port), ("BROWSER", "none")),
                      note=f"starts `{details.get('manager', 'npm')} run {script}` on port {port}"),
                Stage(name="http_ready", kind=KIND_PROBE, required=True, timeout_s=300,
                      argv=(), handler="src.targets.probes:http_ready",
                      env=(("url", url), ("timeout_s", "180"))),
            ])
            notes.append(
                "element-level proof: call verify_ui_workspace(command=..., url="
                f"{url}, screenshot_name=...) — it reuses this same running app"
            )
        return RunPlan(
            target=self.id, provider=self.id, stages=tuple(stages), app_id=request.app_id,
            requires=self.requirements(root, request), notes=tuple(notes),
        )

    def requirements(self, workspace: str | Path, request: TargetRequest) -> tuple[str, ...]:
        needs = ["node"]
        if any_path(Path(workspace), ("package.json",)):
            needs.append("npm")
        return tuple(needs)

    # ---- interpretation ------------------------------------------------ #

    def interpret(self, workspace: str | Path, request: TargetRequest,
                  outcome: RunOutcome) -> TargetReceipt:
        receipt = super().interpret(workspace, request, outcome)
        ready = outcome.output_of("http_ready")
        if ready.strip():
            receipt.notes.append(ready.strip().splitlines()[0])
        return receipt


__all__ = ["WebProvider", "web_port"]
