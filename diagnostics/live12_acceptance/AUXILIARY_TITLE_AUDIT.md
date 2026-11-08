# Auxiliary Title-Generation Audit

## 1. Current path

At the end of a successful turn, `_run_turn` calls:

```text
_maybe_autotitle_session(sid, text, result, wait=True)   # acceptance mode
  -> GovernedProviderGateway.invoke(...)
  -> generate_session_title(...)
  -> store.set_title(...)
  -> self.emit({"type": "session_info", "renamed": true})
       -> BridgeServer.emit()
       -> _engine_build() -> subprocess.run(...)
```

The title call is governed as `subsystem=session_titling`,
`operation_type=auxiliary`:

- `CRUSORAI_AUX_BUDGET_INR` default `0.50`;
- `CRUSORAI_AUX_TOKEN_BUDGET` default `4000`;
- `CRUSORAI_AUX_MAX_TOKENS` default `64`;
- `GovernedProviderGateway` reserves **before** client construction/invoke,
  records usage, calculates cost, and settles exactly once.

In Live11 the title call settled at 461/64 tokens, ₹0.004809. The model returned
no usable text and the bridge used a local fallback; the call was still settled.

---

## 2. Does it block the terminal event?

**Yes, in acceptance mode.** `wait=True` (or any `CRUSORAI_ACCEPTANCE_RUN_ID`)
runs `_run()` synchronously **before** `_finalize_evidence` and `turn_done`.
Inside `_run`, `emit(session_info)` calls `_engine_build()`, which runs a
subprocess with no timeout/cache. In Live11 that subprocess blocked for about
9.5 minutes, holding the first turn's terminal frame.

Outside acceptance mode the title runs on a daemon thread, so it does not block
the caller — but its `emit`/`_engine_build` work can still be slow in the
background.

**Not proven:** that this delay caused Live11's duplicate submission. The
harness recorded one Enter and no second gesture; the delay created a window,
not a demonstrated cause.

---

## 3. Can it create a session or turn?

**No.** The title path never sends `session_create` or `prompt`. It only:

- reads the session row;
- optionally calls the auxiliary provider;
- writes a title (`store.set_title`);
- emits a `session_info` rename ack.

A delayed title can mutate the **title** of a completed session after the turn,
which is intended. It cannot create a new session, turn, reservation, or
submission. It cannot cause an event replay by itself; a slow `session_info`
emit delays the terminal frame and may trip renderer watchdogs.

---

## 4. Timeout / failure behavior

- `generate_session_title()` catches provider exceptions and returns `""`.
- `_maybe_autotitle_session()` catches outer exceptions and logs; the task
  continues.
- If the model returns no usable text, a local title is used; the provider call
  is still settled honestly.
- The unhandled blocking point is `_engine_build()` inside `emit`, not the
  provider call. It has no explicit timeout/cache.

---

## 5. Recommendation (documented, not implemented)

For a clean LIVE12 acceptance, either:

1. Set `CRUSORAI_AUTOTITLE=off` for the run (recommended). This removes the
   title call and the `_engine_build` terminal delay entirely; auxiliary spend
   is then 0.
2. Or bound/cache `_engine_build()` (e.g., compute the build stamp once at
   startup with a short timeout) before a title-enabled acceptance. This is a
   separate reliability fix, not part of this preflight.

If the founder wants the auxiliary title path exercised live, use option 2 and
budget the ₹0.20 auxiliary lane. The title path cannot be claimed as
non-blocking today.
