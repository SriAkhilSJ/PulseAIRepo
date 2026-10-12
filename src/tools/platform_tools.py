"""Platform-aware build, test, and end-to-end UI verification tools.

The agent used to verify only web projects. These tools detect what kind of
project is in the workspace (web, Electron, Tauri, Flutter, React Native,
Android, iOS, Python desktop), run that platform's own build/test/e2e command
through the normal terminal tool (so approvals and hardline guards still
apply), and return receipts in the same ✅ / ❌ shape the completion gate reads.
"""
from __future__ import annotations

import platform as _platform
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.platforms.detect import (
    PlatformProject,
    Recipe,
    detect_platforms,
    exit_code_of,
    missing_requirements,
    recipe_for,
)

_BUILD_TIMEOUT = 900
_TEST_TIMEOUT = 900
_E2E_TIMEOUT = 1200


def _workspace(config: RunnableConfig) -> Path:
    return Path(config["configurable"]["workspace"]).resolve()


def _label(project: PlatformProject) -> str:
    return f"{project.platform} @ {project.root}"


def _select(workspace: Path, platform: str) -> tuple[PlatformProject | None, str]:
    """Pick the one project the tool should act on, or explain why not."""
    found = detect_platforms(workspace)
    if not found:
        return None, (
            "no supported project found in the workspace (looked for web, Electron, "
            "Tauri, Flutter, React Native, Android, iOS, and Python desktop markers)."
        )
    wanted = (platform or "").strip().lower()
    if wanted:
        matches = [p for p in found if p.platform == wanted]
        if not matches:
            return None, (
                f"no '{wanted}' project found. Detected: "
                + ", ".join(_label(p) for p in found)
            )
        return matches[0], ""
    if len(found) > 1:
        return None, (
            "several projects detected; pass platform= to choose one: "
            + ", ".join(_label(p) for p in found)
        )
    return found[0], ""


def _run(recipe: Recipe, command: str, config: RunnableConfig, timeout: int) -> tuple[bool, str]:
    """Run one command at the project root via the terminal tool."""
    from src.tools.terminal_tools import terminal

    if recipe.root not in (".", ""):
        if _platform.system() == "Windows":
            command = f'cd /d "{recipe.root}" && {command}'
        else:
            command = f'cd "{recipe.root}" && {command}'
    output = str(terminal.func(command, config, timeout))
    code = exit_code_of(output)
    return code == 0, output


def _tail(text: str, limit: int = 2500) -> str:
    text = text.strip()
    return text if len(text) <= limit else "...\n" + text[-limit:]


def _run_stage(stage: str, workspace: Path, platform: str, config: RunnableConfig,
               timeout: int, command_attr: str, missing_suite_msg: str = "") -> str:
    project, error = _select(workspace, platform)
    if project is None:
        return f"❌ {stage} FAILED: {error}"
    recipe = recipe_for(workspace, project)
    label = _label(project)

    command = getattr(recipe, command_attr)
    if not command:
        if missing_suite_msg:
            return f"❌ {stage} FAILED [{label}]: {missing_suite_msg}"
        return (
            f"ℹ️ {stage} SKIPPED [{label}]: no {command_attr.replace('unit_test', 'test')} "
            "step is defined for this project."
        )

    problems = missing_requirements(recipe)
    if problems:
        return (
            f"❌ {stage} FAILED [{label}]: prerequisites missing: "
            + "; ".join(problems)
            + ". Install these on this machine, then run it again."
        )

    passed, output = _run(recipe, command, config, timeout)
    notes = (" Notes: " + " ".join(recipe.notes)) if recipe.notes else ""
    if passed:
        return (
            f"✅ {stage} PASSED [{label}]: `{command}`{notes}\n"
            f"PLATFORM: {recipe.platform}\n{_tail(output, 1200)}"
        )
    return (
        f"❌ {stage} FAILED [{label}]: `{command}` did not succeed.{notes}\n"
        f"PLATFORM: {recipe.platform}\n{_tail(output)}"
    )


@tool("detect_platforms")
def detect_platforms_tool(config: RunnableConfig) -> str:
    """Detect which kinds of projects are in the workspace (web, Electron,
    Tauri, Flutter, React Native, Android, iOS, Python desktop) and show the
    build, test, and end-to-end commands available for each one.
    """
    workspace = _workspace(config)
    found = detect_platforms(workspace)
    if not found:
        return "ℹ️ No supported project found in the workspace."
    lines = ["Detected projects:"]
    for project in found:
        recipe = recipe_for(workspace, project)
        lines.append(f"- {_label(project)} (evidence: {', '.join(project.evidence)})")
        lines.append(f"    build: {recipe.build or '—'}")
        lines.append(f"    unit tests: {recipe.unit_test or '—'}")
        lines.append(f"    end-to-end UI tests: {recipe.e2e or '— (none yet; use scaffold_ui_e2e)'}")
        problems = missing_requirements(recipe)
        if problems:
            lines.append("    missing on this machine: " + "; ".join(problems))
    return "\n".join(lines)


@tool
def build_project(config: RunnableConfig, platform: str = "") -> str:
    """Build the detected project (web, Electron, Tauri, Flutter, React Native,
    Android, iOS, or Python desktop). Pass platform= when several are present.
    Returns a ✅ PLATFORM BUILD PASSED or ❌ PLATFORM BUILD FAILED receipt.
    """
    return _run_stage("PLATFORM BUILD", _workspace(config), platform, config,
                      _BUILD_TIMEOUT, "build")


@tool
def test_project(config: RunnableConfig, platform: str = "") -> str:
    """Run the detected project's unit tests (npm test, cargo test, flutter test,
    Gradle unit tests, pytest, ...). Returns a ✅ PLATFORM TESTS PASSED or
    ❌ PLATFORM TESTS FAILED receipt.
    """
    return _run_stage("PLATFORM TESTS", _workspace(config), platform, config,
                      _TEST_TIMEOUT, "unit_test")


@tool
def run_ui_e2e(config: RunnableConfig, platform: str = "") -> str:
    """Run the end-to-end UI test suite for the detected project: Playwright for
    web/Electron/Tauri frontends, Maestro or Gradle instrumented tests for
    Android and React Native, flutter integration_test for Flutter, pytest for
    Python desktop. Needs an emulator/device for mobile. If no suite exists,
    call scaffold_ui_e2e first. Returns ✅ UI E2E PASSED or ❌ UI E2E FAILED.
    """
    workspace = _workspace(config)
    project, error = _select(workspace, platform)
    if project is None:
        return f"❌ UI E2E FAILED: {error}"
    recipe = recipe_for(workspace, project)
    label = _label(project)
    if not recipe.e2e:
        hint = _SCAFFOLD_HINTS.get(recipe.platform, "")
        return (
            f"❌ UI E2E FAILED [{label}]: no end-to-end UI test suite exists yet. "
            f"Call scaffold_ui_e2e(platform='{recipe.platform}') to create a starter "
            f"suite ({hint}), fill it in for the real user flows, then run this again."
        )
    problems = missing_requirements(recipe)
    if problems:
        return (
            f"❌ UI E2E FAILED [{label}]: prerequisites missing: "
            + "; ".join(problems) + ". Install or start these, then run it again."
        )
    passed, output = _run(recipe, recipe.e2e, config, _E2E_TIMEOUT)
    notes = (" Notes: " + " ".join(recipe.notes)) if recipe.notes else ""
    if passed:
        return (
            f"✅ UI E2E PASSED [{label}]: `{recipe.e2e}`{notes}\n"
            f"PLATFORM: {recipe.platform}\n{_tail(output, 1200)}"
        )
    return (
        f"❌ UI E2E FAILED [{label}]: `{recipe.e2e}` did not succeed.{notes}\n"
        f"PLATFORM: {recipe.platform}\n{_tail(output)}"
    )


# --------------------------------------------------------------------------- #
# Starter end-to-end suites. Written only when the file does not already exist.
# --------------------------------------------------------------------------- #

_PLAYWRIGHT_CONFIG = """import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests/e2e',
  use: { baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173', screenshot: 'only-on-failure' },
  webServer: process.env.E2E_BASE_URL ? undefined : {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
  },
});
"""

_PLAYWRIGHT_SMOKE = """import { test, expect } from '@playwright/test';

test('home page renders and shows content', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(err.message));
  await page.goto('/');
  await expect(page.locator('body')).not.toBeEmpty();
  await page.screenshot({ path: 'test-results/home.png', fullPage: true });
  expect(errors).toEqual([]);
});
"""

_ELECTRON_SMOKE = """import { test, expect, _electron as electron } from '@playwright/test';

test('desktop window launches and renders', async () => {
  const app = await electron.launch({ args: ['.'] });
  const window = await app.firstWindow();
  await expect(window.locator('body')).not.toBeEmpty();
  await window.screenshot({ path: 'test-results/window.png' });
  await app.close();
});
"""

_MAESTRO_SMOKE = """# Replace the appId with the real package/bundle id of the app.
appId: com.example.app
---
- launchApp
- assertVisible: "Welcome"
"""

_FLUTTER_SMOKE = """import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'package:app/main.dart' as app;

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('app launches and shows the first screen', (tester) async {
    app.main();
    await tester.pumpAndSettle();
    expect(find.byType(MaterialApp), findsOneWidget);
  });
}
"""

# platform -> list of (relative path, template); "" key list is the starter set.
_SCAFFOLDS: dict[str, list[tuple[str, str]]] = {
    "web": [
        ("playwright.config.ts", _PLAYWRIGHT_CONFIG),
        ("tests/e2e/smoke.spec.ts", _PLAYWRIGHT_SMOKE),
    ],
    "electron": [
        ("playwright.config.ts", _PLAYWRIGHT_CONFIG),
        ("tests/e2e/smoke.spec.ts", _ELECTRON_SMOKE),
    ],
    "tauri": [
        ("playwright.config.ts", _PLAYWRIGHT_CONFIG),
        ("tests/e2e/smoke.spec.ts", _PLAYWRIGHT_SMOKE),
    ],
    "android": [(".maestro/smoke.yaml", _MAESTRO_SMOKE)],
    "react_native": [(".maestro/smoke.yaml", _MAESTRO_SMOKE)],
    "flutter": [("integration_test/app_test.dart", _FLUTTER_SMOKE)],
}

_SCAFFOLD_HINTS = {
    "web": "Playwright opens a real browser and clicks through the site",
    "electron": "Playwright launches the real desktop window",
    "tauri": "Playwright tests the web frontend",
    "android": "Maestro taps through the installed app on an emulator",
    "react_native": "Maestro taps through the installed app on an emulator",
    "flutter": "Flutter integration_test drives the app on an emulator",
    "ios": "iOS UI tests need Xcode on a Mac; write XCUITest targets by hand",
    "desktop_python": "pytest tests under tests/e2e drive the GUI",
}


@tool
def scaffold_ui_e2e(config: RunnableConfig, platform: str = "") -> str:
    """Create a starter end-to-end UI test suite for the detected project
    (Playwright for web/Electron/Tauri, Maestro for Android/React Native,
    Flutter integration_test for Flutter). Existing files are never overwritten.
    After scaffolding, edit the tests to cover the real user flows, then call
    run_ui_e2e.
    """
    workspace = _workspace(config)
    project, error = _select(workspace, platform)
    if project is None:
        return f"❌ SCAFFOLD FAILED: {error}"
    label = _label(project)
    templates = _SCAFFOLDS.get(project.platform)
    if not templates:
        return (
            f"ℹ️ SCAFFOLD SKIPPED [{label}]: no automatic starter for this platform. "
            f"Hint: {_SCAFFOLD_HINTS.get(project.platform, 'write tests by hand')}."
        )
    base = workspace if project.root in (".", "") else workspace / project.root
    created: list[str] = []
    kept: list[str] = []
    for rel, content in templates:
        target = base / rel
        if target.exists():
            kept.append(rel)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        created.append(rel)
    parts = [f"✅ SCAFFOLD READY [{label}]"]
    if created:
        parts.append("created: " + ", ".join(created))
    if kept:
        parts.append("kept (already existed): " + ", ".join(kept))
    parts.append("Next: edit the tests to cover the real user flows, then call run_ui_e2e.")
    return "\n".join(parts)


PLATFORM_TOOLS = [
    detect_platforms_tool,
    build_project,
    test_project,
    run_ui_e2e,
    scaffold_ui_e2e,
]

PLATFORM_TOOL_NAMES = tuple(t.name for t in PLATFORM_TOOLS)
