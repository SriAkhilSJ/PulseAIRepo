# Android Evidence Contract — proving work instead of showing pictures

**Status:** design for review — no code written yet
**Companion to:** [`ANDROID_AGENT_PLAN.md`](ANDROID_AGENT_PLAN.md)
**Owner input that drove this:** *"giving it as evidence rather than only screenshots will build user trust"*

---

## 1. You're right, and your own repo proves it

A screenshot is the **weakest** artifact an agent can produce. It proves a pixel buffer existed at some moment. It does not prove a state was reached, an assertion was evaluated, or that two captures differ.

I found this in your own evidence corpus. In `bench-results/agent-ui-execution-modes-desktop/`:

```
8393f5724fd1c4df3e03502c669c6d1a6a8d02ed408c07a16cf85f9f4208ce0e  01-agent-ready.png
8393f5724fd1c4df3e03502c669c6d1a6a8d02ed408c07a16cf85f9f4208ce0e  02-agent-narrow.png
```

Two screenshots, two different intended states ("agent ready" vs. "agent narrow"), **byte-identical** — same SHA-256, same 200,545 bytes. Four such duplicate-hash groups exist across the bench screenshots.

**To be precise about what this does and doesn't mean:** those two checks were CDP/DOM-based and may well have been genuinely evaluated — the run's `validation-summary.json` records 16 discrete DOM checks separately from the screenshot list. The DOM query was the evidence. The screenshot was decoration that happened to lie. **If anyone had trusted the picture, they would have been fooled**, and nothing in the pipeline would have flagged it.

That's the whole argument in one finding. So: screenshots stay in the artifact set as *supplementary* material, and the trust load moves to artifacts that record **what was observed**, not what it looked like.

### What you already do right — and should extend, not replace

| Asset | Where | Why it's the right foundation |
|---|---|---|
| Structured per-check results | `bench-results/*/validation-summary.json` — 12 tracked runs | Named check → PASS/FAIL map + exit codes. Machine-readable. |
| **Cryptographic anchoring** | `bench-results/*/sha256sums.txt` | Artifacts can't be silently swapped after the fact. |
| **Provenance** | `source_commit`, `required_implementation_ancestor` | Evidence is tied to the exact code that produced it. |
| Human-readable report | `bench-results/*/validation-report.md` | Same data, readable in a PR review. |
| SQLite verification ledger | `src/context/verification_evidence.py` — `verification_events` + `verification_state`, status ∈ `{passed, failed, stale, unverified, unavailable}` | Cross-session state, already pipe-masking-aware. |
| JSONL turn receipts | `src/observability.py` `record_turn_receipt()` — fail-closed by contract | Evidence can never break a turn. Correct posture. |
| **Durable by convention** | 524 artifacts tracked in git (force-added past `.gitignore:94`) | Your culture already treats evidence as committed proof. |
| Reachability receipts | `src/preview/` — `target_reachable` | Precedent: never report success on an unreachable target. |

---

## 2. Evidence tiers

Every Android claim gets classified. The tier is recorded, so a reader instantly knows how much weight to give it.

| Tier | Name | What it proves | Example | Trust |
|---|---|---|---|---|
| **0** | Existence | A file was written | `app-debug.apk` exists | ⚠️ near zero |
| **1** | Structurally valid | The artifact is genuinely what it claims | APK is a valid ZIP, contains `AndroidManifest.xml`, `aapt dump badging` yields package `com.foo`, versionCode 1, minSdk 24 | low–medium |
| **2** | Executed | It actually ran on a device | `adb install` exit 0; `pidof com.foo` returns a live PID; `dumpsys activity` shows the launcher activity resumed | medium–high |
| **3** | **Asserted** | Each claim was evaluated with an observed value | `assertVisible "Welcome back"` → matched node `text="Welcome back"` at bounds `[48,312][1032,384]` | **high** |
| **4** | Anchored & reproducible | Anyone can re-derive it | sha256 of every artifact + git commit + tool versions + device fingerprint + the flow YAML that ran | **highest** |

**Rule: the agent may not report `passed` below Tier 2 for "the app works," or below Tier 3 for any specific UI claim.** Tier 0–1 can only ever support "it built."

The critical distinction between Tier 2 and 3: *"app launched"* is not *"login works."* Conflating them is how agents end up confidently wrong.

---

## 3. The artifact set

One directory per verification run:

```
<workspace>/.crusorai/android-evidence/<run-id>/
├── evidence.json          ← THE manifest. Machine-readable. Everything below is referenced from here.
├── build.log              ← full Gradle output (not a tail)
├── apk.json               ← aapt badging: package, versionCode, minSdk, permissions, launcher activity
├── apk.sha256             ← artifact identity + byte size
├── install.json           ← adb install result, device serial, android version
├── launch.json            ← pidof + dumpsys activity — proof the process is alive
├── logcat.txt             ← filtered: FATAL / ANR / crash / AndroidRuntime
├── maestro-junit.xml      ← per-assertion results, industry-standard format
├── assertions.json        ← each assertion with its OBSERVED value (the Tier-3 core)
├── hierarchy/             ← UI tree captured at each assertion point
│   └── 03-after-login.json
├── flows/                 ← the exact YAML that ran — so the run is re-runnable
│   └── login.yaml
└── screenshots/           ← supplementary. NEVER load-bearing.
    ├── 01-launch.png
    └── screenshots.sha256
```

### `evidence.json` — the manifest

```jsonc
{
  "schema": "crusor.android.evidence/1",
  "run_id": "2026-10-10T14:32:07Z-a1b2c3",
  "tier_reached": 4,
  "overall": "PASS",

  "provenance": {
    "git_commit": "75b0add277885c2734a6ed1d6a9562b150017d4c",
    "git_dirty": false,
    "workspace": "/path/to/project",
    "started_at": "2026-10-10T14:32:07Z",
    "duration_s": 412
  },

  "toolchain": {
    "java": "17.0.11",
    "gradle": "8.9",
    "agp": "8.5.2",
    "kotlin": "2.0.20",
    "maestro": "1.42.0",
    "adb": "1.0.41"
  },

  "device": {
    "kind": "emulator",
    "serial": "emulator-5554",
    "avd": "Pixel_7_API_34",
    "android_version": "14",
    "api_level": 34,
    "fingerprint": "google/sdk_gphone64_x86_64/...",
    "online": true                    // false ⇒ overall is "unavailable", never "passed"
  },

  "checks": {
    "gradle_assembleDebug": { "status": "passed", "tier": 1, "exit": 0,
                              "attributable_exit": true, "artifact": "apk.json" },
    "apk_is_valid_zip":     { "status": "passed", "tier": 1 },
    "apk_manifest_parses":  { "status": "passed", "tier": 1,
                              "observed": { "package": "com.example.notes",
                                            "versionCode": 1, "minSdk": 24 } },
    "adb_install":          { "status": "passed", "tier": 2, "exit": 0 },
    "app_process_alive":    { "status": "passed", "tier": 2,
                              "observed": { "pid": 8421 } },
    "no_fatal_in_logcat":   { "status": "passed", "tier": 2,
                              "observed": { "fatal": 0, "anr": 0 } },
    "flow:login":           { "status": "passed", "tier": 3,
                              "assertions_passed": 7, "assertions_failed": 0,
                              "junit": "maestro-junit.xml" },
    "screenshots_distinct": { "status": "passed", "tier": 4,
                              "observed": { "count": 5, "unique_hashes": 5 } }
  },

  "integrity": {
    "duplicate_screenshot_hashes": [],   // non-empty ⇒ flagged, see §4
    "untruncated_logs": true,
    "flows_replayable": true
  }
}
```

Note `"tier"` on every check. A reader can filter to Tier 3+ and know exactly which claims are actually load-bearing.

---

## 4. The anti-fraud rules — this is what actually builds trust

Evidence is only trustworthy if it's expensive to fake. These rules come directly from failure modes already documented in your README.

| # | Rule | Failure it prevents |
|---|---|---|
| **R1** | **Record the observed value, not just the verdict.** `assertVisible "Welcome back"` must store the matched node and its bounds. | A pass with no observation is indistinguishable from a fabricated pass. |
| **R2** | **Exit codes must be attributable.** Reuse the existing `_exit_status_is_attributable()` guard. `./gradlew test 2>&1 \| tail -40` records `attributable_exit: false` and can never be `passed`. | **Exactly the attempts-11/12 bug** — a pipe's exit 0 masking a broken build. Gradle's own docs recommend piping to cut log noise, so this will come up constantly. |
| **R3** | **Duplicate artifact hashes are flagged, never silent.** Two screenshots with the same sha256 in one run ⇒ `integrity.duplicate_screenshot_hashes` is non-empty and the run is annotated. | The bug I found in your own `agent-ui-execution-modes-desktop` corpus. |
| **R4** | **`device.online: false` ⇒ `overall: "unavailable"`.** Never `passed`, never `failed`. Mirrors your `target_reachable` rule. | Claiming success against a device that was never there. |
| **R5** | **Failures are immutable.** A failed run stays failed in the ledger forever. Later fixes add a new run; they never reclassify an old one. | Your README already commits to this for attempts 11/12. Make it structural. |
| **R6** | **Untruncated logs.** Full `build.log`, not a 4000-char tail. The interesting Gradle error is usually mid-file. | A tail that shows only `BUILD FAILED` with no cause is not evidence. |
| **R7** | **Flows are archived and replayable.** The exact YAML that ran is stored, so any human can re-run it and get the same result. | Evidence you can't reproduce is just a claim with extra steps. |
| **R8** | **Negative evidence is first-class.** `assertions_failed` and `logcat` fatal counts are always present, including when zero. A suite that has *never* recorded a failure is itself a signal worth surfacing. | An agent that only ever reports green teaches the user nothing about whether the tests can fail at all. |
| **R9** | **Screenshots can never be the sole evidence for a Tier 3 claim.** | The core point of this document. |

---

## 5. What the user actually sees

Trust is built at the moment of reading, so the surface matters as much as the artifact.

**In the agent pane — a compact evidence receipt, not a picture dump:**

```
✅ Android verified — Tier 4 · 412s · emulator-5554 (Pixel 7, API 34)

   build      assembleDebug          exit 0   (attributable)
   artifact   app-debug.apk          14.2 MB  sha256:9f2c…d41e
              package com.example.notes · versionCode 1 · minSdk 24
   install    adb install            exit 0
   launched   pid 8421               alive, activity resumed
   logcat     0 fatal · 0 ANR
   flow       login.yaml             7/7 assertions passed

   Evidence: .crusorai/android-evidence/2026-10-10T14:32:07Z-a1b2c3/
   Replay:   maestro test flows/login.yaml
   [View report]  [Open evidence]  [Re-run]
```

Every line is a claim with its observation attached. `exit 0 (attributable)` is doing real work there — it tells the reader the exit code was *verified* to belong to Gradle, not to a pipe.

**In the PR —** the same data as `validation-report.md` + `evidence.json` + `sha256sums.txt`, committed, following your existing 524-artifact convention.

**Watch-it-work stays** (Maestro Viewer, live emulator) — that's the *engagement* surface. But when the user asks "did it actually work?", the answer comes from the receipt above, not the video.

---

## 6. How it plugs into what exists

```
verify_android_app()  ── one tool call, one receipt ──────────────────┐
                                                                     │
   ├─ build      → run_terminal (NOT MCP: 60s MCP timeout vs         │
   │               multi-minute Gradle)  → build.log, exit code      │
   ├─ artifact   → aapt dump badging     → apk.json, apk.sha256      │
   ├─ install    → adb install           → install.json              │
   ├─ launch     → adb shell pidof       → launch.json               │
   ├─ logcat     → adb logcat -d         → logcat.txt                │
   ├─ drive      → MCP "maestro mcp"     → assertions.json,          │
   │               inspect_screen / run     hierarchy/, flows/       │
   ├─ report     → maestro test --format junit → maestro-junit.xml   │
   └─ manifest   → assemble all of the above → evidence.json         │
                                                                     │
   ┌───────────────────────────────────────────────────────────────┐ │
   │ src/context/verification_evidence.py  (EXTEND, don't replace) │◀┘
   │   verification_state.status ← overall                         │
   │   verification_events       ← one row per check + exit code   │
   └───────────────────────────────────────────────────────────────┘
   ┌───────────────────────────────────────────────────────────────┐
   │ src/observability.py  record_turn_receipt()                   │
   │   fail-closed: evidence writing can never break a turn        │
   └───────────────────────────────────────────────────────────────┘
```

**Deliberate non-goals:**
- No new evidence database. Extend the existing SQLite ledger + the JSON-file convention you already have.
- No cloud upload. Consistent with your `observability.py` "no upload" stance.
- Evidence writing is **best-effort and fail-closed**. A disk-full error must never fail a turn — it should degrade to `unavailable` with a reason, exactly as `mark_unavailable()` already does.

---

## 7. Effect on the phase plan

This **changes Phase 0 and Phase 3** of `ANDROID_AGENT_PLAN.md`:

- **Phase 0 grows.** Fixing `_VERIFY_RE`/`_TARGET_RE` was necessary but not sufficient. Phase 0 now also defines `evidence.json` schema v1 and the Tier model, with unit tests for R1–R9 as pure functions — **no Android SDK needed**, so it's fully verifiable in this sandbox.
- **Phase 3 changes shape.** `verify_android_app` is no longer "run the steps and screenshot." It's "run the steps and *emit evidence*," and it refuses to return `passed` below its required tier.

New tests, all hermetic:

| Test | Proves |
|---|---|
| `test_duplicate_hash_flagged` | R3 — two identical hashes get flagged |
| `test_piped_gradle_not_attributable` | R2 — `gradlew … \| tail` can't pass |
| `test_device_offline_is_unavailable` | R4 — never `passed` |
| `test_tier_gate_blocks_low_tier_pass` | Tier rules — "app works" below Tier 2 is refused |
| `test_failed_run_immutable` | R5 — a later pass doesn't rewrite history |
| `test_observed_value_required_for_tier3` | R1 — verdict without observation is rejected |
| `test_evidence_write_failure_is_failclosed` | Best-effort contract |

---

## 8. Open questions

1. **Where does evidence live by default?** `.crusorai/android-evidence/` is gitignored (`.gitignore:37`), but your 524 tracked artifacts show the culture wants evidence committed. Proposal: write local by default, with an explicit `Export evidence to repo` action that mirrors the `bench-results/` layout. Agree?
2. **Retention.** Per-run directories with screenshots and full logs add up fast (your existing screenshots are ~200 KB each). Cap at N runs? Drop screenshots past the newest M?
3. **Does `maestro test --format junit` exist in the version you'll install?** I sourced this from Maestro's docs, not from a local binary — there's no Maestro in this sandbox to check. First implementation task is to confirm the flag and its exact XML shape.
4. **Should the Tier model generalize past Android?** It would apply cleanly to your existing web `verify_ui_workspace` too — which currently leans on screenshots more than it should, for the same reason. Worth a follow-up, out of scope here.
