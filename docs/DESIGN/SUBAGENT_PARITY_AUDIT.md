# Sub-agent parity audit — Crusor vs OpenCode (A–Z)

Founder-requested, 2026-10-15. OpenCode studied at upstream v2 (`f40dc43`,
v2.0.30): `packages/core/src/tool/plugin/{subagent,question,form}.ts`,
`session/{subagent-job,subagent-completion,session}.ts`, `agent.ts`, and the
client's `session/requests/{session-request-tree,model}.ts` +
`composer/session-composer-region.tsx`. Crusor state includes everything
through this audit's fix build (clarify tree-surfacing + stop cascade).

**Plain-English summary.** A sub-agent is a worker the main agent hires for
one job. OpenCode's whole design is: *a worker is just another conversation*
— same screen, same question popups, same stop button behaviour. Crusor now
matches that core. What remains is depth, not shape: workers can't yet be
re-hired for a follow-up (resume), can't be given a different brain (model
choice), their file-approval popups don't surface in the parent's view,
and they clutter the session list.

## The audit

| # | OpenCode behaviour | Crusor | Status |
|---|---|---|---|
| 1 | Spawn takes `{agent, description, prompt}`; child title = description | `delegate_to_subagent(mode, description, task)`; batch tasks may each be `{task, mode}` | ✅ DONE |
| 2 | Child is a real session (`parentID`), opens live mid-run, same UI as any session | Child runs under its navigable session id, own lineage, durable row, opens mid-run, paints like a parent + nav row at transcript end | ✅ DONE |
| 3 | Workspace/location inherited from parent | Parent workspace passed to every child | ✅ DONE |
| 4 | Child prompt announces "You are a subagent spawned by another session" | Per-mode child persona prompts (research/code/test/review) | ✅ DONE (equivalent) |
| 5 | Depth cap `experimental.subagent_depth` (default 1) | `CRUSORAI_SUBAGENT_DEPTH` env (default 1), store-depth checked | ✅ DONE |
| 6 | Child binds only its agent's tools/permissions | Strict capability waist per mode (research 26 tools vs 67, measured −60% schema tokens/call) | ✅ DONE |
| 7 | Foreground call blocks; result returns as `<task_result sessionID>` | Lifecycle wait + `format_task_output` XML with session id | ✅ DONE |
| 8 | **Question tool works in any session; the ask surfaces in the viewed session's TREE (self, then BFS descendants) as a dock above the composer; the reply routes to the asking session** | Was WRONG (children were silently walked away from asking). **Fixed in this audit's build**: engine gate reverted, service tracks asks by request id tree-wide, tree-picked per render, dock above composer for descendants, in-transcript form for own, reply carries the asker's session id | ✅ DONE (was ❌ WRONG) |
| 9 | Parent **Stop interrupts children** (job cancel + child interrupt; also wakes their pending questions) | Was missing. **Fixed in this audit's build**: delegate registers a turn abort that cancels the child (foreground + batch); proven by `test_subagent_stop_cascade.py` | ✅ DONE (was ❌ MISSING) |
| 10 | Deleting a session cascades to children | `delete_session` removes child rows + checkpoints | ✅ DONE |
| 11 | Background tasks: completion delivered INTO the parent as a synthetic `<subagent>` message; an idle parent resumes | Event → bridge frame → service appends the text to the viewed transcript. No persisted synthetic message; an idle/backgrounded parent is not re-invoked to react | ⚠️ PARTIAL |
| 12 | **Approvals (permissions) from children surface by the same tree rule** | `safety_request` from a child only flags its session-list row `needsInput`; the approval dock answers only the viewed session's own asks | ❌ NOT DONE — next fix (same shape as #8) |
| 13 | **Resume/continue**: passing `sessionID` continues a previous child (may switch agent/model) | No resume argument; every delegation spawns fresh | ❌ NOT DONE |
| 14 | **Model choice**: per-agent model, per-call override (`model` arg) | Children inherit the parent's provider/model verbatim | ❌ NOT DONE |
| 15 | **Open agent registry**: custom agents (own prompt/model/permissions/colour), tool description lists available agents dynamically | Closed 4-mode set (`research/code/test/review`), static tool text | ❌ NOT DONE |
| 16 | Spawn is permission-gated per agent (a parent agent may be denied specific subagents) | Capability waist exists, but no per-agent spawn permission | ❌ NOT DONE |
| 17 | Child header lists **siblings** (other children of the same parent) for quick switching | Child nav row shows parent link + task label only | ❌ NOT DONE |
| 18 | Session list shows only root sessions (children reached via cards) | `list_sessions_rich` has no parent filter — children appear as ordinary rows in the Manager list | ❌ NOT DONE (small fix) |
| 19 | Child view: composer disabled — "return to parent to send" | Child sessions accept prompts (they are full sessions). Different, arguably better; flagged, not changed | ⚠️ DIFFERENT BY DESIGN |
| 20 | Open child view streams tokens live | Checkpoint-polled every 3s + settle hooks (snapshot, not token stream) | ⚠️ KNOWN GAP (accepted for MVP) |

## Recommended order from here

1. **#12 approvals tree-surfacing** — same one-afternoon shape as #8; without
   it a child that wants to write a file stalls invisibly until timeout.
2. **#18 session-list parent filter** — small store/bridge change; keeps the
   Manager list trustworthy as delegation gets common.
3. **#13 resume** — the highest product value: follow-up questions to a
   worker that already has context ("now check the other file too").
4. **#14 model override** — cost lever (cheap model for research children).
5. #15/#16/#17 — registry breadth; post-MVP.

## What this audit changed in code

- `src/tools/clarify_tool.py` — the child walk-away gate reverted; children
  block and ask (300s bound, Stop wakes them via the existing abort wiring).
- `desktop/…/crusorAIRendererService.ts` — `clarifies` map keyed by request
  id (any session), `pickTreeClarify()` (viewed → BFS descendants),
  `replyToClarify` sends the asking session, settle/turn-end retirement.
- `desktop/…/crusorAIRenderer.ts` — descendant questions dock above the
  composer; the viewed session's own question stays in its transcript.
- `src/graphs/chat_graph.py` — Stop cascade for foreground and batch
  delegates (`turn_controls` aborts → child turn cancel).
- Tests: `test_clarify_child_gate.py` (rewritten as block-and-answer),
  `test_subagent_stop_cascade.py` (real delegate→lifecycle chain),
  architecture pins, jsdom harness dock cases (46/46).
