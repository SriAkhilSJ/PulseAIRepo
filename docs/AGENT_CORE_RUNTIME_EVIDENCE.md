# Agent Core Runtime Evidence

Agent Core now captures one machine-verifiable evidence manifest for every bridge turn. The capture is automatic and originates at the bridge lifecycle boundary; it is not assembled from a later narrative.

## Scope

Each manifest declares:

```json
{
  "kind": "agent_core_runtime",
  "desktop_capture": false,
  "synthetic_desktop_evidence": false
}
```

This proves runtime behavior. It does **not** claim to be a desktop screenshot, rendered UI receipt, or engine-log capture. Desktop acceptance evidence remains a separate desktop-agent responsibility.

## Location

By default:

```text
$CRUSORAI_HOME/evidence/turns/<session-id>/<turn-id>.json
$CRUSORAI_HOME/evidence/turns/<session-id>/<turn-id>.json.sha256
$CRUSORAI_HOME/evidence/turns/<session-id>/<turn-id>.artifacts/
```

`CRUSORAI_HOME` defaults to `~/.crusorai`. `CRUSORAI_EVIDENCE_DIR` can override only the evidence root. Manifest, checksum, trace snapshot, and report snapshot are written atomically. Artifact entries include a manifest-relative path so a copied session evidence directory remains verifiable; use `--journal` when the SQLite snapshot is relocated. Evidence files use owner-only permissions where the operating system supports them.

## CI bridge-run publication

The durable runtime manifest above and the headless bridge runner's `outcome.json` are complementary receipts. `scripts/run_bridge_turn.py` records bounded request and tool timing summaries for a controlled run. When `GITHUB_ACTIONS=true`, it now publishes that sanitized outcome as multiple standalone JSON notices rather than one oversized annotation:

- one allowlisted summary annotation;
- one or more request-receipt annotations; and
- one or more tool-outcome annotations.

Each message is capped at 3,500 characters, below GitHub's observed 4,096-character truncation boundary. Every chunk is independently parseable. Tool arguments, prompts, commands, file bodies, IDs, and full results are omitted; result summaries and configured secret values are redacted and bounded again before publication.

This publication path does not replace the manifest/checksum verifier and does not turn monitoring into completion evidence. It exists so a failed bounded run remains diagnosable when an Actions log archive is unavailable. The chunk builder is provider-free tested; retrieval of the new multi-annotation shape still needs observation in a future explicitly authorized Actions run.

## What is bound

A finalized manifest binds:

- session, runtime-session, lineage-root, workspace, and turn identities;
- runtime instance and process identity, which distinguishes a restart from a fresh turn;
- repository commit, dirty-worktree content fingerprint, renderer build commit, renderer source hash, and source/emitted UI stamps (the worktree fingerprint binds tracked output bytes and is explicitly unavailable, never partial, if its bounded probe cannot cover every byte); a dirty tree may record a non-ancestor renderer commit as an explicit fact only when the worktree fingerprint, renderer source hash, and emitted stamp are exact;
- prompt and final-message SHA-256 plus byte length, without persisting their raw bodies;
- durable journal sequence, event type counts, full session-chain verification, and exact terminal-event hash;
- each tool call's intent/result sequence and pairing status;
- versioned verification transitions from the same turn;
- an immutable, privacy-filtered trace slice containing only rows appended during this turn;
- an immutable, privacy-filtered performance-report snapshot;
- explicit missing-artifact and monitoring-degradation fields.

The journal enforces one `turn.started` and first-writer-wins terminal state per turn. Terminal states are `completed`, `cancelled`, `failed`, `watchdog`, or `interrupted`. Tool intent/result retries with the same turn-scoped call identity are idempotent. A retry replays the durable result without running the side effect again; an unresolved intent with no result fails closed because the runtime cannot safely infer whether the prior process mutated the workspace.

If a process restarts while a prior manifest is still `in_progress`, the next turn in that session appends `turn.interrupted`, seals the abandoned manifest as degraded, and records the recovery in the new manifest. If a terminal row committed before a crash but the final manifest did not, recovery adopts that existing terminal row instead of inventing another.

## Privacy

Raw prompt, final-answer, and terminal-error text are not written to the manifest or copied evidence artifacts. They are represented by SHA-256 and UTF-8 byte length. Trace snapshotting recursively replaces prompt/final-text fields, and report snapshotting removes the raw `User Ask` field before the artifact is sealed. Tool and verification persistence continues to use Agent Core's recursive sanitizer and tool-body omission rules. The manifest includes safe tool argument shape/path evidence and hashes result text instead of copying it.

Trace and report snapshot sizes are each bounded at 16 MiB. A bound hit is reported as an explicit artifact gap rather than allowing monitoring to consume unbounded memory or delay the turn indefinitely.

## Fail-open behavior

Monitoring cannot fail the user's turn. Capture failure appears as `evidence.status = "degraded"` or `"unavailable"` on the bridge's `turn_started`, `turn_done`, or `turn_failed` frame and remains visible as a desktop monitoring warning. It is never silently upgraded to success.

At the tool boundary, failure to persist a pre-execution intent safely returns a normal tool error without running the unrecordable side effect, so the agent loop can continue. If result persistence fails after a tool already ran, Agent Core returns the truthful tool result, emits a degraded-monitoring event, and leaves the unmatched durable intent visible for verification; it does not misreport the real execution as a tool failure. Retries of that unresolved intent remain fail-closed.

## Verify a receipt

```bash
python scripts/verify_runtime_evidence.py \
  "$CRUSORAI_HOME/evidence/turns/<session-id>/<turn-id>.json"
```

The verifier independently checks:

- manifest sidecar checksum;
- immutable artifact location, size, and SHA-256;
- the complete session journal hash chain through a read-only, query-only SQLite connection (verification does not migrate or rewrite the journal);
- exact turn event counts and types;
- exactly one start and one terminal row;
- terminal sequence, type, lifecycle flags, and event hash;
- trace/report verdict consistency with the authoritative terminal lifecycle;
- verification transition identity/hash;
- tool intent/result pairing.

Integrity-valid but intentionally incomplete turns (for example, a watchdog release before finalization) exit successfully while reporting gaps. To require a fully complete runtime capture:

```bash
python scripts/verify_runtime_evidence.py <manifest.json> --require-complete
```

Exit codes:

- `0`: integrity is valid (and complete when `--require-complete` is used);
- `1`: integrity validation failed;
- `2`: integrity is valid, but strict completeness was requested and not met.
