"""CAP_ANDROID: the posture resolver routes Android work, and the tool is real.

Three things this pins:

1. **Android resolves to Android.** `_BROWSER_PATTERNS` contains ``\\bui\\b``, so
   "build an Android UI" used to resolve to the BROWSER posture and bind
   CDP/Playwright tools that cannot drive a phone. Android now owns the "ui"
   signal unless an explicit web stack is also present.
2. **The tool the resolver names actually exists.** A capability that binds a
   phantom tool is worse than no capability: the model calls it and gets a
   KeyError-shaped silence. ``android_doctor`` must be in ``_TOOLS_BY_NAME``.
3. **No false positives.** Bare "activity", "fragment" and "compose" are
   ordinary words — an analytics task must not be handed a phone toolchain.

Also pins that CAP_ANDROID is APPENDED to CAPABILITY_ORDER: that tuple's order
is part of the prompt-cache contract, so inserting mid-tuple would churn cache
keys for every unrelated profile.
"""
from __future__ import annotations

import pytest

from src.agents.runtime_profile import (
    CAPABILITY_ORDER,
    CAP_ANDROID,
    CAP_BROWSER,
    CAP_EXECUTION,
    CAP_VERIFICATION,
    CAP_WORKSPACE_READ,
    CAP_WORKSPACE_WRITE,
    KNOWN_CAPABILITIES,
    resolve_runtime_profile,
)
from src.tools.toolsets import all_known_tool_names, resolve_toolset_names


# ---------------------------------------------------------------------------
# capability registration
# ---------------------------------------------------------------------------

def test_cap_android_is_registered_and_last():
    assert CAP_ANDROID in KNOWN_CAPABILITIES
    assert CAPABILITY_ORDER[-1] == CAP_ANDROID, (
        "CAP_ANDROID must be APPENDED — CAPABILITY_ORDER's order is part of the "
        "prompt-cache contract; inserting mid-tuple churns unrelated cache keys"
    )


def test_existing_capability_order_is_unchanged():
    assert CAPABILITY_ORDER[:-1] == (
        "workspace_read", "workspace_write", "execution",
        "verification", "research", "browser", "delegation",
    )


# ---------------------------------------------------------------------------
# routing: Android tasks get the Android posture
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("task", [
    "build an Android notes app in Kotlin",
    "build me an Android UI with Jetpack Compose",
    "write a MainActivity.kt for the login screen",
    "run connectedAndroidTest on the emulator",
    "fix the gradle build for my android project",
    "UI test my android app with agent-device",
    "publish the apk to the Play Store",
    "set up androidx dependencies in build.gradle.kts",
])
def test_android_tasks_resolve_to_the_android_posture(task):
    profile = resolve_runtime_profile(task)
    assert profile.has(CAP_ANDROID), task
    assert profile.name == "android"


@pytest.mark.parametrize("task", [
    "build an Android notes app in Kotlin",
    "build me an Android UI with Jetpack Compose",
    "UI test my android app with agent-device",
])
def test_android_ui_task_is_not_misrouted_to_the_browser(task):
    """The bug this capability exists to fix.

    `_BROWSER_PATTERNS` matches "ui", so these used to bind browser tools and
    get no mobile toolchain — the agent was handed Playwright to test a phone.
    """
    profile = resolve_runtime_profile(task)
    assert profile.has(CAP_ANDROID)
    assert not profile.has(CAP_BROWSER), (
        f"{task!r} got browser tools; a phone is not a web page"
    )


def test_android_implies_a_full_coding_posture():
    """Building an app needs read, write, execute and verify — not just a probe."""
    caps = resolve_runtime_profile("build an Android notes app").capabilities
    assert {
        CAP_ANDROID, CAP_WORKSPACE_READ, CAP_WORKSPACE_WRITE,
        CAP_EXECUTION, CAP_VERIFICATION,
    } <= set(caps)


# ---------------------------------------------------------------------------
# no false positives
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("task", [
    "log user activity to the database",           # "activity" is English
    "fix the fragment shader in the renderer",     # "fragment" is English
    "write a docker compose file",                 # compose != Jetpack Compose
    "compose an email to the team",
    "build me a React dashboard",
    "create a website with a landing page",
    "refactor the auth module",
])
def test_non_android_tasks_do_not_get_the_android_posture(task):
    profile = resolve_runtime_profile(task)
    assert not profile.has(CAP_ANDROID), f"{task!r} was wrongly classified Android"
    assert "android_doctor" not in resolve_toolset_names(task)


@pytest.mark.parametrize("task", [
    "build me a React dashboard",
    "create a website with a landing page",
    "verify the web page renders in the browser",
])
def test_web_tasks_keep_the_browser_posture(task):
    """Regression guard: suppressing browser for Android must not leak to web."""
    profile = resolve_runtime_profile(task)
    assert profile.has(CAP_BROWSER), task
    assert not profile.has(CAP_ANDROID)


def test_mixed_android_and_web_task_keeps_both():
    """An explicit web stack outranks the Android inference.

    Losing browser access here would mean building a landing page with no way
    to verify it renders.
    """
    profile = resolve_runtime_profile(
        "build an Android app and a landing page website for it"
    )
    assert profile.has(CAP_ANDROID)
    assert profile.has(CAP_BROWSER)


# ---------------------------------------------------------------------------
# the tool is real, not a phantom
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("task", [
    "build an Android notes app in Kotlin",
    "UI test my android app with agent-device",
    "run connectedAndroidTest on the emulator",
])
def test_android_doctor_is_bound_for_android_tasks(task):
    assert "android_doctor" in resolve_toolset_names(task)


def test_android_doctor_is_bound_in_the_graph():
    """The resolver must never name a tool the graph cannot call."""
    from src.graphs.chat_graph import _TOOLS_BY_NAME

    assert "android_doctor" in _TOOLS_BY_NAME
    assert "android_doctor" in all_known_tool_names()


def test_no_resolver_name_is_a_phantom():
    """Every name the resolver can emit must be callable by the graph."""
    from src.graphs.chat_graph import _TOOLS_BY_NAME

    phantom = set(all_known_tool_names()) - set(_TOOLS_BY_NAME)
    assert not phantom, f"resolver names tools the graph cannot call: {phantom}"


# ---------------------------------------------------------------------------
# android_doctor behaviour
# ---------------------------------------------------------------------------

def _doctor(workspace="/tmp"):
    from src.tools.android_tools import android_doctor

    return android_doctor.invoke({}, config={"configurable": {"workspace": workspace}})


def test_android_doctor_returns_a_string_and_never_raises():
    result = _doctor()
    assert isinstance(result, str) and result


@pytest.mark.parametrize("label", [
    "JDK", "Android SDK", "adb", "emulator", "AVDs",
    "Gradle wrapper", "Node.js", "agent-device",
])
def test_android_doctor_reports_every_component(label):
    """A report that omits a component is how a missing JDK becomes a mystery."""
    assert label in _doctor()


def test_android_doctor_gives_a_verdict_and_next_actions():
    result = _doctor()
    assert any(marker in result for marker in ("✅ READY", "⚠️ DEGRADED", "⛔ NOT READY"))
    # Every gap must carry its fix, or the user is left holding a red X.
    if "⛔ NOT READY" in result or "⚠️ DEGRADED" in result:
        assert "Next actions, in order:" in result


def test_android_doctor_handles_a_missing_workspace_without_raising():
    """D17: a broken probe degrades to a line, never an exception into the turn."""
    result = _doctor("/nonexistent/path/that/is/not/here")
    assert isinstance(result, str) and "Gradle wrapper" in result
