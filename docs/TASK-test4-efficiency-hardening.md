# Test-4 Readiness — Hermes-derived Efficiency and Evidence Hardening

**Date:** 2026-08-14  
**Status:** Implemented and offline-verified; no live provider used  
**Live gate:** Wait for a new API key and the user's Test-4 prompt.

## Why this pass exists

Test 3 proved file delivery and compiler capability but consumed a known minimum of 336,722 tokens / 32 calls across successful phases, needed a focused continuation, and accepted a weak screenshot. The goal is not to blame a model; it is to make deterministic runtime work deterministic and reserve model calls for decisions and repairs.

## Hermes source patterns reviewed

| Hermes source | Value extracted |
|---|---|
| `agent/tool_executor.py` | Tool execution owns bounded concurrency, persistence before UI projection, cancellation, and bounded results |
| `agent/tool_result_classification.py` | Side effects and landed mutations are classified from receipts, not prose |
| `agent/verification_evidence.py` | Passive persistent verification evidence with kind/scope/status |
| `agent/verification_stop.py` | Turn-end policy consumes fresh evidence instead of running arbitrary checks itself |
| `agent/context_compressor.py` | Tool outputs are pruned before structural/LLM compaction; head/tail and tool-pair invariants are protected |
| `agent/context_references.py` | Large context is referenced/expanded deliberately rather than blindly replayed |
| `agent/iteration_budget.py` | Independent, thread-safe hard budgets are runtime state, not prompt suggestions |
| `agent/turn_finalizer.py` | Budget exhaustion is an incomplete/timed-out outcome; finalization must not fabricate success |

## Implemented changes

### 1. Receipt-bound plan completion

`src/agents/planner.py`

- Infers required tool receipts from each plan-step description.
- Multi-copy steps require multiple `copy_file` receipts.
- Browser steps require navigate/snapshot/screenshot receipts.
- A composite `verify_ui_workspace` receipt can satisfy the complete UI contract.
- Failed/near-blank results do not complete steps.
- `finalize_plan()` no longer converts every pending step to completed.

### 2. Aggregate verification domains

`src/graphs/gates.py`

- Evidence is evaluated after the most recent mutation.
- Non-UI code requires a fresh static receipt.
- Rendered UI tasks require all of: static verification, successful navigation, non-empty snapshot, and meaningful screenshot.
- A later typecheck cannot hide missing browser proof.
- Bounded nudge exhaustion no longer changes the final honesty label to PASS.
- Copy-only React component work remains a static integration task unless rendering/preview/UI proof was requested.

### 3. Deterministic one-call UI verification

`src/tools/ui_verification.py`

One model-selected tool call owns:

```text
typecheck → start server → wait for readiness → navigate → snapshot
→ screenshot-quality analysis → stop server → structured receipt
```

This replaces 5–8 model-supervised mechanical turns. Individual browser tools remain available for interactive click/type flows.

### 4. Screenshot-quality gate

`src/tools/visual_quality.py`, `src/tools/browser_mcp.py`

- Measures dominant-color ratio, luminance variance, and edge density.
- Rejects near-uniform/low-detail screenshots.
- A PNG existing is no longer sufficient visual evidence.
- Browser results explicitly say `VISUAL QUALITY PASSED` or `VISUAL QUALITY FAILED`.

### 5. Mutation-aware typecheck cache

`src/tools/file_tools.py`

A successful full typecheck receipt is reused while the verification ledger has no changed paths. Reads and model turns do not rerun the compiler. Any file mutation marks the receipt stale and forces a new real check.

### 6. Always-bound tool-result replay

`src/context/compaction.py`, `src/context/summarizer.py`

- Free tool summarization now runs even when raw history fits under the context budget.
- Large file results are no longer re-billed raw on every subsequent call.
- Short multi-line files preserve their actual content; no false “shown in full above” placeholder replaces the only copy.

### 7. Hard token budget

`src/graphs/budget.py`, `src/graphs/chat_graph.py`

- `AGENT_TOKEN_BUDGET` defaults to 120,000 known tokens per run.
- `0` disables the cap; values are bounded.
- The existing iteration grace path now activates on either iteration or token exhaustion.
- Budget exhaustion can produce an honest partial summary but cannot fabricate evidence.

### 8. Focused tool waist

`src/tools/toolsets.py`, `src/prompts/planner_prompt.py`

- UI profiles expose `verify_ui_workspace` with `scaffold_nextjs`.
- Planner guidance prefers one deterministic UI receipt.
- Scope remains general-purpose; this is capability profiling, not a coding-only router.

## Offline verification

README-equivalent selection:

```text
601 passed, 1 upstream warning
```

Command shape:

```bash
python -m pytest src/tests -q --no-header \
  --ignore=src/tests/test_session_engines.py \
  --basetemp=/home/user/pytest-pulse-test4-ready
```

Focused receipt/compaction/gate/toolset tests also pass. New behavior contracts live in `src/tests/test_efficiency_receipts.py`.

## Test-4 targets

| Metric | Hard target |
|---|---:|
| Provider calls | ≤ 12 |
| Known total tokens | ≤ 100,000 preferred; 120,000 hard runtime cap |
| Wall time | ≤ 180 seconds unless the task itself requires a longer external operation |
| Human/evaluator intervention | 0 |
| Run shape | One uninterrupted run |
| Named artifacts | Present and independently checked |
| Static verification | Fresh passed receipt |
| UI proof, when requested | Non-empty snapshot + screenshot quality PASS |
| Final status | Derived from evidence, never process exit alone |

## Remaining caveats before live Test 4

- A live run is still required to measure the actual prompt/call reduction; offline tests prove behavior contracts, not provider latency.
- Browser dependencies must be present in the live environment. A missing browser must produce `Unavailable`, not PASS.
- The default 120K token cap is a safety ceiling. Test-4 harness should set `AGENT_TOKEN_BUDGET=100000` if the user wants the stricter benchmark target.
- No API credential is stored in the repository.
