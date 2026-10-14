"""Desktop target provider (Electron, Tauri, Wails, Neutralino, .NET, Node).

Desktop verification is where agents usually cheat: "the build succeeded" is
not "the window opened". This provider makes the difference explicit.

* **Electron / WebView2 / Chromium** — launch with a remote-debugging port and
  *prove* a titled document exists (``cdp_ready``). Once that passes, the
  workbench's existing browser tools can drive and screenshot the app window
  over CDP: the same surface that already proves web UIs.
* **WKWebView (Tauri on macOS) / WebKitGTK (Linux)** — no CDP. The plan proves
  process liveness and says plainly that element-level assertions need
  ``tauri-driver``/WebDriver or Playwright, instead of implying verification
  that never happened.
* Headless Linux CI is wrapped in ``xvfb-run`` automatically.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from src.targets.contract import (
        KIND_LAUNCH,
    KIND_PROBE,
    RunPlan,
    Stage,
    TargetReceipt,
)
from src.targets.detect import (
    TargetCandidate,
    any_path,
    electron_entry,
    has_dependency,
    has_script,
    node_manifest,
    package_manager,
    read_json,
    read_text,
    tauri_config,
)
from src.targets.evidence import scan_crashes
from src.targets.providers.base import (
    PlanUnavailable,
    TargetProvider,
    artifact_for_evidence,
    npm_run_argv,
    npx_argv,
    read_evidence,
    tool_path,
)
from src.targets.runner import RunOutcome, TargetRequest
from src.targets.toolchain import HOST_LINUX, HOST_WINDOWS, host_platform

SHELL_LABELS = {
    "electron": "Electron desktop app",
    "tauri": "Tauri desktop app (Rust + WebView)",
    "wails": "Wails desktop app (Go + WebView)",
    "neutralino": "Neutralino desktop app",
    "dotnet": ".NET desktop app (WPF/WinUI/MAUI)",
    "node": "Node desktop shell",
}

CDP_PORT_ENV = "CRUSORAI_CDP_PORT"
DEFAULT_CDP_PORT = "9222"


def cdp_port() -> str:
    return os.environ.get(CDP_PORT_ENV, DEFAULT_CDP_PORT).strip() or DEFAULT_CDP_PORT


# --------------------------------------------------------------------------- #
# resolvers
# --------------------------------------------------------------------------- #


def _executable_like(path: Path) -> bool:
    if path.suffix.lower() in (".exe", ".app", ".bat", ".cmd", ".dll", ".pdb", ".rlib", ".d"):
        return path.suffix.lower() in (".exe", ".app")
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def resolve_desktop_binary(workspace: Path, request: TargetRequest, tokens: dict[str, str]) -> str:
    """Newest launchable binary a desktop build produced (per shell layout)."""
    shell = str(tokens.get("shell") or request.extra_args[0] if request.extra_args else "").strip()
    patterns_by_shell = {
        "tauri": ("src-tauri/target/debug/*", "src-tauri/target/release/*"),
        "wails": ("build/bin/*", "build/bin/**/*"),
        "neutralino": ("dist/*/*", "dist/**/*"),
        "electron": ("dist/**/*.exe", "out/**/*.exe"),
    }
    ordered = list(patterns_by_shell.get(shell, ()))
    ordered += ["src-tauri/target/debug/*", "build/bin/*", "dist/*/*", "out/**/*", "dist/**/*"]
    hits: list[Path] = []
    for pattern in dict.fromkeys(ordered):
        try:
            hits.extend(path for path in workspace.glob(pattern) if path.is_file())
        except (OSError, ValueError):
            continue
    usable = [path for path in hits if _executable_like(path) and path.stat().st_size > 20_000]
    if not usable:
        raise RuntimeError(
            "the build produced no launchable desktop binary (looked for src-tauri/target/debug/*, "
            "build/bin/*, dist/*/*) — read the build stage output above"
        )
    return str(max(usable, key=lambda path: path.stat().st_mtime))


# --------------------------------------------------------------------------- #
# provider
# --------------------------------------------------------------------------- #


class DesktopProvider(TargetProvider):
    id = "desktop"
    label = "Desktop app (Electron / Tauri / Wails / .NET)"
    requires = ("node",)
    recommended = ("playwright", "cargo", "dotnet", "xvfb-run")

    RESOLVERS = {"exe": "src.targets.providers.desktop:resolve_desktop_binary"}

    # ---- detection ------------------------------------------------------ #

    def _shell(self, workspace: Path) -> tuple[str, dict[str, object]]:
        root = Path(workspace)
        manifest = node_manifest(root)
        tauri = tauri_config(root)
        if tauri and (root / "src-tauri/tauri.conf.json").is_file():
            return "tauri", {
                "product": str(tauri.get("productName") or root.name),
                "frontend": str(tauri.get("build", {}).get("frontendDist") or "") \
                    if isinstance(tauri.get("build"), dict) else "",
            }
        if read_json(root, "wails.json"):
            return "wails", {}
        if read_json(root, "neutralino.config.json"):
            return "neutralino", {}
        if has_dependency(manifest, "electron", "electron-builder", "@electron-forge/cli"):
            return "electron", {
                "entry": electron_entry(root, manifest),
                "has_build": has_script(manifest, "build"),
                "has_start": has_script(manifest, "start", "electron", "electron:dev", "dev"),
            }
        dotnet = _dotnet_project(root)
        if dotnet:
            return "dotnet", {"project": dotnet}
        if manifest and has_script(manifest, "start") and has_dependency(
            manifest, "electron", "webview2", "@tauri-apps/api", "@neutralinojs/lib"
        ):
            return "node", {"has_start": True, "has_build": has_script(manifest, "build")}
        return "", {}

    def detect(self, workspace: str | Path) -> list[TargetCandidate]:
        root = Path(workspace)
        shell, details = self._shell(root)
        if not shell:
            return []
        evidence: tuple[str, ...] = ()
        if shell == "tauri":
            evidence = ("src-tauri/tauri.conf.json", "src-tauri/Cargo.toml")
            evidence = tuple(item for item in evidence if (root / item).exists())
        elif shell == "wails":
            evidence = ("wails.json",)
        elif shell == "neutralino":
            evidence = ("neutralino.config.json",)
        elif shell == "dotnet":
            project = str(details.get("project") or "")
            evidence = (project,) if project else ()
        else:
            evidence = tuple(any_path(root, ("package.json", "electron/main.js", "electron/main.ts")))
        app_id = ""
        if shell == "tauri":
            app_id = str(tauri_config(root).get("identifier") or "")
        return [TargetCandidate(
            target=self.id, label=SHELL_LABELS.get(shell, self.label), confidence=0.9,
            evidence=evidence, framework=shell, app_id=app_id, details=dict(details, shell=shell),
        )]

    # ---- planning ------------------------------------------------------- #

    def requirements(self, workspace: str | Path, request: TargetRequest) -> tuple[str, ...]:
        shell, _details = self._shell(Path(workspace))
        needs: list[str] = []
        if shell in ("electron", "node", "tauri", "wails", "neutralino"):
            needs.append("node")
        if shell == "tauri":
            needs.append("cargo")
        if shell == "wails":
            needs.extend(["go", "wails"])
        if shell == "dotnet":
            needs.append("dotnet")
        if host_platform() == HOST_LINUX and not os.environ.get("DISPLAY"):
            needs.append("xvfb-run")
        return tuple(needs)

    def plan(self, workspace: str | Path, request: TargetRequest) -> RunPlan:
        root = Path(workspace)
        shell, details = self._shell(root)
        if not shell:
            raise PlanUnavailable(
                "no desktop shell detected (looked for src-tauri/tauri.conf.json, wails.json, "
                "neutralino.config.json, an electron dependency, or a .csproj)"
            )
        stages: list[Stage] = []
        notes: list[str] = [f"shell={shell}"]

        if shell == "electron":
            stages.extend(self._node_stages(root, details))
            launch = self.launch_argv([*npx_argv("electron", f"--remote-debugging-port={cdp_port()}", ".")])
            stages.append(Stage(
                name="launch", kind=KIND_LAUNCH, background=True, required=True, timeout_s=120,
                argv=tuple(launch), env=(("ELECTRON_ENABLE_LOGGING", "1"),),
                note="Electron with a remote-debugging port (Chromium switch before the app path)",
            ))
            stages.append(Stage(name="cdp_ready", kind=KIND_PROBE, required=True, timeout_s=120,
                                argv=(), handler="src.targets.probes:cdp_ready",
                                env=(("port", cdp_port()), ("timeout_s", "60"),)))
            notes.append(
                f"the app window is debuggable at http://127.0.0.1:{cdp_port()} — element-level proof "
                "runs through the workbench browser tools (browser_navigate + browser_snapshot)"
            )
        elif shell == "tauri":
            stages.append(Stage(
                name="build", kind="build", required=True, timeout_s=3600,
                argv=(tool_path("cargo", fallback="cargo"), "build", "--manifest-path",
                      "src-tauri/Cargo.toml"),
                note="cargo build (debug) for the Tauri shell",
            ))
            env: list[tuple[str, str]] = []
            if host_platform() == HOST_WINDOWS:
                env.append(("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", f"--remote-debugging-port={cdp_port()}"))
            stages.append(Stage(
                name="launch", kind=KIND_LAUNCH, background=True, required=True, timeout_s=180,
                argv=tuple(self.launch_argv(["{exe}"])), env=tuple(env),
                note="starts the Tauri binary (WebView2 gets a CDP port on Windows)",
            ))
            stages.append(Stage(name="process_alive", kind=KIND_PROBE, required=True, timeout_s=90,
                                argv=(), handler="src.targets.probes:process_alive",
                                env=(("name", "launch"), ("timeout_s", "25"))))
            if host_platform() == HOST_WINDOWS:
                stages.append(Stage(name="cdp_ready", kind=KIND_PROBE, required=False, timeout_s=120,
                                    argv=(), handler="src.targets.probes:cdp_ready",
                                    env=(("port", cdp_port()), ("timeout_s", "45"))))
            else:
                notes.append(
                    "WKWebView (macOS) / WebKitGTK (Linux) expose no CDP endpoint: UI assertions need "
                    "`cargo install tauri-driver` + WebDriver, or Playwright. Liveness + logs are the "
                    "proof captured here."
                )
        elif shell in ("wails", "neutralino"):
            build_argv = (
                [tool_path("wails", fallback="wails"), "build"] if shell == "wails" else
                [*npx_argv("@neutralinojs/neu", "build")]
            )
            stages.append(Stage(name="build", kind="build", required=True, timeout_s=2400,
                                argv=tuple(build_argv)))
            stages.append(Stage(name="launch", kind=KIND_LAUNCH, background=True, required=True,
                                timeout_s=180, argv=tuple(self.launch_argv(["{exe}"]))))
            stages.append(Stage(name="process_alive", kind=KIND_PROBE, required=True, timeout_s=90,
                                argv=(), handler="src.targets.probes:process_alive",
                                env=(("name", "launch"), ("timeout_s", "20"))))
            notes.append("no CDP endpoint for this shell — liveness + logs are the captured proof")
        elif shell == "dotnet":
            project = str(details.get("project") or "")
            build_argv = [tool_path("dotnet", fallback="dotnet"), "build", "-c", "Debug"]
            if project:
                build_argv.append(project)
            stages.append(Stage(name="build", kind="build", required=True, timeout_s=1800,
                                argv=tuple(build_argv)))
            stages.append(Stage(name="launch", kind=KIND_LAUNCH, background=True, required=True,
                                timeout_s=180,
                                argv=tuple(self.launch_argv([
                                    tool_path("dotnet", fallback="dotnet"), "run", "--project", project,
                                    "--no-build",
                                ] if project else [tool_path("dotnet", fallback="dotnet"), "run", "--no-build"]))))
            stages.append(Stage(name="process_alive", kind=KIND_PROBE, required=True, timeout_s=90,
                                argv=(), handler="src.targets.probes:process_alive",
                                env=(("name", "launch"), ("timeout_s", "25"))))
            notes.append(
                "for element-level assertions on Windows desktop apps use WinAppDriver, FlaUI or "
                "Appium's Windows driver; on Linux use AT-SPI (pyatspi) — this plan captures "
                "liveness and logs"
            )
        else:  # node shell
            stages.extend(self._node_stages(root, details))
            stages.append(Stage(name="launch", kind=KIND_LAUNCH, background=True, required=True,
                                timeout_s=180,
                                argv=tuple(self.launch_argv(npm_run_argv(root, "start")))))
            stages.append(Stage(name="process_alive", kind=KIND_PROBE, required=True, timeout_s=90,
                                argv=(), handler="src.targets.probes:process_alive",
                                env=(("name", "launch"), ("timeout_s", "20"))))

        # No cleanup stage: background launches (the app itself, dev servers)
        # are reaped by the runner unless the caller asked to keep them running.
        return RunPlan(
            target=self.id, provider=self.id, stages=tuple(stages),
            app_id=str(details.get("product") or details.get("entry") or ""),
            requires=self.requirements(root, request), notes=tuple(notes),
        )

    # ---- helpers -------------------------------------------------------- #

    def _node_stages(self, root: Path, details: dict[str, object]) -> list[Stage]:
        stages: list[Stage] = []
        if not (root / "node_modules").exists():
            manager, lockfile = package_manager(root)
            argv = _install_argv(root, manager, lockfile)
            stages.append(Stage(name="install_deps", kind="build", required=True, timeout_s=1800,
                                argv=tuple(argv), note=f"{manager} install ({lockfile or 'no lockfile'})"))
        if details.get("has_build"):
            stages.append(Stage(name="build", kind="build", required=True, timeout_s=1800,
                                argv=tuple(npm_run_argv(root, "build"))))
        return stages

    def launch_argv(self, argv: list[str]) -> list[str]:
        """Wrap GUI launches in ``xvfb-run`` on headless Linux hosts."""
        if host_platform() == HOST_LINUX and not os.environ.get("DISPLAY"):
            xvfb = tool_path("xvfb-run", fallback="")
            if xvfb:
                return [xvfb, "-a", "--server-args=-screen 0 1440x900x24", *argv]
        return argv

    # ---- interpretation ------------------------------------------------ #

    def interpret(self, workspace: str | Path, request: TargetRequest,
                  outcome: RunOutcome) -> TargetReceipt:
        receipt = super().interpret(workspace, request, outcome)
        cdp_output = outcome.output_of("cdp_ready")
        if cdp_output.strip():
            receipt.notes.append("CDP: " + " | ".join(cdp_output.strip().splitlines()[:4]))
        for name in ("launch", "process_alive"):
            text = outcome.output_of(name).strip()
            if text.startswith("started background") or text.startswith("PROCESS ALIVE"):
                receipt.notes.append(text.splitlines()[0])

        log_names = [f"{index:02d}-launch.log" for index in range(1, 40)]
        combined = ""
        for name in log_names:
            chunk = read_evidence(outcome, name, limit=200_000)
            if chunk:
                combined += "\n" + chunk
        crash_source = combined or outcome.output_of("launch")
        receipt.crash_findings = scan_crashes(crash_source, "desktop")
        if crash_source.strip():
            receipt.notes.append("desktop launcher output scanned for uncaught errors")
        screenshot = artifact_for_evidence(outcome, "screen.png", "screenshot")
        if screenshot:
            receipt.artifacts.append(screenshot)
        return receipt


def _install_argv(root: Path, manager: str, lockfile: str) -> list[str]:
    """Deterministic dependency install for the project's own package manager."""
    from src.targets.providers.base import package_manager_argv

    del lockfile  # the manager itself already encodes which lockfile is honoured
    argv = package_manager_argv(root)
    if manager in ("npm",):
        return [*argv, "ci"]
    if manager in ("pnpm",):
        return [*argv, "install", "--frozen-lockfile"]
    if manager in ("yarn",):
        return [*argv, "install", "--immutable"]
    if manager in ("bun",):
        return [*argv, "install", "--frozen-lockfile"]
    return [*argv, "install"]


def _dotnet_project(root: Path) -> str:
    """First project file that looks like a desktop (Windows/WPF/MAUI) app."""
    for rel in any_path(root, ("*.csproj", "*/*.csproj", "*/*/*.csproj")):
        text = read_text(root, rel, limit=20_000)
        lowered = text.lower()
        if any(marker in lowered for marker in (
            "<usewpf>true", "<usewindowsforms>true", "windowsdesktop", "<usemaui>true",
            "-windows<", "winui", "presentationframework",
        )):
            return rel
    return ""


__all__ = ["DesktopProvider", "cdp_port", "resolve_desktop_binary"]
