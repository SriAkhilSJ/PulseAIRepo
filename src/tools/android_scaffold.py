"""Deterministic Android project scaffolding.

A model writing a Gradle project from memory produces a build that fails on a
version mismatch, a missing intent filter, or a namespace that does not match
the manifest. Those are boring, deterministic, and identical every time — so
the runtime owns them instead of the model.

Emits a minimal but REAL Kotlin + Jetpack Compose project that `./gradlew
assembleDebug` can build once a JDK and Android SDK are present.

Honest limitation, surfaced in the return value rather than hidden: the Gradle
wrapper JAR is a binary and cannot be written here. `gradle-wrapper.properties`
is emitted and the caller is told the one command that materializes the JAR.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

# Versions that are known to work together. AGP 8.5 wants Gradle 8.7+ and
# JDK 17; the Compose compiler plugin is versioned with Kotlin from 2.0 on.
COMPILE_SDK = 34
MIN_SDK_DEFAULT = 24
TARGET_SDK = 34
GRADLE_VERSION = "8.9"
AGP_VERSION = "8.5.2"
KOTLIN_VERSION = "2.0.20"
COMPOSE_BOM = "2024.09.00"

_PACKAGE_RE = re.compile(
    r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"
)
# Segments that would collide with a real platform namespace if used as the
# package ROOT. `com`/`org`/`net` are deliberately NOT here: `com.yourname.app`
# is the standard Android convention, and rejecting it would break every
# normal package id.
_RESERVED_ROOTS = {"java", "javax", "kotlin", "android", "androidx", "google"}
# Language keywords can never be a package segment at any depth.
_KEYWORD_SEGMENTS = {
    "int", "long", "short", "byte", "char", "float", "double", "boolean",
    "class", "object", "fun", "val", "var", "package", "import", "return",
    "if", "else", "for", "while", "when", "this", "super", "null", "true",
    "false", "new", "void", "public", "private", "static", "final",
}


def _settings_gradle(app_name: str) -> str:
    return f'''pluginManagement {{
    repositories {{
        google {{
            content {{
                includeGroupByRegex("com\\\\.android.*")
                includeGroupByRegex("com\\\\.google.*")
                includeGroupByRegex("androidx.*")
            }}
        }}
        mavenCentral()
        gradlePluginPortal()
    }}
}}
dependencyResolutionManagement {{
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {{
        google()
        mavenCentral()
    }}
}}

rootProject.name = "{app_name}"
include(":app")
'''


def _root_build_gradle() -> str:
    return '''// Top-level build file. Plugin versions live in gradle/libs.versions.toml
// so there is exactly one place to change them.
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
}
'''


def _gradle_properties(package_id: str) -> str:
    return f'''org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
org.gradle.parallel=true
org.gradle.caching=true
android.useAndroidX=true
android.nonTransitiveRClass=true
kotlin.code.style=official
# Lets the debug build run on an emulator without a signing config.
android.defaults.buildfeatures.buildconfig=true
'''


def _version_catalog() -> str:
    return f'''[versions]
agp = "{AGP_VERSION}"
kotlin = "{KOTLIN_VERSION}"
coreKtx = "1.13.1"
lifecycle = "2.8.6"
activityCompose = "1.9.2"
composeBom = "{COMPOSE_BOM}"
junit = "4.13.2"
androidxJunit = "1.2.1"
espresso = "3.6.1"

[libraries]
androidx-core-ktx = {{ group = "androidx.core", name = "core-ktx", version.ref = "coreKtx" }}
androidx-lifecycle-runtime-ktx = {{ group = "androidx.lifecycle", name = "lifecycle-runtime-ktx", version.ref = "lifecycle" }}
androidx-activity-compose = {{ group = "androidx.activity", name = "activity-compose", version.ref = "activityCompose" }}
androidx-compose-bom = {{ group = "androidx.compose", name = "compose-bom", version.ref = "composeBom" }}
androidx-ui = {{ group = "androidx.compose.ui", name = "ui" }}
androidx-ui-graphics = {{ group = "androidx.compose.ui", name = "ui-graphics" }}
androidx-ui-tooling = {{ group = "androidx.compose.ui", name = "ui-tooling" }}
androidx-ui-tooling-preview = {{ group = "androidx.compose.ui", name = "ui-tooling-preview" }}
androidx-ui-test-manifest = {{ group = "androidx.compose.ui", name = "ui-test-manifest" }}
androidx-ui-test-junit4 = {{ group = "androidx.compose.ui", name = "ui-test-junit4" }}
androidx-material3 = {{ group = "androidx.compose.material3", name = "material3" }}
junit = {{ group = "junit", name = "junit", version.ref = "junit" }}
androidx-junit = {{ group = "androidx.test.ext", name = "junit", version.ref = "androidxJunit" }}
androidx-espresso-core = {{ group = "androidx.test.espresso", name = "espresso-core", version.ref = "espresso" }}

[plugins]
android-application = {{ id = "com.android.application", version.ref = "agp" }}
kotlin-android = {{ id = "org.jetbrains.kotlin.android", version.ref = "kotlin" }}
kotlin-compose = {{ id = "org.jetbrains.kotlin.plugin.compose", version.ref = "kotlin" }}
'''


def _wrapper_properties() -> str:
    return f'''distributionBase=GRADLE_USER_HOME
distributionPath=wrapper/dists
distributionUrl=https\\://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip
networkTimeout=10000
validateDistributionUrl=true
zipStoreBase=GRADLE_USER_HOME
zipStorePath=wrapper/dists
'''


def _app_build_gradle(package_id: str, min_sdk: int) -> str:
    return f'''plugins {{
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}}

android {{
    namespace = "{package_id}"
    compileSdk = {COMPILE_SDK}

    defaultConfig {{
        applicationId = "{package_id}"
        minSdk = {min_sdk}
        targetSdk = {TARGET_SDK}
        versionCode = 1
        versionName = "1.0"
        // `adb shell am instrument` and agent-device target this id.
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }}

    buildTypes {{
        release {{
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }}
    }}
    compileOptions {{
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }}
    kotlinOptions {{
        jvmTarget = "17"
    }}
    buildFeatures {{
        compose = true
    }}
}}

dependencies {{
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)

    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.ui.test.junit4)
    debugImplementation(libs.androidx.ui.tooling)
    debugImplementation(libs.androidx.ui.test.manifest)
}}
'''


def _manifest(package_id: str) -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <application
        android:allowBackup="true"
        android:label="@string/app_name"
        android:supportsRtl="true"
        android:theme="@style/Theme.App">

        <!-- BOTH filters are required. Without LAUNCHER the app installs and
             then cannot be opened, and nothing fails at build time. -->
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:label="@string/app_name"
            android:theme="@style/Theme.App">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>

</manifest>
'''


def _main_activity(package_id: str, app_name: str) -> str:
    return f'''package {package_id}

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {{
    override fun onCreate(savedInstanceState: Bundle?) {{
        super.onCreate(savedInstanceState)
        setContent {{
            MaterialTheme {{
                Surface(modifier = Modifier.fillMaxSize()) {{
                    Greeting()
                }}
            }}
        }}
    }}
}}

/**
 * contentDescription is set deliberately: UI testing drives the app through
 * the accessibility tree, so an element with no label cannot be targeted.
 */
@Composable
fun Greeting(modifier: Modifier = Modifier) {{
    Column(
        modifier = modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {{
        Text(
            text = stringResource(R.string.hello),
            style = MaterialTheme.typography.headlineMedium,
            modifier = Modifier.semantics {{
                contentDescription = "greeting"
            }},
        )
    }}
}}

@Preview(showBackground = true)
@Composable
private fun GreetingPreview() {{
    MaterialTheme {{ Greeting() }}
}}
'''


def _strings(app_name: str) -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">{app_name}</string>
    <string name="hello">Hello from {app_name}</string>
</resources>
'''


def _themes() -> str:
    return '''<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="Theme.App" parent="android:Theme.Material.Light.NoActionBar" />
</resources>
'''


def _gitignore() -> str:
    return '''*.iml
.gradle/
/local.properties
/.idea/
.DS_Store
/build
/captures
.externalNativeBuild
.cxx
local.properties
app/build/
'''


def _proguard() -> str:
    return "# Add project specific ProGuard rules here.\n"


def _unit_test(package_id: str) -> str:
    return f'''package {package_id}

import org.junit.Assert.assertEquals
import org.junit.Test

class ExampleUnitTest {{
    @Test
    fun sanityCheck() {{
        assertEquals(4, 2 + 2)
    }}
}}
'''


@tool
def scaffold_android(
    app_name: str,
    package_id: str,
    config: RunnableConfig,
    min_sdk: int = MIN_SDK_DEFAULT,
) -> str:
    """Create a real Kotlin + Jetpack Compose Android project in the workspace.

    USE when an Android app must be built and no Gradle project exists yet.
    Writes settings/build Gradle files, a version catalog, the wrapper config,
    AndroidManifest with a correct MAIN+LAUNCHER intent filter, a Compose
    MainActivity, resources, and one JVM unit test — a project that
    `./gradlew assembleDebug` can build.

    `app_name` is the human label, e.g. "Notes". `package_id` must be a valid
    reverse-domain id such as "com.example.notes"; it becomes `applicationId`,
    which is what adb and agent-device target. Refuses a non-empty workspace
    rather than overwriting existing work.
    """
    workspace = Path(str(config["configurable"]["workspace"])).resolve()

    name = (app_name or "").strip()
    if not name or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{0,60}", name):
        return "⛔ scaffold_android refused: app_name must start with a letter and be at most 61 characters."

    pkg = (package_id or "").strip().lower()
    if not _PACKAGE_RE.fullmatch(pkg):
        return (
            "⛔ scaffold_android refused: package_id must be a reverse-domain id "
            f"like com.example.notes (got {package_id!r}). At least two lowercase "
            "dot-separated segments, each starting with a letter."
        )
    segments = pkg.split(".")
    if segments[0] in _RESERVED_ROOTS:
        return (
            f"⛔ scaffold_android refused: package_id {pkg!r} starts with "
            f"{segments[0]!r}, a platform namespace you do not own. Use a "
            "reverse-domain id you control, like com.yourname.notes."
        )
    keyword = next((s for s in segments if s in _KEYWORD_SEGMENTS), None)
    if keyword:
        return (
            f"⛔ scaffold_android refused: package_id {pkg!r} contains {keyword!r}, "
            "which is a language keyword and cannot be a package segment."
        )
    if not 2 <= min_sdk <= COMPILE_SDK:
        return f"⛔ scaffold_android refused: min_sdk must be between 2 and {COMPILE_SDK}."

    if (workspace / "settings.gradle.kts").is_file() or (workspace / "settings.gradle").is_file():
        return (
            "ℹ️ scaffold_android skipped: a Gradle project already exists at the "
            "workspace root. Inspect and use the existing setup."
        )
    unexpected = sorted(
        p.name for p in workspace.iterdir()
        if workspace.exists() and p.name not in {"_provided", ".git", ".crusorai"}
    ) if workspace.exists() else []
    if unexpected:
        return (
            "⛔ scaffold_android refused to write over an existing workspace. "
            f"Unexpected entries: {unexpected[:12]}. Inspect them first, or open "
            "an empty folder."
        )

    from src.tools.shadow_checkpoints import checkpoint_before_mutation
    checkpoint_before_mutation(str(workspace), "scaffold_android")

    pkg_path = pkg.replace(".", "/")
    src_main = workspace / "app" / "src" / "main"
    files: dict[Path, str] = {
        workspace / "settings.gradle.kts": _settings_gradle(name),
        workspace / "build.gradle.kts": _root_build_gradle(),
        workspace / "gradle.properties": _gradle_properties(pkg),
        workspace / "gradle" / "libs.versions.toml": _version_catalog(),
        workspace / "gradle" / "wrapper" / "gradle-wrapper.properties": _wrapper_properties(),
        workspace / "app" / "build.gradle.kts": _app_build_gradle(pkg, min_sdk),
        workspace / "app" / "proguard-rules.pro": _proguard(),
        src_main / "AndroidManifest.xml": _manifest(pkg),
        src_main / "java" / pkg_path / "MainActivity.kt": _main_activity(pkg, name),
        src_main / "res" / "values" / "strings.xml": _strings(name),
        src_main / "res" / "values" / "themes.xml": _themes(),
        workspace / "app" / "src" / "test" / "java" / pkg_path / "ExampleUnitTest.kt": _unit_test(pkg),
        workspace / ".gitignore": _gitignore(),
    }

    try:
        for path, content in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    except OSError as exc:
        return f"⛔ scaffold_android failed while writing files: {exc}"

    # The wrapper scripts are text and CAN be written; only the JAR cannot.
    # Rather than leave a half-wrapper that looks complete, report the exact
    # one command that finishes it.
    wrapper_jar = workspace / "gradle" / "wrapper" / "gradle-wrapper.jar"
    wrapper_note = ""
    if not wrapper_jar.is_file():
        wrapper_note = (
            "\n\n⚠️ gradle/wrapper/gradle-wrapper.jar is a binary and was not "
            "written. Before the first build, run ONE of:\n"
            f"  gradle wrapper --gradle-version {GRADLE_VERSION}   (if gradle is on PATH)\n"
            "  — or open the folder once in Android Studio, which materializes it.\n"
            "Until then use a system `gradle` instead of `./gradlew`."
        )

    try:
        from src.context.repo_map import invalidate_repo_map
        invalidate_repo_map(str(workspace))
    except Exception:
        pass
    try:
        from src.tools.file_tools import _record_workspace_edit
        _record_workspace_edit(config, str(workspace), [str(p) for p in files])
    except Exception:
        pass

    tree = "\n".join(
        f"  {p.relative_to(workspace)}" for p in sorted(files)
    )
    return (
        f"✅ scaffold_android created a Kotlin + Compose project at {workspace}\n\n"
        f"  applicationId  {pkg}\n"
        f"  compileSdk     {COMPILE_SDK}   minSdk {min_sdk}   targetSdk {TARGET_SDK}\n"
        f"  Gradle {GRADLE_VERSION} · AGP {AGP_VERSION} · Kotlin {KOTLIN_VERSION} · Compose BOM {COMPOSE_BOM}\n\n"
        f"Files written:\n{tree}{wrapper_note}\n\n"
        "Next: run android_doctor to confirm the JDK and SDK are present, then "
        "`gradle assembleDebug` (or `./gradlew assembleDebug` once the wrapper "
        "JAR exists). Do NOT pipe the build through tail — the runtime will "
        "correctly refuse to record a piped exit code as evidence."
    )
