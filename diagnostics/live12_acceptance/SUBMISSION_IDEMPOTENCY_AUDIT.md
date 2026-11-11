# Submission Idempotency Audit

## 1. Implementation

`src/runtime/submission_ledger.py`

- Durable JSON: `<workspace>/.crusorai/submissions/submissions.json`
- Audit: `submissions.jsonl`
- States: `accepted → running → completed | failed | cancelled`
- Atomic `record_session`, `claim_prompt`, `mark_terminal`, `reconcile_running`
- Thread-safe; 8 concurrent claims accept exactly one
- Stores prompt SHA-256, never prompt text

`src/bridge/__main__.py`

- Guard runs **before** `_session()` mints and **before** a worker starts.
- `session_create` with an existing id returns the original session; a running/
  completed/failed id cannot mint a second session.
- `prompt` claim is atomic; duplicate/running/completed prompt returns a
  duplicate ack and never dispatches.
- Cross-session replay produces an error and no dispatch.
- `_run_turn` writes the terminal submission state in `finally`.
- Queued prompts carry their submission id.
- Startup/reconnect turns `running` into `failed` (no replay).
- A brand-new session repeating a completed prompt within 60 s is rejected even
  with a new id; an existing session may repeat it.

`desktop/.../crusorAIRendererService.ts`

- Generates `sub-<uuid>` per logical submission.
- Carries it on `session_create` and `prompt`.
- Keeps `pendingSubmissionId` with `pendingPrompt` across surface restore.
- Duplicate pending gesture reuses the id; no second session.
- A completed turn is not automatically replayed by `retryEngine`.
- `duplicate_submission` ack is observational; it does not start a turn.

Protocol (`crusorAIProtocol.ts`): `submission_id`, `duplicate_submission`,
`submission_state`, `submission_reason`, `legacy_replay`.

---

## 2. Test evidence

`src/tests/test_live11_repair.py` (25 tests) proves:

- one create + one prompt -> one turn;
- duplicate IPC delivery -> no second worker;
- duplicate create -> same session;
- completed submission cannot be reclaimed;
- reload/restart cannot replay;
- concurrent claims -> exactly one;
- distinct submissions -> distinct turns;
- cross-session replay -> error/no dispatch;
- new-session same-prompt -> rejected;
- existing-session same-prompt -> allowed (deliberate repeat);
- title path has no submission creation route;
- legacy no-id replay is blocked for another session within the window.

The original generation-boundary suite remains 15/15.

---

## 3. The 60-second identical-prompt rule

Behavior:

- If the target session has **no durable row** (a brand-new session) and an
  identical prompt SHA completed in this workspace within
  `CRUSORAI_NEW_SESSION_REPLAY_WINDOW_S` (default 60 s), the bridge rejects the
  new id as a duplicate.
- The same prompt in an **existing** session is allowed.
- A different prompt in a new session is allowed.
- A deliberate repeat in a new session must wait 60 s or change the prompt.

Trade-off: this intentionally covers the Live11 shape (a second session with the
same prompt) even if a replay generated a fresh id. It is deliberately
conservative; it is not a general rate limit. The window is configurable,
observable in the duplicate ack (`submission_reason=new_session_same_prompt`),
and does not silently remove the protection.

---

## 4. Known gaps

- The exact renderer event that emitted Live11's second `session_create` is not
  in the preserved evidence. The boundary fix protects any replay that reaches
  the bridge, independent of route.
- A legacy client that sends no id is protected only by the 600 s
  same-workspace/same-prompt window for a different session; a fixed desktop
  always sends an id.
- `crypto.randomUUID()` falls back to time/random if unavailable.

## 5. Readiness

The exactly-once boundary is implemented, durable and tested. It is ready for a
live single-submission run.
