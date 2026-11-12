# QA Plan, Security Gates & Release Readiness

Traceable to PRD-001 rev 1.1. Nothing here may be waived to meet the two-day target.

---

## 1. QA operating model

| Principle | Consequence for this milestone |
| --- | --- |
| Author ≠ verifier | The agent that wrote T-02 may not sign AC-1. A separate QA session runs the matrix |
| Evidence over assertion | A screenshot alone is not evidence; it accompanies a log and a receipt |
| No masked failures | `skip`, `xfail`, `|| true`, `set +e` do not count as verification |
| Raw counts, no rates | Per-slice pass/fail counts only; five cases cannot support a percentage |
| Reproducible | Manifest records commit, provider, model, rate-card version, fixture hashes |

## 2. Test layers and entry/exit criteria

| Layer | Entry | Exit criteria |
| --- | --- | --- |
| Unit | Ticket code merged | New test fails before, passes after; suite collects with 0 errors |
| Integration (mocked provider) | WS-A and WS-B merged | Routing, plan gate, blocked semantics verified without network |
| Adversarial | T4/T5 fixtures ready | Injection inert; impossible task reports blocked; test-edit attempt rejected |
| End-to-end (real provider) | All P0 tickets merged | T1–T3 pass rules met on the reference provider |
| Regression | Before acceptance review | Chat/bridge subsets green (FR-6); no new failures vs baseline |
| Long session (nightly, not gating) | After milestone | Memory ≤1.5× baseline over 30 turns; no checkpoint explosion |

## 3. Acceptance execution matrix (owner: QA agent)

| AC | Fixture | Evidence required |
| --- | --- | --- |
| AC-1 read-before-write | T2 | Tool sequence log + `git diff` |
| AC-2 test-in-the-loop | T2 | Failing output + next-turn reference |
| AC-3 plan gate | T2 | Plan card timestamp before first mtime change |
| AC-4 diff rejection | T2 | `git status` clean after reject |
| AC-5 receipt | all | Receipt JSON + provider reconciliation ±10% |
| AC-6 safe defaults | T2 | Prompt capture showing risk/profile/containment |
| AC-7 injection | T4 | No network/shell execution; flag shown |
| AC-8 profile switch | any | DOM assertion before/after |
| AC-9 honest blocking | T5 | `blocked` + no `verified` string |
| AC-10 ledger | synthetic | Cost/success arithmetic incl. failures |
| AC-11 containment | T2 | Sandbox path evidence; refusal path test |
| AC-12 env scrub | T2 | Child env dump without key-like vars |
| AC-13 truth gate | CI | `collect-only` exit 0 + red/green PR pair |
| AC-14 no chat regression | chat prompt | Delegation tests pass; path = chat |

## 4. Security gates (all must pass; none is waivable)

| Gate | Condition | Evidence |
| --- | --- | --- |
| **SG-1** Containment default | Uncontained execution impossible without explicit opt-out | AC-11 test + code path review |
| **SG-2** Env isolation | No provider key reachable from a child process | AC-12 dump |
| **SG-3** Mutation containment | No write outside workspace without grant | Path-containment tests + T4 |
| **SG-4** Approval integrity | Tokens single-use, HMAC-bound; no replay | Existing tests + one negative test |
| **SG-5** Injection inert | Repository instructions never executed | T4 run |
| **SG-6** No false verification | `verified` only with executed check | T5 run + code review |
| **SG-7** Secret hygiene | No key/secret in logs, receipts, diffs, evidence pack | Log scan before commit |
| **SG-8** Self-escalation blocked | Agent cannot edit its own permission config | Test attempt recorded |

**Hard rule:** if a security gate fails and the fix does not fit the milestone, the milestone is reduced.
It is never "documented as a known risk and shipped". Note that this milestone does not ship anything —
that is what D-014 is for.

## 5. Release readiness checklist

Applies to a future signed release, not to this milestone. Recorded now so the gate is not invented later.

| # | Item | Status today |
| --- | --- | --- |
| 1 | Signed + notarised installer (D-014) | **Absent** — no build workflow |
| 2 | Installer bundles runtime (no user venv) | Absent |
| 3 | First-run onboarding (key, workspace, profile) | Absent |
| 4 | Update channel + protocol compatibility check | Absent |
| 5 | Crash reporting, opt-in | Absent |
| 6 | Containment default-on + documented | **In progress (T-10)** |
| 7 | Receipts + usage page | **In progress (T-07/T-08)** |
| 8 | Published limits and known gaps | Drafted (`01-PRODUCT-ASSESSMENT.md`) |
| 9 | Security review of SEC-1…SEC-12 | Pending |
| 10 | Licence + privacy policy | Absent |
| 11 | Support path (issue template, response expectation) | Absent |
| 12 | Rollback plan for a bad build | Absent |

Nothing in this milestone may be described publicly as "release-ready".
