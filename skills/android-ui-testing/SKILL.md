---
name: android-ui-testing
description: "Prove an Android app works on a device, with real evidence."
version: 1.0.0
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [android, testing, ui-testing, agent-device, evidence, mobile]
    related_skills: [android-app-building, test-driven-development, systematic-debugging]
keywords: [android test, ui test, agent-device, maestro, espresso, emulator, e2e, connectedAndroidTest]
---

**Triggers:** android test, ui test, e2e test, agent-device, maestro, espresso, emulator, connectedAndroidTest, test my app

# Android UI Testing

## The rule that governs this skill

**A screenshot is not evidence.** It proves a pixel buffer existed at some
moment — not that a state was reached, or that an assertion was evaluated.
Two screenshots of supposedly different screens have been byte-identical in
this repo's own evidence corpus, and nothing flagged it.

Report what was **observed**: the matched element and its bounds, the process
ID, the parsed manifest, the exit code. Those cannot be mistaken for a
different outcome the way a picture can.

## Tooling

**`agent-device`** is the device layer (MIT). Install once, user-owned:

```bash
npm install -g agent-device@latest    # requires Node 22.12+
```

Treat install/upgrade as the user's step — do not run it autonomously, and do
not substitute `npx -y agent-device@latest`.

It reads the app's **accessibility tree** as token-efficient snapshots instead
of reasoning over screenshots, acts through refs, and saves evidence.

**Call it through the `android_device` tool**, not `run_terminal`. That tool
takes `subcommand` plus `arguments` as a list, checks the subcommand against
agent-device's real command registry, runs it without a shell, reads the true
exit code, and appends every invocation to
`.crusorai/android-evidence/device-log.jsonl` with the full output saved. It
also labels each step `read-only` / `mutating` / `consequential`, so the trail
says plainly which calls changed the device.

```
android_device("open", ["com.example.notes", "--foreground"])
android_device("snapshot", ["-i"])        →  @e2 [button] "Add note"
android_device("press", ["@e2", "--settle"])   → the diff shows new refs
android_device("fill", ["@e7", "First real note", "--settle"])
```

Shell metacharacters are refused, so `;`, `&&`, pipes and redirection are not
available — split the work into separate calls.

## The inspect → act → verify loop

`doctor` first if the toolchain is in doubt, then `open`, then alternate
`snapshot` and action. `screenshot` is for the user to look at, never as the
only proof that something worked — cite the snapshot refs and the exit codes.
Finish with `close` so the next run starts clean.

**Refs are valid only in the latest output.** After a `--settle` command, use
the refs from *its* diff. Take a fresh snapshot only when the diff omits what
you need. Re-using a stale ref is the most common failure.

## Rules that keep this cheap and reliable

These come from how agent-device is designed; ignoring them costs turns.

- **Do not probe first.** No `--help`, `--version`, `devices`, `appstate`,
  `snapshot` or `screenshot` before starting. Open the app and follow the
  snapshot it returns. Every probe is a wasted turn.
- **Copy refs byte-for-byte** — `@e12`, `@e12~s4`. Keep the `@` and any `~sN`.
  Prefer current refs, then `id`/`label`/`role` selectors; coordinates are a
  last resort.
- **Use `--settle`.** The action returns a *diff* of what changed, so you do
  not need a fresh snapshot after every step.
- **Reaching an off-screen element is ONE command:** `scroll down --until
  <selector>`. A loop of bare `scroll down` calls is the slow way.
- **Follow the corrective hint in an error instead of re-planning.** The error
  output already says what to do; re-deriving a plan burns a turn and usually
  reproduces the same failure.
- **If the snapshot is sparse or reports AX unavailable, its refs are invalid.**
  Take a screenshot, read the image, use coordinates, then retry `snapshot -i`
  after navigating.

## One receipt, not a transcript

Prefer `verify_android_app` over driving each step yourself. It runs build →
install → launch → process-alive → logcat in one call, reads the **real** exit
code rather than grepping text, never pipes, and writes the evidence bundle.
Pass `flow_yaml` to have it drive the UI too, and `run_tests=true` for the
project's own Gradle tests.

Drive agent-device step by step only when you are *exploring* the app. To
*prove* something, use the receipt.

## Evidence tiers — know which one you are claiming

| Tier | Proves | Example |
|---|---|---|
| 0 | A file exists | `app-debug.apk` is on disk |
| 1 | It is genuinely what it claims | `aapt` parses it: package, versionCode, minSdk |
| 2 | It actually ran | `pidof com.example.notes` returns a live PID |
| 3 | **Each claim was evaluated** | `assertVisible "Welcome"` matched a real node |
| 4 | Anyone can re-derive it | sha256 + git commit + tool versions + the flow that ran |

**Never claim "the app works" below Tier 2. Never claim a specific UI behaviour
below Tier 3.** "It launched" is not "login works" — conflating them is how an
agent ends up confidently wrong.

## What to collect per run

- Build log (untruncated — the real Gradle error is usually mid-file, not in the tail)
- APK identity: sha256 + byte size + parsed manifest
- `adb install` result and device serial
- Process-alive proof (`pidof`) and resumed activity
- `logcat` filtered for FATAL / ANR / crash
- Per-assertion results with the **observed value**, not just pass/fail
- The flow that ran, so a human can replay it
- Screenshots — supplementary, never load-bearing

## Failures are information

Record what failed and why. A suite that has never recorded a failure is itself
a signal worth surfacing — it may mean the assertions cannot fail.

Never reclassify a failed run as passed after a fix. The fix produces a **new**
run; the old failure stays on the record.

## If the device will not cooperate

Run `android_doctor` and report the named gap. An emulator that never booted
yields **`unavailable`**, never `passed` and never `failed` — those mean
different things, and a user reading `passed` believes it.
