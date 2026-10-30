# MCP: the plan after skills

Status 2026-10-30. Companion to `docs/MCP_SKILLS_PLAN.md` (the skills *library*
served over MCP) — this document is about the other direction: **third-party MCP
servers as agent capability**, and how we solve it now that the skills library has
taught us what the failure modes look like.

## Verdict

Same disease, different cure.

| | Skills | MCP servers |
|---|---|---|
| What it is | static knowledge, bounded, ours | dynamic capability, unbounded, third-party |
| Precomputable | yes — index once, ship the index | no — only the *shapes* can be cached, per server |
| Per-turn cost driver | book bytes | **tool schemas**, and they multiply per server |
| Failure mode we hit | index rebuilt every turn (39.7 ms) | server spawned every call (24.4 ms) |
| Zero-call possible? | yes | **no** — 0 only if a catalog is cached from a previous session; otherwise 1 |

So the *principles* transfer (index once, constant per-turn cost, phase gate,
receipts) and the *mechanism* does not: you cannot precompute a third-party
server's tools, and you must not bind them all.

## What the code does today (measured, this commit)

1. **The client is not wired into the runtime.** `discover_mcp_tools` and
   `call_mcp_tool` are referenced by tests and by one status string in
   `skills_hub.py`; nothing puts MCP tools into the bound tool list. A user who
   writes `.crusorai/mcp.json` gets a "connected" badge and **zero tools**.
   `chat_graph._resolve_bound_tools` binds `tools` (the registry) and says so:
   *"every registered tool is bound, every turn"*.
2. **One spawn per call.** `call_mcp_tool` spawned → initialized → called →
   closed, every time: **24.4 ms per call** on a local stdio server (node/npx
   servers cost seconds). Fixed: pooled session, **0.2 ms** per call after the
   first (≈165×), dropped the moment its process dies.
3. **One page of tools.** `tools/list` was read once; a paginating server
   silently hid everything after `nextCursor`. Fixed: follow the cursor,
   bounded at 20 pages.
4. **No catalog cache, no invalidation.** Every discovery re-asked every server.
   Fixed: per-server TTL cache (300 s, `CRUSORAI_MCP_TOOLS_TTL`) plus
   `invalidate_mcp_cache(workspace, server)`.

## The decision that matters: meta-tools, not pass-through

Registering each MCP tool in the global registry is the obvious wiring and the
wrong one — the registry is bound whole, every turn, so a GitHub server (~90
tools) and a Playwright server would add tens of thousands of tokens of schema to
*every* turn, including the ones that never touch them. GitHub's own MCP server
ships `--toolsets` for exactly this reason: *"help the LLM with tool choice and
reduce the context size."*

So the waist is three fixed tools, constant cost:

| Tool | Job | Cost |
|---|---|---|
| `mcp_servers` | which servers exist, alive/dead, tool counts, read-only share | ~60 tok |
| `mcp_tools(server?, query?)` | the catalog, filtered — schemas only for the tools asked about | ~180 tok |
| `mcp_call(server, tool, args)` | run it, approval-gated, receipted | ~140 tok |

Measured (`scripts/bench_skill_retrieval.py --mcp-tools N`, the same harness that
measures skills):

| Server tools | Meta-tools (per turn) | `mcp_tools` listing | Bound directly instead |
|---|---|---|---|
| 10 | 564 tok | 325 tok | 749 tok (1.3×) |
| 40 | 564 tok | 661 tok | 3 011 tok (5.3×) |
| 200 | 564 tok | **662 tok** | 15 126 tok (**26.8×**) |

Two things fall out of that table. The per-turn cost is **flat at 564 tokens**
however many servers or tools exist. And the listing is **bounded by its own
`limit` (20), not by the server** — 200 tools cost the same to list as 40. The model pays
one round trip to see a schema instead of every turn paying for all of them —
the same trade as `skills_search` (1 call) versus injecting the whole library.

## Plan

**P0 — wire the waist. DONE.** `src/tools/mcp_tool.py` (`mcp_servers`,
`mcp_tools`, `mcp_call`), registered in `chat_graph.tools` and carried on the
always-on waist (`toolsets._MCP_TOOLS`); 11 end-to-end tests in
`src/tests/test_mcp_meta_tools.py`, including the counter proof that an
unconfirmed mutating call **does not execute**. Original acceptance criteria:
Register `mcp_servers`, `mcp_tools`, `mcp_call` in `src/tools/toolsets.py`
(`_MCP_TOOLS`, always on, like `_SKILL_TOOLS`), implement them in
`src/tools/mcp_tool.py` over the pooled client, and route `mcp_call` through the
existing `guarded` approval path. Acceptance: a workspace with the `skills`
server bound can call a third-party server's tool end-to-end; **no** MCP schema
appears in the bound list beyond the three; a dead server returns the honest
string, never raises.

**P1 — session pool. DONE.** 24.4 ms → 0.2 ms, 7 tests
(`src/tests/test_mcp_session_pool.py`).

**P2 — catalog lifecycle. DONE.** `_rpc` now keeps notifications instead of
skipping them: `notifications/tools/list_changed` sets a flag on the session,
and the next catalog read consumes it once and drops that server's cache entry.
Tested with a server that gains a tool mid-call and announces it while answering
(the response is still matched by id, not by arrival order). Still open from the
original scope: honoring `ttlMs`/`cacheScope` when a server sends them.

**P3 — phase gate. DONE.** `_resolve_bound_tools` now writes
`configurable["tool_phase"]` from `state["execution_mode"]` — the flag the UI
actually sets — and `mcp_call` refuses a non-read-only tool in Plan Mode with
`PHASE_DENIED`. A plan may inspect third-party state and may not change it;
asking a human to approve a mutation mid-plan is the wrong question. Read-only
tools stay available.

**P4 — receipts. DONE.** Every executed `mcp_call` writes a `mcp_call` line to
the ledger (`thread`, `server`, `tool`, `wall_s`, `ok`, `chars`), kind-separated
from model `call` rows so a token summary is never polluted. A phase-denied or
approval-pending call writes nothing, because nothing ran.

## Measured end to end (local stdio server, after P0–P4)

| Step | Time | Note |
|---|---|---|
| `mcp_servers` | 9.5 ms | reads `mcp.json` only — never starts a server |
| `mcp_tools` (cold) | 28.2 ms | one spawn + `tools/list` |
| `mcp_tools` (warm) | 1.0 ms | cached catalog |
| `mcp_call` (pooled) | 2.9 ms | same session, no respawn |

Per turn that is **564 tokens of schema, flat** — no MCP schema is bound per
server, so the cost does not move when a second or third server is added.

Pooled sessions are child processes, so `close_all()` is registered with
`atexit`: an npx server outliving the IDE would be a real process nobody can see
or kill.

## What this buys

The agent can hold **hundreds** of third-party capabilities for ~300 tokens of
schemas, and pays per capability only when it uses one. That is the honest
version of the skills story: skills are zero-call because we own them; MCP is
one-call because we do not.

## Not doing

- **Not** auto-installing servers or shipping a marketplace: out of scope, and
  the safety surface (third-party code) is already the largest one we have.
- **Not** streaming partial tool output in v1: `tools/call` returns a whole
  result; `notifications/progress` is a later, separate contract.
- **Not** HTTP/SSE transport yet: stdio only, matching the server we ship.
- **Not** `notifications/progress` streaming or `ttlMs`/`cacheScope` hints yet:
  a `tools/call` returns whole, and the catalog TTL is ours (300 s) rather than
  the server's preference. Both are separate contracts, tracked above.
