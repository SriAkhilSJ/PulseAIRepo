# CrusorAI - Architectural Decisions

This is an ADR-style log. Each entry records a decision that constrains current
code. Status values:

- **Accepted** - implemented and observed in the repository.
- **Accepted (derived)** - reconstructed from source and phase evidence; no
  standalone ADR file was found.
- **Proposed** - not implemented; recorded for future work.

Do not rewrite history here. If a decision changes, add a new entry and mark the
old one superseded.

---

## ADR-001 - Build on a pinned Code OSS fork, not a from-scratch editor

**Status:** Accepted
**Date recorded:** 2026-11-08 (decision predates this log)
**Evidence:** `desktop/UPSTREAM_PIN`, `desktop/SELECTIVE_MANIFEST.json`,
`desktop/README.md`, `docs/DESIGN/FORK_REBRANDING.md`

**Context.** The product needs a mature editor, terminal, extension host, and
workbench on day one.

**Decision.** Vendor Code OSS at a pinned commit
(`6c27443ce6fdf6ac798c64025d45175e2e23c4b4`), brand it, and add Crusor as a
workbench contribution. Keep upstream source edits to a named, hash-receipted
set.

**Consequences.**
- Immediate access to editor/terminal/extension infrastructure.
- Large vendored tree (18k tracked files) and an ongoing upstream-sync burden.
- The manifest check (`src/tests/test_desktop_contrib_overlay.py`) must move
  whenever a pinned file changes.
- "Invariant 7" limits upstream source edits; new UI should be additive under
  `contrib/crusorai/`.

---

## ADR-002 - Run the agent as a separate Python process over stdio

**Status:** Accepted
**Evidence:** `src/bridge/__main__.py`, `src/bridge/protocol.py`,
`desktop/.../node/crusorAIWorkerProcessService.ts`

**Context.** The IDE is TypeScript/Electron; the agent stack is Python
(LangGraph, provider SDKs, data tooling). Embedding Python in Electron is
fragile and unsafe.

**Decision.** Spawn a Python worker (`python -m src.bridge`) from an Electron
utility process and speak newline-delimited JSON over stdio, protocol v2.

**Consequences.**
- Clean process isolation, crash containment, and independent testing.
- Protocol versioning and generated TypeScript types become mandatory.
- No runtime schema validator on both ends; drift is caught by tests.
- Desktop and engine can be packaged/updated separately.

---

## ADR-003 - Use LangGraph for the turn lifecycle

**Status:** Accepted
**Evidence:** `src/graphs/chat_graph.py`, `src/graphs/state.py`,
`pyproject.toml` (`langgraph`)

**Context.** Agent turns need explicit planning, tool loops, recovery, budget
limits, and terminal states that can be inspected and replayed.

**Decision.** Model the turn as a LangGraph state machine with named nodes:
task manager, planner, AI, tools, progress, recovery limit, tool-cycle limit,
pivot, plan preview/reviser/cancel, finish gate, finalize.

**Consequences.**
- Deterministic routing and a clear place for gates/checkpoints.
- The graph file is very large; changes require careful regression testing.
- A second orchestrator path exists for engineering tasks, so divergence is a
  standing risk.

---

## ADR-004 - One fixed right-side agent surface

**Status:** Accepted
**Evidence:** `desktop/.../browser/crusorAI.contribution.ts`,
`docs/DESIGN/CRUSORAI_DESIGN_PLAN.md`, `README.md`

**Context.** Multiple chat surfaces and movable panes fragment the experience.

**Decision.** Crusor lives in the Auxiliary Bar, fixed, non-movable, as a single
agent. Copilot remains available but hidden by default without deleting source.

**Consequences.**
- Predictable layout and a single session model.
- New capabilities must fit the panel/dialog/preview patterns rather than add
  panes.
- UI tests pin dock location and visibility.

---

## ADR-005 - Context assembly is a layered, budgeted engine

**Status:** Accepted
**Evidence:** `src/context/engine.py`, `src/context/context_engine.py`,
`src/context/token_budget.py`, `src/context/compaction.py`

**Context.** A coding agent needs repository, task, memory, history, and
verification context without exceeding model windows or cost caps.

**Decision.** Define `ContextEngine` as an ABC and a facade with named layers;
assemble under a shared token budget; compact based on actual provider usage;
preserve a stable prompt prefix where possible.

**Consequences.**
- Context selection is inspectable and testable per layer.
- Compaction can invalidate the prompt cache (known warning).
- Layer additions must respect ordering, dedup, and budget policy.

---

## ADR-006 - Route management calls to a cheap auxiliary model

**Status:** Accepted
**Evidence:** `src/config/settings.py` (`resolve_aux_llm`),
`src/llm/factory.py`

**Context.** Summaries, titling, classification, and memory maintenance should
not bill at flagship rates or share the main request chain.

**Decision.** Default auxiliary provider to `cheap`, with
`CRUSORAI_CHEAP_*` credentials/model and `AUX_LLM_*` overrides. Keep structural
separation from the main conversation.

**Consequences.**
- Lower cost for housekeeping.
- Another credential surface to configure and audit.
- `SUMMARIZER_LLM` remains off by default for budget safety.

---

## ADR-007 - SQLite is the canonical durable store

**Status:** Accepted
**Evidence:** `src/server.py`, `src/agents/financial_store.py`,
`src/bridge/__main__.py` (checkpoint read), `src/runtime/persistence.py`

**Context.** Sessions, checkpoints, and financial records must survive restarts
on a desktop machine without a database server.

**Decision.** Use `~/.crusorai/sessions.db` (SQLite) as the canonical store for
checkpoints and financial reservations; keep workspace-scoped JSON/JSONL
ledgers for audit and portability.

**Consequences.**
- Zero-install local persistence and easy backup.
- Multiple money surfaces require reconciliation; no single transaction spans
  them.
- Persistence redaction is mandatory before writes.

---

## ADR-008 - Fail closed at the security boundary

**Status:** Accepted
**Evidence:** `src/security/contracts.py`,
`src/security/execution_broker.py`, `src/security/sandbox/`,
`src/tests/test_security_containment.py`

**Context.** The agent executes model-chosen commands and file mutations. A
mistake is a real host risk, not a UI bug.

**Decision.** Route execution through a single broker with single-use approval
tokens, workspace jailing, environment allowlists, output caps, and OS sandbox
backends. Fail closed when the platform or policy is unknown. Keep the
AppContainer AST allowlist exact and adversarial-tested.

**Consequences.**
- Stronger containment and auditable receipts.
- Platform-specific code paths and CI matrix complexity.
- A static AST guard is not an OS sandbox; native/direct OS calls remain out of
  reach.

---

## ADR-009 - Completion is derived from verification, not model claims

**Status:** Accepted
**Evidence:** `src/verification/`, `src/graphs/gates.py`,
`src/runtime/status_contract.py`, `README.md` status-contract notes

**Context.** Models regularly claim success after partial work.

**Decision.** Separate runtime outcome, verification status, and specification
status. Require landed mutations and exact-check evidence before clearing
failed-check debt; weaker green commands cannot authorize completion.

**Consequences.**
- More honest completion and better failure diagnosis.
- More state to track and more tests to maintain.
- Users may see "failed/incomplete" when the model believes it succeeded,
  which is intentional.

---

## ADR-010 - Multi-platform delivery is evidence-gated

**Status:** Accepted
**Evidence:** `src/targets/`, `src/tools/target_tools.py`,
`docs/MULTI_PLATFORM_TARGETS.md`, `docs/pipelines/`

**Context.** "Build succeeded" is not "the app runs".

**Decision.** Resolve targets from real manifests, run per-target build plans,
and issue a receipt only when deterministic probes pass (window/CDP, device
foreground, screenshot quality, logs, UI assertions). Dry runs are `PLAN`, never
`passed`.

**Consequences.**
- Honest cross-platform claims.
- Host toolchains and devices are required; many environments yield
  `UNAVAILABLE`.
- CI uses general-purpose runners, so device proof is often local-only.

---

## ADR-011 - Phase-gated hardening with written evidence

**Status:** Accepted
**Evidence:** `docs/production/phase-0` through `phase-1`,
root `PHASE_*.md`, Git commit chain from `a6455e25` to `b72d04c5`

**Context.** Earlier work produced false greens and undocumented regressions.

**Decision.** Work in narrow phases with an explicit starting HEAD, scope,
non-actions, tests, CI runs, and a final report. Preserve historical failures.

**Consequences.**
- Traceable changes and reviewable scope.
- Documentation overhead per phase.
- Phase work must not silently absorb unrelated dirty entries.

---

## ADR-012 - Maintain project memory inside the repository

**Status:** Accepted (this task)
**Date:** 2026-11-08
**Evidence:** `AGENTS.md`, `docs/PROJECT_MASTER.md`, `docs/CURRENT_STATE.md`,
`docs/ARCHITECTURE.md`, `docs/DECISIONS.md`,
`docs/BUGS_AND_LIMITATIONS.md`, `docs/ROADMAP.md`,
`docs/phases/PHASE_TRACKER.md`, `docs/handoffs/`

**Context.** Project knowledge was spread across hundreds of root/phase/audit
documents, and future sessions repeatedly re-derived or contradicted it.

**Decision.** Keep a small, always-current memory layer in `docs/` and a root
`AGENTS.md` that requires every session to read it before implementation and
update it after verified work.

**Consequences.**
- Faster, safer onboarding for humans and AI sessions.
- The memory files must be maintained or they become misleading.
- Historical documents remain authoritative evidence; the new files are the
  index and current truth, not a replacement for evidence.

---

## ADR-013 - The AppContainer grant uses an exact structural whitelist

**Status:** Accepted (Phase 1.3.2)
**Date:** 2026-11-09
**Evidence:** `src/tests/test_security_containment.py`,
`docs/production/phase-1/PHASE_1_3_2_AST_BINDING_HARDENING.md`

**Context.** Per-node validation of assignments and calls still missed aliases,
rebinding, destructuring, walrus assignments, loop/with targets, import and
nested-scope shadowing, and attribute monkeypatching.

**Decision.** Require the exact documented signature and the exact eighteen
statements of `_grant_to_object`, validate the module shape and canonical
bindings, reject protected-name bindings in every function/class scope, reject
protected attribute mutation and `setattr`, and validate every API argument,
both `LocalFree` calls, order, branches and return.

**Consequences.**
- Any unexpected statement or binding form fails closed.
- A legitimate policy change requires updating the expected structure, the
  module constants, and the positive control together.
- The guard remains static AST analysis; the OS sandbox is still the runtime
  boundary.

---

## ADR-014 - Structure layouts and module initialization are exact

**Status:** Accepted (Phase 1.3.3)
**Date:** 2026-11-09
**Evidence:** `src/tests/test_security_containment.py`,
`docs/production/phase-1/PHASE_1_3_3_MODULE_STRUCTURE.md`

**Context.** Header-only class validation and loose DLL initialization checks
left class-body execution, layout tampering and arbitrary module expressions
outside the allowlist.

**Decision.** Record the exact ordered `_fields_` layout of every sandbox
`ctypes.Structure`, require structure classes to contain only that assignment,
allow only `WindowsSandboxManager` as a non-structure module class (docstring
and methods only), and require the exact
`ctypes.WinDLL(...) if sys.platform == "win32" else None` initialization with
`use_last_error=True` and no extra arguments.

**Consequences.**
- Class bodies and module initialization fail closed on any unexpected change.
- Legitimate layout changes require an audited update to the expected map and
  the positive control.
- The guard remains static AST analysis; the OS sandbox is the runtime boundary.

---

## ADR-015 - Module declaration surface is pinned

**Status:** Accepted (Phase 1.3.4)
**Date:** 2026-11-09
**Evidence:** `src/tests/test_security_containment.py`,
`docs/production/phase-1/PHASE_1_3_4_MODULE_DECLARATION_HARDENING.md`

**Context.** Validation of the grant function, structures and DLL loads still
left imports, module-level declarations, the helper signature and manager
methods unconstrained.

**Decision.** Pin an exact 16-entry import manifest, a 62-entry ordered module
declaration manifest (docstring, imports, WinDLL carriers, constants,
structures, state flag, helper, manager), the exact helper signature, the exact
thirteen-method manager manifest, and require all eleven structures to be
present exactly once.

**Consequences.**
- Additional imports, functions, classes, methods or declarations fail closed.
- The manifests duplicate the real module surface; legitimate changes require
  an audited update and a fresh positive control.
- Method bodies remain outside this declaration check; only their signatures and
  decorators are pinned.

---

## ADR-016 - The ACL grant is owned by the validated helper

**Status:** Accepted (Phase 1.3.4R)
**Date:** 2026-11-09
**Evidence:** `src/tests/test_security_containment.py`,
`docs/production/phase-1/PHASE_1_3_4_MODULE_DECLARATION_HARDENING.md` section 13

**Context.** Phase 1.3.4 pinned the helper signature but not its body, and the
grant function was discovered by a whole-tree search. Additional helper
statements or a relocated grant could still be accepted.

**Decision.** Pin the helper's exact eleven-statement body and require exactly
one `_grant_to_object`, as a direct child of
`_ensure_windowstation_desktop_access`. Relocation into manager methods, other
functions, nested scopes, or duplication fails closed.

**Consequences.**
- The helper's early returns, dependency guard, handle acquisition, grant calls,
  state update and return are all structural.
- Any legitimate helper change requires an audited update and a fresh positive
  control.
- Manager method bodies remain outside this narrow declaration check.

---

## ADR-017 - Grant declaration uniqueness counts async functions

**Status:** Accepted (Phase 1.3.4R2)
**Date:** 2026-11-09
**Evidence:** `src/tests/test_security_containment.py`,
`docs/production/phase-1/PHASE_1_3_4_MODULE_DECLARATION_HARDENING.md` section 14

**Context.** The grant uniqueness search counted only `ast.FunctionDef`, so an
additional asynchronous `_grant_to_object` in another scope was invisible.

**Decision.** Count both `ast.FunctionDef` and `ast.AsyncFunctionDef` in the
whole-tree search, require exactly one declaration named `_grant_to_object`, and
require that declaration to be synchronous, helper-owned, and valid under the
existing signature and body checks.

**Consequences.**
- Async duplicates or relocations fail closed.
- The sole grant remains the documented synchronous function.
- Manager method bodies remain outside this narrow declaration check.

---

## ADR-018 - Runtime qualification is separate from static validation

**Status:** Accepted (Phase 1.4)
**Date:** 2026-11-09
**Evidence:** `docs/production/phase-1/PHASE_1_4_WINDOWS_RUNTIME_QUALIFICATION.md`,
`src/tests/test_windows_sandbox_runtime.py`

**Context.** Static AST checks and mocks cannot prove that Windows enforces the
intended sandbox boundary.

**Decision.** Keep a Windows-only runtime harness that observes the real
AppContainer token, Job Object limits, DACL denial, environment sanitization,
termination and cleanup. AppContainer tests are opt-in and monkeypatch the
WindowStation/Desktop ACL helper to a no-op so no machine ACL is changed. Record
unexecuted coverage as NOT RUN rather than mocking a PASS.

**Consequences.**
- Runtime evidence is separated from static guarantees.
- The production ACL-grant branch and network denial remain explicitly
  unproven until a safe elevated/isolated environment exists.
- A confirmed output-cap defect was fixed with a runtime regression test.

---

## ADR-019 - Windows AppContainer never rewrites machine ACLs

**Status:** Accepted (Phase 1.4 final)
**Date:** 2026-11-09
**Evidence:** `docs/production/phase-1/PHASE_1_4_WINDOWS_RUNTIME_QUALIFICATION.md`

**Context.** The production initializer called
`_ensure_windowstation_desktop_access()`, which added ALL APPLICATION PACKAGES
to the current WindowStation/Desktop DACL. That is a machine-level security
change and was not safely qualifiable on this host.

**Decision.** Remove the automatic call. AppContainer launch uses the
environment's existing WindowStation/Desktop permissions; if they are
insufficient, process creation fails closed. The helper remains for explicit,
audited operator provisioning only.

**Consequences.**
- No silent machine ACL modification by the agent runtime.
- Hosts requiring the grant must provision it out of band; otherwise
  AppContainer execution is unavailable.
- Runtime tests replace the helper with a raise-if-called sentinel and pass.

---

## ADR-020 - AppContainer startup fails closed and never silently downgrades

**Status:** Accepted (Phase 1.4 fail-closed correction)
**Date:** 2026-11-09
**Evidence:** `docs/production/phase-1/PHASE_1_4_WINDOWS_RUNTIME_QUALIFICATION.md`
section 16

**Context.** Process creation ignored several security-critical return values,
and AppContainer provisioning failure silently fell back to Job Object-only
execution. Capability reporting also claimed network/low-integrity protections
that the fallback did not provide.

**Decision.** Check attribute-list setup, security-capability/handle-list
updates, Job assignment and resume; never resume after assignment failure; fail
initialization on AppContainer provisioning failure by default. Job Object-only
degradation requires `CRUSOR_ALLOW_JOB_OBJECT_FALLBACK=1`, and capabilities
report the actual backend.

**Consequences.**
- No process executes before AppContainer attributes and Job containment are
  established.
- No silent reduction in isolation.
- Degraded operators see accurate false capability flags.
- Failure-injection tests cover every path without destructive machine changes.

---

## ADR-021 - Renderer architecture pins assert behaviour, not refactor spelling

**Status:** Accepted (Phase 2 r2)

**Context.** Three `test_desktop_renderer_architecture.py` pins froze exact
source strings (`host.submitPrompt(value)`, `this.send({ type: 'prompt'`, the
subagent ternary). The implementation had been refactored to equivalent shapes
(context chips, a typed payload, an early `taskToolCard` return), so the pins
failed while the behaviour was correct.

**Decision.** Assert the contract: prompt submission may carry
`model.contextChips`; the prompt frame is a typed `CrusorClientMethod` with
`type:'prompt'` and `mode:this.mode` followed by `this.send(payload)`; the
subagent family returns through `taskToolCard()` before generic args chips are
built. The real defect (four raw font sizes) stays a hard assertion and now has
its own selector-level regression.

**Consequences.** The suite verifies behaviour without freezing harmless
refactors; a genuinely missing behaviour still fails.

---

## ADR-022 - Cancellation during turn startup is a bounded pending slot

**Status:** Accepted (Phase 2 r2)

**Context.** A Stop sent ~0.9 s after Send returned `accepted=False` because the
turn had been accepted but `turn_controls.begin()` had not run; the prompt still
completed (r1 runtime evidence).

**Decision.** `TurnControlRegistry` keeps one pending slot per session
(`mark_pending` before warm-up/dispatch). `cancel()` on an inactive session
accepts the Stop only while that slot is live (`PENDING_CANCEL_TTL_S = 120 s`);
`begin()` consumes it into `cancel_event`; `_run_turn` emits one cancelled
terminal before any model/echo work. `end()` clears both. A late or expired Stop
is rejected and cannot poison the next turn.

**Consequences.** Startup Stops are honoured without an unbounded queue and
without weakening session identity; the branch is deterministic under
`CRUSORAI_TURN_STARTUP_BARRIER_MS` (bounded test seam).

---

## ADR-023 - Cancelled-before-execution receipts are complete, not degraded

**Status:** Accepted (Phase 2 r2 follow-up)

**Context.** Every cancelled turn painted "Agent Core evidence capture is
degraded. Missing: trace, report." A turn cancelled before any model/tool work
has no trace or report by construction; the warning misdescribed a clean Stop.

**Decision.** When the turn is cancelled, no trace/report exists, no tool
receipts exist, and the reason is a cancellation/echo-seam reason, the coverage
records `not_applicable: [trace, report]` and the receipt is `persisted`.
Executed turns keep the strict missing-artifact check.

**Consequences.** The UI no longer cries wolf on a clean Stop; real monitoring
gaps on executed turns still degrade the receipt.

---

## ADR-024 - The default orchestrator asks the shared ApprovalQueue

**Status:** Accepted (Phase 3.1)

**Context.** Stage 9 of `EngineeringExecutionOrchestrator` called
`grant_approval(..., "APPROVE")` itself, so the default desktop path never
asked a human; the bridge's `safety_reply` resolved a queue the orchestrator
never used.

**Decision.** A new `OrchestratorApprovalGateway` publishes
`tool.approval.request` to the existing `ApprovalQueue`/`event_bus`, waits for
the bridge's `safety_reply` (waking on turn cancellation), validates session and
request, and issues an `APPV-` token bound to task/workspace/path/operation.
The token travels through `model_adapter` to the mutation broker, which verifies
and consumes it. `ask` gates every mutation; session policies auto-allow only
low-risk in-workspace operations; high risk always asks. Headless callers
without `approval_channel` keep the historical supervision path.

**Consequences.** Denial, timeout, cancellation, wrong-session, stale/duplicate
replies and resource mismatches cannot authorize a mutation. Approvals are
requested before code generation, so the dock carries resource/operation but no
file diff body (follow-up).

---

## ADR-025 - Role-correct synthesis for non-source requirements

**Status:** Accepted (Phase 3.2)

**Context.** Product requests beginning with “build” were classified as BUILD
file requirements, and CONFIG/DOC/BUILD requirements with no matching file were
attached to a source (or left unassigned), which rejected the plan. Separately,
the extractor did not treat fix/refactor/clean requests as explicit
requirements, so verification had no requirement evidence.

**Decision.** `requirement_intent` matches build-system nouns only. Necessary
CONFIG/DOC/BUILD requirements receive deterministic role-appropriate targets
(`config/<req>.yaml`, `docs/<req>.md`, `build/<req>.py`) and `detect_file_role`
recognises those directories. The extractor recognises repair/refactor/cleanup
verbs and keeps requests ≥6 characters. Contract validation, coalescing,
optional-suggestion exclusion and dispatch budgets are unchanged.

**Consequences.** Normal product/repair requests produce a valid requirement →
file → work-unit plan with the user's files authoritative; ambiguous
descriptions and conflicting symbols still block; SOURCE/TEST are never
synthesized when the user named a file.

---

## ADR-026 - LangGraph is the one interactive owner; engineering is delegated

**Status:** Accepted and implemented (Agent Runtime Increment 1)

**Context.** Two top-level owners existed: the bridge could run
`EngineeringExecutionOrchestrator` directly or `stream_agent`. That split the
transcript/checkpoint, approval and mutation surfaces.

**Decision.** `stream_agent` is the only interactive turn lifecycle. The graph
classifies chat vs engineering and delegates engineering work through
`engineering_task_node` using `EngineeringTaskRequest → DeliveryContract`.
The orchestrator keeps contract/plan/impact/implementation/verification/repair.
The bridge no longer selects a competing owner; the direct branch was removed
in Increment 3.

**Consequences.** One transcript, checkpoint, cancellation and completion
surface. Engineering work is a graph node, not a second lifecycle. Chat stays
conversational. No environment flag can reactivate the old top-level route.

---

## ADR-027 - One receipt, one model gateway, digest+precondition approvals

**Status:** Accepted and implemented (Agent Runtime Increments 2–3)

**Context.** Context was assembled twice, graph/engineering provider calls were
separate, graph tools bypassed the broker, approvals were path-only and could
be applied to changed bytes/state, and completion/FinOps were reconstructed
from disconnected events.

**Decision.**
1. `ContextEngine.build_engineering_context()` assembles one bounded structured
   bundle; the engine never retrieves its own context.
2. `src/llm/gateway.py` wraps the existing `get_llm`/`RetryLLMProxy` and attaches
   session/turn/task/invocation ids; retry/timeout/cancellation ownership does
   not move.
3. Every supported workspace mutation goes through `WorkspaceMutationBroker`.
   Approval tokens bind task, session, turn, workspace, path, operation,
   proposed-content digest, workspace pre-image, expiry and single use. The
   broker recomputes digest + pre-image before applying.
4. `src/runtime/turn_receipt.py` builds one terminal receipt persisted in the
   LangGraph checkpoint and emitted on `turn_done`.
5. One FinOps invocation ledger per workspace (`.crusorai/finops/
   provider_invocations.jsonl`) records attempts, tokens, latency, known/unknown
   cost and correlation ids, with invocation/task/session/daily reports.
6. Unsupported/opaque tools fail closed; shell execution remains disabled until
   an equivalent sandbox/mutation-capture exists.

**Consequences.** Graph `write_file`/`edit_file` are broker-mediated; denied,
cancelled, stale or replayed approvals do not mutate. One terminal status
(`COMPLETED|FAILED|CANCELLED|DENIED|PARTIAL|NOT_VERIFIED`) is authoritative.
Live provider cost and Electron interactive E2E remain unproven.

---

## ADR-028 - Desktop workbench registers chat routing; panel hash is emitted

**Status:** Accepted and implemented (desktop integration repair, 2026-11-10)

**Context.** The workbench chat contribution injected
`IChatSessionRoutingProviderService`, but the real singleton was side-effect
imported only by the separate sessions app entry, so the Agent pane failed with
`depends on UNKNOWN service chatSessionRoutingProviderService`. Compiling the
workbench also did not update the shipped panel hash consumed by the bridge.

**Decision.** The always-loaded workbench chat contribution imports the real
`sessionRouter/chatSessionRoutingProviderService.js`. After any TypeScript
compile, `node scripts/emit-crusorai-bundle.mjs` regenerates the shipped
`SOURCES_HASH`/manifest and DI bundle before the app is relaunched. Electron
acceptance uses CDP on port **9222** and the real command palette / dock.

**Consequences.** The Agent pane opens and can submit chat/engineering prompts,
show the diff dock, apply broker-mediated writes and display denial/cancellation
receipts. Full `TurnReceipt` field rendering and live-provider qualification
remain open.

---

## Proposed decisions (not implemented)

| ID | Proposal | Why it matters |
|---|---|---|
| P-001 | Wire `IdentityAwareToolAuthorizer` into the live tool path | RBAC exists but is not enforced. |
| P-002 | Add bridge events for architecture/impact/regression/verification artifacts | Desktop cannot render them today. |
| P-003 | Replace `platform.system()` with `os.name == "nt"` in `src/runtime/windows_shell.py` | Removes an import-time process spawn on CPython <= 3.12 and allows 3.11 CI. |
| P-004 | Commit or discard the working-tree mutation-broker wiring | HEAD still bypasses the broker for interactive file tools. |
| P-005 | Unify financial persistence or document the reconciliation contract | Multiple stores can disagree after a crash. |
| P-006 | Re-run and record a full-suite baseline on current HEAD | Historical 25 failures are unresolved. |

Note (2026-11-10): P-004 and P-005 are addressed in the uncommitted working tree
by ADR-027 (broker-mediated writes, one invocation ledger with reservation ids
preserved). They remain uncommitted. P-006 is still open.

## D-2026-11-10-01 — App data vs user workspace

Canonical desktop turns bind a per-workspace application-data root
(`~/.crusorai/workspaces/<hash>`); explicit `CRUSORAI_APP_DATA_ROOT` overrides it
for tests/packaging. Legacy direct callers keep `<workspace>/.crusorai` for
migration compatibility. Internal runtime metadata must never be treated as a
user deliverable.

## D-2026-11-10-02 — Typed agent cards over a parallel event system

Agent cards are a presentation projection of canonical bridge events, not a
second execution stream. The wire carries versioned, schema-validated data; the
renderer re-validates and paints text only. Unknown card types remain visible as
an unsupported indicator and can never crash the pane or execute markup.
