# Crusor — Product Strategy

Status: **DRAFT FOR FOUNDER APPROVAL** · 2026-11-12 · pins to `PulseAIRepo@fb5bd528` and the 2026-11-12 audit (F-01…F-15).
Legend: **[V]** verified in code/docs · **[R]** research finding with source · **[A]** assumption needing validation.

---

## 0. The strategic tension I must name first

Founder direction says the **primary** customer is non-technical vibe coders. The evidence says that is
the hardest fight available, for four reasons:

1. The product is a **local VS Code fork** requiring Python, a venv, a bridge process and env keys **[V]**.
   Lovable, Bolt and v0 win on the inverse: zero install, hosted runtime, deploy button **[R]**.
2. Those three bundle preview + database + auth + hosting + custom domain **[R]**. Crusor bundles an
   *editor*. To a non-technical user, an editor is the least valuable part of the outcome.
3. They price at $25–30/mo with credits **[R]** and spend heavily on acquisition. A solo founder cannot
   out-market them in that segment.
4. Crusor has **no external users and no user research** **[V: PROJECT_MASTER, CURRENT_STATE]**. Personas
   for non-technical users would be pure fiction today.

**Recommendation (decision needed):** keep non-technical users as a *product mode*, not as the *go-to-market
beachhead*. Enter through the segment that can install a fork today and pay for correctness — semi-technical
builders and professional devs — and ship a guided beginner profile once deployment and onboarding exist.
This is a sequencing recommendation, not a rejection of the vision.

---

## 1. Market positioning

**Category:** local-first AI software agent with an auditable execution record.

**Positioning statement (external, one sentence):**
> Crusor is the AI IDE that shows its work: it runs on your machine, asks before it touches anything
> dangerous, and tells you what every task cost — so you can trust it with real repositories.

**Why this position is defensible with the code that exists [V]:**

| Asset | Competitive read |
| --- | --- |
| 19-layer context engine with tree-sitter + sqlite-vec + RRF | Deeper than Cursor's "no embeddings" stance and Claude Code's agentic grep, Windsurf's trained SWE-grep excepted. Unproven in public benchmarks. |
| Native fork integration (diff review, approval tokens, tool cards) | Extensions cannot reach this depth. |
| Provider-reported token accounting + priced rate card + budget governor | Ahead of most vendors *internally*, behind them in *surfacing* (receipts are dead **[V]**). |
| Real Windows AppContainer implementation | Rare in this category; currently off by default **[V]**. |

**What we must not claim until proven:** "production-hardened", "autonomous engineering", "beats Cursor".
The repo's own Nov-12 audit contradicts the first two **[V]**.

---

## 2. Primary persona (and its evidence status)

All personas below are **hypotheses**, not research. Evidence base: zero external users, zero interviews,
zero support tickets **[V]**. Confidence labels are deliberate.

### P1 — "The Builder" (primary revenue persona) — confidence: MEDIUM [A]
Semi-technical founder, indie dev, or 1–3 person studio. Ships real web apps, uses GitHub, has API keys,
is cost-aware. Needs: an agent that survives a real repo, doesn't burn $40 silently, and doesn't run
`rm -rf` because a README told it to.
*Buys because:* correctness + cost visibility + local control.

### P2 — "The Vibe Coder" (volume/community persona) — confidence: LOW [A]
Non-technical operator with an idea. Has never used a terminal. Needs: prompt → working app, deployed,
with a domain; edit by pointing at the screen; undo that works.
*Buys because:* outcome, not tooling. **Cannot be served by the current product without a guided mode
and hosting.** Lovable/Bolt/v0 own this today **[R]**.

### P3 — "The Professional / AI power user" (credibility persona) — confidence: MEDIUM [A]
Senior engineer or agent tinkerer who runs OpenCode/Codex/Claude Code. Needs: model choice, MCP, hooks,
scriptability, measurable quality, no vendor lock.
*Buys because:* configurability + evidence. Also the persona that produces public benchmarks and word of mouth.

### P4 — "Enterprise engineering org" (later) — confidence: LOW [A]
Needs SSO/SCIM, policy enforcement, egress control, audit export, signed builds, support SLA. **None exist
today** **[V]**. Not a 6-month segment for a solo founder.

---

## 3. Customer problems and unmet needs

| # | Problem | Who feels it | Evidence | Crusor's current answer |
| --- | --- | --- | --- | --- |
| N1 | Agents that can't survive a real repo — they hallucinate structure, edit blind, never run tests | P1, P3 | Engineering path has no read/search/test tools **[V]** | Not solved (P0-1) |
| N2 | Cost is opaque and unpredictable per task | P1, P2 | Lovable admits no upfront estimate; v0 publishes no per-build cost **[R]** | Accounting exists, surfacing dead **[V]** — opportunity |
| N3 | Permission fatigue vs. blind trust — no usable middle | P1, P2, P4 | Competitors expose explicit modes (Cursor 3, Claude Code 6, Codex sandbox+approval, v0 Ask/Auto/Full) **[R]** | Env-var sandbox, off by default **[V]** — worst of both |
| N4 | Vibe tools trap you in their stack and their host | P2 → P1 graduation | Lovable: one stack, no repo import; Bolt: JS only; v0: Next.js only **[R]** | Crusor is stack-agnostic — genuine edge |
| N5 | Nobody can verify vendor claims about agent quality | P3, P4 | Vendors publish marketing benchmarks; Crusor publishes 970 self-authored docs **[V]** | Opportunity: publish reproducible task benchmarks |
| N6 | Enterprise can't adopt an agent without policy control | P4 | Codex ships `requirements.toml` admin enforcement; nobody else documents it **[R]** | Absent |

---

## 4. Competitive differentiation (chosen, not claimed)

We will compete on **three** things and explicitly decline two:

**Compete on**
1. **Verified execution** — every task produces a receipt: plan, tool calls, diffs, test results, tokens,
   cost, outcome. Nobody in the benchmark publishes "cost per successful task" as a user-facing metric **[R]**.
2. **Configurable autonomy that is actually enforced** — beginner / developer / enterprise profiles mapped
   to real permission modes, default-safe, visible in UI.
3. **Context quality, measured** — publish a reproducible benchmark of Crusor's 19-layer engine against
   naive grep/RAG baselines on task success, not on vibes.

**Decline (for now)**
- **Hosted app generation** (Lovable/Bolt/v0 lane) — different runtime, different cost structure, different buyer.
- **Model leadership** — we are a router, not a lab. Every competitor now sells a router too **[R]**.

**Moat reality check:** the fork is not a moat (18k files, rebase tax); the context engine is a *candidate*
moat only when measured; the receipts/trust surface is a *positioning* moat that is cheap to copy but
expensive to copy *credibly* once you have published benchmarks.

---

## 5. Beginner-to-professional journey

| Stage | User state | Product mode | Gate to next stage | Exists today? |
| --- | --- | --- | --- | --- |
| 0 Install | Has an idea, no toolchain | One-click installer, bundled runtime, no Python visible | Installs without terminal | **No** — needs Python/venv **[V]** |
| 1 First win | Types a goal | Guided profile: plan → approve once → run → show result + cost | App runs locally | Partial (approval UI exists **[V]**) |
| 2 Iterate | Wants changes | Select-and-edit / chat, diff review, undo | User understands diffs | Partial (diff review exists **[V]**) |
| 3 Real repo | Imports existing project | Developer profile, model choice, MCP, terminal | Agent survives a real bug fix | **No** — P0-1 |
| 4 Power | Wants control | Config files, hooks, custom providers, budgets | Trusts cost numbers | Partial |
| 5 Team | Wants shared policy | Enterprise profile, SSO, audit export | Compliance review | **No** — P4 |

The journey is the argument for sequencing: stage 3 is where revenue and credibility live, and it is the
stage that is currently broken. Stage 0 is where the non-technical volume lives, and it does not exist.

---

## 6. Enterprise expansion strategy (deliberately late)

Order of construction, each gated on a paying design partner:

1. **Signed + reproducible desktop build** (no enterprise conversation starts without it) — P1.
2. **Policy file** (`crusor.policy.json`: allowed models, allowed tools, egress domains, approval floors)
   — the Codex `requirements.toml` pattern **[R]**. Admin-enforced, not user-editable.
3. **Audit export** — the receipts ledger, already planned in Deliverable 5, exported as JSONL/SIEM.
4. **SSO (OIDC/SAML) + SCIM** — requires the auth layer that is currently per-process and unwired **[V]**.
5. **Egress control + DLP** — currently absent entirely **[V]**.

Realistic entry: **Q3–Q4 2027**, one lighthouse customer, services-led. Do not build a control plane before
a customer pays for it.

---

## 7. Business and monetization strategy

**Constraint:** solo founder, revenue target 3–6 months, no billing code today **[V]**.

| Tier | Price | What it is | Why it works solo |
| --- | --- | --- | --- |
| **Free (local, BYOK)** | $0 | Full IDE + agent, user's own API keys, local-only | Zero marginal cost to us; distribution engine; no infra |
| **Pro** | $19/mo | BYOK + receipts history, benchmark reports, priority fixes, guided beginner mode | Margin ~100%, no inference cost |
| **Credits (optional)** | usage-based, 25–30% margin | Hosted inference for users without keys | Only after Pro proves demand; needs a margin model |
| **Team** | $39/seat | Shared policy file, usage roll-up, approvals audit | Reuses enterprise work; no server needed initially |
| **Enterprise** | annual, $15k+ | SSO, policy enforcement, audit export, support | Services-led, Q3+ |

**Sequencing rule:** do not build hosted inference or Stripe before 20 paying Pro users. The 3–6 month
revenue target is reachable with BYOK Pro because it requires no infrastructure — only trust and a working agent.

**Pricing anchor:** publish **cost per successful task** and price Pro below the monthly API spend of a
typical user. That is a claim no competitor can currently match with public numbers **[R]**.

---

## 8. Strategic bets, kill criteria, and what would change my mind

| Bet | Kill criterion (review at 90 days) |
| --- | --- |
| Verified execution is a buying criterion | Fewer than 5 of 20 design partners cite cost/trust as the reason they stayed |
| Context engine beats naive retrieval measurably | < 10 percentage-point task-success delta on our own benchmark |
| Local-first is still a wedge in 2027 | > 60% of prospects say hosted is required, not preferred |
| Pro/BYOK can reach $2–5k MRR | < 10 paid conversions from 300 installs |

**What would change the strategy:** if a hosted runtime partner (or a deploy integration) removes stage-0
friction cheaply, the non-technical segment moves from "later" to "parallel" without building infra.
