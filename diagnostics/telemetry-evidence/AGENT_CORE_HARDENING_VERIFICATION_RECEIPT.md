# Agent Core Hardening Verification Receipt

**Date:** 2026-10-23

**Branch:** `arena/a7c2c868-pulseairepo`

**Measured commit:** `9206348d2de43b00edd2fd6d6d1506bc0cea3652`

**Host environment:** Windows (win32), Python 3.14.4, pytest 9.1.1

## 1. Compilation and patch hygiene

The desktop agent reported:

- command: `python -m compileall src scripts`;
- result: zero syntax/compilation errors across `src/` and `scripts/`.

The evidence Markdown whitespace was corrected in the follow-up evidence review.
The final branch is checked with `git diff --check ec7897b5..HEAD`; this receipt
does not preserve the earlier, inaccurate claim that the pre-correction evidence
commit was already whitespace-clean.

## 2. Hardening benchmark

Command:

```bash
python scripts/agent_core_hardening_benchmark.py \
  --writes 200 --cpu-iterations 2000 --scan-runs 8
```

The values below match the committed machine-readable artifact
`agent_core_hardening_benchmark_receipt.json`.

| Metric | Unsafe reference | Hardened | Observed delta |
|---|---:|---:|---:|
| Representative tool-intent payload | 50,165 B | 180 B | **-99.64%** |
| SQLite database after 200 intent writes | 10,137,600 B | 90,112 B | **-99.11%** |
| Body-heavy encode/sanitize median | 259.45 µs | 146.80 µs | **-112.65 µs** |
| Body-heavy durable append median | 10.0045 ms | 2.2229 ms | **-7.7816 ms** on this Windows host |
| Small verification encode/sanitize median | 8.00 µs | 81.80 µs | **+73.80 µs** |
| Small verification durable append median | 1.7389 ms | 1.8209 ms | **+0.0820 ms** |
| Priority scan, 8 shuffled runs | — | 1 unique prefix | deterministic over the fully considered window |
| Provider calls/tokens/cost | 0 / 0 / $0.00 | 0 / 0 / $0.00 | unchanged |

The body-heavy append improvement is an observed host result, not a universal
latency guarantee; omitting roughly 50 KB before SQLite can outweigh sanitizer
CPU on that workload. Small events show the expected local sanitizer overhead.

Security fields in the artifact confirm:

- `before_contains_body: true` → `after_contains_body: false`;
- `before_contains_opaque_secret: true` → `after_contains_opaque_secret: false`;
- `before_contains_prefixed_secret: true` → `after_contains_prefixed_secret: false`.

## 3. Desktop test receipts

These are human-readable desktop-agent command receipts; raw pytest/JUnit logs
were not committed.

1. **Persistence redaction and bounded scan**
   - files: `test_persistence_redaction.py`, `test_bounded_scan.py`;
   - reported result: **37 passed** in 1.43 seconds.

2. **Context budget, masked success, Protocol v2, OTel, and typecheck**
   - files: `test_context_budget.py`, `test_terminal_masked_success.py`,
     `test_bridge_protocol_v2.py`, `test_otel_tracing.py`, and
     `test_typecheck_subdir_project.py`;
   - reported result: **123 passed** in 2 minutes 58 seconds.

3. **Event safety**
   - file: `test_event_safety.py`;
   - reported result: **21 passed** in 1.65 seconds.

**Desktop-reported total:** **181 passed, 0 failed.**

These receipts complement the implementation commit's sandbox validation and
the separate live SQLite evidence. They do not claim a provider-cost reduction,
an end-to-end model-quality score, or retroactive scrubbing of historical rows.
