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

No Electron session was launched in this preflight; the chain is verified by
the actual source paths above plus the provider-free tests.

## 4. Result

With `CRUSORAI_AUTOTITLE=off`:

- no title provider call is made;
- no auxiliary reservation/settlement is created for titling;
- the synchronous title step is skipped;
- the main turn's terminal event is not held by title generation.

Auxiliary title remains available when enabled, with its own governed
reservation and settlement.
