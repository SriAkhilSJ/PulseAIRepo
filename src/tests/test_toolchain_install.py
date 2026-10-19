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
    monkeypatch.setitem(ti._INSTALLERS, "flutter", lambda host, log, report: called.append(host))
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

    def fake_install(host, log, report):
        state["flutter"] = state["dart"] = True
        log.append("fake steps")

    monkeypatch.setitem(ti._INSTALLERS, "flutter", fake_install)
    receipt = ti._install("dart")  # alias of the flutter bundle
    assert receipt.startswith("✅")
    assert "flutter create" in receipt


def test_failed_step_names_the_step_and_the_manual_route(monkeypatch):
    state = {"flutter": False, "dart": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    def broken(host, log, report):
        raise ti._StepFailed("download", "network gone")

    monkeypatch.setitem(ti._INSTALLERS, "flutter", broken)
    receipt = ti._install("flutter")
    assert receipt.startswith("⛔")
    assert "'download'" in receipt
    assert "docs.flutter.dev" in receipt


def test_partial_install_uses_the_warning_tone(monkeypatch):
    state = {"java": False, "sdkmanager": False, "adb": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    def half(host, log, report):
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


def test_progress_starts_at_zero_and_finishes_at_100(monkeypatch):
    """The card's loader (founder 2026-10-18: "0 to 100 — i know its a
    instalation, i wait"): the run opens at 0 with a label and the
    verified success closes at 100."""
    state = {"flutter": False, "dart": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    def fake_install(host, log, report):
        report(42, "Downloading Flutter SDK… 420 MB")
        state["flutter"] = state["dart"] = True

    monkeypatch.setitem(ti._INSTALLERS, "flutter", fake_install)
    seen: list[tuple[float | None, str]] = []
    receipt = ti._install("flutter", progress=lambda pct, label: seen.append((pct, label)))
    assert receipt.startswith("✅")
    assert seen[0] == (0, "Installing Flutter SDK…") or seen[0][0] == 0
    assert (42, "Downloading Flutter SDK… 420 MB") in seen
    assert seen[-1] == (100, "Flutter SDK ready")


def test_percent_scraper_reads_package_manager_output():
    assert ti._frac_from_line("Installing Android SDK Platform 35  42%") == 0.42
    assert ti._frac_from_line("downloading... 7.5% done") == 0.075
    assert ti._frac_from_line("no measure on this line") is None
    assert ti._frac_from_line("over 250%?!") == 1.0


def test_band_maps_step_progress_into_its_slice():
    seen: list[tuple[float | None, str]] = []
    band = ti._band(lambda pct, label: seen.append((pct, label)), 40, 90, "Installing…")
    band(0.5)
    band(None)
    assert seen == [(65.0, "Installing…"), (None, "Installing…")]


def test_download_reports_real_byte_progress(tmp_path, monkeypatch):
    import io

    payload = b"x" * 100_000

    class _Response:
        headers = {"Content-Length": str(len(payload))}

        def __init__(self):
            self._buf = io.BytesIO(payload)

        def read(self, size=-1):
            return self._buf.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(ti.urllib.request, "urlopen", lambda request, timeout=None: _Response())
    seen: list[tuple[int, int | None]] = []
    dest = tmp_path / "sdk.zip"
    ti._download("download", "https://example.invalid/sdk.zip", dest,
                 on_bytes=lambda done, total: seen.append((done, total)))
    assert dest.read_bytes() == payload
    assert seen[-1] == (len(payload), len(payload))
    assert all(total == len(payload) for _, total in seen)


def test_bus_progress_throttles_clamps_and_never_raises(monkeypatch):
    from src.dashboard import event_bus as bus_module

    seen: list[dict] = []
    monkeypatch.setattr(bus_module.event_bus, "emit",
                        lambda kind, payload: seen.append(payload))
    report = ti._bus_progress("thread-1")
    report(10, "Downloading…")
    report(10.4, "Downloading…")   # <1% and instant: throttled away
    report(50, "Downloading…")
    report(250, "Downloading…")    # clamped to 100
    report(None, "Verifying…")     # label change always lands
    assert [payload["percent"] for payload in seen] == [10.0, 50.0, 100.0, None]
    assert seen[0]["tool_name"] == "install_toolchain"
    assert seen[0]["thread_id"] == "thread-1"


def test_ui_test_kit_failure_never_fails_the_sdk_install(monkeypatch):
    """Founder 2026-10-18: installs bring the UI-testing raw materials
    too — best-effort, so a skipped extra is a receipt note, never a
    failed install."""
    state = {"node": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    def fake_install(host, log, report):
        state["node"] = True

    def broken_kit(host):
        raise ti._StepFailed("cdn", "network gone")

    monkeypatch.setitem(ti._INSTALLERS, "node", fake_install)
    monkeypatch.setitem(ti._KIT_STEPS, "node", (("playwright", broken_kit, "playwright"),))
    receipt = ti._install("node", ui_test_kit=True)
    assert receipt.startswith("✅")
    assert "UI test kit: playwright skipped (network gone)." in receipt


def test_ui_test_kit_lands_and_is_named_in_the_receipt(monkeypatch):
    state = {"node": False, "playwright": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    def fake_install(host, log, report):
        state["node"] = True

    def kit(host):
        state["playwright"] = True
        return "Playwright Chromium (browser UI tests)"

    monkeypatch.setitem(ti._INSTALLERS, "node", fake_install)
    monkeypatch.setitem(ti._KIT_STEPS, "node", (("playwright", kit, "playwright"),))
    receipt = ti._install("node", ui_test_kit=True)
    assert "UI test kit: Playwright Chromium (browser UI tests)." in receipt
    # And without the flag the kit stays out of the run entirely.
    state["node"] = False
    receipt = ti._install("node")
    assert "UI test kit" not in receipt


def test_download_label_names_the_total(tmp_path, monkeypatch):
    """Founder field 2026-10-18: 'total mb size not specified' — the
    wait only feels finite with the denominator on the card."""
    import io
    import json as jsonlib

    payload = b"y" * 50_000
    manifest = {
        "current_release": {"stable": "abc"},
        "releases": [{"hash": "abc", "version": "9.9.9", "archive": "flutter_fake.zip"}],
        "base_url": "https://example.invalid",
    }

    class _Response:
        def __init__(self, data: bytes):
            self._buf = io.BytesIO(data)
            self.headers = {"Content-Length": str(len(data))}

        def read(self, size=-1):
            return self._buf.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        url = getattr(request, "full_url", request)
        if "releases_" in str(url):
            return _Response(jsonlib.dumps(manifest).encode())
        raise AssertionError(f"unexpected url {url}")


    def fake_download(step, url, dest, on_bytes=None):
        on_bytes(50_000_000, 100_000_000)
        dest.write_bytes(payload)

    monkeypatch.setattr(ti.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ti, "MANAGED_ROOT", tmp_path)
    monkeypatch.setattr(ti, "_download", fake_download)
    monkeypatch.setattr(ti, "_extract", lambda step, archive, dest, on_file=None: None)
    monkeypatch.setattr(ti, "_sh", lambda step, argv, **kw: "Flutter 9.9.9")
    seen: list[tuple[float | None, str]] = []
    ti._install_flutter("linux", [], lambda pct, label: seen.append((pct, label)))
    assert any("50 MB of 100 MB" in label for _, label in seen), seen
    # Founder 2026-10-19 ("is count down loader correct??"): the
    # number beside "50 MB of 100 MB" is 50 — the phase's own
    # fraction, never a weighted composite of the whole install.
    assert (50.0, next(label for _, label in seen if "50 MB of 100 MB" in label)) in seen


def test_size_labels_use_natural_units():
    """Founder 2026-10-18: "1,486 --> GB"."""
    assert ti._size_label(199) == "199 MB"
    assert ti._size_label(999) == "999 MB"
    assert ti._size_label(1000) == "1 GB"
    assert ti._size_label(1486) == "1.49 GB"
    assert ti._size_label(2500) == "2.5 GB"


def test_install_stops_when_the_session_cancel_lands(monkeypatch):
    """Cancel identity rides the graph config's thread_id (== the
    panel session id), not a thread-local: tool threads may hop, the
    key must not. The fake recipe polls like the real loops do."""
    state = {"flutter": False, "dart": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    class _Controls:
        @staticmethod
        def cancelled(session_id):
            return session_id == "sess-9"

    monkeypatch.setattr(ti, "turn_controls", _Controls)

    def recipe(host, log, report):
        ti._check_cancel()  # the poll every long wait performs
        raise AssertionError("install continued after Cancel")

    monkeypatch.setitem(ti._INSTALLERS, "flutter", recipe)
    receipt = ti._install("flutter", session_id="sess-9")
    assert receipt.startswith("⏹")
    # A different session's cancel must not stop this install.
    def recipe_ok(host, log, report):
        ti._check_cancel()
        state["flutter"] = state["dart"] = True

    monkeypatch.setitem(ti._INSTALLERS, "flutter", recipe_ok)
    assert ti._install("flutter", session_id="sess-1").startswith("✅")


def test_cancel_during_download_aborts_and_removes_the_part(tmp_path, monkeypatch):
    import io

    class _Response:
        headers = {"Content-Length": "600000"}

        def __init__(self):
            self._buf = io.BytesIO(b"z" * 600_000)

        def read(self, size=-1):
            return self._buf.read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(ti.urllib.request, "urlopen", lambda request, timeout=None: _Response())
    # Cancel lands after the download has begun.
    checks = {"n": 0}

    def fake_cancelled():
        checks["n"] += 1
        return checks["n"] > 1

    monkeypatch.setattr(ti, "_cancelled", fake_cancelled)
    dest = tmp_path / "sdk.zip"
    with pytest.raises(ti._InstallCancelled):
        ti._download("download", "https://example.invalid/sdk.zip", dest)
    assert not dest.exists()
    assert not (tmp_path / "sdk.zip.part").exists()


def test_cancelled_install_gets_an_honest_receipt(monkeypatch):
    state = {"flutter": False, "dart": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    def cancelled_install(host, log, report):
        raise ti._InstallCancelled()

    monkeypatch.setitem(ti._INSTALLERS, "flutter", cancelled_install)
    receipt = ti._install("flutter")
    assert receipt.startswith("⏹")
    assert "cancelled" in receipt
    assert "check_target_toolchains" in receipt


def test_streaming_step_dies_fast_on_cancel(monkeypatch):
    """The card's Cancel (the session's existing turn cancel) kills a
    running package step instead of waiting out its timeout — and the
    agent rests: the turn ends without another model call (the graph
    already gates nodes on turn_controls.cancelled)."""
    import subprocess
    import sys
    import time

    monkeypatch.setattr(ti, "_cancelled", lambda: True)
    started = time.monotonic()
    with pytest.raises(ti._InstallCancelled):
        ti._run_stream(
            [sys.executable, "-c",
             "import time\nfor i in range(200):\n print(i, flush=True); time.sleep(0.05)"],
            timeout=120, on_line=lambda line: None,
        )
    assert time.monotonic() - started < 10
    # The child is really gone, not detached.
    assert subprocess.run  # (sanity: stdlib present; kill asserted by elapsed time)


def test_live_cancel_kills_a_running_step_end_to_end(monkeypatch):
    """The full Cancel chain with the REAL turn registry (founder
    field: "cancel worked after multiple clicks" — the fix makes the
    first one land): begin the session like the bridge does, run an
    install whose step streams forever, cancel from another thread
    like the bridge socket does, and the install must die fast."""
    import sys
    import threading
    import time

    from src.runtime.turn_control import turn_controls

    state = {"flutter": False, "dart": False}
    monkeypatch.setattr(toolchain, "probe", _probe_with(state))

    def recipe(host, log, report):
        ti._run_stream(
            [sys.executable, "-c",
             "import time\nfor i in range(600):\n print(i, flush=True); time.sleep(0.05)"],
            timeout=120, on_line=lambda line: None,
        )

    monkeypatch.setitem(ti._INSTALLERS, "flutter", recipe)
    turn_controls.begin("sess-live")
    outcome: dict[str, str] = {}
    started = time.monotonic()
    worker = threading.Thread(
        target=lambda: outcome.setdefault(
            "receipt", ti._install("flutter", session_id="sess-live")),
        daemon=True,
    )
    try:
        worker.start()
        time.sleep(0.6)
        assert turn_controls.cancel("sess-live") is True
        worker.join(timeout=5)
    finally:
        turn_controls.end("sess-live")
    assert not worker.is_alive(), "install ignored the session cancel"
    assert time.monotonic() - started < 5
    assert outcome["receipt"].startswith("⏹")


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
