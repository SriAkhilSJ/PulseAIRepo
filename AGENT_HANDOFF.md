# Agent Handoff — PulseAI / CopilotKit

Start here. This records the state of the CopilotKit work as of **2026-08-29**, what was
verified, what was fixed, and the traps that will waste your time if you don't know them.

Read [`COPILOTKIT_VERIFICATION.md`](COPILOTKIT_VERIFICATION.md) for the full defect-by-defect
evidence. This file is the orientation layer on top of it.

---

## TL;DR

**Question that was asked:** "Does the agent really render?"

**Answer at commit `14b8862b`: No.** The webview mounted, but the agent was unreachable and the
generative task card painted as an empty white box.

**Answer after `4f88a907`: Yes**, verified end-to-end up to the LLM call. Browser → Copilot
Runtime → Python LangGraph agent → A2UI card with real content and a live action button.

**Still open:** no live LLM turn has ever been executed. Two independent blockers — see
[Open items](#open-items).

---

## The 7 defects that were found and fixed

| # | Defect | Root cause | Fix |
|---|---|---|---|
| 1 | Card rendered **empty** | Schema used legacy `props`-nested format; A2UI v0.9 destructures `{ id, component, ...properties }`, so props landed under a `props` key and `props.child` was `undefined` | Flattened `src/a2ui_schemas/pulse_task_schema.json` |
| 2 | Runs **never reached** the Python agent | `server.ts` mixed a v1 `LangGraphHttpAgent` with `CopilotKitIntelligence` → every run routed to `api.intelligence.copilotkit.ai` | Use AG-UI `HttpAgent`; Intelligence now optional |
| 3 | Agent crashed on first node | `KeyError: 'latest_instruction'`, then `'provider'` — set by CLI/bridge, not by any graph node; AG-UI sends only `messages` | `_latest_instruction_from_messages()` + `_cfg()` helper |
| 4 | `tsc -b` broken, **12 errors** | `agent=` prop doesn't exist in v2 API; zod **4.5.2** in app vs zod **3.25.76** in a2ui | `agentId`; zod pinned to `3.25.76` |
| 5 | Action button **inert** | Renderer ignored the bound `action` | `onClick={props.action}` |
| 6 | Preview unreachable | Hard-coded `runtimeUrl="http://localhost:8200/..."` | Relative URL + Vite proxy |
| 7 | Runtime **died** on upstream socket close | Unhandled rejection killed the Node process | `unhandledRejection` / `uncaughtException` guards |

`tsc -b`: **12 errors → 0**.

---

## Architecture — the 3-tier stack

```
Browser  ──►  Vite :5173  ──proxy /api/copilotkit──►  Copilot Runtime :8200  ──AG-UI──►  FastAPI :8123
                                                       (@copilotkit/runtime v2)          (src/server.py)
                                                       AG-UI HttpAgent                   LangGraph + checkpointer
```

Key facts:

- `src/server.py` exposes an **AG-UI** endpoint (`add_langgraph_fastapi_endpoint`), *not* a
  LangGraph Platform deployment. The runtime must use an AG-UI `HttpAgent` from `@ag-ui/client`.
- The webview calls a **relative** `runtimeUrl`. Vite proxies `/api/copilotkit` → `:8200`.
  Never hard-code `localhost` — it breaks every non-localhost origin.
- `CopilotKitIntelligence` is **optional**. Set `INTELLIGENCE_API_KEY` to enable Cloud mode;
  without it the runtime runs in `sse` mode, direct to the agent.
- The A2UI catalog lives in `pulse-webview/src/a2ui/`; the card schema (the agent's contract)
  lives in `src/a2ui_schemas/pulse_task_schema.json`. **These two must agree.**

### Running it

```bash
uv run python -m uvicorn src.server:app --host 0.0.0.0 --port 8123   # term 1
cd pulse-webview && npm run runtime                                   # term 2
cd pulse-webview && npm run dev                                       # term 3
```

---

## Traps — read this before changing anything

These cost real time to discover. Don't rediscover them.

1. **A2UI v0.9 props are FLAT.** `{"id","component","child":"col"}` — not
   `{"id","component","props":{"child":"col"}}`. A nested `props` wrapper produces a card that
   mounts with `data-testid="pulse-task-card"` but is **completely empty**. It fails silently:
   no error, no warning, just a blank box. Guarded by a regression test.

2. **zod must stay on 3.25.76.** `@copilotkit/a2ui-renderer` and `@a2ui/web_core` bundle
   zod 3.25.76. `GenericBinder` classifies props via `schema._def.typeName`, which is
   `undefined` on zod v4. Upgrading the app to zod 4 compiles fine (esbuild strips types) but
   silently breaks every dynamic binding and action. Pin it.

3. **`CopilotKitProvider` has no `agent`/`agentId` prop.** Only `CopilotChat` takes `agentId`.
   Passing `agent=` to the provider is a silent no-op — the agent never binds.

4. **`vite build` passing proves nothing about types.** `npm run build` is `tsc -b && vite build`,
   but esbuild strips types without checking. Always run `npx tsc -b` explicitly.

5. **Custom catalog entries override built-ins.** `createCatalog(..., {includeBasicCatalog:true})`
   appends yours last, so `Card` and `Button` replace the basic catalog's. If yours ignores
   `dispatch`/`action`, the button goes dead.

6. **AG-UI entry carries only `messages`.** Anything the CLI/bridge sets in
   `config.configurable` (`provider`, `model`, `workspace`) or in state (`latest_instruction`)
   is absent on this path. Read them defensively; don't hard-index.

7. **24 pytest failures are pre-existing and expected** in a bare environment: 17 from missing
   tree-sitter grammars, 5 from an absent `ui/` directory, 1 in
   `test_autonomous_runtime_contract.py`. Verified identical on pristine `14b8862b`.
   Don't chase them.

---

## Test commands

```bash
cd pulse-webview && npm test        # 9 DOM tests, provider-free (no key, no tokens)
cd pulse-webview && npx tsc -b      # must exit 0
uv run python -m pytest src/tests -q
```

The DOM harness (`pulse-webview/src/__tests__/`) mounts the real components with the real catalog
and drives them with the exact operations the Python agent emits
(`src/__tests__/fixtures/pulse-a2ui-operations.json`). It asserts the card paints real text, the
button dispatches, the schema stays flat, and the App shell mounts. **It spends zero tokens.**

---

## Open items

### 1. 🔴 Credentials are committed and this repo is PUBLIC — rotate immediately

`4fe2d33d` added `.env` to `main`; `3dd78a25` deleted the file, but **git history keeps it**.
Both a Sarvam API key and a CopilotKit Intelligence key are retrievable by anyone:

```bash
git clone https://github.com/SriAkhilSJ/PulseAIRepo && git show 4fe2d33d:.env
```

**Action, in order:** (a) revoke/rotate both keys — purging history does not un-leak a secret
that has already been pulled; (b) purge with `git filter-repo --path .env --invert-paths` and
force-push; (c) add a pre-commit secret scan.

`.env` is untracked again as of this handoff (the local copy was kept on disk intentionally for
verification). **Never commit it.** It is gitignored — if you find yourself reaching for
`git add -f .env`, stop.

### 2. No live LLM turn has ever run

Two independent blockers:

- **Network.** The verification sandbox allows GitHub and npm but blocks all LLM providers
  (`api.sarvam.ai`, `api.openai.com`, `api.groq.com` all unreachable). Zero provider calls are
  possible from there, so no credits were ever spent and the diagnosis never depended on one.
- **Key.** Not available in that environment.

To close it, run the three commands above on a machine with network access and send one message.
Expected SSE sequence:

```
RUN_STARTED → STEP_STARTED task_manager → STATE_SNAPSHOT → … → assistant reply → A2UI card
```

Currently it reaches `task_manager` successfully and stops at the LLM call.

If credits are a concern, add a mock provider instead — a deterministic fake LLM exercises the
entire pipeline including tool calls and card rendering at zero cost and runs forever in CI.

### 3. Minor

- `pulse-webview/e2e-verify.spec.ts` writes screenshots to a hard-coded Windows path
  (`D:/pulseAIagent/...`) and sleeps 12s waiting for an LLM. It will not pass as written.
- `README.md` still says Node 24.18.0 / Vite 7 for the webview; the app actually builds on
  Node 22.22 with Vite 8. Worth reconciling.
- The `ui/` directory is referenced by some tests but does not exist in the tree.

---

## File map for this work

| File | Role |
|---|---|
| `COPILOTKIT_VERIFICATION.md` | Full defect evidence, measurements, test results |
| `AGENT_HANDOFF.md` | This file — orientation |
| `src/a2ui_schemas/pulse_task_schema.json` | Agent→UI card contract (flat v0.9) |
| `src/graphs/chat_graph.py` | `_cfg()` + `_latest_instruction_from_messages()` |
| `pulse-webview/server.ts` | AG-UI `HttpAgent`, optional Intelligence, crash guards |
| `pulse-webview/src/App.tsx` | `agentId`, relative runtime URL |
| `pulse-webview/src/a2ui/renderers.tsx` | Wired button `onClick` |
| `pulse-webview/src/__tests__/` | Provider-free DOM harness + operations fixture |

## Commit history

```
cab30792  chore: add .env for arena verification          ← reverted (untracked again); see Open items #1
4f88a907  fix(copilotkit): make the Pulse agent actually render end-to-end
14b8862b  feat: Hermes-grade context/security + CopilotKit desktop fixed-right
```
