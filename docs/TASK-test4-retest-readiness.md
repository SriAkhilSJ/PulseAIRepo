# Test-4 Retest Readiness — Phase Enforcement and Provider Freeze Controls

**Date:** 2026-08-14  
**Status:** Implemented and offline-verified before any new key  
**Prior live Test-4 verdict:** FAIL (`lab/REPORT_TEST4_FAIL.md`)

## Hermes review used for this pass

- `agent/tool_guardrails.py`: pure per-turn signatures, no-progress decisions, and hard caps projected by runtime.
- `agent/verify/runner.py`: deterministic build/start/readiness/teardown phases rather than model-supervised mechanics.
- `agent/tool_result_classification.py`: mutations count only when result receipts prove they landed.
- `agent/turn_finalizer.py`: exhausted work remains incomplete; finalization does not manufacture completion.
- `agent/context_compressor.py`: tool results are bounded before expensive compaction.
- `agent/bounded_response.py`: provider I/O must have hard byte/time bounds and fail closed.

## Failure evidence from the first Test 4

- Known successful provider accounting: 14 calls / 123,138 tokens minimum.
- No showcase source file was delivered.
- The initial plan was correct, but execution was allowed to spend calls on boilerplate reads, package inspection, terminal metadata, and `think`.
- Focused large multi-file generations returned no tool response.
- A direct pre-approved-plan request ended in `openai.APITimeoutError`.
- Browser verification was never reached.

## New retest controls

### Phase-specific capability enforcement

`src/runtime/execution_phases.py`

| Phase | Exposed capabilities |
|---|---|
| Setup | scaffold/install/copy only |
| Deliver | write/edit/copy only |
| Static verify | typecheck/test plus targeted read/edit repair |
| Visual verify | composite UI verifier/browser plus targeted repair |
| General | normal focused profile |

The allowlist is enforced twice: at provider tool binding and again at tool execution, so textual tool-call repair cannot bypass it.

### Bounded delivery responses

- Delivery phase injects a direct system instruction: no think/read/list/search/terminal.
- At most two file mutations per response.
- Named multi-file plan steps require one landed receipt per named file.
- Delivery output is capped by `PULSEAI_DELIVERY_MAX_TOKENS` (default 3072, bounded 512–8192).
- This deliberately turns one timeout-prone mega-response into 2–3 bounded source batches.

### Turn-scoped budgets

- `turn_token_usage` is separate from cumulative task analytics.
- Iteration and token safety budgets reset on a real new user turn/continuation.
- Durable resumes no longer inherit an exhausted prior turn while total cost remains visible.

### Pre-approved plan seam

`stream_agent(initial_plan=...)` allows IDE/programmatic callers to provide an already-approved deterministic plan. Ordinary chat behavior is unchanged. This removes the two advisory planner calls when the user/harness has already supplied an exact workflow.

### Provider preflight

`src/llm/preflight.py` sends one redacted two-token readiness request before any benchmark mutation. A timeout/non-success result blocks the benchmark. Keys are never returned or logged.

### Streaming custom-provider option

- `PULSEAI_LLM_STREAMING=1` enables ChatOpenAI streaming for custom providers so active token chunks reset socket read timeout during bounded source generation.
- `PULSEAI_LLM_TIMEOUT` is configurable from 10–300 seconds (default 60).
- Read timeouts remain non-retryable to avoid charging repeated identical requests.

### Deterministic multi-route visual receipt

`verify_ui_routes` uses one server and one browser session for every route. With `required_selector=video`, each route must prove:

- a real `<video>` exists;
- autoplay/muted/loop/playsInline are true;
- media reaches `readyState >= 2` within a bounded wait;
- rendered text is non-empty;
- screenshot visual-quality metrics pass.

## Planned retest shape

```text
provider_preflight
→ seeded approved plan
→ delivery batch 1 (≤2 files / ≤3072 output tokens)
→ delivery batch 2
→ optional delivery batch 3
→ typecheck
→ at most one targeted repair batch
→ one verify_ui_routes receipt for all four pages
→ evidence-derived final status
```

## Retest environment

```env
AGENT_ITERATION_BUDGET=8
AGENT_TOKEN_BUDGET=80000
PULSEAI_PHASE_GUARD=on
PULSEAI_DELIVERY_MAX_TOKENS=3072
PULSEAI_LLM_STREAMING=1
PULSEAI_LLM_TIMEOUT=90
PULSEAI_DISABLE_LONG_TERM_MEMORY=1
SUMMARIZER_LLM=
PROVIDER_SAFE_LIMIT=0   # AUTO: budget = the window the endpoint reports (was 6000, which pinned it regardless)
```

## Retest targets

| Metric | Target |
|---|---:|
| Provider preflight | PASS before workspace creation |
| Successful provider calls | ≤8 |
| Known tokens | ≤80K |
| Wall time | ≤240s |
| Setup inspection calls | 0 after scaffold receipt |
| Source delivery calls | 2–3 |
| Static verification | 1 real pass; one repair cycle maximum |
| Visual verification | 1 composite call, 4/4 routes |
| Screenshots | 4 meaningful captures |
| Human intervention | 0 |
| Final verdict | Derived from receipts only |

## Offline verification

```text
615 passed in 32.38s (final 2026-08-14 verification)
```

Selection matches the README baseline and excludes `src/tests/test_session_engines.py`. New focused contracts cover phase tool filtering, named multi-file receipt counts, turn-scoped token budgets, provider-preflight redaction/fail-closed behavior, pre-approved plans, composite route verification, playback readiness, and screenshot quality.

No new live retest should start until the user provides a fresh key and the readiness probe passes.
