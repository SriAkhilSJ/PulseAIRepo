# Phase 2 desktop remediation r2 — verdict

**Verdict: `DESKTOP_PARTIAL`**

The bounded remediation shipped and the targeted defects that could be fixed in
the desktop layer are fixed and proven:

- the four renderer-architecture failures are reconciled with semantic tests;
- the typography contract is restored;
- the approval dock fits the default 299 px pane (0 px overflow);
- the startup cancellation race is fixed, unit-tested and re-proven at runtime.

Two acceptance items remain unproven, and one new visual defect was found:

- real approval execution and cold durable transcript replay are blocked by a
  **pre-existing Agent Core import defect** (`history_shaper` imports two
  functions that do not exist in `compaction.py`);
- the Crusor pane ignores the built-in light theme.

## Provenance

| Item | Value |
|---|---|
| Branch | `feat/prompt-cache-stabilization` |
| Starting HEAD | `165dc16f321e04037a6bde643c8021d1bc0f9d0b` |
| Origin at start | identical |
| Pre-existing dirty entries | 184; preserved |
| Evidence dir | new (r1 untouched) |

## Commands and results

| Gate | Result |
|---|---|
| Focused suite (5 r1 files + 3 new/related) | **194 passed, 7 skipped, 1 xfailed, exit 0** (`focused-tests.txt`) |
| Protocol generator `--check` | PASS (`protocol-validation.txt`) |
| `npm run typecheck-client` | exit 0 (`typecheck.txt`) |
| `npm run compile-client` | exit 0, 144.33 s (`compile.txt`) |
| `scripts/emit-crusorai-bundle.mjs` | 42 files written, `SOURCES_HASH` = current source hash |
| Security guarded import surface | 1 passed |
| Actual Electron launches | 3 (dark dock, light dock, cancellation/recovery) |
| Worker/bridge handshake | `hello.protocol=2`, exact `workspace.bound` |
| Approval dock at 299 px | overflow 0, all actions visible |
| Startup cancellation (runtime) | accepted=True pending=True, cancelled turn, no completion |
| Warm replay | 6 rows identical, no duplicates |
| Cold transcript replay | NOT EXERCISED |
| Real approval execution | NOT EXERCISED (blocked) |
| Worker restart | one supervised restart, next turn OK |

## First blocking failure

`CRUSORAI_ORCHESTRATOR_ENGINE=legacy` (the real Agent Core graph) fails on the
first ai-node call:

```
ImportError: cannot import name 'compact_assistant_tool_call_arguments'
from 'src.context.compaction'
```

`src/context/history_shaper.py:159-165` imports
`compact_assistant_tool_call_arguments` and `transform_completed_tool_receipts`;
neither exists anywhere in `src` at `165dc16f`, and `git log -S` finds no
implementation. `src/tests/test_eager_history_compaction.py` fails at collection
for the same reason. The bridge's default path (orchestrator) avoids the import
but never receives `approval_channel`/`approval_policy`, so it does not produce a
`safety_request` either.

This is outside the desktop remediation and was not patched. Details:
`approval-execution.txt`, `logs/probe-approve.out.txt`,
`logs/probe-orchestrator-default.out.txt`.

## Findings

Fixed:

1. Renderer tests: prompt submission with context chips, typed prompt payload,
   subagent routing, tokenized typography — now pinned semantically.
2. Four raw `font-size` literals replaced with existing tokens; new selector
   regression.
3. Approval dock: `min-width: 0/width: 100%/box-sizing`, wrapping question and
   verdicts; 299 px measured with 0 overflow and a fully visible `Allow once`.
4. Startup cancellation: single pending slot in `turn_control`, `mark_pending`
   before warm-up/dispatch, consumed by `begin()`, early cancelled terminal
   before any provider/echo work; bounded by a 120 s TTL; deterministic barrier
   seam for tests; 7 unit tests + runtime proof.

Open:

5. **Agent Core graph unusable at HEAD** — missing compaction functions
   (critical, pre-existing, blocks approval and durable replay).
6. **Light theme ignored by the Crusor pane** — black pane on a light workbench
   (medium, visual).
7. **Ctrl/Cmd+L not proven** — OS input injection did not reach the app in this
   session (control chord also ignored); command palette works. Environment
   limitation, not confirmed product defect.
8. Default orchestrator path issues no approval for writes; not qualified.

## Scenario matrix

| Scenario | Result |
|---|---|
| A. Workbench startup | PASS |
| B. Worker/bridge v2 | PASS |
| C. Agent render/states | PASS (light theme FAIL) |
| D. Manager render | PASS |
| E. Approval flow | UI PASS (dock fixed, pairing exact); execution BLOCKED |
| F. Cancellation | PASS (startup race fixed; active path unchanged) |
| G. Replay | warm PASS; cold NOT EXERCISED |
| H. Worker recovery | PASS (single restart) |

## Limitations

1. Real approval execution / mutation proof is blocked by the graph import
   defect; not manufactured with a stub.
2. Cold durable transcript replay is not proven; the echo seam persists a session
   row but no messages.
3. The scripted-model seam (`src/llm/scripted_model.py`) is implemented and
   unit-tested but cannot be exercised end-to-end until the graph imports work.
4. Cancellation of a real provider/tool turn is not exercised.
5. Restart backoff/attempt caps and in-flight crash recovery not measured.
6. Light theme pane defect (above).
7. Ctrl/Cmd+L unproven through a genuine input path.
8. Startup DI/optional-module errors remain (see `visual-findings.md`).
9. `CRUSORAI_TURN_STARTUP_BARRIER_MS` is a bounded test-only seam (≤30 s).

## Evidence hygiene

- Every launch/probe used disposable `USERPROFILE/HOME/HOMEDRIVE/HOMEPATH/
  APPDATA/LOCALAPPDATA`, user-data, extensions and workspace. The real
  `%USERPROFILE%\.crusorai` was not written by isolated runs; the first pytest
  batches (before 10:52) used the ambient profile and may have touched WAL
  metadata only. See `logs/profile-isolation.txt`.
- No credentials or personal paths in committed evidence (placeholders only).
- Generated outputs from the build: `out/.../media/crusorAI.css`,
  `SOURCES_HASH`, `SOURCES_MANIFEST.json`, `BUILD_INFO.json` are included because
  the shipped-panel hash test requires them; the 18 other `out/*.js` entries
  with stat-only changes have no content diff and are not staged.

## Release decision

`DESKTOP_PARTIAL`. Desktop-layer defects from r1 are resolved and proven; the
qualification cannot be completed until the Agent Core graph import is repaired
and the pane honours the light theme. This is not whole-product production
readiness.
