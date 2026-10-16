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
matches that core, including the follow-ups: workers can be re-hired with
their context intact (resume), given a cheaper brain (model choice), defined
by you (custom agents), and both their questions AND their permission
requests surface where you're standing.

*Status update, same day: every ❌ below was closed in the "important" build
(`test_subagent_registry_resume.py`, 11 tests; jsdom harness; architecture
pins). Remaining known deltas are the two ⚠️ rows (11 and 20) and #19's
deliberate difference.*

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
| 12 | **Approvals (permissions) from children surface by the same tree rule** | Was row-chip only. **Fixed**: approvals tracked by tool id tree-wide, tree-picked into the approval dock, verdict routed to the asking session | ✅ DONE |
| 13 | **Resume/continue**: passing `sessionID` continues a previous child (may switch agent/model) | **Fixed**: `session_id` on both delegate tools; same thread/checkpoint, follow-up verbatim (no persona re-applied); only the own parent may resume, only once settled. (Model CAN switch on resume via `model`; agent is the child's own.) | ✅ DONE |
| 14 | **Model choice**: per-agent model, per-call override (`model` arg) | **Fixed**: per-call `model` > custom agent's frontmatter model > parent's model, threaded delegate → lifecycle → coordinator → invoke_agent | ✅ DONE |
| 15 | **Open agent registry**: custom agents (own prompt/model/permissions/colour), tool description lists available agents dynamically | **Fixed**: built-ins + `.crusorai/agents/*.md` (workspace) and `~/.crusorai/agents/*.md` (global), frontmatter description/capabilities/model/base + body prompt; custom shadows built-in by name; delegate descriptions rebuilt from the live registry at bind. (No per-agent colour — the card has no colour slot.) | ✅ DONE |
| 16 | Spawn is permission-gated per agent (a parent agent may be denied specific subagents) | **Fixed**: `CRUSORAI_SUBAGENT_DENIED` / `CRUSORAI_SUBAGENT_ALLOWED` env policy, enforced in both delegate tools with the reason returned to the model | ✅ DONE |
| 17 | Child header lists **siblings** (other children of the same parent) for quick switching | **Fixed**: sibling chips in the child nav row (service computes them from the session store + tree), click navigates directly | ✅ DONE |
| 18 | Session list shows only root sessions (children reached via cards) | **Fixed**: `sessionRows()` projects root sessions only; records stay in the store for titles/tree/navigation | ✅ DONE |
| 19 | Child view: composer disabled — "return to parent to send" | Child sessions accept prompts (they are full sessions). Different, arguably better; flagged, not changed | ⚠️ DIFFERENT BY DESIGN |
| 20 | Open child view streams tokens live | Bridge forwards PROVEN in-tree content; the desktop adopts the snapshot tail into the live lane on the first frame (stream, not poll) | ✅ SHIPPED `6afaf93c` (laptop verify pending) |

## Recommended order from here

All seven gaps above are closed. What remains, in value order:

1. **#11 background completion** — persist the synthetic `<subagent>`
   message into the parent thread and re-invoke an idle parent so it can
   react without being poked (today: the completion text paints live).
2. ~~**#20 token streaming into an open child view**~~ — SHIPPED: the bridge forwards proven in-tree frames; the service adopts the checkpoint tail turn into the live lane and stands the 3s poll down. (Was: replace the 3s
   checkpoint poll with the child's live token frames while it's open.
3. Field-verify resume + custom agents with real provider calls (sandbox
   has no provider keys; the chains are proven with `invoke_agent` faked
   at exactly the provider seam).

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

Second build (the seven gaps):

- `desktop/…/crusorAIRendererService.ts` — `approvals` map + tree pick +
  asking-session verdicts; root-only session list; `childSiblings`.
- `desktop/…/crusorAIRenderer.ts` + `crusorAI.css` — sibling chips in the
  child nav row.
- `src/agents/subagent_registry.py` (new) — built-ins + `.crusorai/agents`
  custom agents, spawn policy (`CRUSORAI_SUBAGENT_ALLOWED/DENIED`).
- `src/agents/subagent_lifecycle.py` — launch carries provider/model/
  agent-prompt; `resume_child()` (same thread, verbatim continuation).
- `src/agents/sub_agent.py` — spawn honours custom prompts and
  continuations; spawn_batch threads per-task agents/prompts/scopes.
- `src/graphs/chat_graph.py` — delegate tools take `model` + `session_id`,
  resolve agents through the registry (unknown = hard error with the
  available list), enforce spawn policy; the binder rebuilds the delegate
  descriptions from the live registry per bind.
- Tests: `test_subagent_registry_resume.py` (11 tests: registry, policy,
  model override, custom agent end-to-end, resume same-thread-verbatim,
  foreign/unknown resume rejection, batch resume, dynamic description),
  architecture pins, jsdom harness approval-dock + sibling cases.
