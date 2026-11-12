# Competitive Benchmark

Status: **DRAFT FOR APPROVAL** · Research date 2026-11-12 · Sources: official docs, GitHub API, this repo.
Every cell is either sourced **[R]** or marked **NPD** (not publicly documented) / **UNVERIFIED**.
Crusor column = verified against `PulseAIRepo@fb5bd528` **[V]**.

---

## 1. Method and its limits

- Repo facts from `api.github.com` (stars, licence, last push) — reproducible.
- Capability facts from each vendor's own docs, one URL per claim, recorded in the research log.
- **No vendor's internals are observable.** "NPD" means the vendor does not say, not that the feature is absent.
- No hands-on evaluation of competitor products was performed. Any claim of *behaviour* (quality, speed) is
  therefore out of scope; this table compares *documented capability*, not measured performance.

---

## 2. Headline set — agentic coding products

| Dimension | OpenCode | Codex (OpenAI) | Cursor | Windsurf / Devin Desktop | Claude Code | **Crusor [V]** |
|---|---|---|---|---|---|---|
| Repo / scale | `sst/opencode` MIT, 226,425★, pushed 2026-11-12 **[R]** | `openai/codex` Apache-2.0, 135,034★, Rust **[R]** | Closed source | Closed source | Repo `anthropics/claude-code` 155,429★ (issues/dist, no OSS licence) **[R]** | Code OSS fork, 18,154 files + 1,083 `.py` |
| Planning | Agents/sessions documented; explicit plan-approval mode **NPD** **[R]** | `/plan`, `update_plan` tool, clarifying questions **[R]** | Plan Mode, editable plan, save to workspace **[R]** | Plan mode read-only → approval; plans in `~/.devin/plans` **[R]** | Plan mode + `ExitPlanMode` approval **[R]** | `planner` → `plan_preview` → approval nodes exist in chat path; **absent in engineering path** |
| Repo exploration | LSP package + tools; retrieval strategy **NPD** **[R]** | Shell-driven inspection, no index documented **[R]** | Custom "Instant Grep" beating ripgrep; explicitly **no embeddings**; Explore subagent **[R]** | `SWE-grep` trained retrieval model, 8 parallel calls, ~2,800 tok/s **[R]** | Agentic `Grep`/`Glob` over bundled ripgrep; no index **[R]** | tree-sitter chunking, sqlite-vec KNN, RRF fusion, 19 ranked layers |
| Context mgmt | Skills + agents + sessions; compaction **NPD** **[R]** | `/compact` + auto-compaction; AGENTS.md capped 32 KiB **[R]** | `.cursor/rules` + AGENTS.md injected at start; compaction **NPD** **[R]** | Rules with 4 activation modes; progressive-disclosure skills **[R]** | Auto-compact, CLAUDE.md hierarchy, auto-memory, prompt caching **[R]** | 19 layers, micro-compaction, per-model budgets from live `/models` |
| Tool calling | Tools + MCP + plugins documented **[R]** | `apply_patch`, `shell`, `update_plan`, `spawn_agent`, web, MCP **[R]** | 9 documented tool families incl. browser **[R]** | Search/analyze/MCP/terminal **[R]** | Named Bash/Edit/Read/Grep/Glob/Agent/WebFetch **[R]** | 55 tools bound in chat graph |
| Multi-step | Server/session model, TUI + desktop **[R]** | Cloud tasks that continue while machine sleeps; subagents **[R]** | Cloud Agents in isolated VMs; parallel; Projects coordinator **[R]** | Cloud via Devin; Kanban across local+cloud; Arena parallelism **[R]** | Subagents, agent teams (experimental), parallel cloud sessions **[R]** | Subagents depth-1; no cloud/parallel |
| Code editing | Patch/edit tools documented **[R]** | `apply_patch` patches **[R]** | Auto-apply + checkpoints + Agent Review **[R]** | Editor diffs, revert per prompt step, named checkpoints **[R]** | Targeted `Edit`, `/rewind`, inline diffs **[R]** | diff review + accept/reject + checkpoints in desktop |
| Terminal | Documented tool **[R]** | OS-enforced sandbox; local shell **[R]** | Local shell + optional sandbox; cloud = VM **[R]** | Dedicated local terminal, per-command allow/ask/deny **[R]** | Local `Bash`, sandbox available **[R]** | `run_terminal` with approvals; **containment default OFF** |
| Test execution in loop | **NPD** | Explicitly in scope of sandbox/tests **[R]** | Cloud agents build/test; local loop NPD **[R]** | **NPD** | Explicit: "running tests to check its work" **[R]** | chat path: yes via terminal; **engineering path: cannot** |
| Error recovery | Session resume; loop policy **NPD** **[R]** | `/fork`, approvals, compaction **[R]** | Checkpoints; "no limit on tool calls"; sandbox classifier rerun **[R]** | 40 invocations/prompt; auto-continue; reverts irreversible **[R]** | 100 snapshots/session, `/rewind` **[R]** | loop guards, recovery node, pivot node, budgets |
| Memory | Sessions + skills **[R]** | AGENTS.md chain + resume **[R]** | Rules + local conversation index; auto-memory **NPD** **[R]** | Rules (always_on/glob/model_decision/manual) **[R]** | CLAUDE.md + auto-memory + `/resume` **[R]** | long-term memory, reflections, tool memory layers |
| Permissions / sandbox | Permission rules documented (allow/ask/deny) **[R]** | `sandbox_mode` (read-only/workspace-write/full) + approval policy + protected paths + **network off by default** + admin `requirements.toml` **[R]** | 3 run modes + `sandbox.json` + network limited to GitHub/web/docs **[R]** | 5 modes, deny>ask>allow, org rules override bypass, enforceable sandbox **[R]** | 6 modes incl. classifier "auto"; OS sandbox (Seatbelt/bwrap), **off by default**, macOS/Linux only **[R]** | HMAC approvals + path containment + AppContainer code, **env-var gated, default 0** |
| Model flexibility | Multi-provider, BYOK/custom base URL, plugins **[R]** | GPT family + `model_provider` (OpenRouter/Bedrock/custom) **[R]** | Cursor models + BYOK (keys routed via Cursor) **[R]** | First-party SWE models + Claude/GPT/Gemini; BYOK UNVERIFIED **[R]** | Claude only; Bedrock/Vertex/gateways **[R]** | 8 provider branches incl. custom/cheap base URL |
| Cost / perf tracking | **NPD** | `/status` limits, usage dashboard, credits **[R]** | Weekly pool, per-model $/1M, usage dashboard, admin APIs **[R]** | Per-1M rates published, ACUs, extra usage at API pricing **[R]** | `/usage` with local $ estimate, OTel, `--max-budget-usd` **[R]** | real token accounting + rate card; **turn receipts broken** |
| Cheapest paid tier | Free/OSS | Go $8/mo (desktop); $20 for CLI/IDE **[R]** | Plus $8/mo **[R]** | Pro $20/mo **[R]** | Pro $20/mo **[R]** | $0 (not launched) |

### Reading of the table

1. **Crusor's context layer is not behind on documented capability** and may be ahead on ranking policy.
   It is behind on *proof*: no benchmark, no public comparison.
2. **Planning parity is real in the chat path** (planner/preview/approval nodes) and **absent where it matters**
   (engineering execution).
3. **Permissions is the sharpest gap.** Every competitor turns autonomy into a *visible product surface* with
   named modes. Crusor implements stronger primitives (HMAC-bound approvals, path containment, AppContainer)
   and then hides them behind an env var that defaults to off. Note the nuance: Claude Code's OS sandbox is
   also off by default — but it is documented, discoverable and configurable; Crusor's is neither.
4. **Test-in-the-loop is the single clearest capability line** between "agent" and "code generator".
   Claude Code and Codex document it. Crusor's chat path has it; the engineering path structurally cannot.
5. **Cost transparency is an open field.** Cursor and Claude Code surface usage; nobody surfaces *cost per
   successful task*, and the vibe-coding products publish no per-build cost at all.

---

## 3. Non-technical segment — different product, same buyer

| Dimension | Lovable | Bolt | v0 | **Crusor** |
|---|---|---|---|---|
| Stated audience | "every level of experience" **[R]** | "everyone… never written a line of code" **[R]** | "anyone with an idea" **[R]** | developers (today) |
| First 5 minutes | prompt → build (~minutes) **[R]** | prompt → Build now → ~5 min **[R]** | prompt → app in VM sandbox **[R]** | install Python + venv + keys **[V]** |
| Real code ownership | yes, `.zip` on paid tiers, Git sync, **no repo import** **[R]** | yes, ZIP (desktop), GitHub import/create **[R]** | yes, VS Code-style editor, GitHub branches/PRs **[R]** | full local repo, native |
| Hosting / DB / auth | included (`*.lovable.app`, Postgres, auth, payments) **[R]** | included (Bolt Cloud: DB, auth, Stripe) **[R]** | included (Vercel, Neon/Supabase/Upstash) **[R]** | **none** **[V]** |
| Stack freedom | none (TanStack Start) **[R]** | JS/Node only **[R]** | Next.js only **[R]** | any **[V]** |
| Agent visibility | task cards, timeline, changes, up to 10h runs **[R]** | chat progress only; telemetry **NPD** **[R]** | screenshots, tool cards, citations **[R]** | tool cards, diffs, terminal cards **[V]** |
| Permissions model | **NPD** | **NPD** | Ask / Auto (default) / Full + JSON rules **[R]** | env-var sandbox, off **[V]** |
| Model choice | none **[R]** | none (auto-routing) **[R]** | v0 Mini/Pro/Max selectable **[R]** | 8 providers **[V]** |
| Price | Free 30 credits/mo; Pro $25 **[R]** | Free 1M tokens/mo; Pro $25 **[R]** | Free 7 msg/day; Plus $30 **[R]** | — |
| Documented limits | one stack, no native apps, revert not transactional **[R]** | JS only, no API/CLI, free host offline at cap **[R]** | offline impossible, Vercel-centric, SSO enterprise-only **[R]** | no installer, no hosting, no auth **[V]** |

**Conclusion:** these are *runtime* businesses, not editor businesses. Competing with them requires hosting,
deployment, auth, and a guided UI — none of which exist. Crusor's honest edge against them is the escape
hatch: real repos, any stack, local control, auditable cost. That is a *graduation* story ("outgrow Loveable"),
which is a marketing partnership/positioning play, not a feature fight.

---

## 4. Verified vs assumption ledger

| Claim | Status |
|---|---|
| Cursor searches without embeddings; Windsurf uses a trained retrieval model | **[R]** vendor docs, contrary to common belief — worth checking before we market context superiority |
| Codex defaults network off and enforces sandbox per OS | **[R]** |
| Claude Code sandbox is off by default and unsupported on native Windows | **[R]** — directly relevant to Crusor's Windows-first fork |
| Lovable cannot import existing repos; Bolt is JS-only; v0 is Next.js-only | **[R]** |
| Competitors' internal context-compaction algorithms | **UNVERIFIED / NPD** — do not claim we do it better |
| Competitor task success rates | **UNVERIFIED** — no vendor publishes reproducible numbers; our benchmark would be first-party, label it as such |
| OpenCode's plan-mode and sandbox behaviour | **UNVERIFIED** — not in the sources reviewed; do not cite either way |
| "Crusor is faster / better" on any dimension | **UNVERIFIED** — requires the benchmark in Deliverable 5 + P0-1 fixed |

## 5. What this means for the roadmap

1. Do not enter the hosted-generation lane (Lovable/Bolt/v0) before P3.
2. Match the *visible* permission surface immediately (P0) — it is cheap and it is the category norm.
3. Make test-in-the-loop real (P0-1) — it is the credibility line for every buyer persona.
4. Publish cost-per-successful-task before any competitor does (P2) — it is a first-mover claim we can
   support with code that already exists.
