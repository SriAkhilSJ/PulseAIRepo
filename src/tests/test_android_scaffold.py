"""scaffold_android emits a project that is internally consistent.

A generated Gradle project fails in ways that are invisible until the build
runs: a version-catalog alias with no entry behind it, a `namespace` that
disagrees with the manifest, a launcher activity missing its LAUNCHER intent
filter (installs fine, then cannot be opened, with no build error). None of
those need a JDK or an Android SDK to catch — they are pure text invariants,
so they are pinned here and run in every CI.

The alias check is the important one. It is the single most common way a
model-written Gradle project fails, and it is completely mechanical.
"""
from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET

import pytest

from src.tools.android_scaffold import scaffold_android

PKG = "com.akhil.notes"
NAME = "Notes"


@pytest.fixture
def project(tmp_path):
    """Scaffold once into a clean dir and hand back the workspace path."""
    result = scaffold_android.invoke(
        {"app_name": NAME, "package_id": PKG},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert result.startswith("✅"), result
    return tmp_path


def _read(project, rel):
    return (project / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# the tree exists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "settings.gradle.kts",
    "build.gradle.kts",
    "gradle.properties",
    "gradle/libs.versions.toml",
    "gradle/wrapper/gradle-wrapper.properties",
    "app/build.gradle.kts",
    "app/proguard-rules.pro",
    "app/src/main/AndroidManifest.xml",
    "app/src/main/java/com/akhil/notes/MainActivity.kt",
    "app/src/main/res/values/strings.xml",
    "app/src/main/res/values/themes.xml",
    "app/src/test/java/com/akhil/notes/ExampleUnitTest.kt",
    ".gitignore",
])
def test_every_expected_file_is_written(project, rel):
    assert (project / rel).is_file(), f"missing {rel}"


# ---------------------------------------------------------------------------
# text invariants that a build would otherwise catch too late
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "app/src/main/AndroidManifest.xml",
    "app/src/main/res/values/strings.xml",
    "app/src/main/res/values/themes.xml",
])
def test_xml_is_well_formed(project, rel):
    ET.parse(project / rel)


def test_version_catalog_is_valid_toml(project):
    catalog = tomllib.loads(_read(project, "gradle/libs.versions.toml"))
    assert catalog["libraries"] and catalog["plugins"] and catalog["versions"]


def test_kotlin_package_matches_its_directory(project):
    source = _read(project, "app/src/main/java/com/akhil/notes/MainActivity.kt")
    declared = re.search(r"^package (\S+)", source, re.M).group(1)
    assert declared == PKG


def test_namespace_and_application_id_match_the_package(project):
    """A namespace that disagrees with the sources is a build failure, and
    `applicationId` is what adb and agent-device target — a mismatch there
    means the app installs and then cannot be found."""
    gradle = _read(project, "app/build.gradle.kts")
    assert re.search(rf'namespace = "{re.escape(PKG)}"', gradle)
    assert re.search(rf'applicationId = "{re.escape(PKG)}"', gradle)


def test_launcher_activity_has_both_intent_filters(project):
    """MAIN without LAUNCHER installs cleanly and then cannot be opened, with
    no build error anywhere. This is the quietest way to ship a dead app."""
    manifest = _read(project, "app/src/main/AndroidManifest.xml")
    assert "android.intent.action.MAIN" in manifest
    assert "android.intent.category.LAUNCHER" in manifest


def test_every_catalog_alias_referenced_actually_exists(project):
    """The most common failure in a generated Gradle project.

    `libs.androidx.core.ktx` must map to a catalog entry named
    `androidx-core-ktx`. A dangling alias fails at configuration time with a
    message that does not name the alias, so it is expensive to diagnose and
    free to prevent.
    """
    catalog = tomllib.loads(_read(project, "gradle/libs.versions.toml"))
    libraries = set(catalog["libraries"])
    plugins = set(catalog["plugins"])

    app_gradle = _read(project, "app/build.gradle.kts")
    root_gradle = _read(project, "build.gradle.kts")

    used_libraries = [
        ref for ref in re.findall(r"\blibs\.([\w.]+)\b", app_gradle)
        if not ref.startswith("plugins.")
    ]
    used_plugins = re.findall(
        r"alias\(libs\.plugins\.([\w.]+)\)", app_gradle + root_gradle
    )
    assert used_libraries, "no library aliases found — the check is vacuous"
    assert used_plugins, "no plugin aliases found — the check is vacuous"

    missing = [
        f"libs.{ref} -> '{ref.replace('.', '-')}'"
        for ref in used_libraries
        if ref.replace(".", "-") not in libraries
    ] + [
        f"libs.plugins.{ref} -> '{ref.replace('.', '-')}'"
        for ref in used_plugins
        if ref.replace(".", "-") not in plugins
    ]
    assert not missing, f"catalog aliases with no entry behind them: {missing}"


def test_every_catalog_version_reference_resolves(project):
    """Walk the parsed dict. `version.ref = "x"` becomes {"version": {"ref": "x"}},
    so a text regex over str(entry) matches nothing and the check silently
    passes while proving nothing."""
    catalog = tomllib.loads(_read(project, "gradle/libs.versions.toml"))
    versions = set(catalog["versions"])

    def refs(node):
        if isinstance(node, dict):
            version = node.get("version")
            if isinstance(version, dict) and isinstance(version.get("ref"), str):
                yield version["ref"]
            for value in node.values():
                yield from refs(value)

    declared = {
        ref
        for group in ("libraries", "plugins")
        for entry in catalog[group].values()
        for ref in refs(entry)
    }
    assert declared, "no version.ref found — the check is vacuous"
    assert declared <= versions, f"unresolved version refs: {declared - versions}"


def test_compose_and_testing_dependencies_are_present(project):
    gradle = _read(project, "app/build.gradle.kts")
    assert "compose = true" in gradle
    # Without these the agent cannot write an instrumented UI test later.
    assert "androidTestImplementation" in gradle
    assert "testInstrumentationRunner" in gradle


def test_ui_elements_are_labelled_for_accessibility(project):
    """agent-device drives the app through the accessibility tree, so an
    element with no label cannot be targeted. Scaffolding unlabelled UI would
    make the app untestable by the very tool the next skill reaches for."""
    source = _read(project, "app/src/main/java/com/akhil/notes/MainActivity.kt")
    assert "contentDescription" in source


# ---------------------------------------------------------------------------
# refusal behaviour
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("package_id", [
    "Notes",                      # no dot
    "com",                        # single segment
    "com.akhil.notes.",           # trailing dot
    "com.akhil..notes",           # empty segment
    ".com.akhil",                 # leading dot
    "com.9akhil.notes",           # digit-leading segment
])
def test_invalid_package_id_is_refused(tmp_path, package_id):
    result = scaffold_android.invoke(
        {"app_name": NAME, "package_id": package_id},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert result.startswith("⛔"), result
    assert not (tmp_path / "settings.gradle.kts").exists(), "refused but still wrote"


@pytest.mark.parametrize("package_id,why", [
    ("android.foo.bar", "platform namespace"),
    ("androidx.foo.bar", "platform namespace"),
    ("java.util.thing", "platform namespace"),
    ("com.akhil.class.notes", "language keyword"),
])
def test_reserved_package_ids_are_refused(tmp_path, package_id, why):
    result = scaffold_android.invoke(
        {"app_name": NAME, "package_id": package_id},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert result.startswith("⛔"), f"{package_id} should be refused ({why})"


@pytest.mark.parametrize("package_id", [
    "com.akhil.notes",
    "com.example.notes",
    "in.crusor.demo",
    "org.akhil.notes",       # org is a normal root, not reserved
    "net.akhil.notes",
    "com.akhil.my_app.v2",
])
def test_normal_convention_package_ids_are_accepted(tmp_path, package_id):
    """`com.*` and `org.*` are the standard Android convention and must work.

    An earlier cut of this validator rejected them, which would have broken
    essentially every real package id — and its own error message suggested
    `com.yourname.notes`, an id it would then also refuse.
    """
    result = scaffold_android.invoke(
        {"app_name": NAME, "package_id": package_id},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert result.startswith("✅"), f"{package_id} wrongly refused: {result}"


def test_refuses_to_overwrite_an_existing_workspace(tmp_path):
    (tmp_path / "important.txt").write_text("do not lose me", encoding="utf-8")
    result = scaffold_android.invoke(
        {"app_name": NAME, "package_id": PKG},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert result.startswith("⛔")
    assert (tmp_path / "important.txt").read_text(encoding="utf-8") == "do not lose me"
    assert not (tmp_path / "settings.gradle.kts").exists()


def test_skips_when_a_gradle_project_already_exists(tmp_path):
    (tmp_path / "settings.gradle.kts").write_text("// existing", encoding="utf-8")
    result = scaffold_android.invoke(
        {"app_name": NAME, "package_id": PKG},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert result.startswith("ℹ️")
    assert (tmp_path / "settings.gradle.kts").read_text(encoding="utf-8") == "// existing"


def test_rejects_an_out_of_range_min_sdk(tmp_path):
    result = scaffold_android.invoke(
        {"app_name": NAME, "package_id": PKG, "min_sdk": 99},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert result.startswith("⛔")


# ---------------------------------------------------------------------------
# honesty about what it cannot do
# ---------------------------------------------------------------------------

def test_reports_the_missing_wrapper_jar_instead_of_hiding_it(project, tmp_path):
    """The wrapper JAR is a binary and cannot be written here. Claiming the
    project is build-ready would send the agent straight into a confusing
    `./gradlew: not found`, so the gap is named with the command that closes it.
    """
    result = scaffold_android.invoke(
        {"app_name": "Second", "package_id": "com.akhil.second"},
        config={"configurable": {"workspace": str(tmp_path / "x")}},
    )
    assert "gradle-wrapper.jar" in result
    assert "gradle wrapper" in result, "must name the command that materializes it"
    assert not (tmp_path / "x" / "gradle" / "wrapper" / "gradle-wrapper.jar").exists()


def test_warns_against_piping_the_build(tmp_path):
    result = scaffold_android.invoke(
        {"app_name": NAME, "package_id": PKG},
        config={"configurable": {"workspace": str(tmp_path)}},
    )
    assert "pipe" in result.lower(), (
        "must warn that a piped Gradle exit code is not attributable"
    )


# ---------------------------------------------------------------------------
# wiring
# ---------------------------------------------------------------------------

def test_scaffold_android_is_bound_and_gated():
    from src.graphs.chat_graph import _TOOLS_BY_NAME
    from src.tools.toolsets import all_known_tool_names, resolve_toolset_names

    assert "scaffold_android" in _TOOLS_BY_NAME
    assert "scaffold_android" in all_known_tool_names()
    assert "scaffold_android" in resolve_toolset_names("build an Android app in Kotlin")
    assert "scaffold_android" not in resolve_toolset_names("refactor the auth module")
