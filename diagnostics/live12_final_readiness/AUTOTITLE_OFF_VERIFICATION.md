# Autotitle-Off Verification

## 1. Required configuration

```powershell
$env:CRUSORAI_AUTOTITLE = "off"
```

Set before Electron launch. The harness does not add this key to its
`build_acceptance_env`, so the parent environment survives into the child.

## 2. Chain

| Hop | Code | Behavior |
|---|---|---|
| Harness | `benchmarks/.../desktop_launcher.py` `launch_app` | `env = dict(os.environ)`; `extra_env` does not contain `CRUSORAI_AUTOTITLE`; parent value survives |
| Electron utility process | VS Code utility-process service | inherits the Electron process environment |
| Worker | `desktop/.../node/crusorAIWorkerProcessService.ts:158` | `env: { ...process.env, PYTHONUNBUFFERED: '1' }` preserves `CRUSORAI_AUTOTITLE` |
| Python bridge | child `python -m src.bridge` | inherits the worker environment |
| Dotenv | `src/config/settings.py` | `load_dotenv(..., override=False)` in all three loads; exported env wins |
| Gate | `BridgeServer._auxiliary_llm_allowed()` | reads `CRUSORAI_AUTOTITLE` at call time; `off/0/false/no` returns `False` |
| Title path | `_maybe_autotitle_session()` | returns before `_durable_store()` and before `GovernedProviderGateway` |

## 3. Tests

`src/tests/test_live12_readiness.py`:

- `test_acceptance_env_does_not_override_autotitle`: `build_acceptance_env`
  does not add the key and the exported value remains `off`.
- `test_off_disables_auxiliary`: `_auxiliary_llm_allowed()` is `False` for
  `off`, `True` for `on`.
- `test_off_returns_before_store_or_provider`: with the store raising if
  touched, `_maybe_autotitle_session()` returns silently under `off`.
- `test_harness_and_bridge_agree_on_off_values`: the harness helper and the
  bridge gate accept exactly `0/off/false/no` (case/space insensitive).
- `test_auxiliary_wait_is_skipped_when_titling_disabled`: the 90 s auxiliary
  wait returns immediately with `skipped=auxiliary_disabled`.
- `test_title_off_with_zero_title_calls_passes`: a titling-off verdict passes
  with zero `session_titling` records and an empty session title.
- `test_title_off_with_a_title_call_fails`: any `session_titling` record fails
  the titling-off verdict.
- `test_title_enabled_still_requires_a_settled_title_call`: the original
  titling-enabled requirement is unchanged.

## 5. Harness classification (the LIVE12 blocker)

Live11 acceptance required a settled title call and a non-empty session title.
With titling disabled, both are impossible, so even a perfect run returned
`P0.6.9_ACCEPTANCE_FAILED`. That contradiction is removed in the harness,
**without weakening the acceptance**:

- the titling-off flag is captured at finalisation in `state.autotitle`;
- the run passes only if `len(session_titling records) == 0` — a title call is
  treated as an unauthorized auxiliary dispatch and fails;
- the empty session title is expected and is not a failure;
- the auxiliary accounting wait is skipped (no 90 s burn);
- titling-enabled runs keep the original settled-title gate.

The gate inputs are recorded in `state.auxiliary_gate`.

## 6. Result

With `CRUSORAI_AUTOTITLE=off`:

- no title provider call is made;
- no auxiliary reservation/settlement is created for titling;
- the synchronous title step is skipped;
- the main turn's terminal event is not held by title generation.

Auxiliary title remains available when enabled, with its own governed
reservation and settlement.
