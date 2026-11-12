# Crusor AI IDE — Honest Product Assessment

Status: **DRAFT — discovery input, not approved**
Date: 2026-11-12
Repo: `PulseAIRepo` @ `fb5bd528` (branch `feat/prompt-cache-stabilization`)
Method: direct code/git inspection + independent re-verification of the repo's own audit claims.

Legend: **[V]** verified by me in code/git · **[D]** stated in the repo's docs only, not independently
verified · **[A]** my inference/assumption, to be confirmed with the founder.

---

## 1. What the product actually is [V]

Three layers, all present in-tree:

| Layer | Reality |
| --- | --- |
| Desktop IDE | A **vendored Code OSS fork** at a pinned upstream SHA (`desktop/UPSTREAM_PIN`), rebranded (`product.json`: CrusorAI IDE, `crusorai://`). 18,154 tracked files. |
| First-party IDE contribution | `src/vs/workbench/contrib/crusorai/` — 43 TS files, ~15.9k lines: agent pane, Manager editor, renderer (4,976 lines), diff review, permission prompts, tool cards, theme. |
| Agent runtime | Python, **LangGraph** (`StateGraph`, 16 nodes, `SqliteSaver` checkpoints), 8 provider branches, 55 bound tools, 19-layer context engine. |
| Transport | Not HTTP. A **versioned stdio JSON-lines bridge ("Protocol v2")**, 39 client methods / 44 server events, spawned by the Electron workbench as a sidecar. |

This is a **local, single-user desktop product** by design. `PROJECT_MASTER.md` lists hosted
multi-tenant SaaS as explicitly out of scope. Any roadmap that assumes cloud/multiplayer is a
different product, not a feature.

## 2. Genuine assets — what is actually built

1. **Context engine — the deepest technical asset [V].** 19 ranked layers in a fixed emission order
   (`repo_map → relevant_chunks → task → plan → progress → recovery … → git_context`), tree-sitter
   chunking across 6 languages, `sqlite-vec` KNN with JSON fallback, RRF fusion of vector + keyword +
   rerank, micro/compaction, per-model token budgets probed from live provider `/models`. Referenced
   by 32 test modules. This is the thing competitors find hardest to copy quickly.
2. **Native IDE integration that is real, not mocked [V].** Permission prompt UI ("Allow once /
   Allow always"), multi-diff editor with accept/reject, typed tool-call cards (activity, plan,
   file_change, approval, tool, test_results, verification, delivery, cost), ANSI terminal cards,
   custom theme. Evidence includes CDP captures of the running Electron app.
3. **A real tool loop with risk gating [V].** `ai → tools → progress → ai` with `SafeToolNode`,
   loop guards, drill-down budget governor, subagent delegation with depth cap 1.
4. **Security primitives that exist and are partly wired [V].** HMAC-SHA256 single-use approval
   tokens bound to session/request/command/workspace; path containment (traversal, UNC, ADS, device
   names, symlinks, 8.3 aliases) enforced on every file tool; secret redaction on reads; real Windows
   AppContainer + Job Object containment implementation; Linux bwrap fail-closed.
5. **FinOps that is real [V].** Provider-reported token usage, idempotent accounting, priced rate
   card, budget governor in the live loop. Rare for a product at this stage.

## 3. Hard truths — claims vs code

### 3.1 The engineering path is not an agent [V] — most serious product-integrity issue

The product headline is "plan, edit, execute, verify". That is true of the *chat* path. The
*engineering* path (`src/orchestration/`), which is what "autonomous engineering" means, has
**no tool binding at all**: `git grep 'bind_tools|read_file|search_code' -- src/orchestration`
returns zero matches. It generates whole files and then verifies them with text heuristics.
It cannot read a file it is about to change, search the repo, or run the tests it must pass.

Consequence: "autonomous engineering" today is a code generator with a report attached. A user will
notice within one real task.

### 3.2 Sandboxing is implemented but off by default [V]

`src/tools/terminal_tools.py:1093` — `CRUSOR_SANDBOX_TERMINAL` / `CRUSOR_APPCONTAINER_TERMINAL`
default to `"0"`. Only test modules set it to `1`. On any exception the code falls through to plain
`subprocess.Popen` unless `CRUSOR_STRICT_SANDBOX=1`. Environment is inherited, so provider API keys
are in the child process.

This is the sharpest contradiction in the product: the security architecture is real and the
default configuration bypasses it. For an app that runs model-written commands, that is the single
largest user-facing risk, and it undermines the "production-hardened" claim more than any missing
feature.

### 3.3 The test baseline is not green, and CI does not check it [V]

I collected the suite myself: **4,986 tests collected, 3 collection errors, interrupted**. Root cause
of one: `src/observability/` package shadows `src/observability.py`, so
`from src.observability import record_turn_receipt` raises `ImportError`.

CI never runs the suite. The full-suite workflow exists but sits in `ci/agent-core.yml` — outside
`.github/workflows`, so it never executes. Live workflows each run a handful of files, some with
`|| true` / `set +e` / `exit 0`.

Meanwhile the docs carry "395/395 QUALIFIED". The repo's own 2026-11-12 audit already retracts this;
`BUGS_AND_LIMITATIONS.md` says "Do not claim a clean full suite". Both statements are currently in
the repository.

### 3.4 Per-turn cost/telemetry receipts are dead [V]

Same shadowing bug. `chat_graph.py` calls `record_turn_receipt` via `hasattr` guard, gets `False`,
and silently skips. The product therefore has no per-turn cost receipt, no failure forensics, and the
`cost` tool card has nothing real to show.

### 3.5 No identity, no billing, no teams — by design, but unstated to users [V]

Auth exists (`PBKDF2`, JWT, refresh rotation) but is **not wired to the agent path**: no login
endpoint, `src/server.py` has no auth, signing key is `os.urandom(32)` per process so tokens die on
restart. Billing is a stub with a hardcoded balance of `42.5`. `PAID_LAUNCH_MAP.md` is honest:
"no login, no plan, no balance, no portal… 4 weeks to first dollar". No Stripe/checkout code exists.

### 3.6 Documentation is a second source of truth that disagrees with the first [V]

970 markdown files, 81 untracked root-level reports, 55 stashes, 41 branches. Concrete contradictions
found today:

| Capability | Doc A says | Doc B says |
| --- | --- | --- |
| OS sandbox | "True OS kernel sandboxing qualified" (Phase 12.1.3) | "Kernel sandbox absence… not enforced" (Phase 12.1.1) / "architecture claim is false today" (Nov-12 audit) |
| Billing | README: "portal-backed BillingState" | PAID_LAUNCH_MAP: "Billing: NONE — no portal" (code agrees) |
| Mutation broker | Root REMAINING_LIMITATIONS: "completely bypassing broker (CRITICAL)" | BUGS_AND_LIMITATIONS: "B-001 FIXED at HEAD" |
| Desktop | Phase 12.1.1: "Real desktop launch: LIMITATION" | CURRENT_STATE: "Desktop GUI acceptance: PASS" |
| Test suite | "395/395 flawless, 0 failures" | "OPEN — collection fails… do not claim a clean suite" |

For a founder this matters more than code debt: **you cannot make a launch decision from these
documents.** Any PM work I produce must pin to HEAD + a single condition-of-record, or it inherits
the same ambiguity.

### 3.7 Delivery/trust gaps [V]

- No signed or notarised desktop build pipeline (signing gated on Microsoft ESRP in `code.iss`); no
  workflow builds the desktop. Users cannot verify binary provenance.
- MCP client is **stdio only** — no HTTP/SSE transport. Competitive gap (see §5).
- Prompt-injection defence is advisory: matched patterns prepend a warning string, never block.
- Orphaned build artifact: a 541-file compiled React chat SPA under `out/.../crusorai-spa/` with no
  source, unmounted since 2026-10-21. Confusing to any new engineer.

## 4. Product surface inventory

| Surface | Verdict | Note |
| --- | --- | --- |
| Code OSS fork + agent pane + Manager editor | SHIPPED | The product |
| Permission prompts, diff accept/reject, tool cards, theme | SHIPPED | Real UX, real evidence |
| Bridge v2 sidecar | SHIPPED | 39 methods, tested |
| Crusor Preview (aux window + iframe) | PARTIAL | Refuses without live proxy |
| AG-UI FastAPI endpoint (`:8123`) | PARTIAL | Mounted, untested; separate `MemorySaver` → state diverges from desktop |
| Flask dashboard (`dashboard.html`, `:8080`) | DEMO-ONLY | A second, divergent product surface |
| `showcase/`, `apps/personal_finance`, `preview-lab/`, `lab/` | DEMO-ONLY | Benchmark outputs / harnesses |
| `linkedin-app/`, `nature/` | NOT PRODUCT | Assets only |
| Hosted service, billing, teams | ABSENT | Out of declared scope |

## 5. Competitive frame [A — needs verification pass]

Direct set: **Cursor, Windsurf, Zed, Cline/Roo Code, Claude Code, OpenAI Codex CLI, OpenCode, Aider.**
Their defensible positions: distribution and model deals (Cursor/Windsurf), terminal-first agent
ergonomics (Claude Code/Codex/OpenCode), and open extensibility (Cline/OpenCode).

Where Crusor could plausibly win, given what is actually built:

1. **Context quality** — the 19-layer ranked engine is a real differentiator if it demonstrably beats
   naive retrieval on a measured benchmark. Today that evidence is internal and mixed.
2. **Local-first trust** — verifiable containment + no telemetry is a wedge against cloud IDEs *if*
   the sandbox ships default-on and the build is signed. Currently neither is true, so the wedge is
   claimed, not held.
3. **Cost governance** — real token accounting and budget governors are ahead of most competitors at
   this price tier. Under-marketed and currently invisible in UI (dead receipts).
4. **Fork-level integration** — owning the editor lets Crusor do diff/permission/UX things extensions
   cannot. Also the biggest maintenance tax (18k vendored files, rebase cost every upstream release).

Not a differentiator: "agent that edits code" (table stakes), "multi-model" (table stakes),
"autonomous engineering" (unproven, and currently untrue on the engineering path).

## 6. Gap register, ranked by consequence

| # | Gap | Consequence if unfixed | Evidence |
| --- | --- | --- | --- |
| **P0-1** | Engineering path cannot use tools | Core promise fails in the first real user task | `git grep` in `src/orchestration` = 0 hits |
| **P0-2** | Sandbox default-off, env inherited | One malicious repo instruction = full user compromise incl. API keys | `terminal_tools.py:1093` |
| **P0-3** | No trustworthy build/verification signal | You cannot tell a broken release from a good one; "qualified" is meaningless | 3 collection errors; CI never runs suite |
| **P0-4** | Contradictory documentation | Every plan inherits ambiguity; investors/engineers lose trust | §3.6 table |
| **P1-5** | Dead cost receipts / no per-turn telemetry | Cannot price, cannot debug user reports, cannot show value | `src/observability/` shadowing |
| **P1-6** | No auth/billing/entitlement enforcement | Cannot charge, cannot onboard a team, cannot gate a paid tier | `billing_state.py:58` stub |
| **P1-7** | stdio-only MCP, advisory injection defence | Behind competitors on integrations; agent can be steered by repo content | `mcp_client.py`, `file_tools.py:356` |
| **P1-8** | Unsigned desktop build | Security-conscious users and enterprise blockers | `code.iss:43` |
| **P2-9** | Second product surface (dashboard/AG-UI) diverges | Support confusion, double maintenance | `dashboard_server.py` vs `bridge` |
| **P2-10** | Documentation-as-truth debt (970 md, 81 root reports) | Slows every future decision | `docs/`, repo root |

## 7. Assessment in one paragraph

Crusor is a real, unusually deep local AI IDE — not a prototype and not a demo: the context engine,
the native agent pane, the bridge protocol and the cost accounting are all genuine engineering that
most seed-stage competitors do not have. But two things are true at once: the *marketed* autonomous
engineering loop is not implemented (the engineering path has no tools), and the *safety and quality*
story is inverted (the sandbox is real but off, the test suite is real but unchecked). The product is
therefore roughly "80% of a differentiated agent core, 40% of a shippable product": it needs a
truth-and-trust pass (P0-1…P0-4) before any launch work, and that pass is smaller than it looks
because the hard components already exist. The main risk is not technical capability — it is
sustaining the current rate of unverified claims, which has already produced a documentation set that
contradicts itself.
