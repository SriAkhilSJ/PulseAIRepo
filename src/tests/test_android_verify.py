"""verify_android_app: the receipt must never outrank the evidence.

Run against a stubbed toolchain (fake java/gradlew/adb on PATH) so the whole
pipeline is exercised with no JDK, no Android SDK and no device. That is the
point: the *logic* — what counts as proof, and what stops the run short — is
deterministic and testable here, while a real build is not.

The behaviours that matter are the ones that refuse to overclaim:

  - a build that exits 0 but produces no APK is a FAILURE, not a pass
  - an APK whose real package differs from the one requested is a FAILURE
  - no JDK / no gradle / no device yields `UNAVAILABLE` or `PARTIAL`,
    never `PASSED` — those read completely differently to a user
  - a launch that installs cleanly and then dies is caught by `pidof`, not
    by the exit code of `am start`
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from src.tools.android_verify import verify_android_app

PKG = "com.akhil.notes"


# ---------------------------------------------------------------------------
# stub toolchain
# ---------------------------------------------------------------------------

def _write_exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture(autouse=True)
def _fast_settle(monkeypatch):
    """The launch settle exists for a real device cold start; tests use stubs."""
    from src.tools import android_verify

    monkeypatch.setattr(android_verify, "_LAUNCH_SETTLE_S", 0.0)


@pytest.fixture
def stubbin(tmp_path_factory):
    """A directory of fake toolchain binaries, put first on PATH."""
    d = tmp_path_factory.mktemp("stubbin")
    _write_exe(d / "java", 'echo \'openjdk version "17.0.11"\' >&2')
    return d


@pytest.fixture
def adb_stub(stubbin):
    """Install a cooperative adb into the stub dir and return a rewriter."""
    _write_exe(stubbin / "adb", """
case "$*" in
  *devices*)   printf 'List of devices attached\\nemulator-5554\\tdevice\\n' ;;
  *install*)   echo 'Success' ;;
  *"am start"*) echo 'Starting: Intent' ;;
  *pidof*)     echo '8421' ;;
  *logcat*)    echo '01-01 00:00:00 I com.akhil.notes: started' ;;
  *)           echo '' ;;
esac
""")
    return stubbin


def _adb_with(stubbin: Path, *, devices: str = "emulator-5554\tdevice",
              install: str = "Success", pidof: str = "8421",
              logcat: str = "I com.akhil.notes: started") -> None:
    _write_exe(stubbin / "adb", f"""
case "$*" in
  *devices*)   printf 'List of devices attached\\n{devices}\\n' ;;
  *install*)   echo '{install}' ;;
  *"am start"*) echo 'Starting: Intent' ;;
  *pidof*)     echo '{pidof}' ;;
  *logcat*)    echo '{logcat}' ;;
  *)           echo '' ;;
esac
""")


@pytest.fixture
def use_path(monkeypatch):
    def _apply(d: Path) -> None:
        monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ.get('PATH', '')}")
    return _apply


def _project(tmp_path: Path, *, build: str, makes_apk: bool = True) -> Path:
    """A minimal workspace with a fake Gradle wrapper."""
    ws = tmp_path / "ws"
    ws.mkdir()
    apk_line = (
        'mkdir -p app/build/outputs/apk/debug; '
        'echo "fake apk bytes" > app/build/outputs/apk/debug/app-debug.apk; '
        if makes_apk else ""
    )
    _write_exe(ws / "gradlew", f"""
if [ "$1" = "assembleDebug" ]; then
  {apk_line}{build}
fi
exit 0
""")
    return ws


def _verify(ws: Path, **kwargs) -> str:
    return verify_android_app.invoke(
        {"package_id": PKG, **kwargs},
        config={"configurable": {"workspace": str(ws)}},
    )


def _evidence(ws: Path) -> dict:
    runs = sorted((ws / ".crusorai" / "android-evidence").iterdir())
    return json.loads((runs[-1] / "evidence.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# the happy path
# ---------------------------------------------------------------------------

def test_full_pipeline_reaches_tier_2(tmp_path, adb_stub, use_path):
    use_path(adb_stub)
    ws = _project(tmp_path, build='echo "BUILD SUCCESSFUL"; exit 0')
    out = _verify(ws)

    assert out.startswith("✅ PASSED"), out
    manifest = _evidence(ws)
    assert manifest["overall"].startswith("✅")
    assert manifest["tier_reached"] == 2
    for name in ("gradle_assembleDebug", "apk_identity", "device_online",
                 "adb_install", "process_alive", "no_fatal_in_logcat"):
        assert manifest["checks"][name]["status"] == "passed", name


def test_every_check_carries_an_observed_value_or_exit_code(tmp_path, adb_stub, use_path):
    """A verdict with no observation is indistinguishable from a fabricated one."""
    use_path(adb_stub)
    ws = _project(tmp_path, build='exit 0')
    _verify(ws)
    manifest = _evidence(ws)
    for name, check in manifest["checks"].items():
        assert "observed" in check or "exit" in check, (
            f"{name} recorded a verdict with nothing behind it"
        )


def test_apk_identity_is_anchored_by_hash(tmp_path, adb_stub, use_path):
    use_path(adb_stub)
    ws = _project(tmp_path, build='exit 0')
    _verify(ws)
    manifest = _evidence(ws)
    identity = manifest["checks"]["apk_identity"]["observed"]
    assert identity["sha256"] and identity["bytes"] > 0
    assert (ws / ".crusorai" / "android-evidence").exists()


def test_build_log_is_written_untruncated(tmp_path, adb_stub, use_path):
    """The real Gradle error is usually mid-file, not in the tail."""
    use_path(adb_stub)
    ws = _project(tmp_path, build='exit 0')
    _verify(ws)
    runs = sorted((ws / ".crusorai" / "android-evidence").iterdir())
    assert (runs[-1] / "build.log").is_file()


# ---------------------------------------------------------------------------
# refusing to overclaim
# ---------------------------------------------------------------------------

def test_green_exit_with_no_apk_is_a_failure(tmp_path, adb_stub, use_path):
    """The quietest way to ship nothing: Gradle says success, no artifact exists."""
    use_path(adb_stub)
    ws = _project(tmp_path, build='echo "BUILD SUCCESSFUL"; exit 0', makes_apk=False)
    out = _verify(ws)
    assert out.startswith("❌ FAILED"), out
    assert _evidence(ws)["checks"]["apk_present"]["status"] == "failed"


def test_build_failure_reports_the_exit_code_and_the_log(tmp_path, adb_stub, use_path):
    use_path(adb_stub)
    ws = _project(tmp_path, build='echo "e: unresolved reference: foo" >&2; exit 1')
    out = _verify(ws)
    assert out.startswith("❌ FAILED")
    assert "exited 1" in out and "exit=1" in out
    assert "unresolved reference" in out, "the actual error must reach the model"
    assert _evidence(ws)["tier_reached"] == 0


def test_app_that_crashes_on_launch_is_caught_by_pidof(tmp_path, stubbin, use_path):
    """`am start` exits 0 even when the app dies immediately. Only the process
    check proves it is actually running."""
    _adb_with(stubbin, pidof="", logcat="E AndroidRuntime: FATAL EXCEPTION: main")
    use_path(stubbin)
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws)
    assert out.startswith("❌ FAILED"), out
    assert _evidence(ws)["checks"]["process_alive"]["status"] == "failed"


def test_fatal_logcat_fails_the_run(tmp_path, stubbin, use_path):
    _adb_with(stubbin, logcat="E AndroidRuntime: FATAL EXCEPTION: main")
    use_path(stubbin)
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws)
    assert out.startswith("❌ FAILED")
    assert _evidence(ws)["checks"]["no_fatal_in_logcat"]["observed"]["fatal"] >= 1


def test_install_failure_is_reported(tmp_path, stubbin, use_path):
    _adb_with(stubbin, install="Failure [INSTALL_FAILED_OLDER_SDK]")
    use_path(stubbin)
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws)
    assert out.startswith("❌ FAILED")
    assert "INSTALL_FAILED" in out


# ---------------------------------------------------------------------------
# unavailable is not failed, and neither is passed
# ---------------------------------------------------------------------------

def test_no_jdk_is_unavailable_not_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))  # empty dir: nothing on PATH
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws)
    assert out.startswith("⛔ UNAVAILABLE"), out
    assert "NOT a failure of the code" in out
    assert _evidence(ws)["tier_reached"] == 0


def test_no_gradle_is_unavailable(tmp_path, stubbin, use_path):
    use_path(stubbin)
    ws = tmp_path / "empty"
    ws.mkdir()
    out = _verify(ws)
    assert out.startswith("⛔ UNAVAILABLE"), out
    assert "scaffold_android" in out, "must name the way forward"


def test_builds_but_no_device_is_partial_tier_1(tmp_path, stubbin, use_path):
    """A real build with no device must never read as a working app."""
    use_path(stubbin)  # java only, no adb
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws)
    assert out.startswith("⚠️ PARTIAL"), out
    manifest = _evidence(ws)
    assert manifest["tier_reached"] == 1
    assert "do not describe this as a working app" in out


def test_no_attached_device_is_partial_tier_1(tmp_path, stubbin, use_path):
    _adb_with(stubbin, devices="")
    use_path(stubbin)
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws)
    assert out.startswith("⚠️ PARTIAL"), out
    assert _evidence(ws)["tier_reached"] == 1


def test_ui_flow_without_agent_device_does_not_claim_tier_3(tmp_path, adb_stub, use_path):
    """A requested UI flow that could not run must not silently vanish."""
    use_path(adb_stub)
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws, flow_yaml="- launchApp\n- assertVisible: Hello\n")
    assert out.startswith("⚠️ PARTIAL"), out
    manifest = _evidence(ws)
    assert manifest["checks"]["ui_flow"]["status"] == "unavailable"
    assert manifest["tier_reached"] == 2, "must not claim Tier 3 it never reached"
    assert "do not describe the UI as verified" in out


def test_ui_flow_is_archived_so_it_can_be_replayed(tmp_path, adb_stub, use_path):
    """Evidence you cannot re-run is just a claim with extra steps."""
    _write_exe(adb_stub / "agent-device", 'echo "flow passed"; exit 0')
    use_path(adb_stub)
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws, flow_yaml="- launchApp\n- assertVisible: Hello\n")
    assert out.startswith("✅ PASSED"), out
    manifest = _evidence(ws)
    assert manifest["tier_reached"] == 3
    runs = sorted((ws / ".crusorai" / "android-evidence").iterdir())
    assert (runs[-1] / "flow.yaml").is_file()


# ---------------------------------------------------------------------------
# the exit code must be real, not grepped out of text
# ---------------------------------------------------------------------------

def test_build_never_pipes_so_the_exit_code_cannot_be_masked(tmp_path, adb_stub, use_path):
    """The whole point of reading returncode: a piped build reports the pipe's
    status. This tool must not construct one."""
    import inspect

    from src.tools import android_verify

    source = inspect.getsource(android_verify)
    assert "| tail" not in source and "| grep" not in source
    assert "shell=True" not in source, "a shell would reintroduce masking"


def test_run_tests_flag_runs_the_project_tests(tmp_path, adb_stub, use_path):
    _write_exe(tmp_path / "marker", "true")
    ws = _project(tmp_path, build='exit 0')
    # rewrite the wrapper so `test` leaves a trace we can assert on
    _write_exe(ws / "gradlew", """
if [ "$1" = "assembleDebug" ]; then
  mkdir -p app/build/outputs/apk/debug
  echo "fake apk bytes" > app/build/outputs/apk/debug/app-debug.apk
  exit 0
fi
if [ "$1" = "test" ]; then
  echo "TESTS RAN" > tested.marker
  exit 0
fi
exit 0
""")
    use_path(adb_stub)
    out = _verify(ws, run_tests=True)
    assert out.startswith("✅ PASSED"), out
    assert (ws / "tested.marker").is_file(), "run_tests did not invoke gradle test"


# ---------------------------------------------------------------------------
# Phase B: crash reports as first-class evidence
# ---------------------------------------------------------------------------

_JAVA_CRASH = """\
01-01 00:00:01.000  1234  1234 E AndroidRuntime: FATAL EXCEPTION: main
01-01 00:00:01.000  1234  1234 E AndroidRuntime: Process: com.akhil.notes, PID: 1234
01-01 00:00:01.000  1234  1234 E AndroidRuntime: java.lang.NullPointerException: Attempt to invoke virtual method
01-01 00:00:01.000  1234  1234 E AndroidRuntime: \tat com.akhil.notes.MainActivity.onCreate(MainActivity.kt:42)
"""

_NATIVE_CRASH = """\
*** *** *** *** *** *** *** *** *** *** *** *** *** *** *** ***
pid: 1234, tid: 1234, name: main  >>> com.akhil.notes <<<
signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 0x0
"""


def _adb_crash(stubbin: Path, *, crash: str) -> None:
    """adb whose crash buffer holds `crash` and whose main buffer is quiet."""
    _write_exe(stubbin / "adb", f"""
case "$*" in
  *devices*)      printf 'List of devices attached\\nemulator-5554\\tdevice\\n' ;;
  *install*)      echo 'Success' ;;
  *"am start"*)   echo 'Starting: Intent' ;;
  *pidof*)        echo '8421' ;;
  *"-b crash"*)   printf '{crash}' ;;
  *logcat*)       echo '01-01 00:00:00 I com.akhil.notes: started' ;;
  *)              echo '' ;;
esac
""")


def test_java_crash_fails_the_run_and_names_the_exception(tmp_path, stubbin, use_path):
    """A crash dump is Tier-3 evidence about a specific defect, so the receipt
    must carry the throwable rather than a count of scary lines."""
    _adb_crash(stubbin, crash=_JAVA_CRASH)
    use_path(stubbin)
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws)
    assert out.startswith("❌ FAILED"), out
    assert "java.lang.NullPointerException" in out
    assert "Tier-3" in out
    assert "do not describe the app as working" in out

    manifest = _evidence(ws)
    check = manifest["checks"]["crash_reports"]
    assert check["status"] == "failed"
    assert check["tier"] == 3
    assert check["observed"]["count"] == 1
    assert check["observed"]["signatures"] == ["java.lang.NullPointerException"]
    assert len(check["observed"]["sha256"]) == 64, "the dump must be hash-anchored"


def test_native_signal_crash_is_recognised(tmp_path, stubbin, use_path):
    _adb_crash(stubbin, crash=_NATIVE_CRASH)
    use_path(stubbin)
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws)
    assert out.startswith("❌ FAILED"), out
    assert _evidence(ws)["checks"]["crash_reports"]["observed"]["signatures"] == ["SIGSEGV"]


def test_crash_dump_is_saved_in_full(tmp_path, stubbin, use_path):
    _adb_crash(stubbin, crash=_JAVA_CRASH)
    use_path(stubbin)
    ws = _project(tmp_path, build='exit 0')
    _verify(ws)
    runs = sorted((ws / ".crusorai" / "android-evidence").iterdir())
    saved = (runs[-1] / "crash.txt").read_text(encoding="utf-8")
    assert "MainActivity.kt:42" in saved, "the stack frame is the useful part"


def test_clean_crash_buffer_passes(tmp_path, adb_stub, use_path):
    """The default stub has a quiet crash buffer — it must read as passed."""
    use_path(adb_stub)
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws)
    assert out.startswith("✅ PASSED"), out
    assert _evidence(ws)["checks"]["crash_reports"]["status"] == "passed"


def test_missing_crash_buffer_is_unavailable_not_a_pass(tmp_path, stubbin, use_path):
    """Older devices have no crash ring. Absence of evidence must not be
    laundered into a green tick."""
    _write_exe(stubbin / "adb", """
case "$*" in
  *devices*)      printf 'List of devices attached\\nemulator-5554\\tdevice\\n' ;;
  *install*)      echo 'Success' ;;
  *"am start"*)   echo 'Starting: Intent' ;;
  *pidof*)        echo '8421' ;;
  *"-b crash"*)   echo 'logcat: bad buffer name' >&2; exit 1 ;;
  *logcat*)       echo '01-01 00:00:00 I com.akhil.notes: started' ;;
  *)              echo '' ;;
esac
""")
    use_path(stubbin)
    ws = _project(tmp_path, build='exit 0')
    out = _verify(ws)
    manifest = _evidence(ws)
    assert manifest["checks"]["crash_reports"]["status"] == "unavailable"
    assert manifest["tier_reached"] == 2, "no crash data must not lift the tier"


def test_signature_extraction_deduplicates():
    from src.tools.android_verify import _crash_signatures

    assert _crash_signatures(_JAVA_CRASH * 5) == ["java.lang.NullPointerException"]
    assert _crash_signatures(_NATIVE_CRASH) == ["SIGSEGV"]
    assert _crash_signatures("I ok: nothing wrong here") == []
    # both kinds in one dump, in order of appearance
    both = _crash_signatures(_JAVA_CRASH + _NATIVE_CRASH)
    assert both == ["java.lang.NullPointerException", "SIGSEGV"]
