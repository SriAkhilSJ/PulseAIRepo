# PHASE 11.3 TRANSACTION & CRASH RECOVERY REPORT

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Phase:** 11.3 Workspace Discipline & Change Management  

---

## 1. WORKSPACE JOURNAL MANAGER

`WorkspaceJournalManager` (`src/workspace/journal.py`) provides transactional atomicity across multi-file edits:
- State Machine: `PREPARING` -> `COMMITTED` -> `ROLLING_BACK` -> `ROLLED_BACK` | `ABORTED`.
- Persisted to disk atomically: `.crusorai/tenants/{tenant_id}/journals/{task_id}_journal.json`.
- Backup Storage: Pre-images of modified or deleted files are preserved under `.crusorai/tenants/{tenant_id}/backups/`.

---

## 2. SELECTIVE ROLLBACK & CRASH RECOVERY

In the event of an unhandled exception, task failure, or process crash:
1. `recover_interrupted_transactions()` scans for uncommitted transactions in `PREPARING` state.
2. For each transaction, agent-created files are deleted, and agent-modified files are restored from backup pre-images.
3. **Safety Guarantee:** Before restoring or deleting any file, the journal checks `ledger.is_safe_for_agent_rollback()`. If the file was modified by the user (`USER_SUPERSEDED_AGENT`), rollback skips the file and logs a warning.
