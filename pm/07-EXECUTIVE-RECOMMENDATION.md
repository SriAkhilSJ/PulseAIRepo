# Executive Recommendation

Status: **FOR FOUNDER DECISION** · 2026-11-12

---

## 1. The biggest product opportunity

**Trust as a product surface.** Every competitor has converged on the same three things — a permission
mode, a cost number, and a plan you can edit — but none of them publishes *cost per successful task*
(Cursor, Claude Code, Codex surface usage; Lovable sells credits and admits it cannot estimate a run;
v0 publishes no per-build cost) **[R]**. Meanwhile Crusor already has the expensive half of that system
built: provider-reported token accounting, a priced rate card, a budget governor, HMAC-bound approvals and
real OS containment **[V]**.

The opportunity is not "better agent". It is **"the agent that can prove what it did and what it cost"** —
shipped as a visible UI, not a JSON file. That claim is cheap to make, expensive to make credibly, and you
are one wiring change (receipts) plus one benchmark away from being able to make it.

## 2. The biggest engineering risk

**Breadth over verification, in a solo-founder body.** Not competitors. The evidence: 970 markdown files
and five self-contradicting capability claims; 4,986 tests that CI never runs; two agent architectures where
only the unglamorous one works; 18,154 vendored files that need a rebase every upstream release; 81 untracked
root reports and 55 stashes.

This risk compounds: every week spent widening scope makes the one claim that matters ("it works, here is
the receipt") harder to make. **The single highest-leverage act this month is deletion and proof, not
features.** Note that the founder's own two-day target is the correct antidote — as long as the scope is
enforced.

## 3. Next 10 highest-priority tasks

| # | Task | Effort | Depends on |
| --- | --- | --- | --- |
| 1 | `TRUTH.md`: one condition-of-record; supersede the 5 contradictory docs | 1d | — |
| 2 | Fix 3 collection errors; suite collects clean | 1d | — |
| 3 | Move full-suite CI into `.github/workflows`; remove `\|\| true` / `set +e` | 1d | 2 |
| 4 | Route engineering execution through the tool loop (read → edit → test) | 4d | 1 |
| 5 | Fix `src/observability/` shadowing; emit TurnReceipt per task | 1.5d | — |
| 6 | Containment default-on, fail-closed, env scrubbed | 2d | — |
| 7 | Three visible autonomy profiles (beginner/developer/enterprise) | 2d | 6 |
| 8 | Task ledger + `/ops` view (cost per successful task) | 2d | 5 |
| 9 | Run T1–T5 acceptance tasks; publish evidence pack | 1d | 4,5,6 |
| 10 | Installer + signing pipeline | 5d | 7 |

Total ≈ **20.5 focused days** for the P0/P1 spine. Realistic elapsed time solo: **5–6 weeks**, not 3.

## 4. Recommended development sequence

```
Now ──────► Truth + proof (1,2,3,5)  ──►  Agent works (4,9)  ──►  Agent is safe (6,7)
          ──►  Measurable (8)  ──►  Installable (10)  ──►  Public launch  ──►  Money (P3-lite)
```

Rationale: 5 → 8 must precede any public claim, because a launch without cost data wastes the only
first impression you get. 6 → 7 must precede launch, because a security researcher will run the
prompt-injection test on day one, and today it wins.

## 5. Effort and dependencies (summary)

| Band | Effort | Elapsed (solo) | Blocking risk |
| --- | --- | --- | --- |
| P0-A agent works | 10d | 2–3 weeks | Option A/B decision (§4 of Deliverable 4) |
| P0-B safe by default | 5d | 1 week | Windows AppContainer behaviour variance |
| P0-C truth gate | 3d | 3 days, parallel | none |
| P1 installable | 26d | 4–6 weeks | signing certificate/procurement |
| P2 launch | 18d | 3–4 weeks | benchmark honesty (do not over-claim) |
| P3 money | 23d | 6–8 weeks | auth rewrite (tokens die on restart today) |
| P4 enterprise | 40d+ | Q3 2027 | five absent systems |

## 6. What can realistically be demonstrated publicly

**Yes, after the two-day milestone (with P0-B done):**
- One real bug fixed in a real repository: plan shown, two files read, correct file edited, tests green,
  diff approved, cost printed. Recorded in one take.

**Yes, after P1:**
- A non-technical tester installing from a file and shipping a small app without opening a terminal.

**Not yet, and saying so is the differentiator:**
- Multi-file refactors, migrations, enterprise policy, team collaboration, hosting/deploy, non-JS stacks
  in the guided flow.

## 7. What should wait until after launch

| Deferred | Why |
| --- | --- |
| Hosted inference / credits infrastructure | Margin risk before demand is proven; BYOK Pro needs no infra |
| Team collaboration, shared sessions | No auth system that survives a restart |
| Enterprise (SSO, SCIM, DLP, egress) | Requires signing + policy + audit export first |
| Marketplace/skill hub expansion | The repo has 26 skills and 55 tools; discovery, not quantity, is the gap |
| Model/provider expansion beyond 8 | Every provider is a maintenance contract; 8 is already a support burden |
| Fork upstream rebase automation | Worth doing only after the product ships; currently 2d per release |
| Non-technical guided mode | Correct *after* an installer exists — it is the installer's payoff, not a substitute |

---

## 8. Three decisions I need from you

1. **Segment sequencing.** I recommend developer/builder first, non-technical second (guided mode after the
   installer), because the non-technical lane requires hosting + auth + guided UI that do not exist and that
   three funded competitors already own. **Accept, or override with reasoning?**
2. **Option A vs B** for closing the tool gap (Deliverable 4 §4): ship the demo honestly via the existing
   tool loop, or spend 4+ days making the orchestrator authoritative. My recommendation: **A now, B later.**
3. **Launch gate.** I recommend a hard rule: no public launch before a signed installer exists, even if that
   pushes launch by 3 weeks. **Accept, or accept the reputational risk explicitly?**

## 9. What I will not do without your approval

- Write the PRD, user stories or acceptance criteria (next step after this document is approved).
- Touch application code, create implementation PRs, or modify repository memory beyond the PM folder.
- Publish or cite any benchmark number. None exists yet, and fabricated evidence is the one failure mode
  this product cannot survive.
