# Pulse Autonomous Agent Strengthening Plan

**Status:** Active, provider-free engineering  
**Last updated:** 2026-08-26  
**Scope:** Preserve Pulse's current architecture, repair reliability first, then connect the strongest relevant capabilities already present in the vendored Code OSS workbench.

## The plan in one minute

Pulse already has two useful halves:

1. the Python agent can plan, edit files, run commands, and enforce completion gates;
2. the desktop contains mature editor intelligence, diagnostics, search, source control, tasks, tests, terminals, debugging, notebooks, remote support, MCP, and extension-contributed tools.

The main weakness is the connection between those halves. Pulse currently declares 29 workbench capability IDs but wires 19 of them. Its Python agent exposes 34 canonical tools, yet most native workbench capabilities cannot be selected through that tool protocol.

We will not solve this by showing every possible tool to the model. That would make requests larger, slower, more confusing, and less safe. Pulse will instead use a **capability broker**: a small searchable index that discovers what is available, checks trust and permissions, and reveals only the few tools relevant to the current task.

Before adding reach, Phase 1 repairs the demonstrated finishing defects. A powerful agent that can incorrectly claim success is worse than a smaller truthful one.

## Design rules that apply to every phase

- **Truth before confidence:** completion requires evidence, not a persuasive final message.
- **Least capability by default:** tools are discovered lazily and granted for the current task/session.
- **No giant prompt catalog:** compact summaries first; full schemas only after selection.
- **One canonical receipt path:** direct, parallel, native, extension, and MCP calls all produce paired start/end events and durable outcomes.
- **Workspace trust is authoritative:** untrusted workspaces cannot silently execute or disclose sensitive information.
- **Secrets stay opaque:** models may refer to a credential handle but do not receive secret values.
- **Provider budgets stay bounded:** Hermes patterns are adapted without copying its effectively unlimited parent-loop budget.
- **Changed-path verification:** verify the affected surface first, then widen only when project rules require it.
- **Graceful degradation:** missing extensions, language servers, MCP servers, remote hosts, or browsers are reported honestly, never treated as PASS.
- **Provider-free development until separately authorized:** unit, integration, fixture, and deterministic desktop tests only.

## What we learned from Hermes

The current Hermes agent provides several strong behavioral patterns worth adapting:

- retain a pending final answer while bounded verification runs;
- treat incomplete provider output as incomplete, especially mid-tool calls;
- classify iteration exhaustion as non-completion rather than success;
- detect changed paths and appropriate verification recipes;
- nudge a model toward verification before stopping;
- compact old tool receipts proactively while preserving structural context;
- state prerequisite and verification expectations explicitly.

Pulse already has stricter bounded spending and a mandatory completion gate. We will preserve those advantages. The goal is not to copy Hermes wholesale, but to combine Hermes's disciplined finishing behavior with Pulse's explicit evidence and safety boundaries.

## What we learned from the vendored Code OSS workbench

A focused review of Copilot's registration is recorded in [How Copilot Is Registered, and What Pulse Should Reuse](PULSE_COPILOT_REGISTRATION_REVIEW.md). Copilot combines core chat infrastructure, a built-in extension, and product-specific authentication/default-agent metadata. Pulse is already correctly registered as a first-party common workbench contribution with a desktop-only engine override; it should consume Code OSS provider registries without adopting Copilot's extension identity or trusted-auth contract.

The repository already includes mature infrastructure for:

- editor context and dirty-buffer awareness;
- symbols, definitions, references, diagnostics, and language services;
- text/file search and repository maps;
- SCM state, diffs, edits, undo, changesets, checkpoints, and review;
- terminal processes, tasks, tests, debugging, and notebooks;
- remote authorities and agent hosts;
- MCP discovery, lifecycle, transports, OAuth, elicitation, prompts, resources, and tools;
- tools contributed by extensions through the language-model tool API;
- dynamic tool search, plugins, model configuration, and telemetry.

Pulse's native workbench adapter already implements a valuable subset: editor context, dirty state, diagnostics, symbols/definitions/references, search, SCM, native edits, terminal, tasks, tests, and workspace trust. The immediate need is a narrow bridge into the Python agent's canonical tool plane, not a second implementation of these facilities.

---

# Phases

## Phase 1 — Build a truthful finisher

### In plain language

Before giving Pulse more instruments, make sure it can tell whether the work is actually finished. This is like teaching a builder to inspect the wiring, open every required door, and test the lights before handing over the keys.

### Why it matters

Attempt 12 served `index.html` with HTTP 200, but that page referenced a missing `src/main.js`. The run also ended with `completed=false`, lacked valid product proof, and had unmatched tool lifecycle events. Those are independent Pulse defects even though provider/model behavior caused most of the latency.

### Engineering work

1. Audit local dependencies referenced by HTML (`src`, `href`, `poster`, and `srcset`) as well as JS/TS imports.
2. Let native HTML/JavaScript projects pass deterministic static prerequisites without pretending TypeScript is installed.
3. Require real browser content/runtime evidence for UI delivery; HTTP 200 alone is only transport readiness.
4. Enter verification mode early enough to finish, not merely after most budget is spent.
5. In verification reserve, prioritize a composite check first; permit inspection/repair after a concrete failure rather than repetitive browsing.
6. Emit durable terminal events for safety denials, approval denials, cancellation, policy denials, exceptions, and successful calls.
7. Preserve a candidate final response while bounded verification runs, but replace it with a truthful unverified verdict if proof fails.
8. Keep `completed=false`, missing integrity, unavailable checks, and HTTP-only evidence out of every PASS classification.
9. Add regressions based directly on Attempt 12 while keeping all historical evidence immutable.

### Exit gate

- Attempt-12 workspace deterministically reports missing `src/main.js`.
- A complete plain HTML/JS fixture can pass static + browser verification without TypeScript.
- A broken plain HTML/JS fixture cannot pass.
- Every admitted or blocked tool start has exactly one terminal outcome.
- Budget exhaustion and incomplete output remain non-completion.
- No provider request is needed for these tests.

### Current progress

Implementation has started:

- HTML local-dependency auditing now covers common loading attributes and URL query/fragment handling.
- Native HTML/JS verification now falls back from an inapplicable TypeScript check to dependency integrity, followed by the existing real-browser proof.
- Autonomous and sub-agent safety denials, plus approval denials, now cross the durable result boundary so the UI receives a terminal error event.
- Cancellation, incomplete-provider tool calls, and phase-policy denials use the same terminal error boundary.
- Verification reserve now exposes checks first instead of more inspection tools; targeted read/edit tools reopen only after a concrete failed receipt identifies what needs repair.
- Attempt-12 and synthetic native-web regressions have been added.

Python syntax and diff checks pass. The focused pytest suite is not yet executed in this workspace because neither `pytest` nor `uv` is installed in the available runtime; that remains an explicit Phase-1 validation item rather than an assumed PASS.

## Phase 2 — Give the agent the editor's senses

### In plain language

Let Pulse see what the editor already sees: the active file, unsaved changes, red error markers, symbol locations, and where a function is used. Today, much of that information is visible to the desktop but not to the agent making decisions.

### Why it matters

Text search alone is guesswork for large projects. Native language intelligence reduces unnecessary reads, edits the right definition, catches unsaved-buffer conflicts, and provides faster feedback than repeatedly running full builds.

### Engineering work

1. Define a versioned bridge envelope for native capability discovery and invocation.
2. Expose a small base set: workspace trust, editor context, dirty buffers, diagnostics, symbols, definitions, references, workspace search, and SCM status.
3. Return compact receipts with result limits, continuation tokens, provenance, and staleness generation.
4. Normalize native errors/unavailability into the same durable tool outcomes as Python tools.
5. Add capability negotiation so older desktop or agent versions degrade safely.
6. Prefer native diagnostics and language services when available; retain Python/text fallbacks.

### Exit gate

A deterministic desktop integration test can discover and invoke each base capability, with correct workspace identity, cancellation, limits, error projection, and no provider request.

## Phase 3 — Give the agent safe hands and proof

### In plain language

After Pulse can see the problem, let it use the editor's existing ways to change and test the project—while keeping undo, approval, and evidence attached.

### Why it matters

Native edits understand dirty files and editor state. Native tasks and tests know the project's configured workflows. Debuggers and notebooks can prove behavior that a shell command cannot. Using those existing facilities is safer and more accurate than rebuilding them in Python.

### Engineering work

1. Bridge native preview diff, bulk edit, undo, tasks, tests, and terminal operations.
2. Add checkpoint-before-mutation and changeset-after-mutation semantics.
3. Add scoped debug operations: start configured session, inspect stopped state, evaluate with approval, stop/cleanup.
4. Add notebook discovery, cell execution, output capture, and kernel cleanup.
5. Build verification recipes from changed paths, diagnostics, project tasks, test providers, and UI requirements.
6. Make every proof receipt identify what ran, where, against which workspace generation, and whether cleanup succeeded.

### Exit gate

Edits are previewable/reversible, task/test/debug/notebook runs are cancellable, stale evidence is rejected after mutation, and completion uses the strongest available relevant proof.

## Phase 4 — Add a dynamic extension and MCP tool marketplace

### In plain language

Instead of handing Pulse a warehouse-sized instruction manual, give it a librarian. Pulse asks what kind of help is available, sees a few relevant choices, and checks out only the tool it needs.

### Why it matters

Installed extensions and MCP servers can add enormous capability, but eagerly placing all schemas in every model request wastes tokens, slows providers, creates name collisions, and increases prompt-injection and data-exposure risk.

### Engineering work

1. Build a compact capability index over:
   - Pulse canonical tools;
   - native workbench capabilities;
   - extension-contributed language-model tools;
   - trusted MCP servers and their tools/resources/prompts.
2. Search by task, language, active editor, changed paths, capability tags, and trust level.
3. Reveal full schemas only for selected candidates and only for the current phase.
4. Namespace tool identities and version schemas to prevent collisions.
5. Enforce workspace trust, server allowlists, extension enablement, OAuth state, and per-call approval.
6. Treat MCP resources/prompts as untrusted external content with provenance and injection boundaries.
7. Limit result size, redact secrets, support cancellation/timeouts, and record durable receipts.
8. Cache discovery by extension/MCP generation and invalidate on install, enablement, server, or trust changes.

### Exit gate

A workspace with many installed tools sends only a compact index plus selected schemas. Unauthorized tools remain undiscoverable or non-invokable. Schema changes, cancellation, server failure, and OAuth denial degrade cleanly.

## Phase 5 — Add specialist workflows, review, and recovery

### In plain language

Turn broad capability into dependable teamwork. Pulse can ask a focused specialist to inspect tests or review a change, while one lead agent remains responsible for the final result.

### Why it matters

Sub-agents help only when work can be separated and their outputs are checked. Unbounded delegation multiplies cost and confusion. Checkpoints and review make autonomy recoverable rather than reckless.

### Engineering work

1. Route language-specific work using installed language providers and project evidence.
2. Keep delegation one level deep, bounded, task-scoped, and capability-scoped.
3. Require the parent to verify sub-agent claims against workspace evidence.
4. Use native changesets/checkpoints for rollback and structured review.
5. Add review findings that link to exact files/ranges and distinguish blocker, warning, and suggestion.
6. Resume interrupted work from durable journal/checkpoint state without replaying completed side effects.

### Exit gate

Delegated work cannot expand its permissions, duplicate side effects, or declare parent completion. A failed review or verification restores/fixes from a known checkpoint.

## Phase 6 — Support remote, repository, and notebook environments

### In plain language

Make Pulse work correctly when the project is not on the local machine—such as a container, remote host, or notebook kernel—without confusing which machine ran a command.

### Why it matters

A command run in the wrong environment can appear successful while changing nothing useful. Remote identity and path mapping must be explicit in every operation and receipt.

### Engineering work

1. Negotiate local versus remote authority and capability ownership.
2. Carry authority, workspace identity, environment, and path mapping in tool receipts.
3. Use relative/browser-safe routing between preview frontend and backend services.
4. Integrate SCM changesets and repository workflows without automatic push/merge permissions.
5. Scope remote secrets and credentials to their owning host/service.
6. Guarantee terminal, task, debug, browser, notebook, and MCP cleanup across disconnects.

### Exit gate

Cross-authority operations cannot silently target the wrong workspace. Disconnect/reconnect preserves truth, cancels or recovers safely, and reports orphaned work.

## Phase 7 — Measure, evaluate, and improve safely

### In plain language

Give Pulse a report card based on what actually happened: how long it waited, what it changed, which checks passed, and whether the delivered product worked.

### Why it matters

A polished explanation can hide a broken product. Evidence-based evaluation prevents regressions and separates provider latency from Pulse runtime overhead.

### Engineering work

1. Maintain provider-free fixtures for completion, HTML/JS integrity, lifecycle pairing, cancellation, safety, dynamic discovery, and stale verification.
2. Split timing into provider queue/generation, Pulse graph, tool execution, desktop bridge, and verification layers.
3. Track useful metrics: first mutation, first verification, repeated observations, repair convergence, unmatched events, stale receipts, completion truth, and cleanup.
4. Add deterministic benchmark gates before any separately authorized live evaluation.
5. Use telemetry for diagnosis and routing—not to silently weaken safety or rewrite policy.
6. Update user-facing README and architecture documentation as each phase becomes real.

### Exit gate

Releases have reproducible provider-free evidence, explicit known limitations, and a truthful separation between transport success, runtime success, verification success, and product acceptance.

---

# Capability broker shape

The broker should expose only a few stable operations to the agent:

1. **discover capabilities** — compact names, summaries, source, trust, availability, and tags;
2. **inspect capability** — fetch one selected schema and permission requirements;
3. **invoke capability** — execute through one durable, cancellable, approval-aware boundary;
4. **read bounded result** — receive a compact receipt and continuation handle when needed.

Selection inputs include the user's task, execution phase, active language/editor, changed paths, diagnostics, workspace trust, configured tasks/tests, and recently failed checks. Selection does **not** include secret values.

The broker must not blindly proxy arbitrary extension or MCP output into privileged prompts. Every result carries source/provenance, content limits, and an untrusted-content marker where applicable.

# Recommended implementation order within the bridge

1. Read-only native context and trust.
2. Diagnostics and language intelligence.
3. Search and SCM state.
4. Previewable native edits, undo, and checkpoints.
5. Tasks, tests, and terminals.
6. Debug and notebooks.
7. Extension tool discovery.
8. MCP discovery and selected invocation.
9. Remote authority support.

This order earns reliability and observability before expanding execution power.

# Explicit non-goals

- No wholesale merge of Hermes, Copilot, agent-host, stale branches, or every extension API.
- No eager dump of every tool schema into every provider request.
- No bypass of existing workspace trust, approval, secret, extension, or MCP policy.
- No claim that an extension's presence means its service is ready.
- No automatic provider fallback, probe, retry, cap increase, PR merge, or branch deletion.
- No modification of historical Attempt-5 through Attempt-12 evidence.

# Delivery tracking

Each phase should land as small reviewable changes with:

- a plain-language behavior statement;
- protocol/schema changes, if any;
- focused provider-free tests;
- security and cancellation tests;
- compatibility/degradation behavior;
- documentation updates;
- an explicit list of checks run and checks not run.

The phases are sequential in safety dependency, but discovery research for later phases can continue while Phase 1 regressions are being hardened. Implementation should not move mutating extension/MCP invocation ahead of trust, lifecycle, and evidence foundations.
