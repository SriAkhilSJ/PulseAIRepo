# Remaining Limitations

This repair is offline-qualified only. No live provider call, Electron run,
benchmark or acceptance was performed.

1. **Exact Live11 duplicate trigger is not proven.** The preserved evidence has
   one Enter, one composer clear, and no second harness action. The second
   session began 0.17 s after `turn.completed`. A queued/replayed renderer
   submission is the leading explanation; the specific renderer event is not in
   the evidence. The fix therefore protects the session/turn boundary itself,
   which is independent of the unknown route.

2. **The 9.5-minute `_engine_build` delay remains.** It is in the title /
   `session_info` path and delayed the first terminal frame. This repair does
   not move `_engine_build` off the critical path; it ensures the delay cannot
   leave financial or submission state silently unresolved. A separate
   performance fix should make `_engine_build` bounded/cached.

3. **Startup sweep is once per workspace, first frame.** A long-lived bridge
   with concurrent sessions in a workspace first seen late could sweep a task
   that is active in the same process. Desktop usage is single-turn per session;
   the risk is documented rather than hidden. A future sweep should filter by
   reservation creation time vs process start.

4. **`financial_call_ledger` is still not populated by the engineering lane.**
   It is a legacy chat/agent table. The engineering authoritative records are
   the task FinOps JSON, `provider_invocations.jsonl`, and canonical
   `financial_reservations`. No dual write was added.

5. **Legacy clients without a submission id** are protected only by the
   same-workspace/same-prompt 600 s replay window. A genuine identical task from
   a legacy client in a new session within that window is refused. The fixed
   desktop always sends an id, so intentional repeats are unaffected.

6. **Restarted `running` submissions become `failed`, not resumed.** A queued
   prompt lost to a bridge restart must be resent; it is not silently replayed.

7. **Renderer's 2-second duplicate guard is UI-only.** It is an additional
   guard, not the authority. The bridge ledger is the authority.

8. **Submission ids use `crypto.randomUUID()` with a time/random fallback.**
   The fallback is unique in practice but not cryptographically guaranteed.

9. **No live acceptance.** Duplicate prevention and orphan reconciliation are
   proven by deterministic tests and simulations, not by a live Electron turn.
   P0.6.9 remains `P0.6.9_ACCEPTANCE_FAILED`; generation recovery remains
   unproven live.

10. **Historical evidence is read-only.** Live9, Live10 and Live11 evidence was
    not modified. The Live11 reservation remains `in_flight` in the historical
    record; the repair describes what the next process will do, not a rewrite of
    the past.

11. **New-session same-prompt cooldown.** An identical prompt in a brand-new
    session within 60 s of a completed submission is rejected as a duplicate,
    even with a new submission id. This is deliberate protection for the Live11
    replay shape; an intentional immediate repeat must wait out the window or
    change the prompt. Existing sessions are unaffected.
