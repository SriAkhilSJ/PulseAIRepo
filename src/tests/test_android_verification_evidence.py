"""Android/mobile toolchain is recognized by BOTH verification surfaces.

There are two independent copies of "is this command verification?" in the
runtime, and they gate different things:

  1. ``src/context/verification_evidence.py`` ``_VERIFY_RE`` — the passive
     ledger the IDE surfaces as correctness state.
  2. ``src/graphs/gates.py`` ``_verification_receipt_status`` — the STOP
     gate that decides whether "✅ Finished" is allowed at all.

Both were blind to the entire mobile toolchain. The gap in (2) was not
symmetric with (1): it matched on substrings like ``" test"``, which needs a
leading space, so ``connectedAndroidTest`` (the Android instrumented UI test
task) and ``assembleDebug`` (the Android build) both failed to match. An
agent could therefore build and device-test a real app and still be told it
had proved nothing — or, worse, learn to assert success anyway because
nothing contradicted it.

These tests pin the recognition AND the pipe-masking guard, so widening the
matcher can never re-open the attempts-11/12 failure mode (a piped exit code
masking a broken build).
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.context.verification_evidence import VerificationLedger
from src.graphs.gates import _verification_receipt_status

WS = "/tmp/android-project"


# ---------------------------------------------------------------------------
# (1) ledger classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command,expected_kind", [
    ("./gradlew assembleDebug", "build"),
    ("./gradlew assembleRelease", "build"),
    ("./gradlew build", "build"),
    ("gradlew.bat assembleDebug", "build"),          # Windows, no ./ prefix
    (r".\gradlew.bat build", "build"),               # Windows path prefix
    ("./gradlew test", "test"),
    ("./gradlew connectedAndroidTest", "test"),      # the Android UI test task
    ("./gradlew connectedDebugAndroidTest", "test"),
    ("./gradlew testDebugUnitTest", "test"),
    ("./gradlew lint", "lint"),
    ("gradle check", "test"),
])
def test_gradle_commands_are_recognized_and_correctly_kinded(command, expected_kind):
    result = VerificationLedger.classify(command)
    assert result is not None, f"{command!r} must be recognized as verification"
    kind, _scope = result
    assert kind == expected_kind, (
        f"{command!r} classified as {kind!r}, expected {expected_kind!r} — "
        "assemble* is a build, connectedAndroidTest is a test"
    )


@pytest.mark.parametrize("command,expected_kind", [
    ("adb install app-debug.apk", "build"),
    ("adb install -r app/build/outputs/apk/debug/app-debug.apk", "build"),
    ("adb shell am instrument -w com.example/.TestRunner", "test"),
])
def test_adb_verification_commands_are_recognized(command, expected_kind):
    result = VerificationLedger.classify(command)
    assert result is not None, f"{command!r} must be recognized as verification"
    assert result[0] == expected_kind


@pytest.mark.parametrize("command", [
    "maestro test flows/login.yaml",
    "maestro test --format junit flows/",
    "agent-device test",
    "agent-device replay flows/checkout.ad",
])
def test_mobile_ui_test_drivers_are_recognized(command):
    assert VerificationLedger.classify(command) is not None


@pytest.mark.parametrize("command", [
    "adb devices",                    # a probe, not a verification
    "adb devices -l",
    "agent-device snapshot",          # inspection, not proof
    "agent-device help",
    "agent-device doctor",
    "agent-device devices",
    "maestro studio",
    "gradlew",                        # no task — nothing was verified
])
def test_probes_and_inspection_are_not_phantom_evidence(command):
    """Looking at a device proves nothing. Only build/test/install does.

    A matcher widened to catch the mobile toolchain must not start recording
    evidence for read-only inspection, or the ledger fills with green noise.
    """
    assert VerificationLedger.classify(command) is None


@pytest.mark.parametrize("command", [
    "mypy main.kt",
    "ruff check MainActivity.java",
    "./gradlew test res/layout/activity_main.xml",
    "./gradlew lint app/src/main/AndroidManifest.xml",
    "tsc build.gradle.kts",
])
def test_kotlin_java_and_xml_targets_are_targeted_not_full(command):
    """File-scoped evidence must not masquerade as a whole-repo green."""
    result = VerificationLedger.classify(command)
    assert result is not None
    assert result[1] == "targeted"


# ---------------------------------------------------------------------------
# (2) the pipe-masking guard must survive the widened matcher
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "./gradlew test 2>&1 | tail -40",
    "./gradlew connectedAndroidTest | grep -i fail",
    "./gradlew assembleDebug | tee build.log",
    "./gradlew build || echo ok",
    "./gradlew test & ",
])
def test_piped_or_masked_gradle_records_no_evidence(tmp_path, command):
    """The attempts-11/12 regression, on the Android toolchain.

    A piped/`||`ed/backgrounded command's exit code says nothing about the
    segment inside it: `./gradlew test 2>&1 | tail -40` on a BROKEN build
    reports tail's 0. Widening the matcher must not widen what counts as
    proof — an unattributable run records NO evidence at all.
    """
    ledger = VerificationLedger(tmp_path / "verification.db")
    recorded = ledger.record_command(
        session_id="s", workspace=WS, command=command,
        exit_code=0, output="BUILD FAILED",
    )
    assert recorded is None, (
        f"{command!r} has an unattributable exit code and must record no "
        "evidence, otherwise a masked failure reads as a pass"
    )
    assert ledger.status(session_id="s", workspace=WS)["status"] != "passed"


def test_plain_gradle_success_records_passed(tmp_path):
    ledger = VerificationLedger(tmp_path / "verification.db")
    recorded = ledger.record_command(
        session_id="s", workspace=WS, command="./gradlew assembleDebug",
        exit_code=0, output="BUILD SUCCESSFUL in 42s",
    )
    assert recorded is not None and recorded["status"] == "passed"
    assert recorded["kind"] == "build"
    assert ledger.status(session_id="s", workspace=WS)["status"] == "passed"


def test_plain_gradle_failure_records_failed(tmp_path):
    ledger = VerificationLedger(tmp_path / "verification.db")
    recorded = ledger.record_command(
        session_id="s", workspace=WS, command="./gradlew assembleDebug",
        exit_code=1, output="FAILURE: Build failed with an exception.",
    )
    assert recorded is not None and recorded["status"] == "failed"
    assert ledger.status(session_id="s", workspace=WS)["status"] == "failed"


# ---------------------------------------------------------------------------
# (3) the STOP gate — the copy that actually permits "✅ Finished"
# ---------------------------------------------------------------------------

def _state_with_terminal(command: str, output: str = "exit code: 0") -> dict:
    """Minimal state: one AIMessage tool call + its ToolMessage result."""
    return {
        "current_task": "refactor the kotlin notes repository",
        "messages": [
            AIMessage(content="", tool_calls=[{
                "id": "call-1", "name": "run_terminal", "args": {"command": command},
            }]),
            ToolMessage(content=output, tool_call_id="call-1", name="run_terminal"),
        ],
    }


@pytest.mark.parametrize("command", [
    "./gradlew assembleDebug",
    "./gradlew connectedAndroidTest",   # no space before "test" — the old gap
    "gradlew.bat assembleDebug",
    "./gradlew testDebugUnitTest",
    "adb install app-debug.apk",
    "maestro test flows/login.yaml",
    "agent-device replay flows/checkout.ad",
])
def test_stop_gate_accepts_android_verification(command):
    """A real Android verification must satisfy the static domain.

    Before the fix this list was matched on substrings like `" test"`, which
    requires a leading space — so `connectedAndroidTest` and `assembleDebug`
    were invisible and the agent could never legitimately finish.
    """
    status = _verification_receipt_status(_state_with_terminal(command))
    assert status["static"] is True, f"{command!r} did not satisfy the stop gate"


@pytest.mark.parametrize("command", [
    "ls -la",
    "cat build.gradle.kts",     # pre-existing false positive: matched `" build"`
    "cat build.sh",             # same, on the shell side
    "cat Makefile && ls",
    "head -40 build.gradle.kts",
    "adb devices",
    "agent-device snapshot",
])
def test_stop_gate_does_not_accept_non_verification(command):
    """Reading a file is not verifying a build.

    `cat build.gradle.kts` satisfied the static domain on 75b0add2 because
    the matcher substring-tested `" build"`. An agent that only read a file
    was being told it had proved the build.
    """
    status = _verification_receipt_status(_state_with_terminal(command))
    assert status["static"] is False


@pytest.mark.parametrize("command", [
    "cd app && ./gradlew test",           # real check behind a chain
    "./gradlew test | tail -40",          # real check that is piped
    "cd app; npm run build",
])
def test_stop_gate_still_accepts_checks_behind_a_chain(command):
    """The read-only guard must not swallow genuine chained verifications."""
    status = _verification_receipt_status(_state_with_terminal(command))
    assert status["static"] is True


def test_stop_gate_rejects_android_failure():
    status = _verification_receipt_status(
        _state_with_terminal("./gradlew assembleDebug", output="exit code: 1\nBUILD FAILED")
    )
    assert status["static"] is False


# ---------------------------------------------------------------------------
# (4) regression — the existing web/python toolchain is unchanged
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("command,expected_kind", [
    ("pytest -q", "test"),
    ("npm run build", "build"),
    ("npm run lint", "lint"),
    ("npm run typecheck", "typecheck"),
    ("tsc --noEmit", "typecheck"),
    ("cargo test", "test"),
    ("go test ./...", "test"),
    ("make build", "build"),
    ("ruff check .", "lint"),
])
def test_existing_toolchains_still_classify_identically(command, expected_kind):
    result = VerificationLedger.classify(command)
    assert result is not None
    assert result[0] == expected_kind


# ---------------------------------------------------------------------------
# (5) reporting-only invocations are not verification, on EITHER surface
#
# The first cut of this change guarded `adb devices` and `agent-device
# snapshot` but let `./gradlew tasks` and `adb shell ls` through — the same
# phantom-evidence hole, just on the tools that were newly matched. These
# tests hold both surfaces to one rule.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "gradle tasks",
    "./gradlew tasks",
    "./gradlew tasks --all",
    "./gradlew help",
    "./gradlew projects",
    "./gradlew properties",
    "./gradlew dependencies",
    "./gradlew wrapper",
    "./gradlew signingReport",
    ":app:tasks",                              # module-qualified
    "./gradlew :app:dependencies --configuration debugRuntimeClasspath",
])
def test_gradle_reporting_tasks_are_not_phantom_evidence(command):
    assert VerificationLedger.classify(command) is None


@pytest.mark.parametrize("command", [
    "adb shell ls /sdcard",
    "adb shell getprop ro.build.version.sdk",
    "adb logcat -d",
    "adb push file.txt /sdcard/",
    "adb pull /sdcard/screen.png .",
])
def test_adb_inspection_is_not_phantom_evidence(command):
    """Only `adb install` and `adb shell am instrument` prove anything."""
    assert VerificationLedger.classify(command) is None


@pytest.mark.parametrize("command,expected_kind", [
    ("adb install app-debug.apk", "build"),
    ("adb install -r -t app-debug.apk", "build"),
    ("adb shell am instrument -w com.example/.TestRunner", "test"),
])
def test_adb_verification_survives_the_narrowing(command, expected_kind):
    result = VerificationLedger.classify(command)
    assert result is not None
    assert result[0] == expected_kind


@pytest.mark.parametrize("command", [
    "./gradlew tasks",
    "./gradlew help",
    "gradle dependencies",
    "cd app && cat build.gradle.kts",   # `cd` must not launder a pure read
    "adb shell ls /sdcard",
])
def test_stop_gate_rejects_reporting_and_chained_reads(command):
    status = _verification_receipt_status(_state_with_terminal(command))
    assert status["static"] is False


# ---------------------------------------------------------------------------
# (6) the two surfaces must not drift apart again
#
# This bug existed because recognition was written twice. A shared table,
# asserted against BOTH surfaces, is the cheapest thing that keeps them
# honest. Anything added to one list without the other fails here.
# ---------------------------------------------------------------------------

_SHOULD_VERIFY = [
    "./gradlew assembleDebug",
    "./gradlew build",
    "./gradlew test",
    "./gradlew connectedAndroidTest",
    "./gradlew lint",
    "gradlew.bat assembleDebug",
    "adb install app-debug.apk",
    "adb shell am instrument -w com.example/.TestRunner",
    "maestro test flows/login.yaml",
    "agent-device replay flows/checkout.ad",
    "pytest -q",
    "npm run build",
]

_SHOULD_NOT_VERIFY = [
    "gradle tasks",
    "./gradlew help",
    "./gradlew projects",
    "adb devices",
    "adb shell ls /sdcard",
    "adb logcat -d",
    "agent-device snapshot",
    "agent-device doctor",
    "cat build.gradle.kts",
    "cd app && cat build.gradle.kts",
    "ls -la",
]


@pytest.mark.parametrize("command", _SHOULD_VERIFY)
def test_both_surfaces_agree_this_is_verification(command):
    assert VerificationLedger.classify(command) is not None, "ledger disagrees"
    assert _verification_receipt_status(_state_with_terminal(command))["static"] is True, (
        "stop gate disagrees"
    )


@pytest.mark.parametrize("command", _SHOULD_NOT_VERIFY)
def test_both_surfaces_agree_this_is_not_verification(command):
    assert VerificationLedger.classify(command) is None, "ledger disagrees"
    assert _verification_receipt_status(_state_with_terminal(command))["static"] is False, (
        "stop gate disagrees"
    )
