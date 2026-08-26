# Desktop Agent Instructions — STOP after Provider-Free Source Repair

**Updated:** 2026-08-26

**Required branch:** `arena/01a03741-pulseairepo`

**Repair validated:** `963eeac0624ed6ff567ca3a3d0b61f2411703a1f`

**Revalidation evidence:** `84b8e35b`

**Open PR:** #9 — do not merge

> The accepted Windows revalidation remains complete. Arena subsequently made
> the separately authorized provider-free product-delivery source repair; it is
> not Windows/browser/live validated. Desktop must remain stopped: no rerun,
> provider probe/request, live turn, dependency install, source change, cap
> increase, PR merge, branch deletion, or Agentic UI work is authorized.

## Accepted deterministic result

```text
Repository:            D:\pulseAIagent\PulseAIRepo
Focused tests:         145/145 passed in 356.15s
Protocol tests:          7/7 passed in 11.14s
Protocol generation:   current
Compilation:            PASS
Diff check:             PASS
Provider probes:        0
Provider requests:      0
Verdict:                DETERMINISTIC_PASS
```

Evidence directory:

```text
bench-results\test5-11-windows-revalidation\
```

## Independent evidence review

Arena confirmed:

- evidence commit `84b8e35b` is a direct child of instruction commit
  `8c9a57a0`;
- repair `963eeac0` is an ancestor of the validated head;
- focused and protocol logs contain the reported pass counts;
- protocol generation, compilation, and diff receipts are green;
- all nine SHA-256 entries match committed bytes; and
- `monitor.log` records an approximately 30-second heartbeat throughout the
  focused command.

This proves deterministic Windows parity for the completion-integrity and
terminal-contract repair. The later verification-reserve/dependency source
repair is documented in `docs/ATTEMPT11_PRODUCT_DELIVERY_REPAIR.md` and has only
provider-free Arena results (183/183 focused; 1013 passed, 3 skipped, four known
unrelated failures full-suite). It does not establish Windows parity, a live
runtime, or product PASS. Attempt 11's delivered product remains FAIL and its
evidence is immutable.

## Preserve

- `C:\test5-ws-attempt11`
- `bench-results\test5-11-desktop\`
- `bench-results\test5-11-completion-repair-validation-windows\`
- `bench-results\test5-11-windows-revalidation\`
- all prior Attempt-5 through Attempt-10 workspaces and evidence

## Mandatory stop

- No provider traffic or live turn.
- No deterministic rerun.
- No evidence edits.
- No desktop source changes or validation of the latest Arena repair.
- No PR merge or branch deletion.
- No Agentic UI work.
- Wait for explicit founder authorization.

```text
STOPPED — deterministic Windows revalidation accepted
```
