# P0.6.4 — Desktop Observability & Acceptance Harness

- **Run ID:** `p0_6_4_20261107T133829_e2320e53`
- **Evidence dir:** `C:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\diagnostics\p0_6_4_1\preflight`
- **Git HEAD:** `6bfb6d6d` on `feat/prompt-cache-stabilization`
- **Workspace id:** `ws_655d9f39400133df`
- **Provider dispatches this run:** 0

## Electron lane

- launched: `True`  pid: `9916`
- renderer belongs to Crusor: `True`
- composer `textarea.crusorai-composer-input` count: `1` visible: `True` enabled: `True`
- screenshots: C:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\diagnostics\p0_6_4_1\preflight\screenshots\renderer-workbench.png, C:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\diagnostics\p0_6_4_1\preflight\screenshots\renderer-composer.png
- unhandled errors: 0 / rejections: 0 / console errors: 0

## Bridge lane

- handshake: `crusorai` protocol `2` version `0.2.0-runtime`
- session id: `session-0936830f55494fd1accf0a3deb225458`
- exit code: `0`
- validation passed: `True`
- compiled workbench stale vs sources: `False` — [bridge] desktop UI: compiled workbench matches the pulled crusorai sources (sha256) — panel is current

## Governance

- pricing verified: `True` (in $0.05/1M, out $0.20/1M)
- max request cost: INR `0.038657` / USD `0.000418` — fits ₹5.0: `True`
- retry posture: `{'provider': 'custom', 'model': 'z-ai/glm-5.3-flash', 'retry_proxy_class': 'RetryLLMProxy', 'max_attempts': 5, 'inner_client_class': 'ReasoningAwareOpenAI', 'max_retries': 0, 'failover': False}`
- Invariant 7 maintained: `True` (drift: [], undeclared: [])

## Acceptance criteria (P0.6.4 = observability only)

| Criterion | Evidence |
| --- | --- |
| 1. real Electron executable running | VERIFIED |
| 2. actual CDP connection to renderer | VERIFIED |
| 3. composer textarea.crusorai-composer-input located | VERIFIED |
| 4. prompt entered through composer | NOT VERIFIED |
| 5. UI submission action triggered | NOT VERIFIED |
| 6. worker + bridge handled same session | VERIFIED |
| 7. provider request belongs to same turn | NOT VERIFIED |
| 8. artifact belongs to same execution | NOT VERIFIED |
| 9. final response rendered in panel | NOT VERIFIED |
| 10. renderer console: zero unhandled exceptions | VERIFIED |
