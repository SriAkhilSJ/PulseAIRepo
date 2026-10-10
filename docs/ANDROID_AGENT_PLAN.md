# Making Crusor build Android apps and test their UI

**Status:** Phase 0A **and** Phase 1 **landed and tested** — see §0 below
**Branch:** `arena/f83d13ef-pulseairepo`
**Decisions locked from owner:** whole Android app **+** tester · free and open source only · good performance · **the user must be able to watch the agent work** · **evidence, not screenshots**

---

## 0. Landed 2026-10-10 — and a change of plan

### Adopted: `callstack/agent-device` as the device + evidence layer

Rather than build emulator lifecycle, accessibility capture, interaction, and evidence collection from scratch on top of Maestro, the device layer is now **[callstack/agent-device](https://github.com/callstack/agent-device)**:

| | |
|---|---|
| Stars / license | 4,954 · **MIT** |
| Maintained | pushed **2026-10-10**, not archived |
| Shape | CLI + built-in MCP server (`agent-device mcp`) + typed Node.js API |
| Requires | Node.js 22.12+ |
| Used by | Expensify, Shopify |

It already solves what §3–5 of this doc proposed to hand-build, and it already embodies the owner's evidence-first correction. From its README: *"Agents read token-efficient accessibility snapshots **instead of reasoning over screenshots alone**, act through refs and selectors, and **save evidence for review**."* Its `docs/evidence/` records SHA-256 anchors, git revisions, hard-gate tables with observed values — and explicitly logs what could *not* be proven (*"The implementing agent had no device access and proved nothing here"*; *"Negative result at `af55e2746b`"*).

Command surface (from `packages/command-registry/src/registry.ts`): `open close snapshot press fill type scroll swipe gesture wait find diff screenshot record logs trace perf debug install install-from-source reinstall apps appstate boot device devices doctor capabilities replay test batch artifacts session mcp`.

**Revised division of labour:**

| Layer | Owner |
|---|---|
| Device lifecycle, emulator, accessibility snapshots, interactions, screenshots/video/logs, replay scripts, device claims, `doctor` | **agent-device** (adopted) |
| Kotlin/Compose codegen, Gradle build, `AndroidManifest`/permissions, project scaffold | **Crusor** (must build — agent-device does not generate apps) |
| Posture wiring, tool gating, skills | **Crusor** |
| **Evidence gate — making the runtime believe Android** | **Crusor** (landed, §0.1) |

This removes `avd_start`/`android_doctor`/evidence-schema work from Crusor's scope. Crusor calls agent-device over its existing MCP client or terminal tool.

### 0.1 Phase 0 Part A — DONE: the evidence gate now believes Android

Two independent copies of "is this command verification?" existed, and **both** were blind to the mobile toolchain:

| Surface | File | Gates |
|---|---|---|
| Passive ledger | `src/context/verification_evidence.py` `_VERIFY_RE` | IDE-visible correctness state |
| **Stop gate** | `src/graphs/gates.py` `_verification_receipt_status` | **whether "✅ Finished" is allowed at all** |

The stop gate's gap was *not* symmetric with the ledger's: it substring-matched `" test"`, which needs a leading space, so **`connectedAndroidTest`** (the Android instrumented UI test task) and **`assembleDebug`** both failed to match. An agent could build and device-test a real app and be told it had proved nothing — or learn to assert success anyway, since nothing contradicted it.

Changes (`git diff --stat`: 2 files, +78/−7):
- `_VERIFY_RE` recognizes `gradlew`/`gradlew.bat`/`gradle`, `adb install|shell|push|pull|logcat`, `maestro test`, `agent-device test|replay|artifacts`. Restricted sub-command lists keep `adb devices` / `agent-device snapshot` from recording **phantom evidence** — a probe is not proof.
- `_TARGET_RE` accepts `.kt .kts .java .xml` → file-scoped Android evidence is `targeted`, not falsely `full`.
- Kind derivation: `assemble*` → `build` (not `test`), `adb install` → `build`.
- Stop gate: match on tool name, not task name.
- **Bonus pre-existing bug fixed:** `cat build.gradle.kts` and `cat build.sh` satisfied the stop gate's static domain by matching `" build"` — the agent could *read a file* and be told it had verified the build. Added `_is_readonly_inspection()`. Confirmed pre-existing on `75b0add2` before my change.

**Verification — 67 new tests, zero regressions:**

```
src/tests/test_android_verification_evidence.py   67 passed
full dependent suite (18 files)                  338 passed, 3 failed
```

All 3 failures reproduce identically on stashed `75b0add2` (verified by `git stash` + re-run): `test_grace_summary_hermes_law.py::test_grace_print_names_both_budget_legs_and_the_tripped_one`, and `test_lab_fixes.py::test_syntax_receipt_tsx_{missing_arrow,jsx_concat_attribute}`. Pre-existing, unrelated, untouched.

Pipe-masking guard (`_exit_status_is_attributable`) verified intact on the Android toolchain — `./gradlew test 2>&1 | tail -40` still records **no** evidence, so widening the matcher did not re-open the attempts-11/12 failure mode.

**Still open in Phase 0:** Part B — the `evidence.json` schema v1, Tier 0–4 model, and rules R1–R9 as pure functions (see `ANDROID_EVIDENCE_CONTRACT.md`). Much of R1/R3/R7 is now delegated to agent-device; what remains is Crusor's side: tier gating and the Gradle/`aapt`/`logcat` artifacts agent-device does not produce.

### 0.2 Phase 1 — DONE: `CAP_ANDROID` + a real tool + skills

"Adopted agent-device" was true only in this document. It is now true in code.

**Posture (`src/agents/runtime_profile.py`)**
- `CAP_ANDROID` **appended** to `CAPABILITY_ORDER` (prompt-cache contract — inserting mid-tuple churns unrelated keys). Pinned by `test_cap_android_is_registered_and_last`.
- **Misrouting bug fixed:** `_BROWSER_PATTERNS` contains `\bui\b`, so *"build an Android UI"* resolved to the **browser** posture and bound CDP/Playwright tools that cannot drive a phone. Android now owns the `ui` signal.
- `_WEB_STACK_PATTERNS` lets an explicit web stack win, so *"Android app + landing page"* keeps browser access instead of silently losing the ability to verify the site.
- `_ANDROID_PATTERNS` is deliberately qualified — bare `activity`, `fragment`, `compose` are ordinary English and `docker compose` is not Jetpack Compose. Pinned by `test_non_android_tasks_do_not_get_the_android_posture`.

Routing, executed:

| task | profile | android | browser |
|---|---|---|---|
| build an Android notes app in Kotlin | `android` | ✅ | — |
| build me an Android UI with Jetpack Compose | `android` | ✅ | — *(was browser)* |
| run connectedAndroidTest on the emulator | `android` | ✅ | — |
| build me a React dashboard | `ui_engineering` | — | ✅ |
| log user activity to the database | `general` | — | — |
| write a docker compose file | `artifact` | — | — |
| build an Android app and a landing page | `android` | ✅ | ✅ |

**Tool (`src/tools/android_tools.py`)** — `android_doctor`: read-only probe of JDK / SDK / adb / emulator / AVDs / Gradle wrapper / Node / agent-device. Names versions and the exact fix per gap, then a verdict naming the **blocking** component. D17: returns a string, never raises. Boots, installs and builds nothing. Bound in `chat_graph`, gated on `CAP_ANDROID`; `all_known_tool_names() - _TOOLS_BY_NAME == ∅` verified.

**Skills** — `android-app-building` and `android-ui-testing` (`skills/`), registered in `skills/SKILL.md` and pinned in `test_expected_skill_names_present`.

**Connectors panel** — an `android` row, probed with `shutil.which` only (runs on every tab open; no process spawn).

**Verification — full suite, both trees:**

```
baseline 75b0add2   29 failed, 2223 passed
this branch         29 failed, 2376 passed   (+153 tests)
diff of FAILED sets: IDENTICAL — zero regressions
```

Baseline taken from a separate `git worktree` at `75b0add2`, not a stash, so the comparison could not be contaminated by my own edits.

> **Field note.** Two test defects surfaced while landing this, both worth keeping:
> `test_skills_hub` asserted a connector by positional index `[-2]`, which broke
> when the `android` row landed — rewritten to the `by_id` pattern the rest of
> that test already used; and `test_lsp_performance` fails under full-suite load
> but passes 3/3 in isolation (timing-sensitive, pre-existing flake).

---

### 0.3 Phase 2 + Phase 3 — DONE: `scaffold_android` and `verify_android_app`

Two tools landed. The agent can now generate a project and prove a build,
which it previously could not do at all.

**`scaffold_android`** (`src/tools/android_scaffold.py`, commit `9626d1d6`)
generates a Compose project from templates. Pins AGP 8.5.2 / Kotlin 2.0.20 /
Gradle 8.9 / Compose BOM 2024.09.00 / compileSdk 34 / minSdk 24. Validated by
generating `com.akhil.notes` and machine-checking the result: all XML and TOML
parse, the Kotlin package matches its directory, `namespace` and
`applicationId` both equal the package id, MAIN+LAUNCHER are present, and
**every one of the 14 library and 3 plugin catalog aliases the generated
Gradle files reference resolves** — so no
`libs.androidx.foo` points at an alias that does not exist.

Reserved-segment handling is split root-vs-any-depth: `java`, `android`,
`androidx`, `kotlin`, `google` are refused only at the **root**; language
keywords are refused at any depth. `com.*`, `org.*` and `net.*` are accepted —
rejecting `com` would have broken the standard Android convention.

**`verify_android_app`** (`src/tools/android_verify.py`, commit `0f020de6`) is
the evidence receipt. preflight → `gradle assembleDebug` → APK identity →
`adb install` → launch → `pidof` → logcat fatal scan → optional `gradle test`
→ optional `agent-device replay <flow>`. Writes
`.crusorai/android-evidence/<run-id>/` with `evidence.json`, the build/install/
launch/test logs, `logcat.txt`, `flow.yaml` and `apk.sha256`.

Two properties are the point, and both are enforced by tests:

1. **It reads `subprocess.run().returncode` and never pipes.** The rest of the
   codebase decides success by grepping `"exit code: 0"` out of rendered text;
   a piped Gradle build reports the pipe's status, so that check can be
   satisfied by a build that failed. This tool cannot be fooled that way, and
   distinguishes 127 (binary missing) from 124 (timeout) from a real failure.
2. **Four verdicts, not two.** `⛔ UNAVAILABLE` (toolchain absent), `⚠️ PARTIAL`
   (built but no device / no UI proof), `❌ FAILED`, `✅ PASSED`. Collapsing the
   first two into `failed` would tell the user their app is broken when the
   real problem is a missing JDK.

What counts as proof, encoded as assertions: a green exit with **no APK** is a
FAILURE; an APK whose real package differs from the requested one is a FAILURE;
a launch that exits 0 but whose process is not alive is caught by `pidof`; a UI
flow that could not run prevents the run from claiming Tier 3.

**What is still not done.** The build has never been executed against a real
JDK/SDK — the version pins are unproven, only internally consistent. And the
agent still has **no path to `agent-device`** for the interactive
open/snapshot/click loop: `verify_android_app` shells out to `agent-device
replay`, but there is no `mcp.json` writer and no CLI-passthrough tool. That is
the next gap.

## 1. The short version, in plain English

Three things need to happen, and they are independent enough to ship one at a time.

**First — the agent needs a phone to work on.**
Today Crusor can build a website and open it in a window so you can see it. Android has no window. So we give the agent a *virtual phone* — an Android emulator. It's a free program that pretends to be a phone on your screen. You watch it like a TV. When the agent taps a button, you literally see the button get tapped. That is the "user sees the agent doing tasks" requirement, and it comes for free.

**Second — the agent needs hands and eyes.**
A tool called **Maestro** gives it those. Maestro is free and open source (Apache 2.0 license — the permissive one, no strings). It already speaks the exact protocol Crusor already understands (MCP — you have a working client at `src/tools/mcp_client.py`). So the agent can say "tap the login button", "type this password", "check that the welcome text appeared", and take screenshots to prove it.

Better: Maestro ships a **Viewer** that shows a live picture of the phone *and* prints every command the agent runs as it runs. That is the demo-quality part. Your agent looks like it is actually driving a phone.

**Third — and this is the one that would have bitten you — Crusor currently does not believe Android.**
Your runtime has a gate that decides whether the agent's claim "I tested it" is backed by real evidence. I ran it. It does not recognize Gradle, which is the tool that builds every Android app:

```
./gradlew assembleDebug        -> False
./gradlew connectedAndroidTest -> False
./gradlew lint                 -> False
```

So the agent could build a perfect app, and Crusor would record it as *unverified*. That is the same failure class your README documents at attempts 11/12, where a shell pipe made a broken build look like a passing one. This gate must be fixed **before** Android capability, not after — otherwise the agent will start confidently lying about Android work, and you will not notice until a user does.

---

## 2. What I verified in your repo (evidence, not assumptions)

### Already built — we reuse this, we don't rebuild it

| Asset | Where | What it saves us |
|---|---|---|
| Kotlin + Java language servers | `src/lsp/servers.py:743-744` (`kotlin-language-server`, `jdtls`) | Code intelligence on Android source already works |
| Gradle project-root detection | `src/lsp/servers.py:704-709` (`settings.gradle`, `build.gradle.kts`) | Already knows where an Android project starts |
| Kotlin/Gradle file icons | `branding/generate_file_icons.py:24,33` | Already shipped |
| Gradle failure recognition | `src/tools/terminal_hints.py:130` (`BUILD FAILED`) | Partial — failure text is already caught |
| **Working MCP client** | `src/tools/mcp_client.py` — `MCPStdioClient`, config in `.crusorai/mcp.json` | **The big one.** Maestro is an MCP server. No new protocol code. |
| MCP safety contract | same file, docstring — "every MCP tool is treated as GUARDED" | Approval gates apply to Maestro calls automatically |
| Zero-code skill format | `skills/<name>/SKILL.md`, 20 bundled | New capability guidance = markdown, not Python |
| One-receipt verify pipeline | `src/tools/ui_verification.py` (`verify_ui_workspace`) | The exact pattern to clone for Android |
| Scaffold tool pattern | `src/tools/scaffold_tools.py` (`scaffold_nextjs`) | The exact pattern to clone for `scaffold_android` |
| Live preview window | `src/preview/` (proxy on `127.0.0.1:8931`) | Precedent + surface for showing the phone |
| Posture-gated tool waist | `src/agents/runtime_profile.py` → `src/tools/toolsets.py` | Clean seam: Android tools only bind when the task needs them |

### Verified missing — the actual work

1. **The evidence gate is blind to Android.** `src/context/verification_evidence.py:17` `_VERIFY_RE` matches `pytest`, `npm`, `tsc`, `mypy`, `pyright`, `ruff`, `cargo`, `go test`, `make`. **No `gradle`, no `gradlew`, no `adb`, no `maestro`.** Confirmed by executing the regex, not by reading it.
2. **File-scoped evidence can't see Kotlin/Java.** Same file, `_TARGET_RE` accepts `.py .ts .tsx .js .jsx .rs .go`. I ran it: `MainActivity.java` → `None`, `src/a.ts` → `src/a.ts`.
3. **No Android capability in the posture resolver.** `CAPABILITY_ORDER` has 7 entries: workspace_read, workspace_write, execution, verification, research, browser, delegation. No `android`. `_BROWSER_PATTERNS` matches "ui" — so an Android UI task today resolves to the *browser* posture and gets Playwright/CDP tools. Wrong tools for the job.
4. **No Android toolchain in this sandbox.** `command -v` for `java`, `gradle`, `adb`, `sdkmanager`, `emulator` → all MISSING. So no real APK build can be verified *here*; wiring can.

### Constraint I found that shapes the design

`src/tools/mcp_client.py:38` — `_CALL_TIMEOUT_S = 60.0`, hardcoded.

A first Gradle build of an Android project routinely takes **3–10 minutes** (it downloads the whole dependency tree). A cold emulator boot takes 30–90s. So:

- **Gradle builds must NOT go through MCP.** They go through `run_terminal` / `start_terminal`, whose foreground ceiling is 600s by default and configurable to 3600s (`_foreground_max_timeout()`, `src/tools/terminal_tools.py:587`).
- **Device control goes through MCP** — taps, screenshots, hierarchy inspection are all sub-second.

Getting this split wrong is the most likely way this project fails in a confusing way: everything works until the first real build, then it times out at 60 seconds.

---

## 3. Recommended stack

| Layer | Choice | License / cost | Why this one |
|---|---|---|---|
| App | **Kotlin + Jetpack Compose** | Free, Apache 2.0 | Google's current Android direction. Kotlin LSP already wired. "Whole Android app" means real native. |
| Build | **Gradle wrapper** (`./gradlew`) | Free | Ships inside every Android project. No separate install, version pinned per project. |
| Device | **Android emulator (AVD)** | Free (AOSP) | No hardware needed. **Visible window = user watches the agent.** Works on Windows. |
| UI test driver | **Maestro** | **Apache 2.0, free** | Declarative YAML, not brittle code. **Ships an MCP server inside the CLI** — plugs into your existing client. **Maestro Viewer shows the live device + every command.** |
| Fast feedback | **Robolectric** | Free, MIT | Runs Compose UI tests on the JVM. No emulator. Keeps the inner loop fast and lets us test *this repo's wiring* without a phone. |

### Why not the alternatives

- **Espresso/UiAutomator** — free and it is what Android teams expect, but the agent must author brittle Kotlin test code with correct selectors. Maestro drives the same accessibility layer through YAML the model writes far more reliably. We keep Espresso available as an *output* for teams that want CI-native tests; we don't make it the agent's primary loop.
- **Appium** — also Apache 2.0, but needs a running server + a platform driver + language bindings. More moving parts, more failure modes, no built-in Viewer.
- **Firebase Test Lab / BrowserStack** — real device matrices, but **paid**. Excluded by your "free and open source" rule.
- **Maestro Cloud** — the same tool's paid tier. Its three MCP tools (`list_cloud_devices`, `run_on_cloud`, `get_cloud_run_status`) will be **filtered out** so the agent can't reach a paid service.

### Windows note (you're on Windows — I checked the repo's `.bat` files)

Maestro added first-class native Windows support in v1.39.9 and no longer requires WSL. The `curl | bash` one-liner in its README is still macOS/Linux/WSL — on Windows you download the release zip and put `maestro/bin` on PATH. **Requires Java 17+.** This goes into a doctor script so the agent can diagnose its own environment instead of failing mysteriously.

---

## 4. How it plugs into your architecture

```
                      task: "build me an Android notes app"
                                       │
                    ┌──────────────────▼───────────────────┐
                    │  runtime_profile.resolve_...()       │  ← ADD CAP_ANDROID
                    │  new _ANDROID_PATTERNS regex         │
                    └──────────────────┬───────────────────┘
                                       │ capabilities
                    ┌──────────────────▼───────────────────┐
                    │  toolsets.resolve_runtime_tool_names │  ← ADD _ANDROID_TOOLS
                    └──────┬───────────────────────┬───────┘
                           │                       │
             ┌─────────────▼─────────┐   ┌─────────▼──────────────────┐
             │ android_tools.py (NEW)│   │ MCP path (EXISTING)        │
             │ scaffold_android      │   │ MCPStdioClient →           │
             │ verify_android_app    │   │   "maestro mcp"            │
             │ android_doctor        │   │ inspect_screen / run /     │
             │ avd_start / avd_stop  │   │ take_screenshot /          │
             │                       │   │ cheat_sheet /              │
             │ build via run_terminal│   │ open_maestro_viewer        │
             │ (600s+, NOT the 60s   │   │ (sub-second, correct fit)  │
             │  MCP timeout)         │   │                            │
             └─────────────┬─────────┘   └─────────┬──────────────────┘
                           │                       │
                    ┌──────▼───────────────────────▼───────┐
                    │  verification_evidence  ← MUST FIX   │
                    │  _VERIFY_RE + _TARGET_RE learn       │
                    │  gradle/gradlew/adb/maestro, .kt/.java│
                    └──────────────────────────────────────┘
```

Two rules that keep this honest — detailed and made structural in [`ANDROID_EVIDENCE_CONTRACT.md`](ANDROID_EVIDENCE_CONTRACT.md):

- **Evidence, not screenshots.** A screenshot proves a pixel buffer existed; it does not prove a state was reached or an assertion was evaluated. Trust load sits on artifacts that record **the observed value** — the matched node and its bounds, the PID, the parsed manifest, the JUnit XML, the attributable exit code. Screenshots stay in the bundle as supplementary material only.
- **No fabricated success.** If the emulator won't boot, the tool says so and names the reason. A device that was never reachable yields `unavailable`, never `passed` — the same discipline as your existing `target_reachable` receipt rule.

---

## 5. Phased plan

Each phase ends with something testable. Phases 0–2 need **no** Android SDK, so I can build and verify them in this sandbox.

### Phase 0 — Make Crusor able to believe Android  *(do this first, ~1 day — grew; see below)*

Without this, everything after it produces confident lies.

**Scope grew after the owner's evidence-first correction.** See [`ANDROID_EVIDENCE_CONTRACT.md`](ANDROID_EVIDENCE_CONTRACT.md) — screenshots are the weakest artifact an agent can produce, so Phase 0 now defines the evidence contract itself, not just the regex fix.

Part A — the regex fix:
- Extend `_VERIFY_RE` in `src/context/verification_evidence.py` to recognize `./gradlew`, `gradlew.bat`, `gradle`, `adb`, `maestro`.
- Extend `_TARGET_RE` to accept `.kt`, `.java`, `.kts`, `.xml`.
- **Critically:** preserve the existing pipe-masking guard (`_exit_status_is_attributable`). `./gradlew test 2>&1 | tail -40` must still NOT count as evidence — that is precisely the bug from attempts 11/12, and Gradle's own docs recommend piping to reduce log noise.

Part B — the evidence contract (new):
- Define `evidence.json` schema v1 and the Tier 0–4 model.
- Implement anti-fraud rules R1–R9 as pure functions.
- **Verified: R2 needs no new logic.** I ran the existing guard against real Gradle commands:

  | command | attributable? |
  |---|---|
  | `./gradlew assembleDebug` | ✅ yes |
  | `./gradlew test 2>&1 \| tail -40` | ❌ **no** — the attempts-11/12 trap, already caught |
  | `./gradlew test; ./gradlew lint` | ❌ no |
  | `./gradlew assembleDebug \|\| echo masked` | ❌ no |
  | `adb install app-debug.apk` | ✅ yes |

  So R2 is wiring, not invention — `_exit_status_is_attributable` already does the right thing.

**Acceptance:** `pytest` on the evidence tests passes, including regression tests proving a piped Gradle build is refused, a duplicate screenshot hash is flagged, and a `passed` verdict with no observed value is rejected.

### Phase 1 — Teach the posture resolver Android exists  *(~1 day)*

- Add `CAP_ANDROID` to `runtime_profile.py`. **Append it to the end of `CAPABILITY_ORDER`** — that tuple's order is part of your prompt-cache contract, and inserting mid-tuple would churn cache keys for unrelated profiles.
- Add `_ANDROID_PATTERNS`: `android`, `kotlin`, `jetpack compose`, `gradle`, `apk`, `.kt`, `manifest.xml`, `activity`, `avd`, `adb`, `maestro`.
- **Fix the misclassification:** an Android UI task currently matches `_BROWSER_PATTERNS` (because of "ui") and gets CDP/Playwright tools. Android must be checked and win.
- Add `_ANDROID_TOOLS` to `toolsets.py`, gated on `CAP_ANDROID`, and extend `all_known_tool_names()`.

**Acceptance:** `resolve_runtime_profile("build an Android notes app in Kotlin")` yields `CAP_ANDROID` and **not** `CAP_BROWSER`; a plain "build me a React dashboard" still yields browser, unchanged. Existing `src/tests/test_toolsets.py` (18 tests) stays green.

### Phase 2 — Skills: the agent's playbook  *(~1 day, zero Python)*

Markdown only, following your `skills/` format:

- `skills/android-app-building/SKILL.md` — project layout, Compose idioms, `AndroidManifest.xml` + permissions, Gradle config, the build command, and what "done" means.
- `skills/android-ui-testing/SKILL.md` — Maestro YAML flow syntax, how to inspect the screen before targeting an element, `assertVisible` over sleeping, capturing screenshots as evidence, reading failures.
- Register both in `skills/SKILL.md`; update the bundled-skill count assertion in `src/tests/test_skill_bundled.py`.

**Acceptance:** `SkillManager.get_relevant_skills("build an Android app")` returns the new skill; trigger derivation works; the 6000-char bundled cap isn't exceeded.

### Phase 3 — Real device control  *(~2 days, needs Android SDK on your machine)*

- `src/tools/android_tools.py`:
  - `android_doctor` — reports JDK, SDK, `adb`, emulator, AVDs, Maestro. Named, actionable errors, never a bare failure.
  - `avd_list` / `avd_start` / `avd_stop` — Crusor owns emulator lifecycle itself via `adb`/`emulator`. **Rationale + caveat:** the *current* bundled MCP server exposes 9 tools per `mobile-dev-inc/maestro-docs` — `list_devices`, `inspect_screen`, `take_screenshot`, `run`, `cheat_sheet`, `list_cloud_devices`, `run_on_cloud`, `get_cloud_run_status`, `open_maestro_viewer` — and **none of them boots a device**. Note the set is version-dependent: the older (now archived) `maestro-mcp` repo exposed a different, larger set that *did* include `start_device`. Re-check `maestro mcp`'s actual `tools/list` at implementation time rather than trusting this doc.
  - `scaffold_android` — clone of the `scaffold_nextjs` shape: temp-dir generate, merge into workspace preserving `_provided`, refuse to overwrite existing work, `checkpoint_before_mutation` first.
  - `verify_android_app` — the one-receipt pipeline mirroring `verify_ui_workspace`: **build → install → launch → drive flow → assert → emit evidence → cleanup**, one tool call. Per the evidence contract it **refuses to return `passed` below its required tier** — "the app works" needs Tier 2 (actually executed on a device), any specific UI claim needs Tier 3 (an assertion with a recorded observed value). Screenshots are captured but are never load-bearing.
- Wire into `chat_graph.py` `tools` list so `_TOOLS_BY_NAME` (line 871) picks them up — a tool the resolver names but the graph can't call is a silent failure, and you already have a test for exactly that in `test_skill_tools.py:5`.
- Ship `.crusorai/mcp.json` Maestro entry, **filtering out the three paid Cloud tools**.

**Acceptance:** on your machine, agent scaffolds a project, `./gradlew assembleDebug` produces a real APK, installs it, the flow taps through the UI, and a screenshot lands on disk.

### Phase 4 — The watch-it-work surface  *(~2 days)*

- Surface **Maestro Viewer** through the same mechanism as Crusor Preview (`src/preview/`, `127.0.0.1:8931`) so the live phone appears in a panel the user is already looking at.
- Stream each MCP command as it runs into the agent pane, so the user reads "tapping *Save*…" then sees it happen.
- Emulator window stays visible throughout — no headless mode by default.

**Acceptance:** a user watching the IDE sees the phone and the command log in sync, live.

### Phase 5 — Close the loop  *(~1 day)*

Failure → read `logcat` + screenshot → diagnose → minimal fix → rebuild → retest, within existing iteration ceilings. Reuses your `systematic-debugging` and `test-driven-development` skills rather than inventing a new loop.

---

## 6. Honest risks and gaps

| Risk | Impact | Mitigation |
|---|---|---|
| **60s MCP timeout vs multi-minute Gradle builds** | Everything works until the first real build, then a confusing timeout | Builds go through `run_terminal`, never MCP. Design rule, tested. |
| **First build downloads ~1GB of deps** | 3–10 min, looks hung | `start_terminal` background + progress; say so upfront in the skill |
| **Emulator RAM/disk (~8GB RAM, ~10GB disk, needs hardware acceleration)** | Won't boot on a weak machine | `android_doctor` checks before attempting; offer Robolectric-only fallback |
| **Windows + `adb` over WSL networking** | Historically painful | Native Windows support since Maestro 1.39.9 — no WSL. Pin this in the doctor check |
| **Java 17+ hard requirement** | Silent Maestro failure | `android_doctor` checks `java -version` first |
| **No Android SDK in this sandbox** | I cannot verify a real APK build here | Phases 0–2 are verifiable here; Phase 3+ needs your machine. I will not claim otherwise. |
| **Prompt-cache churn** | Perf regression repo-wide | Append `CAP_ANDROID`, never insert mid-tuple |
| **Emulator flakiness makes tests non-deterministic** | False failures erode trust | Maestro's built-in waits; retry-once policy; a flake is reported as a flake, not a pass |

---

## 7. What I need from you

1. **Does the phasing look right?** Phase 0 first is deliberate — it is small, it is the trust layer, and shipping Android capability without it would reproduce the attempt-11 failure mode.
2. **Your machine:** do you have Android Studio installed already? That determines whether Phase 3 starts with a 10-minute setup or an afternoon.
3. **Scope check on Phase 4** — is "phone visible in a panel next to the chat" the right shape for "user sees the agent working," or did you mean something closer to a recorded demo/GIF of each run?

Say go and I'll start on Phase 0 — it's the one phase I can fully implement *and* verify with tests inside this sandbox, no Android SDK required.
