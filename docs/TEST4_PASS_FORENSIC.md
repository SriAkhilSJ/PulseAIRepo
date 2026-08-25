# Test 4 “Pass” Forensic Review

Date: 2026-08-25  
Evidence commit: `bbb756337890f0f9fa7257d324942c4c98d682f3`

## Conclusion

Test 4 did **not** demonstrate a clean autonomous one-run pass. Its final product and browser evidence passed only after deterministic evaluator intervention. The authoritative report, `lab/REPORT_TEST4_RETEST_FINAL.md`, classifies the result as:

| Measure | Result |
|---|---|
| Final product/evidence | PASS |
| Static verification after repair | PASS |
| Browser verification after repair | PASS, 4/4 pages |
| Autonomous one-run benchmark | PARTIAL |
| Zero evaluator intervention | FAIL |
| Uninterrupted run | FAIL |

That distinction explains why Test 4 can have passing screenshots while later attempts fail to create a correct file: the passing Test-4 artifact is not the raw autonomous output.

## What the agent accomplished

The agent started from a prepared scaffold and generated multiple source files. The run used 11 provider calls and recorded 99,270 tokens. Its setup was operationally easier than Test 5: explicit architecture, staged/resumed runs, constrained response batches, and an existing project structure.

## Where the autonomous run failed

The raw completion evidence in `lab/report_test4_retest_completion.json` records:

- malformed or truncated writes;
- a `write_file` call missing its required `path` argument;
- a failed typecheck with unresolved `LayoutProps`;
- exhausted turn budget;
- remote-media loading problems; and
- no successful final browser verification by the agent.

The agent therefore ended with an unverified, incomplete product.

## What produced the final pass

After the provider run ended, the evaluator:

1. applied deterministic source repairs;
2. replaced remote media with local MP4 files; and
3. performed the final static and browser verification without further provider calls.

Those repaired files and screenshots are preserved under `lab/test4_final_artifacts/`. They are valid final-product evidence, but they must not be attributed to autonomous delivery.

## Implication for Test 5

Test 4 does not contradict the Test-5 failures. It demonstrates that a partially generated project could be repaired into a passing product, not that Pulse reliably completed an equivalent task end to end. No deterministic repair in the current branch should be described as a runtime or product PASS until a separately authorized live attempt produces independently reviewed evidence.
