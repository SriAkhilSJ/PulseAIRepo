# Agent Core evidence, monitoring, and trusted-shipping MVP

> **Status:** current source audit, implemented hardening slice, and product proposal  
> **Last reviewed:** 2026-10-23  
> **Audit baseline:** `main` at
> `590fe542306ef89547e7909b89da01a9c730e55c`  
> **Runtime evidence checked:** GitHub Host compatibility run `39987746530`
> passed for the baseline; its 78-test selection passed locally. After the
> follow-up implementation, the evidence/telemetry/permission selection and
> four new persistence-security tests passed locally (**102/102**). The newly
> activated broad Agent Core lane passed locally (**2,585 passed, 16 skipped**);
> its separate non-blocking desktop lane remains red on two parity checks.  
> **Scope:** first-party Agent Core, bridge, desktop integration, target
> verification, tests, CI, diagnostics, and telemetry.

## Executive answer

### What is already strong and worth preserving

CrusorAI already has unusually strong **building blocks** for evidence-aware
agent work:

- **Durable tool transactions.** Intent commits before a side effect and result
  commits before live success is projected. This is a sound fail-closed base
  for accountability and interrupted-run recovery.
- **Attributable verification.** The ledger rejects shell constructs whose exit
  status cannot prove the named test/build command, rather than turning
  `build | tail` into a false pass.
- **Freshness after edits.** A passing receipt becomes stale after an
  instrumented mutation. This is a practical correctness invariant many coding
  agents omit.
- **Honest completion gates.** Missing artifacts, failed checks, unavailable
  target tooling, and post-proof edits are represented explicitly instead of
  being converted into confident prose.
- **Deterministic target adapters.** Web and native runners produce bounded
  build/run/probe/assertion/screenshot receipts and preserve unsupported-host
  outcomes.
- **Operational continuity.** Checkpoints, durable sessions, replay, lineage,
  cancellation, clarification, and parent-session approvals form a useful
  execution substrate.
- **Useful local observability.** Call metering, StepTracker diagnostics,
  reliability metrics, and optional OpenTelemetry expose cost, latency, and
  run behavior without making telemetry itself the correctness judge.

These capabilities support the defensible statement: **the agent can collect,
preserve, invalidate, and reason over concrete local evidence.** The next step
is to compose those capabilities into release-grade proof rather than replace
them.

### Constructive improvement map

Each row states an implementation path and acceptance proof—not merely a gap.

| Preserve this strength | Improvement and why it matters | Exact implementation path | Acceptance proof |
|---|---|---|---|
| Intent/result ordering | Protect every durable boundary from credentials and oversized source bodies; replay databases otherwise become a second secret store. | Force recursive redaction in `EventJournal.append`; omit edit/file bodies from persisted tool arguments; apply the same policy to verification SQLite and OTel tool attributes. | Inject prefixed, URL, header, and opaque key-valued secrets; assert none occur in SQLite payloads and body text is omitted. **Implemented in this follow-up.** |
| Persistent verification and stale-on-edit | Give replay/UI/policy one versioned shape; otherwise each consumer invents its own interpretation. | Project ledger outcomes through a schema-versioned `verification.updated` envelope with evidence ID, kind, observation time, journal sequence/status, and durable replay mapping. | Command, edit, explicit, and unavailable updates share the contract and survive restart/replay. **Envelope and replay foundation implemented; policy consumption remains.** |
| Attributable command evidence | Bind a pass to the exact candidate, dependencies, and environment so a later tree cannot inherit an earlier green receipt. | Add a `CandidateManifest` containing Git HEAD plus working-tree digest, lockfile digests, runtime/toolchain versions, policy version, and artifact digests; store its ID on every evidence row and invalidate on mismatch. | Change one tracked byte, untracked app file, lockfile, runtime version, or artifact; the prior receipt is no longer eligible. |
| Completion gates | Make typed facts—not receipt wording—the policy input, preventing UI copy changes from changing correctness. | Add adapters from legacy graph messages/target receipts into typed evidence, run a versioned deterministic policy in shadow mode, compare old/new outcomes, then remove text-prefix decisions after parity. | Property tests show prose cannot create a pass; every verdict identifies rule IDs and evidence IDs. |
| Deterministic target runners | Reproduce proof in a clean runner so warmed caches, untracked dependencies, or already-running services cannot explain a pass. | Package source from the candidate manifest, install from the lockfile in an ephemeral container/VM, run the existing target plan, and retain stage logs plus artifact hashes. | A local-only dependency passes locally but yields `Could not prove` or `Not ready` in clean replay; matching clean runs yield the same candidate/artifact IDs. |
| Explicit unavailable/failed states | Add security and supply-chain evidence without turning scanner outages into false greens. | Introduce secret scan, dependency advisory, SBOM, and license adapters; normalize scanner results and availability into the evidence envelope; make policy thresholds versioned. | Seeded secret/critical advisory blocks `Ready`; an unavailable required scanner produces `Could not prove`, never `Ready`. |
| Parent HITL and lineage | Extend the same approval semantics to delegated children so safe delegation does not require unchecked auto-approval. | Route child approval requests through the session tree, inherit narrowed policy, persist request/decision/scope, and wake only the requesting child. | End-to-end tests cover allow-once, scoped allow-always, reject, cancellation, and no sibling/parent grant leakage. |
| Focused cross-platform CI | Add broad Agent Core validation only after its dependency and isolation contract is demonstrably green. | Run `ci/agent-core.yml` hermetically, repair deterministic failures, then install the verified definition under `.github/workflows/`; keep generated-output parity separate. | Local core lane is **2,585 passed/16 skipped** and the workflow is now installed on this branch. Confirm its first clean GitHub run before making it required; desktop debt remains separately visible. |
| Existing receipts and diagnostics | Give a non-developer one independent ship decision with tested scope and next action. | Feed immutable evidence references into a small policy service; emit `Ready`, `Not ready`, or `Could not prove` plus proven journeys, failures, unknowns, residual risk, and repair actions. | The report can be regenerated from stored evidence without an LLM and never claims an untested journey. |

### Action taken from the evidence

This follow-up implements the first high-value slice rather than stopping at an
audit:

1. repaired both stale focused-test contracts (the renamed terminal drain knob
   and a hermetic home-relative permission fixture);
2. added forced, recursive persistence-boundary redaction and JSON
   normalization in `src/runtime/persistence.py`;
3. made tool intent rows omit source/edit bodies while retaining useful target
   metadata, and reused the safe shape for OTel tool attributes;
4. applied forced redaction to verification command/output persistence;
5. added a versioned verification envelope, journaled command/edit/explicit/
   unavailable updates, and taught durable bridge replay to project it;
6. added security contracts proving secrets and omitted bodies do not reach
   runtime or verification SQLite payloads; and
7. reran the previous 98-test evidence/telemetry/permission selection plus four
   new persistence tests: **102 passed**;
8. ran the staged broad lane, used its five failures as actionable evidence,
   reconciled four stale architecture contracts and restored actionable timeout
   guidance, then reran it: **2,585 passed, 16 skipped**; and
9. installed the proven definition as `.github/workflows/agent-core.yml`, while
   retaining desktop parity as a visible non-blocking lane (currently two red
   checks).

The right product direction remains an **independent proof loop**—working name
**ShipProof**—that turns an AI-generated web app into a reproducible release
decision:

> **Build it, exercise the important journeys, scan the release, reproduce the
> result in a clean runner, and explain exactly what is proven, failed, or still
> unknown.**

Start with TypeScript web applications (Vite/React and Next.js), not every
platform. The existing target system can expand after the evidence model and
policy are trustworthy.

## 1. Repository state checked first

### Latest commits that materially change current behavior

| Commit | Current implication |
|---|---|
| `590fe542` | Refreshed tracked Code OSS output. Also restored 541 generated `crusorai-spa` files without matching source; they are not loaded by the native pane. |
| `0edce5c3`, `7315b599` | Repaired the focused cross-platform Host compatibility workflow. Run `39987746530` is green. |
| `c5bc40f9` | Reasoning consumes the delivery budget; visible answer tokens alone no longer describe cost or exhaustion. |
| `794a5555`, `996aa894` | Ported structured terminal start/output/end behavior and covered streamed subprocess pipes. |
| `ff24590b` | Reverted scoped parent tool binding. The parent currently binds the full configured registry. |
| `1ab5671b`–`b8f068f2` | Added call/run metering, dynamic pricing, request anatomy, and per-call tool-name data. |
| `f4f3a14e`, `7fd8ea61` | Removed the native CopilotKit surface and deleted the old repository webview app. |

The active pane is native TypeScript. The generated SPA payload at HEAD is an
output/source inconsistency, not evidence that the removed architecture is
active.

### Test and CI facts

- Static inventory after this follow-up: 214 non-test Python files, 213
  `test_*.py` files, and 2,576 syntactic `test_*` definitions (2,290 top-level
  functions plus 286 methods).
- `.github/workflows/host-compatibility.yml` runs the focused target-contract
  subset on Windows, macOS, and Linux.
- The previously staged broad workflow was executed locally. Its first run
  surfaced five actionable failures; after contract/source repairs, the exact
  blocking selection passed **2,585 tests with 16 skips**.
- The validated definition is now installed as
  `.github/workflows/agent-core.yml`, with generated-desktop parity isolated in
  a visible non-blocking lane. A clean GitHub run is the next checkpoint.
- The active five-file host selection passed locally (**78/78**). The focused
  evidence selection initially exposed the old terminal drain-knob name and a
  non-hermetic `~/.bashrc` assumption; after repair it passes **98/98**, or
  **102/102** with the four new persistence-security contracts.
- The desktop parity lane was also run separately: **116 passed, 8 skipped,
  1 xfailed, 2 failed**. Those failures remain explicit generated-output and
  renderer-parity debt; they do not silently contaminate the Agent Core claim.

## 2. Capability map

### 2.1 Durable execution accountability

`src/runtime/tool_middleware.py` is the common execution chokepoint:

1. append `tool.intent` to SQLite;
2. invoke the tool;
3. classify and redact the result text;
4. append `tool.result`;
5. emit the live result with the durable journal sequence.

If intent persistence fails, the tool does not run. If result persistence fails,
the side effect may already have occurred, but no successful live result is
projected; the committed intent identifies an interrupted transaction for
recovery. This is a sound base for at-least-once recovery semantics.

`src/runtime/event_journal.py` supplies monotonically ordered, append-only rows
and bridge replay. Production callers now record tool transactions and typed
verification updates. Every appended payload crosses a forced recursive
redaction/normalization boundary, and source/edit bodies are omitted from tool
intent rows. The next implementation increment is to journal turn, model,
approval, graph-node, and final-policy references so the same ordered timeline
can support release-level lineage.

**Assessment:** strong, privacy-hardened tool durability plus a typed
verification seam; extend the same timeline to the remaining lifecycle events.

### 2.2 Persistent verification freshness

`src/context/verification_evidence.py` maintains a separate SQLite ledger:

- recognizes test, lint, typecheck, and build commands;
- accepts evidence only when the shell's exit status is attributable to the
  matched command;
- refuses to treat piped, backgrounded, or `||`-masked status as proof;
- records pass/fail, command kind, scope, exit code, and bounded output;
- changes a prior pass to `stale` after file edits.

This directly addresses a common false green: `npm run build | tail` returning
the status of `tail`, not the build. It is one of the strongest current trust
features.

Next implementation layers:

- evolve regex command recognition behind typed verifier adapters;
- make graph completion consume the new versioned verification envelope rather
  than reconstructing facts independently;
- bind freshness to a candidate manifest (Git tree/worktree, dependency locks,
  environment, policy, and artifact identity), not only session/workspace/edit;
- detect changes made outside instrumented file tools by comparing candidate
  identity at policy time; and
- add explicit retention duration and deletion controls. Forced write-boundary
  redaction is now implemented for command/output storage.

**Assessment:** strong local freshness and attributable proof with a new typed,
redacted event seam; candidate binding is the path to release provenance.

### 2.3 Completion and honesty gates

`src/graphs/gates.py` and finalization logic enforce several important rules:

- execution tasks cannot finish after little or no real work without bounded
  nudges;
- explicitly named files/directories must exist and be non-empty;
- post-verification edits invalidate earlier proof;
- written code requires a verification domain;
- rendered UI asks require static/integrity evidence plus browser evidence;
- explicit visual-proof asks require screenshots, not only a DOM snapshot;
- native receipts must name an eligible rendered target;
- unavailable tooling produces an unavailable/unverified result rather than a
  fabricated pass;
- failed verification cannot stamp a completed verdict.

This makes the final answer more honest than a normal coding agent's prose.
However, the gate reconstructs some evidence from graph messages, tool names,
and textual prefixes such as `✅ UI VERIFICATION PASSED` and target receipt
markers. That couples policy to presentation strings and duplicates facts held
in the verification database.

**Assessment:** strong anti-premature-completion control; medium integrity due
to split and partly text-derived evidence.

### 2.4 Deterministic web and native proof

`src/tools/ui_verification.py` and `src/targets/` can:

- detect project/target types;
- construct build/run/probe plans;
- execute bounded stages;
- start and stop servers/processes;
- wait for readiness;
- inspect DOM/device hierarchy;
- evaluate required selectors/assertions;
- capture screenshots and artifact hashes;
- inspect console, network, launcher, and crash output;
- report unsupported hosts or missing SDKs without pretending success.

Typed target contracts (`TargetRequest`, stage outcomes, assertions, artifacts,
receipts) are a particularly useful substrate. The web verifier is more
string-oriented, and the completion gate ultimately consumes formatted receipt
text in several places.

These pipelines prove that a specific local execution produced observations.
They do not yet prove:

- the same source passes in a clean environment;
- the tested bytes equal the bytes deployed;
- dependencies are free of known critical vulnerabilities;
- no secrets are committed;
- licenses or an SBOM were reviewed;
- migrations, rollback, monitoring, or production configuration are safe;
- all user-critical journeys were selected and exercised.

**Assessment:** strong runtime evidence adapters; incomplete release assurance.

### 2.5 Runtime monitoring

| System | Current capability | Limitation |
|---|---|---|
| Call ledger (`src/telemetry/call_ledger.py`) | One local JSONL row per model call plus run verdict; tokens, latency, reasoning volume, optional provider/dynamic cost, request anatomy, tool names | Cost/outcome meter, not correctness evidence; best-effort writes; local files are not a queryable release record |
| StepTracker (`src/runtime/step_tracker.py`) | JSONL/Markdown diagnostics for AI/tool steps, timing, token use, cost, plan and verification status | Tracks proposed tool calls in `ai` and outcomes in `tools`; naive totals can double-count a logical call. Tool batch duration is not per-call latency |
| OTel (`src/runtime/otel_tracing.py`) | Optional turn, graph-node, LLM, and tool spans; console/file/OTLP; local Langfuse path | Disabled by default, fail-open by design, and not tied to release policy |
| Event bus (`src/dashboard/event_bus.py`) | Responsive live events, approval/clarification queues, progress | In-memory projection; most event types are not durable/replayable |
| Session store/checkpoints | Durable conversations, forks, lineage, resumability | Operational state, not a normalized evidence graph |
| Reliability metrics (`src/runtime/reliability_metrics.py`) | `pass@k`, `pass^k`, Wilson CI, ICC, flakiness, cost/correct edit, test-execution parsing | Useful library with no confirmed runtime or release-gate caller |
| Enterprise monitor (`src/enterprise/monitor.py`) | Small in-memory turn health summary | No production caller found; thresholds are generic, not product SLOs |

**Assessment:** good developer diagnostics, weak unified operations/release
monitoring.

### 2.6 Permission and human-control evidence

The main session has pre-execution approvals, deny/ask/allow rules,
resource-scoped session grants, cancellation, and durable denial results.
Approval waits now remain pending until a human responds or the turn is
cancelled.

Sub-agent clarifying questions are routed through the session tree. Tree-aware
child approval UI also exists, but `SafeToolNode` auto-denies approval-requiring
`sub-*` calls before that channel. The only bypass auto-approves unchecked. A
synthetic bridge/UI test is not end-to-end execution proof.

**Assessment:** strong parent-session HITL; child approval parity is overstated
in older design prose.

## 3. Evidence maturity verdict

The terms below are deliberately narrower than “good/bad”:

- **Operational:** used on the current path and has direct tests/source wiring.
- **Partial:** valuable, but fragmented, heuristic, optional, or not a blocking
  policy.
- **Missing:** no integrated first-party implementation found in the reviewed
  paths.

| Trust question | Status | Why |
|---|---|---|
| Did a guarded tool attempt and finish? | **Operational** | Durable intent/result transaction and IDs |
| Did a recognized local verification command pass? | **Operational** | Persistent ledger with attributable exit status |
| Did edits make prior local proof stale? | **Operational** | Instrumented file tools mark verification stale |
| Did a web/native app build and render on an available target? | **Operational/host-dependent** | Deterministic pipelines and receipts |
| Can a developer inspect latency, tokens, cost, and tool activity? | **Operational/optional** | Call ledger, StepTracker, OTel, UI events |
| Is all evidence one typed, queryable record? | **Partial** | Verification now has a versioned durable envelope; target, graph, telemetry, checkpoint, and policy facts still need adapters into it |
| Is evidence bound to exact source, dependencies, environment, and artifact? | **Partial** | Some artifact hashes; no universal source/lock/environment attestation |
| Is the result reproduced in a clean runner? | **Partial / activation pending** | Broad workflow is locally green and installed; first GitHub run and candidate-bound product replay remain |
| Are secrets and dependencies scanned before ship? | **Missing as a unified gate** | No integrated release decision found |
| Are license/SBOM and supply-chain facts available? | **Missing** | No integrated implementation found |
| Can a non-developer understand scope, residual risk, and next action? | **Partial/weak** | Tool receipts exist; no single release card/report |
| Can the product honestly authorize deployment? | **Not yet** | No complete release policy or artifact/deploy identity |

### The most consequential gaps

1. **Complete the canonical evidence envelope.** Verification updates now have
   a versioned, durable contract. Add adapters for graph messages, target
   receipts, telemetry references, diagnostics, approvals, and policy verdicts
   so the same run is no longer interpreted independently by each surface.
2. **No independent release policy.** The coding agent both creates the change
   and participates in deciding whether work is complete. A deterministic
   policy service should own release status.
3. **Add candidate-bound clean-room replay.** The activated CI lane validates
   Agent Core in a clean checkout, but ShipProof still needs to package and
   replay the exact candidate so local state, untracked dependencies, warmed
   caches, or an already-running service cannot explain a product pass.
4. **Finish broad CI activation.** The broad workflow is locally green and now
   installed. Confirm the first GitHub result, then make its core job required;
   keep desktop parity non-blocking until source/output integrity is repaired.
5. **Security and supply-chain holes.** No integrated secret scan, dependency
   vulnerability policy, license/SBOM output, or deployed-artifact attestation.
6. **Text is sometimes treated as data.** Receipt prefixes and output heuristics
   can drift independently of policy.
7. **No source-to-deployment identity.** A local screenshot is not proof that
   the same bytes reached production.
8. **Finish retention/privacy controls.** Durable tool and verification writes
   now force redaction, edit/source bodies are omitted from intent rows, and
   regression tests inspect SQLite payloads. Add configurable retention,
   storage budgets, deletion/export behavior, and migration handling for older
   pre-hardening rows.
9. **Evaluation helpers are not release controls.** Statistical reliability
   code and the enterprise monitor have no confirmed production gate wiring.
10. **Generated-output integrity is visibly weak.** HEAD's orphaned SPA bundle
    demonstrates that “compiled artifact exists” can disagree with active
    source architecture.

## 4. Product proposal: ShipProof

The attached product-architecture guidance is applied here as four constraints:

- solve one painful job for one initial customer segment before broadening;
- validate with real repositories and observed decisions before a large build;
- make the evidence control plane—not a thin chat wrapper—the product moat;
- use deterministic quality control and tiered models so expensive inference is
  reserved for diagnosis/repair, never for self-grading.

### 4.1 Focused customer and wedge

**Primary user:** a non-developer or lightweight technical builder who created a
small web application with an AI coding tool and now fears breaking users,
leaking a secret, or deploying something that only worked in the coding
session.

**Initial project scope:**

- Git repository;
- TypeScript/JavaScript;
- Vite/React or Next.js;
- one web app and optional HTTP API;
- package-manager lock file;
- GitHub pull request as the first release boundary;
- preview deployment adapter only after local/CI proof is credible.

Do not include mobile, desktop, every language, production penetration testing,
or one-click autonomous deployment in v1. The repository has broader target
adapters, but broad platform claims would dilute validation and multiply false
greens.

### 4.2 Product promise

> Press **Prove it works**. Within a bounded run, ShipProof will either produce
> a reproducible evidence-backed release report, show the exact failures it can
> fix, or say what it could not prove. Unknown never becomes green.

The product should target reducing a 4–5 day manual testing/debugging tail to a
same-session decision for supported apps. The MVP should measure the actual
median rather than promise a fixed 30-minute result before pilots.

### 4.3 User experience

1. **Choose the release candidate.** The app shows branch, commit/tree hash,
   dirty changes, framework, package manager, and detected start/build/test
   commands.
2. **Confirm what matters.** ShipProof proposes three to five plain-language
   journeys (“visitor can sign up,” “user can create and reload a project”).
   The user edits or confirms them; no test syntax is shown.
3. **Run the proof plan.** A seven-stage progress surface replaces a scrolling
   agent transcript:
   `Source → Install → Static → Tests → Launch → Journeys → Security`.
4. **Fix with boundaries.** Failed checks become cards with **Fix and re-prove**.
   The agent can patch on a checkpointed branch, but it cannot mark its own
   check passed.
5. **Re-run from clean state.** After a candidate passes locally, a clean runner
   installs from the lock file and repeats required checks.
6. **Receive one verdict.** Exactly three top-level states:
   - **Ready for preview/deploy** — every required check passed on the exact
     candidate and clean replay;
   - **Not ready** — a required check failed;
   - **Could not prove** — required evidence is unavailable, stale, or outside
     supported scope.
7. **Inspect or share evidence.** The report leads with plain language and keeps
   commands, logs, screenshots, hashes, environment, and timings in an
   expandable evidence drawer.
8. **Ship with rollback.** Deployment, when added, uses the attested artifact
   and records destination/version plus a rollback checkpoint.

A user may override a warning, but not silently convert failed or missing
required evidence into a green badge. Overrides must record who, why, what
scope, and expiration.

### 4.4 MVP required checks

| Gate | Minimum evidence | Failure policy |
|---|---|---|
| Candidate identity | commit, tree hash, dirty patch hash, lock-file hash | Unknown identity blocks green |
| Reproducible install | clean checkout + frozen/locked dependency install | Failure blocks |
| Static integrity | framework-appropriate typecheck/lint/build | Failure blocks; unavailable is explicit |
| Test execution | non-zero attributable test count and exit status | Zero tests is not a pass; policy can require generated smoke tests |
| Runtime health | bounded startup, readiness response, no crash | Failure blocks |
| Critical journeys | deterministic browser steps and assertions for user-confirmed journeys | Any required journey failure blocks |
| Browser quality | uncaught console errors, failed critical network requests, blank-page check, screenshot | Critical error blocks |
| Secret scan | repository + generated artifact scan with redacted findings | Confirmed secret blocks |
| Dependency risk | lock-file-aware known-vulnerability scan and policy threshold | Critical/high threshold blocks or requires explicit policy exception |
| Clean replay | required checks repeated in isolated CI/runner | Local-only pass cannot be “ready” |
| Report integrity | signed/hashed manifest of evidence and artifacts | Missing manifest blocks sharing/deploy |

Accessibility, visual-regression baselines, licenses/SBOM, API contract tests,
database migration checks, and preview-deployment probes should be introduced
as soon as the first supported application profiles require them. SBOM/license
should be a release requirement before expanding beyond private pilots.

## 5. Technical design

### 5.1 Non-negotiable boundary

The **builder may propose and repair; the verifier observes; the policy engine
decides**.

- LLM output can propose acceptance criteria, selectors, fixes, and summaries.
- Deterministic adapters execute checks and return typed observations.
- Only a versioned policy maps observations to a release verdict.
- No model-generated sentence, receipt prefix, or self-assigned confidence can
  create a pass.

### 5.2 Canonical evidence envelope

Every observation should use one schema, regardless of adapter:

```json
{
  "schema_version": 1,
  "run_id": "run_...",
  "evidence_id": "ev_...",
  "candidate": {
    "repo": "...",
    "commit": "...",
    "tree": "...",
    "dirty_patch_sha256": "...",
    "lockfile_sha256": "..."
  },
  "target": {"kind": "web", "profile": "nextjs", "environment": "ci-linux"},
  "check": {"id": "web.journey.signup", "version": "1.0", "required": true},
  "provenance": "deterministic",
  "status": "passed",
  "started_at": "...",
  "ended_at": "...",
  "runner": {"image": "...", "tool_versions": {}},
  "observation": {"exit_code": 0, "assertions": []},
  "artifacts": [{"kind": "screenshot", "sha256": "...", "uri": "..."}],
  "supersedes": null,
  "redaction": {"policy": "v1", "applied": true}
}
```

Statuses should be closed and boring: `passed`, `failed`, `unavailable`,
`cancelled`, `stale`. Store model interpretation separately from observed fact.

### 5.3 Components

```text
Candidate detector
      │
      ▼
Acceptance-contract compiler ── user confirmation
      │
      ▼
Versioned proof-plan compiler
      │
      ├── static/test adapter
      ├── web runtime + browser journey adapter
      ├── secret/dependency adapter
      └── clean-runner adapter
                  │
                  ▼
Append-only evidence store ── artifact object store
                  │
                  ▼
Versioned policy engine ──> materialized release verdict
                  │
         ┌────────┴────────┐
         ▼                 ▼
  plain-language report   bounded repair loop
                              │
                              └── new candidate → entirely new proof run
```

A repair must never mutate an already-green run. It creates a new candidate ID,
marks affected evidence stale, and executes a new plan. This converts the
current edit-driven stale concept into full release lineage.

### 5.4 Reuse from the repository

| Existing asset | Reuse | Required change |
|---|---|---|
| Tool transaction middleware/journal | Execution ordering and tool correlation | Extend schema to all proof events; redact intent before persistence |
| Verification ledger | Attributable shell parsing and stale semantics | Emit canonical envelopes keyed to candidate/check IDs |
| `src/targets/` | Plan/stage runner, host support, artifacts, assertions | Preserve typed observations; stop relying on formatted text at policy boundary |
| UI verifier/browser tools | Launch, DOM, console, screenshot, blank-page proof | Express user journeys as typed steps and network assertions |
| Completion gate | Fail-closed patterns and required domains | Make it consume policy verdict; do not maintain parallel truth |
| Shadow checkpoints | Repair rollback | Bind checkpoint to candidate and report |
| Session/lineage IDs | Correlation and audit | Add durable run/evidence/check IDs across bridge frames |
| Call ledger/OTel | Cost and performance monitoring | Attach `run_id`; keep separate from correctness decision |
| Reliability metrics | Repeated-run/flakiness evaluation | Wire into release-profile qualification and nightly eval, not every user run |

### 5.5 Security and privacy

Before pilot data is trusted:

- redact secrets before journal/database writes, not only at tool-result egress;
- store artifact references and bounded excerpts rather than unlimited command
  output;
- encrypt local evidence at rest where platform facilities allow;
- define default retention and **Delete proof data** behavior;
- never send source, logs, or screenshots to a model without an explicit data
  boundary;
- sandbox project commands with resource/time/network limits;
- pin clean-runner images and scanner versions;
- sign or hash the report manifest and verify it before deployment.

## 6. Model and cost strategy

Use models only where they create user value:

| Work | Default mechanism |
|---|---|
| Project detection, command execution, hashing, scans, assertions, verdict | Deterministic code—no model |
| Turn user goal into candidate journeys | Small/fast structured-output model, followed by user confirmation |
| Diagnose a structured failure | Small model first; escalate only when ambiguity is high |
| Produce a patch | Strong coding model with bounded attempts and checkpoint |
| Explain final report | Small model over typed/redacted facts, with a deterministic fallback template |

This follows three product rules:

1. expensive models do not grade themselves;
2. failed repair attempts are budgeted and visible;
3. optimize **cost per proven release**, not token price or best-of-many demo
   success.

Suggested loop limits for the pilot: at most three repair candidates per run,
one strong-model call at a time, explicit cost ceiling, and stop when the same
check fails twice with the same fingerprint.

## 7. Monitoring the MVP

### Product outcome metrics

- **Time to proven candidate:** user presses Prove → clean-runner verdict.
- **First-proof pass rate:** supported projects that pass without AI repair.
- **Repair yield:** failed projects that become cleanly proven within the cap.
- **False-green rate:** a required check later shown to have been false. Target:
  zero; treat any severity-1 false green as an incident.
- **Escaped-defect rate:** production defects inside a supposedly covered
  journey.
- **Evidence-complete rate:** runs with candidate, environment, check, artifact,
  and clean-replay lineage present.
- **Unsupported/unknown rate by reason:** guides adapter investment.
- **Cost per proven release**, not cost per model call.
- **User comprehension:** can the user correctly answer “what was tested?” and
  “what remains risky?” from the report without reading logs?

### Operational SLOs for the initial scope

- 99% of started checks reach a terminal state or explicit cancellation.
- 100% of green verdicts reference a clean replay and immutable candidate ID.
- 100% of required unavailable checks produce **Could not prove**, never green.
- 100% of evidence artifacts have a digest and retention policy.
- p50 proof time under 30 minutes and p90 under 60 minutes for the agreed pilot
  fixture size; revise from measured data.
- report generation under five seconds after the final check.

Nightly qualification should run representative apps multiple times and report
`pass^3`, flakiness, and confidence intervals. A single best run (`pass@k`) is a
capability demo, not a reliability SLA.

## 8. Validation plan before building broadly

### Week 0: concierge discovery

Recruit 5–8 people who have shipped or abandoned an AI-generated web app. Ask
for a recent repository and observe how they currently decide it is ready.
Validate these assumptions:

- testing/debugging, not initial generation, dominates elapsed time;
- they can name critical journeys in plain language;
- a report with evidence changes a deploy decision;
- clean CI replay is worth waiting for;
- the initial Vite/Next.js scope covers a coherent segment.

Do not ask only whether the idea sounds useful. Give them a manual version of
the report for their own project and ask what decision they make.

### Shadow pilot

Run ShipProof without deployment authority on 20–30 frozen repository
snapshots:

1. have a professional developer write the expected defect/risk list;
2. run the proof plan blind;
3. compare false negatives, false positives, time, and remediation quality;
4. rerun passing candidates three times in clean environments;
5. review every green with a developer before showing it to the user.

Exit criteria for deployment-enabled beta:

- zero known critical false greens;
- at least 90% evidence-complete runs in supported profiles;
- repeated clean-run stability at an agreed `pass^3` threshold;
- median elapsed time materially below the users' baseline;
- at least 70% of pilot users can explain tested scope and residual risks from
  the report alone;
- security/privacy review of retained evidence.

## 9. Delivery sequence

### Phase 0 — make truth coherent (1–2 weeks)

1. **Started:** verification now emits a versioned durable evidence envelope;
   finish candidate, check, artifact, and verdict schemas around it.
2. **Redaction complete:** add source/tree/lock/environment identity and retain
   the forced write-boundary redaction contracts.
3. Adapt current web/static checks to emit typed envelopes.
4. Implement a deterministic policy engine with only three top-level verdicts.
5. **Local proof and installation complete:** confirm the first clean GitHub
   run of the 2,585-test core lane, then make that job required.
6. Remove/quarantine orphaned SPA build output or restore a declared source and
   loader contract—do not leave ambiguous generated payloads.

### Phase 1 — prove a local web candidate (2–3 weeks)

1. Vite/React and Next.js detector/profile.
2. User-confirmed journey contract.
3. Clean local runner, frozen install, static/build/test checks.
4. Browser journeys, console/network assertions, screenshots.
5. Secret and dependency checks.
6. Evidence report with exact scope, failures, unknowns, and artifact hashes.

### Phase 2 — bounded repair and CI replay (2–3 weeks)

1. Checkpointed fix loop driven by structured failures.
2. New candidate/run after each repair; automatic stale propagation.
3. GitHub PR check and clean runner.
4. Cost/time caps, retry fingerprinting, and cancellation.
5. Repeated-run qualification suite and false-green incident process.

### Phase 3 — controlled ship (after pilot evidence)

1. Preview-deployment adapter that deploys the attested artifact.
2. Post-deploy health and critical-journey replay.
3. Deployment identity and rollback receipt.
4. Policy-controlled human override and audit trail.

Only then expand profiles to APIs, databases, mobile, and desktop targets.

## 10. MVP acceptance criteria

The MVP is ready for a private beta when a supported repository can demonstrate
all of the following:

- one click creates a candidate ID and understandable proposed journeys;
- the user can confirm journeys without touching test code;
- every required check produces typed pass/fail/unavailable evidence;
- an edit invalidates affected evidence and creates a new candidate lineage;
- a clean runner reproduces every green-required check from the lock file;
- secret and dependency thresholds are enforced;
- the coding model cannot directly set a pass or final verdict;
- the report binds source, environment, checks, screenshots/logs, artifact, and
  policy version;
- **Could not prove** is used for missing tools/evidence;
- a failed check can be checkpointed, repaired, and re-proven within explicit
  time/cost limits;
- the GitHub status and report agree on the same immutable verdict;
- cancellation leaves a terminal auditable state and no orphan process;
- a user can understand tested scope, residual risk, and next action without a
  professional developer interpreting raw logs.

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| “Ready” is interpreted as bug-free/security-certified | Name the supported profile and covered journeys; show residual risks; never use absolute safety language |
| Generated tests assert the implementation instead of intent | User-confirmed journeys, adversarial fixtures, deterministic assertions, review false greens |
| Agent games its own tests | Separate builder/verifier permissions and processes; immutable policy; clean replay |
| Flaky browser behavior destroys trust | Stable selectors/contracts, bounded retries disclosed in evidence, repeated qualification, `pass^k` metrics |
| Scans overwhelm non-developers | Severity policy plus plain-language remediation; raw findings remain available |
| Proof run becomes as slow as manual QA | Parallel independent checks, cache installs by lock hash, prioritize critical journeys, strict budgets |
| Private source/log leakage | Local-first execution, redaction before persistence/model use, retention/deletion controls |
| Scope expands to every framework too early | Support matrix and explicit Could not prove; promote profiles only after fixture and pilot thresholds |
| Local green differs from deployed app | Build once, hash artifact, deploy that artifact, post-deploy replay |

## Recommendation

Use the next engineering cycle to build **truth infrastructure**, not more agent
surface area:

1. confirm the activated Agent Core workflow on GitHub and make its core job required;
2. extend the new typed verification envelope with candidate identity and policy adapters;
3. convert the existing web pipeline into the first ShipProof profile;
4. add secret/dependency and clean-replay gates;
5. expose one three-state release report;
6. validate it in shadow mode with real non-developer AI builders.

The existing Agent Core can remain the repair engine. Its highest-leverage new
product is the independent verifier and release policy around it—the part that
turns “the agent says it is done” into “these exact checks passed on these exact
bytes, these risks remain, and here is the evidence.”
