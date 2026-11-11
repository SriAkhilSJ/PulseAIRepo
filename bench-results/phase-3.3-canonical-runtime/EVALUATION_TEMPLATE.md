# Coding Benchmark Evaluation Report Template

Run ID:
Commit:
Branch:
Date / operator:
Machine / OS / Python:
Agent under test:
Provider / model / pricing version:
Repetitions (N):

## Environment

- Workspace root:
- User-data root:
- Approval policy:
- Timeout / token ceiling:
- Paid calls authorized: yes/no (if no, run is provider-free and cannot report cost/latency as a market claim)

## Per-task results

| Task | Success | Verification truthful | Scope fidelity | Regression rate | Cost INR | First token ms | Terminal ms | Retries | Notes |
|---|---|---|---|---|---|---|---|---|---|
| B01 | | | | | | | | | |
| B02 | | | | | | | | | |
| B03 | | | | | | | | | |
| B04 | | | | | | | | | |
| B05 | | | | | | | | | |
| B06 | | | | | | | | | |
| B07 | | | | | | | | | |
| B08 | | | | | | | | | |
| B09 | | | | | | | | | |
| B10 | | | | | | | | | |

## Aggregate

- Task success: __ / 10
- Verification success: __ / 10
- Scope-fidelity violations: __
- Regression rate: __ / __ (__%)
- Settled cost INR/USD:
- Unknown-cost calls:
- First-token p50 / p95:
- Terminal p50 / p95:
- Retries / duplicate-counted invocations:
- Recovery success: __ / __
- Repeated-run pass rate: __ / __ (__%)

## Failure classification

| Failure | Class (new / pre-existing / environment / inconclusive) | Evidence |
|---|---|---|
| | | |

## Claims allowed by this run

- What the measurements support:
- What they do **not** support (no cross-provider or market-superiority claim without matched runs):

## Attachments

- Raw transcripts:
- Receipts:
- Workspace diffs:
- Screenshots:
- SHA-256 manifest:
