# CrusorAI Android smoke test

A tiny, real Android Gradle app for checking the Windows build → install → launch → evidence path. It is deliberately separate from `testCRUSOR` and has no third-party app dependencies.

## Open it in CrusorAI

Open this folder as the workspace:

```text
PulseAIRepo/examples/android-smoke-test
```

Then ask CrusorAI to detect the Android target and build/verify it on the already-created `crusor` AVD. The project includes the Gradle wrapper, so a globally installed Gradle is not required. The first build downloads Gradle and the Android Gradle Plugin; allow for network use and a few hundred MB of additional cache.

Expected app id: `com.crusorai.smoketest`.

The app displays a title and a button. Tapping the button changes the status text, giving the verifier visible UI to capture. This is a diagnostic sample, not the user's product app.
