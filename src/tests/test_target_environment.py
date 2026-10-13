"""The environment half of multi-platform support: finding SDKs the OS hides.

Android Studio deliberately does **not** put ``adb``/``emulator`` on PATH — they
live under the SDK root (``%LOCALAPPDATA%\\Android\\Sdk`` on Windows,
``~/Library/Android/sdk`` on macOS, ``~/Android/Sdk`` on Linux). A toolchain doctor
that only reads PATH therefore reports "adb missing" on a machine that is fully
set up, and the agent refuses to build an app it could have built.

These tests pin the resolution order (explicit override → PATH → SDK root), the
Windows spellings (``.exe`` for platform tools, ``.bat`` for cmdline-tools), and
the ``--setup`` plan's honesty: missing tools listed, host-appropriate commands,
and no install advice for a target this host cannot run at all.
"""
from __future__ import annotations

import io
import stat
import subprocess
from pathlib import Path

import pytest

from src.targets.contract import HOST_LINUX, HOST_MACOS, HOST_WINDOWS
from src.targets.providers.base import tool_path
from src.targets.toolchain import (
    TOOLS_BY_ID,
    _probe_binary,
    host_platform,
    probe,
    sdk_candidates,
    sdk_roots,
)

ANDROID_TOOLS = ("adb", "emulator", "sdkmanager", "avdmanager")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "CRUSORAI_ADB", "CRUSORAI_EMULATOR",
                 "CRUSORAI_ANDROID_CLI", "CRUSORAI_SDKMANAGER", "CRUSORAI_AVDMANAGER",
                 "CRUSORAI_ANDROID_RUNNER"):
        monkeypatch.delenv(name, raising=False)
    yield


def _fake_sdk(root: Path, *, host: str) -> Path:
    """Create the directory shape a real SDK has (files are placeholders)."""
    windows = host == HOST_WINDOWS
    (root / "platform-tools").mkdir(parents=True, exist_ok=True)
    (root / "platform-tools" / ("adb.exe" if windows else "adb")).write_text("#!/bin/sh\necho 'Android Debug Bridge version 1.0.41'\n", encoding="utf-8")
    (root / "emulator").mkdir(parents=True, exist_ok=True)
    (root / "emulator" / ("emulator.exe" if windows else "emulator")).write_text("#!/bin/sh\necho 'Android emulator version 35.1.4'\n", encoding="utf-8")
    bin_dir = root / "cmdline-tools" / "latest" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for leaf in ("sdkmanager", "avdmanager"):
        (bin_dir / (leaf + (".bat" if windows else ""))).write_text("#!/bin/sh\necho 13.0\n", encoding="utf-8")
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return root


def _stub_version_probe(monkeypatch) -> None:
    """Read fake SDK versions without executing POSIX scripts on Windows."""
    import src.targets.toolchain as toolchain

    versions = {
        "adb": "Android Debug Bridge version 1.0.41",
        "emulator": "Android emulator version 35.1.4",
        "sdkmanager": "13.0",
        "avdmanager": "13.0",
        "android": "Android CLI 1.0",
    }

    def fake_run(argv, **_kwargs):
        executable = str(argv[0]).replace(chr(92), "/").rsplit("/", 1)[-1].lower()
        for suffix in (".exe", ".bat"):
            if executable.endswith(suffix):
                executable = executable[:-len(suffix)]
        version = versions.get(executable, f"{executable} version")
        return subprocess.CompletedProcess(argv, 0, stdout=version + "\n", stderr="")

    monkeypatch.setattr(toolchain.subprocess, "run", fake_run)


# --------------------------------------------------------------------------- #
# roots
# --------------------------------------------------------------------------- #

def test_android_home_wins_and_duplicates_collapse(monkeypatch, tmp_path):
    primary = tmp_path / "primary"
    monkeypatch.setenv("ANDROID_HOME", str(primary))
    monkeypatch.setenv("ANDROID_SDK_ROOT", str(primary))  # same place, two names
    roots = sdk_roots(HOST_WINDOWS)
    assert roots[0] == primary
    assert len([root for root in roots if root == primary]) == 1


def test_default_roots_match_each_hosts_installer(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    for name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        monkeypatch.delenv(name, raising=False)
    windows = {root.as_posix() for root in sdk_roots(HOST_WINDOWS)}
    macos = {root.as_posix() for root in sdk_roots(HOST_MACOS)}
    linux = {root.as_posix() for root in sdk_roots(HOST_LINUX)}
    assert any("AppData" in root and "Android" in root for root in windows), windows
    assert any(root.endswith("Library/Android/sdk") for root in macos), macos
    assert any(root.endswith("Android/Sdk") for root in linux), linux


# --------------------------------------------------------------------------- #
# candidate paths
# --------------------------------------------------------------------------- #

def test_windows_candidates_use_exe_for_platform_tools_and_bat_for_cmdline_tools(tmp_path, monkeypatch):
    sdk = _fake_sdk(tmp_path / "Sdk", host=HOST_WINDOWS)
    monkeypatch.setenv("ANDROID_HOME", str(sdk))
    adb = sdk_candidates(TOOLS_BY_ID["adb"], HOST_WINDOWS)
    emulator = sdk_candidates(TOOLS_BY_ID["emulator"], HOST_WINDOWS)
    manager = sdk_candidates(TOOLS_BY_ID["sdkmanager"], HOST_WINDOWS)
    assert str(sdk / "platform-tools" / "adb.exe") in adb
    assert str(sdk / "emulator" / "emulator.exe") in emulator
    assert str(sdk / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat") in manager
    assert not any(path.endswith("sdkmanager.exe") for path in manager)


def test_versioned_cmdline_tools_directory_is_found(tmp_path, monkeypatch):
    sdk = _fake_sdk(tmp_path / "Sdk", host=HOST_LINUX)
    versioned = sdk / "cmdline-tools" / "13.0" / "bin"
    versioned.mkdir(parents=True)
    (versioned / "avdmanager").write_text("#!/bin/sh\necho 13.0\n", encoding="utf-8")
    monkeypatch.setenv("ANDROID_HOME", str(sdk))
    candidates = sdk_candidates(TOOLS_BY_ID["avdmanager"], HOST_LINUX)
    assert str(versioned / "avdmanager") in candidates


def test_non_windows_candidates_drop_windows_spellings(tmp_path, monkeypatch):
    sdk = _fake_sdk(tmp_path / "Sdk", host=HOST_LINUX)
    monkeypatch.setenv("ANDROID_HOME", str(sdk))
    for tool_id in ANDROID_TOOLS:
        for candidate in sdk_candidates(TOOLS_BY_ID[tool_id], HOST_LINUX):
            assert not candidate.endswith((".exe", ".bat")), (tool_id, candidate)


# --------------------------------------------------------------------------- #
# resolution (the doctor and the plan must agree)
# --------------------------------------------------------------------------- #

def test_probe_finds_adb_in_the_sdk_root_when_path_is_empty(tmp_path, monkeypatch):
    _stub_version_probe(monkeypatch)
    sdk = _fake_sdk(tmp_path / "Sdk", host=HOST_LINUX)
    monkeypatch.setenv("ANDROID_HOME", str(sdk))
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))  # nothing on PATH at all

    path, version = _probe_binary(TOOLS_BY_ID["adb"], HOST_LINUX)
    assert path == str(sdk / "platform-tools" / "adb")
    assert "Android Debug Bridge" in version

    statuses = probe(HOST_LINUX, fresh=True)
    assert statuses["adb"].available and statuses["emulator"].available
    assert "SDK root" in statuses["adb"].reason or statuses["adb"].path.replace(chr(92), "/").endswith("platform-tools/adb")


def test_probe_reports_where_it_looked_when_the_sdk_is_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("ANDROID_HOME", raising=False)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("HOME", str(tmp_path / "nowhere"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "nowhere"))
    _, reason = _probe_binary(TOOLS_BY_ID["adb"], HOST_LINUX)
    assert "not found on PATH" in reason and "also looked in" in reason


def test_tool_path_resolves_the_same_binary_the_doctor_reported(tmp_path, monkeypatch):
    _stub_version_probe(monkeypatch)
    host = host_platform()
    windows = host == HOST_WINDOWS
    sdk = _fake_sdk(tmp_path / "Sdk", host=host)
    monkeypatch.setenv("ANDROID_HOME", str(sdk))
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))

    expected = {
        "adb": sdk / "platform-tools" / ("adb.exe" if windows else "adb"),
        "emulator": sdk / "emulator" / ("emulator.exe" if windows else "emulator"),
        "sdkmanager": sdk / "cmdline-tools" / "latest" / "bin" / ("sdkmanager.bat" if windows else "sdkmanager"),
    }
    for tool_id, expected_path in expected.items():
        doctor_path, _ = _probe_binary(TOOLS_BY_ID[tool_id], host)
        assert doctor_path == str(expected_path)
        assert tool_path(tool_id) == doctor_path


def test_explicit_override_beats_the_sdk_root(tmp_path, monkeypatch):
    _stub_version_probe(monkeypatch)
    sdk = _fake_sdk(tmp_path / "Sdk", host=HOST_LINUX)
    monkeypatch.setenv("ANDROID_HOME", str(sdk))
    custom = tmp_path / "my-adb"
    custom.write_text("#!/bin/sh\necho custom\n", encoding="utf-8")
    custom.chmod(0o755)
    monkeypatch.setenv("CRUSORAI_ADB", str(custom))
    path, _ = _probe_binary(TOOLS_BY_ID["adb"], HOST_LINUX)
    assert path == str(custom)


def test_host_platform_normalizes_python_spellings():
    assert host_platform("win32") == HOST_WINDOWS
    assert host_platform("darwin") == HOST_MACOS
    assert host_platform("linux") == HOST_LINUX


# --------------------------------------------------------------------------- #
# the --setup plan
# --------------------------------------------------------------------------- #

def _run_setup(monkeypatch, targets, *, readiness, host):
    import scripts.targets_doctor as doctor

    monkeypatch.setattr(doctor, "host_platform", lambda *a, **k: host)
    monkeypatch.setattr(doctor, "target_readiness", lambda targets=None: readiness)
    captured: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *args, **kwargs: captured.append(" ".join(str(a) for a in args)))
    code = doctor._setup_plan(list(targets))
    return code, "\n".join(captured)


def test_setup_cli_does_not_crash_on_cp1252_console(monkeypatch):
    import scripts.targets_doctor as doctor

    output = io.BytesIO()
    cp1252_stdout = io.TextIOWrapper(output, encoding="cp1252", errors="strict")
    readiness = {
        "android": {
            "ready": False,
            "missing": ["adb"],
            "host_supported": True,
            "host_reason": "",
        }
    }
    monkeypatch.setattr(doctor, "host_platform", lambda *a, **k: HOST_WINDOWS)
    monkeypatch.setattr(doctor, "target_readiness", lambda targets=None: readiness)
    with monkeypatch.context() as patch:
        patch.setattr(doctor.sys, "stdout", cp1252_stdout)
        code = doctor.main(["--setup", "android"])
        cp1252_stdout.flush()
    rendered = output.getvalue()
    cp1252_stdout.close()

    assert code == 1  # Android tools are still missing; output itself succeeded.
    assert b"Setup plan" in rendered
    assert b"\\u26d4" in rendered  # unsupported icon is escaped instead of raising.
    assert b"winget install --id Google.AndroidCLI" in rendered


@pytest.mark.parametrize(
    ("host", "expected_command"),
    [
        (HOST_WINDOWS, "winget install --id Google.AndroidCLI"),
        (HOST_MACOS, "brew install openjdk@21"),
        (HOST_LINUX, "sudo apt install openjdk-21-jdk"),
    ],
)
def test_android_setup_plan_has_native_instructions_for_each_host(monkeypatch, host, expected_command):
    code, output = _run_setup(
        monkeypatch,
        ["android"],
        readiness={
            "android": {
                "ready": False,
                "missing": ["adb"],
                "host_supported": True,
                "host_reason": "",
            }
        },
        host=host,
    )
    assert code == 1
    assert expected_command in output


def test_setup_plan_lists_missing_tools_and_windows_commands(monkeypatch):
    code, output = _run_setup(
        monkeypatch, ["android"],
        readiness={"android": {"ready": False, "missing": ["adb", "emulator"], "host_supported": True,
                               "host_reason": ""}},
        host=HOST_WINDOWS,
    )
    assert code == 1
    assert "missing adb, emulator" in output
    assert "winget install --id Google.AndroidCLI" in output        # no Android Studio dependency
    assert "Android Studio is NOT required" in output
    assert "sdkmanager.bat" in output and "avdmanager.bat" in output  # SDK + AVD setup
    assert "system-images/android-35/google_apis/x86_64" in output or "system-images;android-35;google_apis;x86_64" in output
    assert "LOCALAPPDATA" in output                                   # no PATH edits promised
    assert "winget install Google.AndroidStudio" not in output


def test_setup_plan_is_empty_work_when_the_target_is_ready(monkeypatch):
    code, output = _run_setup(
        monkeypatch, ["android"],
        readiness={"android": {"ready": True, "missing": [], "host_supported": True, "host_reason": ""}},
        host=HOST_WINDOWS,
    )
    assert code == 0
    assert "Nothing to install" in output and "winget" not in output


def test_setup_plan_does_not_pretend_a_command_fixes_an_unsupported_host(monkeypatch):
    code, output = _run_setup(
        monkeypatch, ["ios"],
        readiness={"ios": {"ready": False, "missing": ["xcodebuild"], "host_supported": False,
                           "host_reason": "iOS simulator builds requires macOS + Xcode."}},
        host=HOST_WINDOWS,
    )
    assert code == 1
    assert "requires macOS" in output
    assert "no command fixes that" in output
    # No install block at all: nothing on Windows makes xcodebuild exist.
    assert "brew install" not in output and "apt install" not in output


def test_setup_plan_rejects_an_unknown_target(monkeypatch):
    def explode(targets=None):
        raise KeyError("nope")

    import scripts.targets_doctor as doctor

    monkeypatch.setattr(doctor, "host_platform", lambda *a, **k: HOST_WINDOWS)
    monkeypatch.setattr(doctor, "target_readiness", explode)
    code, output = _run_setup(monkeypatch, ["nonsense"], readiness={}, host=HOST_WINDOWS)
    assert code == 2  # unknown target is distinct from an incomplete installation
    assert "unknown" in output


def test_setup_plan_defaults_to_android(monkeypatch):
    code, output = _run_setup(
        monkeypatch, [],
        readiness={"android": {"ready": False, "missing": ["adb"], "host_supported": True,
                               "host_reason": ""}},
        host=HOST_LINUX,
    )
    assert code == 1 and "android" in output and "/dev/kvm" in output


def test_setup_plan_is_target_specific_not_android_for_everything(monkeypatch):
    code, output = _run_setup(
        monkeypatch, ["flutter"],
        readiness={"flutter": {"ready": False, "missing": ["flutter"], "host_supported": True,
                               "host_reason": "", "optional_missing": []}},
        host=HOST_WINDOWS,
    )
    assert code == 1
    assert "Install Flutter for Windows" in output
    assert "sdkmanager.bat" not in output
    assert "AndroidStudio" not in output


def test_windows_android_setup_has_android_cli_and_no_studio(monkeypatch):
    code, output = _run_setup(
        monkeypatch, ["android"],
        readiness={"android": {"ready": False, "missing": ["adb", "java"],
                               "optional_missing": ["android-cli", "emulator", "sdkmanager", "avdmanager"],
                               "host_supported": True, "host_reason": ""}},
        host=HOST_WINDOWS,
    )
    assert code == 1
    assert "android-cli" in output and "emulator" in output
    assert 'android "--sdk=$sdk" sdk install' in output
    assert "Android Studio is NOT required" in output
    assert "winget install Google.AndroidStudio" not in output
    assert "emulator subcommand is currently disabled on Windows" in output
    assert "emulator.exe" in output


def test_setup_ios_windows_explains_prebuilt_physical_device_only(monkeypatch):
    code, output = _run_setup(
        monkeypatch, ["ios"],
        readiness={"ios": {"ready": False, "missing": ["pymobiledevice3"], "host_supported": True,
                           "host_reason": "physical-device proof only; Xcode requires macOS"}},
        host=HOST_WINDOWS,
    )
    assert code == 1
    assert "pymobiledevice3" in output
    assert "cannot build an Xcode project" in output
    assert "Android Studio" not in output


def test_android_cli_tool_spec_is_optional_and_override_aware(monkeypatch, tmp_path):
    _stub_version_probe(monkeypatch)
    spec = TOOLS_BY_ID["android-cli"]
    assert spec.required is False
    assert "Google.AndroidCLI" in spec.hint_for(HOST_WINDOWS)
    cli = tmp_path / "android.exe"
    cli.write_text("#!/bin/sh\necho 'Android CLI 1.0'\n", encoding="utf-8")
    cli.chmod(0o755)
    monkeypatch.setenv("CRUSORAI_ANDROID_CLI", str(cli))
    path, version = _probe_binary(spec, HOST_WINDOWS)
    assert path == str(cli)
    assert "Android CLI" in version
