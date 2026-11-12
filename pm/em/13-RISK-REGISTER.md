# Risk Register — PRD-001

Owner column: who must act. Status values: OPEN / MITIGATED / ACCEPTED / CLOSED.
Reviewed at Day-1 Go/No-Go and at milestone close.

| ID | Risk | L | I | Owner | Trigger to act | Mitigation | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R-01 | Routing engineering into the tool loop exposes hidden coupling in an 8,000-line graph | M | H | Tech Lead | T-02 exceeds 4h | Timebox; fall back to chat-path execution and label it; TL-DR-1 | OPEN |
| R-02 | Total work is ≈42.5h against 16h of elapsed time | H | H | Founder | Day 1 17:00 | Parallel agent sessions per WS; else cut to T2-only reduced scope | **OPEN — highest** |
| R-03 | 273-entry dirty working tree contaminates the implementation branch | H | H | Founder | Before implementation | Disposition via ROADMAP N-2; cut implementation from `origin/main`, not the dirty branch | OPEN |
| R-04 | AppContainer makes `pytest` slow enough to look like a hang | M | M | Security agent | Task >20 min | Measure first; allowlist language runtimes; never disable containment to gain speed | OPEN |
| R-05 | Provider wallet has insufficient credit (repo has recorded ₹0.00 at one point) | M | H | Founder | Before Day 1 09:00 | Verify balance; one reference provider; record spend per run | OPEN |
| R-06 | Agent edits a test to make it pass | M | H | QA | T2 variant | Test-integrity guard (FR-22/36) + held-out AB-6 case | MITIGATED (design) |
| R-07 | Two agents edit the same file concurrently | M | H | EM | Any ticket claims a path outside its WS | Exclusive ownership in `09` §2; one ticket per session | MITIGATED (process) |
| R-08 | Evidence pack leaks a key, path, or proprietary code | L | H | Founder | Before commit/publish | Secret scan; content hashes; redact before publishing | OPEN |
| R-09 | Fixtures drift from "real repo" conditions; demo passes on toy cases only | M | H | QA | Acceptance review | T2 includes 12 files + decoy; state limits next to results | OPEN |
| R-10 | TL decisions arrive late, blocking T-02/T-06/T-10 | M | H | Founder | Day 1 10:00 | Conservative defaults apply automatically; escalate rather than guess | OPEN |
| R-11 | Receipts become a performance cost in the turn loop | L | M | Backend B | Turn latency regression | Append-only async write; never block the turn on disk | OPEN |
| R-12 | Scope creep from "while we're here" fixes during the two days | H | M | EM | New ticket appears mid-milestone | Exclusion list is a contract; new findings go to a backlog file, not into the milestone | MITIGATED (process) |
| R-13 | Upstream Code OSS rebase interacts with UI changes | L | M | Founder | P1 signing work | Keep changes inside `contrib/crusorai/`; never touch `src/vs/**` | MITIGATED (policy) |
| R-14 | Push to GitHub fails (credentials/permissions) | M | L | Founder | Commit step | Report exact error; do not claim success; provide local bundle as fallback | OPEN |

## Top three, in order

1. **R-02 capacity** — the plan is larger than the deadline by design; the Day-1 gate is the only honest control.
2. **R-03 dirty tree** — without disposition, every review of this work includes 84 unrelated files.
3. **R-01 coupling** — the only risk that can invalidate the approved approach itself.

## Accepted risks (explicitly)

| Risk | Why accepted | Revisit |
| --- | --- | --- |
| No checkpoint retention this milestone | Deferred by decision; dev-only DB, not shipped | P1 |
| Enterprise profile absent | Deferred; schema stays extensible | P4 |
| macOS/Linux containment unproven | Windows is the target platform for the fork | P1 |
| No benchmark vs competitors | Needs stable task success first | P2 |
