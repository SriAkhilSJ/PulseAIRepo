# P0.6.4 — Desktop Observability & Acceptance Harness

- **Run ID:** `p0_6_4_20261107T123023_23db66e0`
- **Evidence dir:** `C:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\diagnostics\p0_6_4`
- **Git HEAD:** `6bfb6d6d` on `feat/prompt-cache-stabilization`
- **Workspace id:** `ws_6c522e8ae59962ba`
- **Provider dispatches this run:** 0

## Electron lane

- launched: `True`  pid: `2404`
- renderer belongs to Crusor: `None`
- composer `textarea.crusorai-composer-input` count: `None` visible: `None` enabled: `None`
- screenshots: (none)
- unhandled errors: None / rejections: None / console errors: None

## Bridge lane

- handshake: `crusorai` protocol `2` version `0.2.0-runtime`
- session id: `session-953a605fa45b4c72bd6e489ec655e437`
- exit code: `0`
- validation passed: `True`

## Governance

- pricing verified: `True` (in $0.05/1M, out $0.20/1M)
- max request cost: INR `0.038657` / USD `0.000418` — fits ₹5.0: `True`
- retry posture: `{'provider': 'custom', 'model': 'z-ai/glm-5.3-flash', 'retry_proxy_class': 'RetryLLMProxy', 'max_attempts': 5, 'inner_client_class': 'ReasoningAwareOpenAI', 'max_retries': 0, 'failover': False}`
- Invariant 7 maintained: `True` (drift: [], undeclared: [])

## Acceptance criteria (P0.6.4 = observability only)

| Criterion | Evidence |
| --- | --- |
| 1. real Electron executable running | PARTIALLY VERIFIED |
| 2. actual CDP connection to renderer | NOT VERIFIED |
| 3. composer textarea.crusorai-composer-input located | NOT VERIFIED |
| 4. prompt entered through composer | NOT VERIFIED |
| 5. UI submission action triggered | NOT VERIFIED |
| 6. worker + bridge handled same session | PARTIALLY VERIFIED |
| 7. provider request belongs to same turn | NOT VERIFIED |
| 8. artifact belongs to same execution | NOT VERIFIED |
| 9. final response rendered in panel | NOT VERIFIED |
| 10. renderer console: zero unhandled exceptions | NOT VERIFIED |

## Errors

- desktop lane: LaunchError: no listener appeared on 127.0.0.1:9333 within 150.0s (last=[])
