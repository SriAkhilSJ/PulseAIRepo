"""install_toolchain: the SDK installer (founder 2026-10-18).

When the SDK for the thing being built is missing, the agent installs
the real thing (with the user's approval — the permission rule pins
`ask`) instead of hand-writing a generator's project files. Recipes
are fixed data; these tests pin the receipt grammar and the probe
integration with fake probes/installers — never the network.
"""
from __future__ import annotations

import pytest

from src.targets import toolchain
from src.tools import toolchain_install as ti


class _Status:
    def __init__(self, ok: bool, version: str = "1.0", path: str = "/fake/tool"):
        self.available = ok
        self.version = version if ok else ""
        self.path = path if ok else ""


def _probe_with(state: dict[str, bool]):
    def probe(host=None, fresh=False):
        return {tool_id: _Status(ok) for tool_id, ok in state.items()}
    return probe


def test_unknown_sdk_refuses_and_names_the_choices():
    receipt = ti._install("bogus")
    assert receipt.startswith("⛔")
    assert "flutter" in receipt and "android" in receipt


def test_reported_tool_ids_map_to_bundles():
    assert ti.canonical_sdk("adb") == "android"
    assert ti.canonical_sdk("sdkmanager") == "android"
    assert ti.canonical_sdk("dart") == "flutter"
    assert ti.canonical_sdk("cargo") == "rust"
    assert ti.canonical_sdk("xcodebuild") == "xcode"
    assert ti.canonical_sdk("Flutter") == "flutter"


def test_already_installed_is_a_no_op(monkeypatch):
    state = {"flutter": True, "dart": True}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))
    called = []
    monkeypatch.setitem(ti._INSTALLERS, "flutter", lambda host, log: called.append(host))
    receipt = ti._install("flutter")
    assert receipt.startswith("ℹ️")
    assert called == []


def test_xcode_on_a_non_mac_host_is_an_honest_refusal(monkeypatch):
    state = {"xcodebuild": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))
    receipt = ti._install("xcodebuild", host="windows")
    assert receipt.startswith("⛔")
    assert "macOS" in receipt


def test_successful_install_verifies_with_a_fresh_probe(monkeypatch):
    state = {"flutter": False, "dart": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    def fake_install(host, log):
        state["flutter"] = state["dart"] = True
        log.append("fake steps")

    monkeypatch.setitem(ti._INSTALLERS, "flutter", fake_install)
    receipt = ti._install("dart")  # alias of the flutter bundle
    assert receipt.startswith("✅")
    assert "flutter create" in receipt


def test_failed_step_names_the_step_and_the_manual_route(monkeypatch):
    state = {"flutter": False, "dart": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    def broken(host, log):
        raise ti._StepFailed("download", "network gone")

    monkeypatch.setitem(ti._INSTALLERS, "flutter", broken)
    receipt = ti._install("flutter")
    assert receipt.startswith("⛔")
    assert "'download'" in receipt
    assert "docs.flutter.dev" in receipt


def test_partial_install_uses_the_warning_tone(monkeypatch):
    state = {"java": False, "sdkmanager": False, "adb": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    def half(host, log):
        state["java"] = True

    monkeypatch.setitem(ti._INSTALLERS, "android", half)
    receipt = ti._install("android")
    assert receipt.startswith("⚠️")
    assert "sdkmanager" in receipt


def test_managed_sdk_dir_is_a_probe_candidate(tmp_path, monkeypatch):
    root = tmp_path / "sdks"
    binary = root / "flutter" / "bin" / "flutter"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\necho Flutter 9.9.9\n")
    binary.chmod(0o755)
    monkeypatch.setattr(toolchain, "managed_sdk_root", lambda: root)
    spec = next(s for s in toolchain.TOOLS if s.id == "flutter")
    candidates = toolchain.managed_candidates(spec)
    assert str(binary) in candidates


def test_install_always_asks_under_the_permission_rules(tmp_path):
    from src.context.permission_config import (
        effect_for, load_permission_rules, tool_action_resources,
    )

    action, resources = tool_action_resources("install_toolchain", {"sdk": "flutter"})
    assert action == "install_toolchain"
    assert resources == ["flutter"]
    rules = load_permission_rules(str(tmp_path), "build")
    assert effect_for(action, resources, rules) == "ask"


def test_target_children_receive_the_installer():
    from src.tools.toolsets import resolve_toolset_names

    resolved = set(resolve_toolset_names("Build a React Native app and verify its UI on an Android emulator"))
    assert "install_toolchain" in resolved


def test_toolchain_check_points_at_the_installer(monkeypatch):
    from src.tools import target_tools

    monkeypatch.setattr(
        target_tools, "doctor_report", lambda targets=None: "REPORT")
    monkeypatch.setattr(
        target_tools, "target_readiness",
        lambda targets=None: {"flutter": {"missing": ["flutter", "adb"]}},
    )
    out = target_tools.check_target_toolchains.invoke({"target": "flutter"})
    assert 'install_toolchain(sdk="flutter")' in out
    assert 'install_toolchain(sdk="android")' in out
    assert "hand-author" in out
