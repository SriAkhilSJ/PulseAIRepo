# PulseAI — Paid Launch Map
### What you have today vs what Hermes has for paid users — and what to build

> **For founder, not coder.** This is your checklist to turn the current prototype into a sellable AI IDE.

---

## 1. Where you are TODAY (PulseAIRepo `main` @ 8813f079)

| Area | You have | Path |
|------|----------|------|
| **IDE** | Code OSS fork, Crusor panel fixed right, no movable agent | `desktop/vscode/src/vs/workbench/contrib/crusorai/` |
| **Agent runtime** | LangGraph graph, 32-layer context engine, tools, bridge via stdio | `src/graphs/chat_graph.py`, `src/context/`, `src/bridge/` |
| **Model** | One global model via `.env` only — `LLM_PROVIDER` + `LLM_MODEL` + single `CUSTOM_API_KEY/BASE_URL` | `src/config/settings.py:32`, `PulseAIRepo/.env` |
| **Memory** | Off by default `CRUSORAI_MEMORY=off` | `settings.py:32` |
| **Dashboard** | Flask SSE at 8080, FastAPI AG-UI at 8123, local only, no auth unless `CRUSORAI_DASHBOARD_TOKEN` set | `src/dashboard_server.py`, `src/server.py` |
| **Billing** | **NONE** — no login, no plan, no balance, no portal | — |
| **Telemetry** | Local JSONL `~/.crusorai/observability/turns.jsonl` off by default `CRUSORAI_OBSERVABILITY=off` | `src/observability.py` |
| **Team/Org** | **NONE** — single user local | — |

**In one line:** You have a great *local* single-player IDE. Hermes has a *multi-player* paid service. The gap is all `auth + billing + gating + team`.

---

## 2. What Hermes does for PAID (that you don't)

Hermes keeps **secrets in `.env`**, **settings in `config.yaml`** — `HERMES_HOME=~/.hermes` — `hermes_cli/env_loader.py:470` vs `hermes_cli/config.py:3793`.

* **Login:** Browser OAuth to `portal.nousresearch.com` -> JWT saved `~/.hermes/auth.json` (locked). Free stays anonymous `auth.py:487`.
* **Ask server on every run:** `GET /api/oauth/account` + `GET /api/billing/state` + `GET /api/billing/subscription` -> answers `logged_in, plan: Free/Plus/Pro, balance_usd, role: Owner/Admin/Member, can_change_plan, can_charge`
* **Feature gate:** Free gets `firecrawl, browser-use` but NOT `fal-video`. Paid gets all. Gate is server flag `tool_gateway_entitled_for(cat)`, not hardcoded `if plan==pro`.
* **Money:** IDE never touches card. `POST /api/billing/charge` with `Idempotency-Key` UUID -> Stripe -> poll `GET /charge/{id}`. 3DS opens portal `manage-subscription`, not terminal.
* **Team:** `org_id + context: personal|team + member_spend_cap`. Member exceeded cap -> `Ask admin to raise cap`.
* **Monitoring:** **No prompts uploaded.** Shared metrics `telemetry.shared_metrics.enabled=false` by default; if on, local `metrics.sqlite3` with counters only (`tool_call count`), no content, 30d delete.

---

## 3. PAID LAUNCH MAP — 6 Phases for PulseAI

### Phase 0 — Make `.env` reliable (DONE)
You fixed `src/config/settings.py:12` to load `PulseAIRepo/.env` explicitly. Keep it. Next: add `~/.pulseai/` home like Hermes `~/.hermes` so each user has own `.env` + `config.yaml`.

### Phase 1 — Auth (2 weeks) — MUST HAVE for paid
**Build:**
* `pulse portal login` -> opens `portal.pulseai.com` OAuth device code -> save JWT `~/.pulseai/auth.json` with file lock
* `pulse portal logout`, `hermes_cli/auth.py:113` pattern
* In IDE, show `Not logged in · Run pulse portal` when `logged_in=false` — fail-open, don't crash

**Files to create:** `src/auth/portal_auth.py`, `~/.pulseai/auth.json`
**Borrow from Hermes:** `hermes_cli/auth.py` (113 lines) + `hermes_constants.py:71` `get_hermes_home()`

### Phase 2 — Billing API (2 weeks) — THE MONEY
**Build portal endpoints (your website):**
* `GET /api/billing/state` -> `{logged_in, org_id, role, balance_usd, cli_billing_enabled, card, portal_url}`
* `GET /api/billing/subscription` -> `{current: {tier_id, tier_name, cycle_ends_at}, tiers: [...], context: personal|team}`
* `POST /api/billing/charge` (needs `billing:manage` scope) + `Idempotency-Key`
* `GET /api/billing/charge/{id}` poll

**IDE side:** `src/billing/billing_view.py` + `billing_usage.py` + `subscription_view.py` mirrors — `build_billing_state()` cached 60s, fail-open.

**UI:** Copy `hermes_cli/cli_billing_mixin.py:103` `/subscription` and `_billing_overview:795` — plan line `Plan: Plus · $42.50 left · renews Dec 15`, two-bar dollar view, `Total spendable`.

### Phase 3 — Gate Free vs Paid (1 week)
* Define `TOOL_COVERAGE` e.g. `free: [basic-chat, search]` not `[video-gen]` — `hermes_cli/nous_account.py:22`
* Server returns `tool_gateway_entitled_for(category)` — IDE disables buttons if false, shows `Upgrade at portal`
* Model catalog: `free_tier` flag per model `hermes_cli/inventory.py:970`

### Phase 4 — Team/Enterprise (2 weeks) — WHERE MONEY SCALES
* `org_id, org_slug, role: Owner/Admin/Member` in `GET /state`
* `can_change_plan = server canChangePlan else is_admin` `agent/billing_view.py:186`
* `member_spend_cap_usd` + message `Your access paused — ask admin`
* `Manage on portal: /orgs/{slug}/billing?topup=open` `hermes_cli/nous_account.py:167`
* Org-shared skills pull `cli.py:18113`

### Phase 5 — Observability (1 week) — Pay attention without spying
* Keep your `src/observability.py` JSONL but gate `CRUSORAI_OBSERVABILITY=on`
* Add opt-in `telemetry.shared_metrics.enabled` -> `~/.pulseai/telemetry/metrics.sqlite3` counters only — never prompts `hermes_cli/observability/shared_metrics.py:55`
* Document: `We track dollars, not data` — enterprise trust pitch

### Phase 6 — Hardening (1 week)
* `HERMES_HOME`-style `PULSEAI_HOME` env isolation per profile
* `Idempotency-Key` on every charge, `Decimal` for money, 30s token cache `hermes_cli/nous_billing.py:213`
* 429/401/403 typed errors -> `BillingScopeRequired` -> re-auth flow

---

## 4. Checklist — Copy/Paste for your Trello

- [ ] **Auth:** `portal login` + `~/.pulseai/auth.json` + lock
- [ ] **Portal:** Deploy 4 endpoints (`/account`, `/billing/state`, `/billing/subscription`, `/billing/charge`)
- [ ] **IDE billing view:** `build_billing_state()` + two-bar UI
- [ ] **Subscription UI:** `/subscription` -> plan catalog + `manage-subscription?plan=tier_id` deep link
- [ ] **Topup:** `/topup` -> `Add funds` + `Auto-reload` + `Monthly limit` (read-only)
- [ ] **Gating:** `tool_gateway_entitled` per category
- [ ] **Team:** `org_id, role, member_spend_cap, can_change_plan`
- [ ] **Telemetry opt-in:** Local sqlite, no upload

---

## 5. What to NOT build (Hermes deliberately doesn't)

* Don't upload prompts/responses for billing
* Don't put API keys in `config.yaml` — `.env` only
* Don't add new `HERMES_*` env for non-secrets — put in `config.yaml` `AGENTS.md:102`
* Don't track free users at all

---

## 6. File map — Where to look in Hermes vs PulseAI

| Feature | Hermes original | Your PulseAI place |
|---------|----------------|-------------------|
| Env load | `hermes_cli/env_loader.py:470` | `src/config/settings.py:6` (fixed) |
| Auth JWT | `hermes_cli/auth.py:113` | **TODO** `src/auth/portal_auth.py` |
| Billing client | `hermes_cli/nous_billing.py:475` | **TODO** `src/billing/nous_billing.py` |
| Billing view | `agent/billing_view.py:150` | **TODO** `src/billing/billing_view.py` |
| Subscription | `agent/subscription_view.py:100` | **TODO** `src/billing/subscription_view.py` |
| CLI mixin | `hermes_cli/cli_billing_mixin.py:103` | **TODO** `desktop/.../crusoraiBilling.ts` |
| Telemetry | `hermes_cli/observability/shared_metrics.py:55` | `src/observability.py:55` (extend) |

**Start with Phase 1 + 2.** That's 4 weeks to first dollar. Team comes after.

---
*Generated 2026-09-21 — PulseAIRepo main 8813f079 — compare D:/hermes/hermes-agent 5eb4d…*
