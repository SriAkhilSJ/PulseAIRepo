# Phase 2D — Outside-Workspace Access With Permission (Design)

**Status:** IMPLEMENTED — reads and writes outside the workspace, both behind one
turn-scoped human grant and the existing diff approval. Uncommitted.
**Date:** 2026-11-12
**Why:** Phase 2A deliberately blocks every path outside the session workspace. A
human who says "use the folder next to this project" gets a hard error, with no
way to grant access. Other coding agents ask; Crusor currently does not.

---

## 1. What the user should see (plain language)

```
Crusor: I need to read C:\Projects\shared-lib to continue.
        [ Allow once ]  [ Allow for this task ]  [ Deny ]
```

- The prompt names the **exact folder or file**, why it is needed, and whether
  it is read-only or will also be written.
- Deny is always available and is the default if the prompt is dismissed or
  times out.
- If the user denies, the agent says plainly that it cannot continue without
  that access — it does not silently work around it.

This reuses the existing approval card/dock (the same one that asks before a
file write). No new screen, no layout change.

## 2. Rules (non-negotiable)

1. **Deny by default.** Nothing outside the workspace is readable or writable
   without an explicit human decision in this turn.
2. **Ask only when the request names or clearly points at an outside path.**
   The agent never goes looking outside the workspace on its own, and never
   infers permission from prose ("you can use anything you need" is not a
   grant).
3. **Path-exact grants.** Allowing `C:\Projects\shared-lib` does not allow
   `C:\Projects` or `C:\`. A file request grants that file only.
4. **Read vs write are separate.** A read grant never authorises a mutation.
   Writes still require the normal diff-bound approval at mutation time (two
   gates, not one).
5. **Turn-scoped.** A grant dies when the turn ends. Nothing is remembered
   across turns, sessions or app restarts.
6. **Known-sensitive paths stay blocked even with a grant**: `.ssh`, `.aws`,
   `.gnupg`, `.env*`, credential stores, and anything the existing
   `PathSafetyValidator` classifies as sensitive.
7. **Symlinks are re-checked after the grant.** A link inside the granted
   folder that resolves outside it is still refused.
8. **Auditable.** Request, decision, scope, expiry and every access under a
   grant are journalled and appear in the TurnReceipt. No hidden widening.

## 3. Technical design

### 3.1 Ask, then retry (no silent fallback)

`WorkspaceDiscovery._resolve` currently raises `WorkspaceBoundaryError`
(`path_rejected`). The change:

- when the caller supplied a path that resolves outside the root **and** the
  operation is allowed to request escalation, return a typed
  `AccessRequest(path, operation, reason)` instead of a plain rejection;
- traversal tricks (`..`, symlink escapes, device names, NUL, ADS) are still
  hard rejections — they never become prompts.

The orchestrator turns the first `AccessRequest` for a path into **one**
approval request through the existing `OrchestratorApprovalGateway` / shared
`ApprovalQueue` (same event, `name="workspace.access"`, arguments carrying
`path`, `operation`, `reason`). No second approval system.

### 3.2 Grant object

```
WorkspaceAccessGrant(
    path        = absolute, canonical path (file or directory),
    operation   = "read" | "write",
    scope       = "once" | "turn",
    granted_at  = monotonic timestamp,
    expires_at  = turn end,
    approval_id = the gateway's receipt id,
)
```

Held on the orchestrator for the current turn only; passed into
`WorkspaceDiscovery` and into the contract validator. Matching is
**exact-or-descendant of a granted directory**, case-insensitive on Windows,
and re-validated after resolving symlinks.

### 3.3 Where it plugs in

| Layer | Change |
|---|---|
| `src/workspace/discovery.py` | `AccessRequest` result type; grants list; per-path grant check; sensitive-name block still wins |
| `src/orchestration/orchestrator.py` | ask once per path, store grants for the turn, retry the discovery step, journal every event, revoke at turn end |
| `src/orchestration/contract.py` | a target is valid if inside the workspace **or** covered by a read/write grant; otherwise ambiguity/block |
| `src/orchestration/model_adapter.py` | generation prompt states that the target is outside the workspace and is covered by a temporary grant |
| `src/workspace/mutation_broker.py` **unchanged** | writes still go through the broker + diff approval; a write grant only lifts the boundary check |
| Bridge / renderer **unchanged** | the approval event is the existing one; the card shows the human-readable description already supplied |

### 3.4 Journal / receipt

```
WORKSPACE_ACCESS_REQUESTED  {path, operation, reason, task_id, turn_id, tool_call_id}
WORKSPACE_ACCESS_GRANTED    {path, operation, scope, approval_id, expires_at}
WORKSPACE_ACCESS_DENIED     {path, operation, reason}
WORKSPACE_ACCESS_EXPIRED    {path, operation}
```

`DeliveryContract` gains `outside_workspace_access: [{path, operation, scope,
decision}]`. Denials are recorded as limitations, not silent failures.

### 3.5 Cancellation / timeout

Dismissing the prompt, timeout, Stop, or a mismatched reply for the wrong turn
all resolve to deny. The turn continues and reports the blocked step; it does
not retry the prompt in a loop (one ask per path per turn).

## 4. Deterministic tests (no provider)

1. Read inside the workspace still requires no prompt.
2. Outside path + `Allow once` → one read succeeds; a second read of the same
   path in the same turn is refused (scope `once`).
3. Outside path + `Allow for this task` → repeated reads succeed; the grant
   expires at turn end (next turn refused).
4. `Deny` → `path_rejected`, no bytes read, journal has `ACCESS_DENIED`.
5. Grant for `C:\Projects\lib` does not allow `C:\Projects\lib2` or
   `C:\Projects`.
6. Read grant + write attempt → broker still asks for the diff approval; a
   read-only grant refuses the write outright.
7. Symlink inside the granted folder pointing elsewhere → refused.
8. `.ssh` / `.env` requested with a grant → still refused.
9. Traversal (`..`, absolute outside, drive-relative) never becomes a prompt.
10. Cancelled/timeout prompt → deny, no access, no retry loop.
11. Journal + receipt contain the decision and the path; no file contents.
12. Graph-level: `stream_agent` with a scripted approval reply proves the event
    reaches the existing approval path and the turn resumes after `allow`.

## 5. Out of scope

- No persistent/global "always allow" list.
- No folder-wide recursive grants from a file request.
- No network or command-execution permission (that is a separate capability).
- No frontend redesign; if the current approval card cannot render the
  description sensibly, that is a finding to report, not a licence to change UI.
- No change to the Phase 2A default: everything outside stays blocked unless
  the human explicitly allows it in that turn.

## 6. Acceptance criteria

1. A user can point Crusor at one outside file/folder, approve it, and the
   agent actually uses it — with the exact path shown before access.
2. Deny/timeout/cancel leave the workspace untouched and produce an honest
   message plus a journal record.
3. No access path exists that bypasses the prompt (traversal, symlink, absolute
   path, alias).
4. Read grants never authorise writes; writes keep the diff approval.
5. Grants expire at turn end; nothing persists.
6. All tests above pass deterministically; zero paid calls.
7. `docs/BUGS_AND_LIMITATIONS.md` records what is still not covered.

## 7. Risk notes

- **Prompt fatigue vs. safety.** One ask per path, per turn, with a clear path
  and reason; no repeated nagging.
- **Social engineering / prompt injection.** A file or web page can tell the
  model to request `%USERPROFILE%\.ssh`. The human sees the literal path, and
  sensitive names are refused regardless of the answer.
- **Confused deputy.** Grants are checked at the tool boundary, not trusted
  from the model; the model cannot mint a grant.
- **Cost.** Design and tests are provider-free. Implementation is backend-only.

---

## 8. Implementation status (2026-11-12)

### What was built

| Piece | Where |
|---|---|
| Grant model (`read`/`write`, `once`/`turn`, exact-boundary matching, sensitive-name veto) | `src/workspace/access_grants.py` |
| External path resolution + `access_required` result, no traversal prompts | `src/workspace/discovery.py` |
| External context reads (file or bounded folder scan) | `src/workspace/evidence.py` (`add_external_reference`) |
| `workspace.access` approval request through the existing queue/event | `src/orchestration/approval_gateway.py` (`request_access`) |
| Explicit external-path detection, ask, grant, journal, delivery record | `src/orchestration/orchestrator.py` |
| External paths are context only; outside write targets are rejected pre-dispatch | `src/orchestration/contract.py` |
| `outside_workspace_access` in the delivery/receipt | `src/orchestration/models.py` |

### Behaviour

- A request that names an absolute path or a `../` path outside the workspace
  triggers **one** `workspace.access` approval for that exact path (max 2 paths
  per turn).
- `Allow once` → one content read. `Allow for this task` → reads for the rest of
  the turn. Both die at turn end; nothing is persisted.
- Deny / timeout / cancel / no approval channel → the path is never read, the
  turn continues, and the delivery lists the denied path as a limitation.
- Windows drive-relative (`C:foo`), UNC (`//server/share`), `..` inside a tool
  input, NUL, device names and sensitive names (`.ssh`, `.env*`, key stores)
  stay hard rejections — they never become prompts.
- Symlinks are canonicalised before the grant check, so a link inside a granted
  folder that points elsewhere is refused.
- The external file is attached to the plan node as **read-only context**; no
  plan target and no mutation may live outside the workspace.

### Not implemented (honest limits)

- **No delete/rename/copy outside the workspace.** Only create and modify are
  grant-aware; destructive operations stay workspace-only.
- **UI wording.** The approval is emitted on the existing `tool.approval.request`
  event with `name="workspace.access"`; the renderer was not changed (frontend
  out of scope). The card shows the generic path/arguments, not a bespoke
  sentence.
- **Folder grants are shallow-scoped** to the folder the human names; no
  recursive parent grants and no persistence.
- **`Allow once` spends on the first content read or write**, even if that
  operation then fails. Conservative by design.

### Write path (2D-2, same day)

- `WorkspaceMutationBroker` accepts a turn's grants. An absolute path outside
  the workspace is writable only when a **write** grant covers the canonical
  boundary; otherwise the historical `PathSecurityViolation` is raised.
- External writes still require the normal mutation token: the broker refuses
  any outside create/modify that arrives without one. The token binds the exact
  content digest, the pre-image, the session and the turn (same as workspace
  writes). So the human sees the diff and approves it after approving the
  boundary — two gates, not one.
- The gateway and broker canonicalise the path identically (long names,
  resolved symlinks), otherwise the token signature would not match; this was
  a real bug found by the tests.
- The read-only `VerificationAuthority` may inspect a granted external file
  (read-only) so requirement verification can report on it; it never gains
  write authority.
- Grants are installed on the broker and verifier at discovery time and cleared
  in `run_task`'s `finally`; a later turn must ask again.
- `WorkspaceEvidence.external` stays context-only; an external **target** is
  accepted only when the write grant covers it (`extract_contract` /
  `validate_contract_plan`).

### Tests

`src/tests/test_outside_workspace_access.py` — **17 passed**: the 12 read /
approval tests above plus:

- write grant → broker modifies the outside file, ledger records the absolute
  path, content verified on disk;
- read grant → write refused (`PathSecurityViolation`), file unchanged;
- write grant without a mutation token → refused (`MutationAuthorizationError`);
- clearing grants (turn end) → refused;
- orchestrator write turn: prompt "Edit <outside>" → `WORKSPACE_ACCESS_REQUESTED
  (write)` → granted → contract target is the external file → mock generation
  → broker write → `files_changed`/receipts include it → COMPLETED;
- orchestrator read turn still classifies as `read` (no accidental write grant).

Regression: Phase 2A **9 passed**; contract/approval/verification/runtime/
containment **377 passed, 3 skipped**. No paid calls (`mock_mode=True`,
`max_correction_attempts=0`).
