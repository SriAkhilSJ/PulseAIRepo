# Desktop Agent Instructions — STOP after Accepted Windows R3

**Updated:** 2026-08-26

**Required branch:** `arena/01a03741-pulseairepo`

**Source repair:** `0370515cce811dd4d86d14379dd2729a94e640b1`

**Runner fix:** `c6d9c11cc6334f532081c62b8c96ab500bc786ff`

**Accepted evidence:** `1b7ce9e1f48de834451abde7f0d41aaf0fac106e`

**Open PR:** #9 — do not merge

## Accepted deterministic result

```text
Repository:           D:\pulseAIagent\PulseAIRepo
Focused tests:        183/183 passed in 261.97s
Fixture findings:       3/3 detected
Protocol tests:         7/7 passed in 14.27s
Protocol generation:  current
Compilation:           PASS (9 modules)
Diff check:            PASS
Provider probes:       0
Provider requests:     0
Verdict:               DETERMINISTIC_PASS
```

Evidence directory:

```text
bench-results\test5-11-product-delivery-repair-validation-windows-r3\
```

Arena independently confirmed the exact logs, one-shot stage sequence, repair
and runner ancestry, evidence-only commit, all ten SHA-256 entries, and
approximately 30-second focused heartbeat cadence.

The earlier `22b1f8fd` and `b90cb579` evidence remains preserved as failed
validation history. Do not alter or delete it.

## Mandatory stop

- No deterministic rerun.
- No provider probe/request or live Attempt 12.
- No evidence edits.
- No source/test/runner changes.
- No dependency installation or cap increase.
- No PR merge or branch deletion.
- No Agentic UI work.
- Wait for an explicit founder decision.

This proves provider-free Windows deterministic parity only. It is not browser,
live-runtime, or product PASS evidence. Attempt 11 remains product **FAIL**.

```text
STOPPED — no live attempt authorized
```
