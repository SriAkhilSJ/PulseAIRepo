# Product Quality & Streaming UI Evidence (2026-11-10)

Starting HEAD: `604605b2a02b3b1b6960f7959f4c122aeeed8bd4`
Branch: `feat/prompt-cache-stabilization` (origin 0/0)
No commits, pushes, resets, stashes or deletions were performed.

## 1. Snapshot and recovery

- Snapshot kept at `C:\Users\Administrator\AppData\Local\Temp\opencode\crusor-snapshot-20261110`.
- Manifest check: **1,671 entries, 0 bad**; manifest sha256 `6e9af58d7b07a55561656e65b0808c14fc5fbd1b1061b61844880ea3f62c903f`.
- Tracked patch sha256 unchanged: `de859f22a3ce8241572aaca403020f13ffb946a4beafd769f7ea543e5400dc55`.
- Recovery rehearsal repeated in a separate temp copy with
  `git archive --format=tar --output=... HEAD` + `git apply --binary` + snapshot overlay.
  Patch exit 0; five representative key files matched the snapshot byte-for-byte
  (`chat_graph.py`, `contract.py`, `test_scope_fidelity.py`, `CURRENT_STATE.md`,
  `chat.contribution.ts`).
- No credentials were read, printed or copied.

## 2. UTF-8 correctness

`src/tests/test_utf8_reliability.py` (4 passed) proves the exact string

```text
Crusor — Build and Ship with Ease 🚀
क्रूसोर — आसान और भरोसेमंद
日本語：開発を加速する
“Quotes”, ‘apostrophes’, backslash \\ and dash – done.
```

round-trips through the bridge codec, a fake gateway call, the workspace
mutation broker and `file_tools` writes/edits. Assertions compare raw bytes to
`TEXT.encode("utf-8")`, decode back to the exact string, and reject CRLF.

Fixes:
- broker/file-tool atomic writers now use `encoding="utf-8", newline="\n"`.
- protocol frames use `ensure_ascii=False` + UTF-8 encode (already correct;
  now pinned by test).
- Electron acceptance opened `hello.md` and visibly rendered the emoji,
  Devanagari and Japanese line correctly (`07-complete-cards.png`).

Root cause classification: no remaining lossy code-page conversion was found in
the gateway → broker → protocol → renderer path. The earlier mojibake is
consistent with console-side decoding of UTF-8 output (PowerShell code page),
not file corruption; file and protocol bytes are now proven exact.

## 3. Invocation identity

`src/tests/test_invocation_reconciliation.py` (6 passed):
- gateway mints one `inv-...` id and the ledger stores exactly that id;
- reusing an `InvocationContext` produces a new physical id;
- the adapter adopts `gateway_result.context.invocation_id`;
- replaying the same invocation line counts once (cost/tokens/status);
- genuine retries keep distinct ids and count separately;
- the TurnReceipt references the same id and a duplicated line does not
  duplicate the receipt.

`latest_invocations()` collapses append-only replay rows for all reports;
`new_invocation_id()` now uses the canonical `inv-` format.

## 4. Workspace isolation

`src/tests/test_workspace_isolation.py` (1 passed) runs a one-file Markdown
task and asserts the workspace contains only `README.md` + `hello.md`.
Engine state (orchestration, contracts, baselines, diagnostics, FinOps, journal,
test reports, architecture/ADR, requirements, regression) lands under app data.

New canonical helpers: `src/runtime/app_paths.py`
(`app_data_root`, `workspace_app_data_root`, `activate_workspace_app_data`).
Canonical turns bind `~/.crusorai/workspaces/<hash>`; explicit
`CRUSORAI_APP_DATA_ROOT` wins for packaging/tests. Legacy direct callers still
fall back to `<workspace>/.crusorai` for migration compatibility.

Writers redirected: FinOps ledger/recovery/governor, diagnostics/step tracker,
workspace journal/baseline/ledger/broker backups, orchestration contracts/test
reports/persistence, requirements/architecture/ADR, impact/regression
persistence, submission ledger, recovery log drain.

No existing `.crusorai` directory was deleted; user-authored files are untouched.

## 5. Streaming and typed cards

Contract:
- Python: `src/bridge/agent_cards.py` — version 1, nine allowed card types,
  bounded text/diff/items/depth, control-character stripping, prototype-key
  rejection, unknown types returned as `supported=false`.
- Wire: `agent_card` added to Protocol v2 and `protocol_v2.json`.
- Bridge projects canonical frames onto companion cards and emits an immediate
  activity card on `turn_started`, plus delivery card before terminal receipt.
- Renderer: `common/crusorAICards.ts` independently re-validates every card and
  `agentCardView()` paints only text nodes (no innerHTML), with a controlled
  "Unsupported card type" indicator.
- Types: activity, plan, file_change, approval, tool, test_results,
  verification, delivery, cost.
- CSS lives in the existing panel stylesheet and uses theme tokens; narrow
  layouts stack labels; dark/light inherit workbench variables.

Provider-free proof: `src/tests/test_agent_cards.py` (11 passed) and
`scripts/test_crusorai_cards.mjs` (passes under Node type stripping).

## 6. Electron acceptance (genuine app)

`desktop/vscode/scripts/accept-crusorai-streaming.mjs` launches the real
`CrusorAI.exe` with a disposable workspace/user-data dir and the real bridge in
`CRUSORAI_BRIDGE_RUNNER=scripted` mode (fixed fixture, no provider call).

Passing checks: pane opens; activity card before completion; user message and
non-blank panel; incremental token stream; plan card; approval diff card + real
approval dock; approval updates card state; test-results card; VERIFIED
verification card; delivery card; cost card; exact UTF-8 workspace bytes;
cancellation ends truthfully.

Screenshots and `acceptance.json`:
`bench-results/phase-3.3-canonical-runtime/logs/electron-streaming/`.

**Limitation (honest):** reconnect/replay after a renderer reload shows an empty
transcript (`turns=0`). The scripted fixture bypasses the LangGraph checkpointer,
so no durable turn exists to hydrate. This does not prove or disprove production
checkpoint replay; existing Increment 1–3 checkpoint tests remain the evidence
for that path. No mock was added to make this check pass.

## 7. Focused regression results

| Suite | Result |
|---|---|
| UTF-8 + isolation + invocation + cards + scope fidelity | 29 passed |
| Desktop renderer architecture | 118 passed, 1 skipped, 1 xfailed |
| Bridge protocol v2 (after manifest update) | 9 passed |
| Bridge protocol/runtime/orchestrator + Phase 11.6 | 58 passed, 2 failed → fixed → 9/9 protocol; Phase 11.6 44/44 |
| Desktop startup/session/workspace boundary + security containment | 263 passed, 4 skipped |
| Node card contract test | pass |

Classification of the two protocol failures: **new regression** caused by adding
`agent_card` only to Python/TS and not to `protocol_v2.json`. Fixed by updating
the manifest and regenerating the TypeScript contract; no test was weakened.

Pre-existing failures were not reclassified as new. The 3
`test_autonomous_runtime_contract.py` failures noted in the prior report were not
touched.

## 8. Benchmark preparation

- `BENCHMARK_SPEC.md` — ten balanced tasks, metrics, invariants, run protocol,
  comparability rules and evidence layout.
- `EVALUATION_TEMPLATE.md` — per-task/aggregate report template with failure
  classification and claim limits.

No paid calls were made in this phase. The ₹100 authorization remains consumed;
the Velona key was never accessed or printed.

## 9. Remaining limitations

1. Reconnect/replay unproven for the scripted fixture (see §6).
2. Evidence capture reports DEGRADED for the scripted turn (fixture writes no
   trace/report artifacts); production evidence capture is unchanged.
3. The scripted runner is a test seam (`CRUSORAI_BRIDGE_RUNNER=scripted`), not a
   model simulation; it must never be presented as a streamed real response.
4. Live invocation-ID reconciliation remains unverified against the provider
   because no paid call is authorized; the provider-free proof is complete.
5. No cross-agent benchmark has been executed, so no market-superiority claim is
   permitted.
