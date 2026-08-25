# Test 5 readiness review

**Reviewed:** 2026-08-25

**Integration branch:** `arena/01a03741-pulseairepo`

**Current verdict:** repaired retest candidate; **no Test-5 pass yet**

## History and merge verdict

The old agent-development branch was not safe to merge wholesale: it predates the current R4 desktop tree and would regress hundreds of vendored Code OSS files. Its useful Test-5 commits were reviewed and selectively integrated instead.

Attempts 1–3 failed. Desktop run `test5-4b` also failed runtime and product verification: Sarvam produced a roughly 30KB `main.js` `write_file` request, but the workspace remained empty and no outcome was written. Therefore **do not merge into `main` and do not delete branches**. A provider-backed attempt 5 must pass both runtime and independent product grading first.

## Attempt-4b root cause and repair

The failure was not caused by the bridge's 1 MiB frame limit; a roughly 30KB payload is well below it. The confirmed deadlock was an approval-policy mismatch:

1. `scripts/run_bridge_turn.py` enabled autonomous writes but did not answer `safety_request` frames.
2. The bridge enabled the approval channel while leaving `stream_agent` at its interactive `ask` policy.
3. `SafeToolNode` queued an ordinary workspace mutation and waited up to 300 seconds for a UI that the headless runner does not have.

The repair preserves interactive behavior while making the benchmark path explicit and fail-safe:

- the guarded runner sets `PULSEAI_BRIDGE_APPROVAL_POLICY=workspace_session`;
- the bridge validates and forwards that policy to `stream_agent`;
- the runner always answers any residual approval frame, auto-approving only warning-free `write_file`, `edit_file`, or `copy_file` operations contained by the run workspace and denying sensitive/escaping/other calls;
- outcome evidence records safety request, approval, and denial counts;
- model guidance applies Hermes' recovery rule: keep individual tool argument payloads below roughly 8K tokens, split naturally modular applications across files, and never repeat a dropped oversized payload unchanged.

No Hermes source was copied. The comparison was performed against NousResearch/hermes-agent commit `e5032945cbebb64b8a819b66ec831c1906297b81`.

## Deterministic regression evidence

The new regression drives a 35KB safe write through the real `SafeToolNode` policy/tool path and proves that the file lands without an approval wait. Separate tests pin bridge policy forwarding and fail-closed headless approval classification.

Focused verification on 2026-08-25:

- new approval/large-write regressions: **3 passed**;
- bridge transport, parallel tools, benchmark harness, prompt guard, and prompt-cache audit selection: **79 passed** with the prompt-size budget green;
- Python diff whitespace check: passed.

The provider-backed product test cannot run in this Arena sandbox because TLS to Sarvam fails. That is why these deterministic checks must precede exactly one guarded desktop attempt.

## How to run attempt 5

Follow `DESKTOP_AGENT_INSTRUCTIONS.md` exactly. Use a fresh workspace and immutable run ID:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_test5_guarded.ps1 `
  -Workspace C:\test5-ws-attempt5 `
  -RunId test5-5
```

Monitor the watchdog every 30 seconds and preserve `bench-results/test5-5/`. A clean harness exit is not a product pass: independently launch and grade the generated raytracer against `scripts/test5_prompt.txt`. Do not rerun, merge, or delete branches after any runtime or product failure.
