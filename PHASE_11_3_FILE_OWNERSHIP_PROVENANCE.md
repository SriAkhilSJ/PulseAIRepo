# PHASE 11.3 FILE OWNERSHIP & PROVENANCE REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.3 Workspace Discipline & Change Management  

---

## 1. FILE OWNERSHIP LIFECYCLE CATEGORIES

Crusor enforces an explicit, strictly typed 8-state ownership model (`src/workspace/models.py`):

| Category | Description | Protection Level |
|---|---|---|
| `EXISTING_USER_CLEAN` | Clean tracked user file present at baseline | Protected from overwrite/deletion without approval |
| `EXISTING_USER_MODIFIED` | Dirty unstaged user modifications present at baseline | Strictly protected: rollbacks cannot revert |
| `EXISTING_USER_STAGED` | Staged user modifications present at baseline | Strictly protected: rollbacks cannot unstage |
| `EXISTING_USER_UNTRACKED` | Untracked user file present in workspace at baseline | Protected from deletion and destructive overwrite |
| `AGENT_CREATED` | File created by Crusor agent during active task | Tracked in Ledger; eligible for agent rollback |
| `AGENT_MODIFIED` | Existing file modified by Crusor agent during active task | Tracked with pre-image hash; rollback restores baseline |
| `AGENT_DELETED` | File deleted by Crusor agent during active task | Tracked with tombstone and pre-image backup |
| `USER_SUPERSEDED_AGENT` | Agent-created file subsequently modified by user | Lockout: agent cannot roll back or overwrite |

---

## 2. USER SUPERSEDING & CONCURRENCY CONTROLS

If Crusor creates or modifies a file, and the user subsequently edits or modifies that file outside Crusor:
1. `WorkspaceChangeLedger` detects hash disparity compared to the last recorded agent post-image.
2. Ownership transitions immediately to `USER_SUPERSEDED_AGENT`.
3. Agent rollbacks (`rollback_transaction` or `undo`) fail closed, preventing user code loss.
