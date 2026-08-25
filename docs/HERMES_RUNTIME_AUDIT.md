# Pulse vs Hermes: Test-5 Runtime-Layer Audit

**Date:** 2026-08-25  
**Pulse branch:** `arena/01a03741-pulseairepo`  
**Hermes reference:** `NousResearch/hermes-agent@1bbb6e5bce56e721ab685af4cd87df21bbff4d35`

## Verdict

Sarvam was not simply “ignoring Pulse.” Pulse sent Sarvam a request that made
meta-work easier and more strongly reinforced than delivery:

1. a 16,445-character interactive persona told it to think, plan, verify,
   delegate, and default to `execute_code` for multi-step work;
2. dynamic context then told it to start with an overview, explain reasoning
   before acting, and ask clarifying questions;
3. the initial request exposed 33 tools (18,070 schema characters), including
   `think`, `verify`, `execute_code`, process controls, browser controls, and
   delegation;
4. planner calls ran before the action loop;
5. a phase instruction appended as a `system` role *after* the user message;
6. every tool result injected another generic reflect/replan/verify system
   instruction;
7. the execute-code refund and forced-delivery surface allowed inspection to
   avoid the only structural progress mechanism.

The observed `think` and repeated `os.walk` behavior therefore followed the
most repeated and easiest parts of Pulse's effective contract. The provider
transport delivered too many conflicting choices; the loop then rewarded those
choices. Model capability may affect how badly that contract fails, but it is
not an adequate root cause.

No provider-backed retry was used for this audit.

## Exact initial-request comparison

The Test-5 task is 1,223 characters. Deterministic construction of its first
autonomous request now yields:

| Boundary | Failed-attempt architecture | Repaired autonomous request |
|---|---:|---:|
| Main persona | 16,445 chars | 1,234 chars |
| Complete message content | persona plus overlapping context (not durably captured) | 3,084 chars on the Windows runner (2,771 on Linux) |
| Message order | system/context → human → phase system | persona system → phase system → Windows system → human |
| Initial tools | 33 | 1 (`write_file`) |
| Initial tool schemas | 18,070 chars | 591 chars |
| Pre-action planner calls | classifier + generation/validation path | 0 in agent mode |

The repaired Windows runner sequence is:

1. compact autonomous system contract;
2. direct-delivery phase system contract;
3. Windows terminal contract;
4. the unchanged Test-5 human task.

On non-Windows hosts the terminal contract is omitted, producing the measured
three-message / 2,771-character variant.

This is not a benchmark-name special case. Any non-interactive
`workspace_session` task that requires file delivery and starts in an empty
workspace receives the same structural first-action posture.

## Layer-by-layer matrix

| Runtime layer | Hermes behavior | Pulse finding | Repair / disposition |
|---|---|---|---|
| Runtime surface | Headless/kanban guidance is distinct from interactive behavior and explicitly forbids unavailable clarification. | One rich IDE persona was reused for a headless bridge with no live respondent. | Added a compact autonomous persona selected only by `workspace_session`; interactive behavior remains unchanged. |
| System-prompt assembly | Stable/context/volatile system tiers are assembled as a prefix before conversation history. | Runtime phase/platform warnings were appended after the human message. | Runtime system guidance is inserted before the first non-system message. |
| Prompt consistency | Short action enforcement: tool call or final result; model-specific guidance is scoped. | Persona, tone, quality, and progress layers simultaneously requested action, private/meta reasoning, overview prose, clarification, replanning, and verification. | Autonomous context omits duplicate task, empty plan/progress, interactive tone/quality/ambiguity, and empty-workspace map/conventions layers. |
| Task message | User request remains conversation input. | The complete 1,223-character task was repeated in a 2,503-character `CURRENT TASK` system layer and again as the user message. | Autonomous mode keeps the human task once. |
| Model selection | The selected session provider/model owns the loop. | Main-agent cost routing could replace an explicitly supplied provider/model with process-global tiers. Context budgeting always used global `LLM_MODEL`. | Autonomous execution pins the requested provider/model. Session context engines are created/recreated with the request model. |
| Provider transport | Provider adapters normalize provider-specific requests and preserve loop invariants. | Pulse uses LangChain's OpenAI-compatible adapter for Sarvam. This is acceptable for standard tool calls, but the exact outgoing payload was not retained and post-trim telemetry could describe the pre-trim list. | Added post-sanitizer/post-trim complete message+schema snapshots behind `PULSEAI_CAPTURE_REQUEST_PAYLOADS=1`, plus always-on counts, tool names, schema chars, and SHA-256. Fixed telemetry to point at the trimmed list. |
| Tool discovery | Broad capabilities are organized into toolsets; Hermes can defer discovery and backs them with central guardrails. | Long tasks automatically gained delegation; UI terms gained all browser/process tools; four universal meta-tools were always present. Test 5 paid for 33 schemas before any artifact existed. | Autonomous mode excludes meta, delegation, raw process-management, PTC, and raw browser tools. A fresh required-delivery workspace exposes only `write_file`; after a file lands, a focused read/write/run/research/composite-verification set becomes available. |
| Tool-call parsing | Central helper code normalizes calls and validates results. | Pulse already uses LangChain normalization plus `request_sanitizer`, textual-call repair, and `SafeToolNode`; no evidence showed Sarvam calls being dropped. The absence of exact payload evidence prevented proving the request side. | Kept parsing behavior; added snapshots and fingerprints so request versus response parsing can be separated on a future authorized run. |
| Planning | Hermes' primary conversation loop acts directly; planning is model reasoning within that loop rather than multiple mandatory pre-action provider calls. | Pulse's advisory planner could consume classification, generation, validation, correction, and fallback calls before action. | Autonomous `agent` mode bypasses advisory planning. Explicit `plan` mode and interactive planning are preserved. |
| Reflection | Hermes adds targeted guardrail feedback for concrete repeated failures/no-progress. | Pulse injected a generic “take a moment,” proceed/fix/ask/replan, and `verify()` system message after every processed tool result. | Removed generic reflection injection only for autonomous mode; targeted recovery injections remain. |
| Context compression | Hermes rebuilds on compression while preserving a stable prompt and selected model. | Pulse had bounded context and sanitization, but model-specific budgeting could use the wrong global model; request evidence contained only bounded heads. | Context engine now follows the request model; full opt-in request snapshots capture the actual post-trim boundary. |
| Iteration accounting | Hermes has a large parent budget and refunds pure code execution inside strict call/time/output guardrails. | Pulse copied the refund into a 20-provider-call paid harness while forced delivery depended on the refunded counter. | All provider turns count. This repair preceded the current audit and remains in place. |
| No-progress control | Hermes centralizes repeated-failure, idempotent-result, repeated-read, timeout, and output caps. | Pulse's cap originally counted only its iteration field, waited four observations, and still exposed `execute_code`. | Four varied observations now trigger the non-empty-workspace cap; a fresh autonomous empty workspace enters direct delivery immediately; forced delivery exposes no PTC/terminal/read tools. |
| Execution | Hermes tool executor centrally applies before/after guardrails. | Pulse has a safe tool node and approval policy, but too many schemas allowed valid yet useless actions before those guards mattered. | Kept the existing executor/safety architecture; reduced model-visible capability rather than weakening execution safety. |
| Verification | Hermes requires real action/output and has bounded execution tools. | Pulse has stronger task-specific static/UI receipts, but made verification available on an empty project and verbally promoted it after each action. | Empty workspace hides static verification; autonomous initial delivery is structurally first; composite verification returns after delivery. |
| Cancellation | Hermes propagates interrupt/timeout through the active loop. | Attempt 6's manual cancellation produced ambiguous evidence; PowerShell stream redirection also obscured lifecycle behavior. | Prior repair added request abort propagation, durable `operator-cancelled` outcome, no-delivery breaker, and inherited console streams. |
| Startup / memory | Optional subsystems should not perform remote setup during unrelated graph import. | Importing `chat_graph` eagerly constructed `MemoryManager`, which invoked `SentenceTransformer` and repeatedly attempted a Hugging Face download; old session memories could also perturb a fresh benchmark request. | Added thread-safe lazy memory construction. Autonomous context skips historical memory/reflection layers; successful runs can still store memory. Local embeddings are cache-only by default; network download requires explicit `PULSEAI_ALLOW_MODEL_DOWNLOADS=1`. |
| Observability / replay | Hermes logs loop/tool decisions sufficiently to diagnose provider behavior. | Pulse recorded request heads but not complete schemas or exact post-sanitizer payloads. Root-cause work therefore relied too heavily on after-the-fact interpretation. | Guarded runner enables exact request capture. Every request event now reports model, roles/heads, message chars, tool count/names/schema chars, and deterministic fingerprint; captured payloads can be replayed offline. |
| Finish semantics | Hermes disallows intention-only endings and uses task-completion guidance. | Pulse has finish/evidence gates, but they operated after a broad prompt/tool loop could consume the paid budget without a file. | Gates remain; direct-delivery entry and the 12-request no-file breaker move enforcement to the first boundary. |

## Confirmed causal chain for attempts 5–6

The chain supported by code and preserved attempt evidence is:

1. Test 5 was classified as a long, complex UI task.
2. Complexity and UI terms expanded the capability profile to browser,
   execution, verification, and delegation.
3. Universal meta-tools expanded it further.
4. The full persona explicitly promoted `think` and `execute_code`; context
   promoted overview/reasoning/replanning/verification.
5. Planner/provider calls consumed budget before direct execution.
6. Sarvam selected valid exposed meta/inspection actions.
7. `execute_code` ran repeated `os.walk` inspections successfully.
8. Those turns were refunded, while forced delivery depended on the refunded
   counter and still exposed `execute_code`.
9. Zero file mutations landed before the external call cap/manual cancellation.

Steps 4–8 explain both why Sarvam chose the observed actions and why Pulse's
runtime failed to correct them. The prior accounting repair fixed steps 7–8;
the current repairs fix steps 2–6 at the request-construction boundary.

## Deterministic validation contract

The new tests prove:

- graph import does not construct the embedding backend;
- lazy-memory failure is attempted once and degrades to empty/no-op behavior;
- the autonomous persona is under 2,000 characters and contains none of the
  hidden meta-tool directives;
- an empty autonomous delivery workspace exposes only `write_file` on the
  first provider decision;
- the initial message order is an all-system prefix followed by exactly one
  human task (including the Windows-specific four-message sequence) and
  contains none of the conflicting style instructions;
- full request snapshots preserve messages and schemas deterministically.

A future provider-backed attempt must not be authorized merely because these
unit contracts pass. First inspect the captured first-request payload and
confirm the expected 3-message/1-tool shape. PR #9 remains unmergeable until a
separately authorized run passes runtime and independent product grading.
