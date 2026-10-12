"""Platform detection, recipes, receipts, and the completion gate for non-web apps."""
import json

import pytest
from langchain_core.messages import ToolMessage


def _write(path, text=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _cfg(workspace):
    return {"configurable": {"workspace": str(workspace), "thread_id": "t"}}


# ---------------------------------------------------------------- detection

def test_detects_vite_web_project(tmp_path):
    from src.platforms.detect import detect_platforms
    _write(tmp_path / "package.json", json.dumps({"devDependencies": {"vite": "5"}}))
    _write(tmp_path / "index.html", "<html></html>")
    found = {(p.platform, p.root) for p in detect_platforms(tmp_path)}
    assert ("web", ".") in found


def test_detects_electron_and_suppresses_plain_web(tmp_path):
    from src.platforms.detect import detect_platforms
    _write(tmp_path / "package.json", json.dumps({"dependencies": {"electron": "30", "react": "18"}}))
    _write(tmp_path / "index.html", "")
    platforms = {p.platform for p in detect_platforms(tmp_path)}
    assert "electron" in platforms
    assert "web" not in platforms


def test_detects_flutter(tmp_path):
    from src.platforms.detect import detect_platforms
    _write(tmp_path / "pubspec.yaml", "dependencies:\n  flutter:\n    sdk: flutter\n")
    assert [p.platform for p in detect_platforms(tmp_path)] == ["flutter"]


def test_detects_native_android_in_app_subfolder(tmp_path):
    from src.platforms.detect import detect_platforms
    _write(tmp_path / "MyApp" / "app" / "build.gradle.kts", 'plugins { id("com.android.application") }')
    found = detect_platforms(tmp_path)
    assert [(p.platform, p.root) for p in found] == [("android", "MyApp")]


def test_detects_react_native_tauri_and_python_desktop(tmp_path):
    from src.platforms.detect import detect_platforms
    _write(tmp_path / "rn" / "package.json", json.dumps({"dependencies": {"react-native": "0.75"}}))
    _write(tmp_path / "desk" / "src-tauri" / "tauri.conf.json", "{}")
    _write(tmp_path / "py" / "requirements.txt", "PySide6==6.7\n")
    platforms = {p.platform for p in detect_platforms(tmp_path)}
    assert {"react_native", "tauri", "desktop_python"} <= platforms


def test_empty_workspace_detects_nothing(tmp_path):
    from src.platforms.detect import detect_platforms
    assert detect_platforms(tmp_path) == []


def test_skips_node_modules_and_build_folders(tmp_path):
    from src.platforms.detect import detect_platforms
    _write(tmp_path / "node_modules" / "x" / "package.json", json.dumps({"dependencies": {"electron": "1"}}))
    _write(tmp_path / "build" / "pubspec.yaml", "dependencies:\n  flutter:\n    sdk: flutter\n")
    assert detect_platforms(tmp_path) == []


# ---------------------------------------------------------------- recipes

def test_web_recipe_uses_playwright_when_config_present(tmp_path):
    from src.platforms.detect import detect_platforms, recipe_for
    _write(tmp_path / "package.json", json.dumps({
        "devDependencies": {"vite": "5"},
        "scripts": {"build": "vite build", "test": 'echo "Error: no test specified" && exit 1'},
    }))
    _write(tmp_path / "index.html", "")
    _write(tmp_path / "playwright.config.ts", "export default {}")
    recipe = recipe_for(tmp_path, detect_platforms(tmp_path)[0])
    assert recipe.build == "npm run build"
    assert recipe.unit_test is None          # npm placeholder ignored
    assert recipe.e2e == "npx playwright test"


def test_android_recipe_uses_gradle_and_instrumented_tests(tmp_path):
    from src.platforms.detect import detect_platforms, recipe_for
    _write(tmp_path / "settings.gradle", 'include(":app")')
    _write(tmp_path / "app" / "build.gradle", 'plugins { id "com.android.application" }')
    _write(tmp_path / "app" / "src" / "androidTest" / "ExampleTest.kt", "")
    recipe = recipe_for(tmp_path, detect_platforms(tmp_path)[0])
    assert recipe.build.endswith("assembleDebug")
    assert recipe.unit_test.endswith("testDebugUnitTest")
    assert recipe.e2e.endswith("connectedDebugAndroidTest")


def test_ios_recipe_needs_macos(tmp_path, monkeypatch):
    from src.platforms import detect as det
    _write(tmp_path / "Demo.xcodeproj" / "project.pbxproj", "")
    recipe = det.recipe_for(tmp_path, det.detect_platforms(tmp_path)[0])
    assert recipe.build and "xcodebuild" in recipe.build
    monkeypatch.setattr(det._platform, "system", lambda: "Linux")
    problems = det.missing_requirements(recipe)
    assert any("Darwin" in p for p in problems)


def test_exit_code_parsing():
    from src.platforms.detect import exit_code_of
    assert exit_code_of("Output\nExit code: 0") == 0
    assert exit_code_of("COMPLETED (exit code 2)") == 2
    assert exit_code_of("no code here") is None


# ---------------------------------------------------------------- tools

def test_run_ui_e2e_without_suite_points_to_scaffold(tmp_path):
    from src.tools.platform_tools import run_ui_e2e
    _write(tmp_path / "pubspec.yaml", "dependencies:\n  flutter:\n    sdk: flutter\n")
    out = run_ui_e2e.invoke({}, config=_cfg(tmp_path))
    assert out.startswith("❌ UI E2E FAILED")
    assert "scaffold_ui_e2e" in out


def test_scaffold_writes_starter_and_never_overwrites(tmp_path):
    from src.tools.platform_tools import scaffold_ui_e2e
    _write(tmp_path / "package.json", json.dumps({"devDependencies": {"vite": "5"}}))
    _write(tmp_path / "index.html", "")
    _write(tmp_path / "tests" / "e2e" / "smoke.spec.ts", "KEEP ME")
    out = scaffold_ui_e2e.invoke({}, config=_cfg(tmp_path))
    assert out.startswith("✅ SCAFFOLD READY")
    assert (tmp_path / "playwright.config.ts").is_file()
    assert (tmp_path / "tests" / "e2e" / "smoke.spec.ts").read_text() == "KEEP ME"


def test_scaffold_android_writes_maestro_flow(tmp_path):
    from src.tools.platform_tools import scaffold_ui_e2e
    _write(tmp_path / "app" / "build.gradle", 'plugins { id "com.android.application" }')
    scaffold_ui_e2e.invoke({}, config=_cfg(tmp_path))
    assert (tmp_path / ".maestro" / "smoke.yaml").is_file()


def test_build_receipt_pass_and_fail(tmp_path, monkeypatch):
    from src.tools import terminal_tools
    from src.tools.platform_tools import build_project
    _write(tmp_path / "pubspec.yaml", "dependencies:\n  flutter:\n    sdk: flutter\n")
    monkeypatch.setattr("src.platforms.detect.shutil.which", lambda name: f"/usr/bin/{name}")

    class Fake:
        def __init__(self, out):
            self.out = out
            self.commands = []

        def func(self, command, config, timeout):
            self.commands.append(command)
            return self.out

    fake = Fake("analysis ok\nExit code: 0")
    monkeypatch.setattr(terminal_tools, "terminal", fake)
    ok = build_project.invoke({}, config=_cfg(tmp_path))
    assert ok.startswith("✅ PLATFORM BUILD PASSED")
    assert "PLATFORM: flutter" in ok
    assert fake.commands == ["flutter analyze"]

    monkeypatch.setattr(terminal_tools, "terminal", Fake("error\nExit code: 1"))
    bad = build_project.invoke({}, config=_cfg(tmp_path))
    assert bad.startswith("❌ PLATFORM BUILD FAILED")


def test_missing_prerequisite_is_a_clear_failure(tmp_path, monkeypatch):
    from src.tools.platform_tools import test_project
    _write(tmp_path / "pubspec.yaml", "dependencies:\n  flutter:\n    sdk: flutter\n")
    _write(tmp_path / "test" / "x_test.dart", "")
    monkeypatch.setattr("src.platforms.detect.shutil.which", lambda name: None)
    out = test_project.invoke({}, config=_cfg(tmp_path))
    assert out.startswith("❌ PLATFORM TESTS FAILED")
    assert "'flutter' is not on PATH" in out


def test_several_projects_require_platform_argument(tmp_path):
    from src.tools.platform_tools import build_project
    _write(tmp_path / "pubspec.yaml", "dependencies:\n  flutter:\n    sdk: flutter\n")
    _write(tmp_path / "web" / "package.json", json.dumps({"devDependencies": {"vite": "5"}}))
    _write(tmp_path / "web" / "index.html", "")
    out = build_project.invoke({}, config=_cfg(tmp_path))
    assert "pass platform=" in out


# ---------------------------------------------------------------- gate

def _gate_state(task, messages, workspace):
    return {"current_task": task, "messages": messages, "workspace": str(workspace)}


def _tm(name, content, call_id):
    return ToolMessage(content=content, name=name, tool_call_id=call_id)


def test_gate_native_app_needs_e2e_not_browser(tmp_path):
    from src.graphs.gates import _verification_receipt_status
    _write(tmp_path / "app" / "build.gradle", 'plugins { id "com.android.application" }')
    task = "build an android app with a login screen"
    build_only = _gate_state(task, [
        _tm("build_project", "✅ PLATFORM BUILD PASSED [android @ .]: `x`\nPLATFORM: android\n", "1"),
    ], tmp_path)
    status = _verification_receipt_status(build_only)
    assert "e2e" in status["missing"]
    assert not status["passed"]

    with_e2e = _gate_state(task, build_only["messages"] + [
        _tm("run_ui_e2e", "✅ UI E2E PASSED [android @ .]: `x`\nPLATFORM: android\n", "2"),
    ], tmp_path)
    assert _verification_receipt_status(with_e2e)["passed"]


def test_gate_failed_e2e_does_not_count(tmp_path):
    from src.graphs.gates import _verification_receipt_status
    _write(tmp_path / "app" / "build.gradle", 'plugins { id "com.android.application" }')
    state = _gate_state("build an android app", [
        _tm("build_project", "✅ PLATFORM BUILD PASSED [android @ .]\nPLATFORM: android\n", "1"),
        _tm("run_ui_e2e", "❌ UI E2E FAILED [android @ .]: boom\nPLATFORM: android\n", "2"),
    ], tmp_path)
    assert "e2e" in _verification_receipt_status(state)["missing"]


def test_gate_web_e2e_counts_as_browser_proof(tmp_path):
    from src.graphs.gates import _verification_receipt_status
    state = _gate_state("build a website landing page", [
        _tm("build_project", "✅ PLATFORM BUILD PASSED [web @ .]\nPLATFORM: web\n", "1"),
        _tm("run_ui_e2e", "✅ UI E2E PASSED [web @ .]\nPLATFORM: web\n", "2"),
    ], tmp_path)
    assert _verification_receipt_status(state)["passed"]


# ---------------------------------------------------------------- binding

def test_platform_tools_are_bound_for_coding_tasks():
    from src.agents.runtime_profile import CAP_VERIFICATION, resolve_runtime_profile
    from src.tools.toolsets import resolve_runtime_tool_names
    profile = resolve_runtime_profile("build an android app and run its end to end ui tests")
    assert profile.has(CAP_VERIFICATION)
    names = resolve_runtime_tool_names(profile)
    for name in ("detect_platforms", "build_project", "test_project", "run_ui_e2e", "scaffold_ui_e2e"):
        assert name in names


def test_chat_graph_binds_platform_tools():
    from src.graphs.chat_graph import tools
    names = {t.name for t in tools}
    assert {"build_project", "test_project", "run_ui_e2e", "scaffold_ui_e2e", "detect_platforms"} <= names
