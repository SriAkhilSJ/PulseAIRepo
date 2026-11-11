# Exactly-Once Submission Boundary

## 1. Contract

One logical user submission carries one stable `submission_id` from the
renderer through `session_create` and `prompt`. The bridge's durable ledger is
consulted **before** a session is minted and **before** a turn worker starts.

```text
renderer Enter
   |
   v
submission_id generated (or reused for a pending replay)
   |
   v
session_create{submission_id, workspace}
   |
   v  BridgeServer.handle -> guard -> ledger.record_session (idempotent)
session_info{session_id}
   |
   v
prompt{submission_id, session_id, text}
   |
   v  guard -> ledger.claim_prompt (atomic accepted -> running)
worker starts
   |
   v
turn terminal -> ledger.mark_terminal(completed|failed|cancelled)
```

A replay at any point finds the existing record:

| Record state | Replay result |
| --- | --- |
| `accepted` | same session returned; a second `session_create` never mints |
| `running` | prompt rejected as duplicate; no worker |
| `completed` | prompt rejected; no new turn |
| `failed` / `cancelled` | prompt rejected; a deliberate retry needs a new id |

Different submission ids remain distinct: intentional follow-up prompts are
accepted normally, including in the same session.

**New-session replay rule:** if the target session has no durable row yet and an
identical prompt (same SHA-256) completed in this workspace within
`CRUSORAI_NEW_SESSION_REPLAY_WINDOW_S` (default 60 s), the bridge rejects the
new id as a duplicate. This covers the Live11 shape — a second session with the
same prompt — even if the replay generated a fresh id. The same prompt in an
existing session is allowed as a deliberate repeat.

---

## 2. New module

`src/runtime/submission_ledger.py`

- Durable JSON: `<workspace>/.crusorai/submissions/submissions.json`
  (atomic `os.replace`).
- Append-only audit: `submissions.jsonl` (one event per transition).
- Stores prompt SHA-256, never prompt text.
- `record_session`, `claim_prompt`, `mark_turn_started`, `mark_terminal`,
  `reconcile_running`, `find_recent_completed`.
- Thread-safe (`RLock`); concurrent claims accept exactly one.
- Unreadable ledger fails closed (`SubmissionLedgerError`), never silently
  resets to "no history".

---

## 3. Bridge changes

`src/bridge/__main__.py`

1. **Pre-dispatch guard** (before `_session()` and before any worker):
   - `session_create` with an existing id returns the original
     `session_info{session_id, duplicate_submission: true}`.
   - `prompt` with a running/completed/failed id returns a duplicate ack and
     never starts a worker.
   - A prompt id bound to a different session is refused.
2. **Session creation** binds the id to the minted session before the
   `session_info` reply. Two creates cannot mint two sessions.
3. **Prompt claim** moves `accepted -> running` atomically before dispatch.
4. **Terminal marking** in `_run_turn`'s `finally`: `completed`, `failed`, or
   `cancelled`, with the real `turn_id`.
5. **Queued prompts** carry their submission id (`turn_control.queue(...,
   submission_id=...)`), so a queued turn is still idempotent.
6. **Startup/reconnect reconciliation** turns an orphaned `running` submission
   into `failed` (`process_restart_before_terminal`), so a reconnect cannot
   replay it.
7. **Observability**: `[bridge][submission]` and duplicate acks are emitted to
   stderr/protocol; the ledger JSONL is durable evidence.

### Legacy frames without an id

A pre-fix client may still send no id. Such frames keep legacy behavior, with
one defensive rule: an identical prompt for a **different** session within
`CRUSORAI_SUBMISSION_REPLAY_WINDOW_S` (default 600 s) after a completed one is
refused as a legacy replay. A fixed client always sends an id, so intentional
repeats remain possible.

---

## 4. Renderer changes

`desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIRendererService.ts`

- Generates `sub-<uuid>` (fallback time/random) per logical submission.
- Carries `submission_id` on `session_create` and `prompt`.
- Keeps `pendingSubmissionId` alongside `pendingPrompt`; a duplicate gesture
  while the session is being created replays the **same** id instead of minting
  another.
- Removes the automatic replay of `lastSubmittedPrompt` after a completed turn
  (`retryEngine` only retries a pending prompt or a non-completed turn).
- Ignores a second identical submit within 2 s while a turn is active.
- On `duplicate_submission`, clears the pending state and does not start a turn.
- Surface snapshots carry `pendingSubmissionId` for renderer restore.

`desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAIProtocol.ts`

- `CrusorSessionRequest.submission_id?: string`
- `CrusorSessionInfo.duplicate_submission?: boolean`,
  `submission_state?: string`, `submission_reason?: string`,
  `legacy_replay?: boolean`.

---

## 5. What this prevents

| Failure | Prevention |
| --- | --- |
| One Enter -> two sessions | duplicate `session_create` returns the original session |
| Duplicate IPC delivery -> two turns | `claim_prompt` accepts once |
| Reconnect replays completed submission | terminal state is durable; `running` restart is failed |
| Distinct user actions blocked | distinct ids are independent |
| Title completion creates a submission | title path never sends `session_create`/`prompt`; the guard is on the dispatch boundary |
| Concurrent duplicate requests | atomic ledger lock: one accepted, rest duplicate |

---

## 6. Remaining uncertainty

The exact renderer event that produced the Live11 second session is not recorded
in the preserved evidence. The 9.5-minute `_engine_build` delay is a proven
contributing window, not a proven cause. The repair is deliberately at the
session/turn boundary, so it protects against **any** replay route that reaches
the bridge, including the unknown one.
