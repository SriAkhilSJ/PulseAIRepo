# Knife #1 clean field baseline — same ask, three fresh sessions (2026-10-22)

Harness: `scripts/run_bridge_turn.py` (headless, desktop-parity cap `--max-input-tokens 600000`,
`--timeout-s 1800`, workspace-contained write auto-approval). Ask: byte-identical to the
founder's delivered desktop run (`session-54fab5…`, extracted unmodified from its trace).
Workspaces: three pristine scaffolds (Next+TS+Tailwind shadcn layout, no node_modules) —
identical build, `bench-results/knife1-baseline-{1,2,3}`.

## Result: 0/3 delivered — deterministic non-completion, cap never approached

| | run A | run B | run C |
|---|---:|---:|---:|
| session | t5-0bc5f3addf | t5-662533a896 | t5-80a7c6f0a9 |
| LLM calls | 5 | 5 | 5 |
| total in / out tokens | 65,114 / 2,190 | 64,296 / 18,927 | 65,135 / 1,125 |
| per-call input (first / avg) | 14,435 / 13,023 | 14,400 / 12,859 | 14,402 / 13,027 |
| tool-schema tokens (anatomy) | 4,182 ✓ | 4,182 ✓ | 4,182 ✓ |
| tool_result tokens (5 calls) | 1,558 | 3,608 | 2,331 |
| llm wall/call | 8.0s | 24.1s | 3.3s |
| 600k cap trip | no (~10%) | no | no |
| verdict | failed (ended_mid_task) | failed | failed |
| files written | **0** | **0** | **0** |

Identical run shape all three times: one exploratory lap (list/read/terminal, no write), then
three consecutive responses with `content_chars=0`, zero tool calls, output tokens 72–90
(reasoning-only). The empty-reply nudge circuit (35deba2c) converged at ~5 calls and the
finalize recorded the honest `failed/end_mid_task`. No safety_requests fired; no errors.

## Read against the founder's decision rule

- **Knife #3 (budget/compression): not indicated.** Individual prompts sit at ~14.4k first /
  ~13.0k average with a 600k cap at ~10% after 5 calls. The cap is nowhere near.
- **But this baseline cannot yet call knife #1 "verified-delivered" desktop-equivalent:**
  the founder's desktop runs on the same ask did deliver (7-step/`video-nature` run), while
  three controlled headless runs consistently loop think/list/read and emit empty finals
  without ever calling `write_file`/`edit_file`. The failure is pre-neighborhood: the model
  never writes rather than the budget or compression killing it.

## Two branch-relevant observations

1. **Empty-final handoff (new):** streamed reasoning (804 frames over 5 calls) with
   `content_chars=0` responses in runs A/C on calls 2–5 — responses consumed ~90 output
   tokens but delivered nothing for the transcript. The loop caps made this honest; the
   root cause (why exploration-only, then nothing) is upstream of the caps.
2. **Non-model wall dominates:** ~700s non-model vs 40–120s model time per run
   (~130–150s of gap per step; the bridge/step transport, finalize, review layers). At a
   ~13k/call diet this overhead, not tokens, is the runtime's slowest leg.

Replication set: `bench-results/knife1-baseline-{1,2,3}/` (frames.jsonl, outcome.json,
bridge_stderr.log) + the ledger's per-call anatomy for the three `t5-*` threads.
