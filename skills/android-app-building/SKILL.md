---
name: android-app-building
description: "Build Android apps: Kotlin/Compose, Gradle, manifest, APK."
version: 1.0.0
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [android, kotlin, compose, gradle, mobile]
    related_skills: [android-ui-testing, systematic-debugging, test-driven-development]
keywords: [android, kotlin, jetpack compose, gradle, gradlew, apk, androidx, androidmanifest]
---

**Triggers:** android, kotlin, jetpack compose, gradle, gradlew, apk, androidx, android studio, assembleDebug

# Building Android Apps

## Before writing any code

Run `android_doctor` **first**. One call tells you whether the JDK, Android SDK,
adb, emulator, Gradle wrapper and Node/agent-device are present, with the exact
fix for each gap. Guessing at a failed Gradle build costs ten turns; the doctor
costs one.

If it reports `⛔ NOT READY`, tell the user what is missing and stop. Do not
attempt a build against an absent toolchain and do not silently scaffold
around it.

## Stack

- **Kotlin + Jetpack Compose** for UI. Compose is declarative and has no XML
  layout to keep in sync — prefer it over Views for new screens.
- **Gradle wrapper** (`./gradlew` on Linux/macOS, `gradlew.bat` on Windows).
  Never a system `gradle`: the wrapper pins the version the project expects.
- **`minSdk` 24** unless the user says otherwise — covers ~98% of devices.

## Project shape

```
app/build.gradle.kts        module config, deps, minSdk/targetSdk
app/src/main/AndroidManifest.xml   permissions, launcher activity
app/src/main/java/<pkg>/    Kotlin sources
app/src/main/res/values/    strings.xml, themes.xml, colors.xml
gradle/libs.versions.toml   version catalog — single source for dep versions
gradlew / gradlew.bat       the wrapper, always run this
```

## Rules that prevent the common failures

- **Declare every permission** in `AndroidManifest.xml`. A missing
  `INTERNET` permission fails at runtime with no build error.
- **The launcher activity** needs both `MAIN` and `LAUNCHER` intent filters, or
  the app installs and then cannot be opened.
- **`applicationId`** in `build.gradle.kts` is what `adb install` and
  `agent-device open` target. Know it before claiming the app launched.
- **Never hardcode strings** in Compose — put them in `strings.xml`.
- **Do not pipe Gradle through `tail`.** `./gradlew build 2>&1 | tail -40`
  reports the pipe's exit code, not the build's, and the runtime correctly
  refuses to record it as evidence. Run it un-piped and read the failure.

## Build commands

```bash
./gradlew assembleDebug          # debug APK
./gradlew test                   # JVM unit tests (fast, no device)
./gradlew lint                   # static analysis
./gradlew connectedAndroidTest   # instrumented tests, needs a device
```

The APK lands at `app/build/outputs/apk/debug/app-debug.apk`.

## What "done" means

A build is proven only when `assembleDebug` exits 0 **and that exit code is
attributable to Gradle itself** — not to a `tail`, a pipe, or an `|| echo` — and
the APK exists on disk. "It should compile" is not evidence. If the build fails,
the Gradle error is the answer — read it, do not re-run and hope.

After a successful build, hand off to **android-ui-testing** to prove the app
actually works on a device. A compiling app is not a working app.
