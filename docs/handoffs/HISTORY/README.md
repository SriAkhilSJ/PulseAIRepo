# Handoff History

This directory archives superseded `LATEST_HANDOFF.md` files.

## Convention

1. When a new handoff supersedes the current one, copy the old
   `docs/handoffs/LATEST_HANDOFF.md` here as:
   `YYYY-MM-DD_<phase-or-topic>.md`
2. Keep the archive file immutable. Corrections belong in the new handoff or in
   `docs/CURRENT_STATE.md`, not in history.
3. Replace `LATEST_HANDOFF.md` with the new handoff.
4. Add a one-line entry to the index below.

## Index

| Date | Topic | File |
|---|---|---|
| 2026-11-08 | Phase 1.3.1 closeout and memory-system bootstrap | `HISTORY/` archive pending |
| 2026-11-09 | Phase 3.2 planner/contract closeout | `2026-11-09_phase-3.2-closeout.md` |
| 2026-11-10 | Agent Runtime Increments 1–3 | `2026-11-10_agent-runtime-increments.md` |
| 2026-11-11 | Agentic progress + plan outcome semantics | `2026-11-12_pre-reconciliation.md` (snapshot) |
| 2026-11-12 | Engineering audit + memory reconciliation | `2026-11-12_p1a-pre.md` (snapshot) |
| 2026-11-12 | P1-A test isolation repair (current) | current `LATEST_HANDOFF.md` |

## What belongs here

- The exact state at a handoff boundary.
- Commit SHAs, CI run IDs, test counts, and known failures.
- Open questions and the next recommended task.

## What does not belong here

- Secrets, API keys, credentials, or provider tokens.
- Speculation about unverified behaviour.
- Edits to historical records.
