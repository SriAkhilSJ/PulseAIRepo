# Desktop Agent Instructions — STOP after Deterministic Validation

**Updated:** 2026-08-25

**Required branch:** `arena/01a03741-pulseairepo`

**Repair commit validated:** `0bb00413f4a03b0172c4f6214018bad156fb1d2a`

**Windows evidence commit:** `352099c158b9c70e1ce5ef46f9a17c5020f8cc9d`

**Open PR:** #9 — do not merge

> The authorized provider-free Windows validation is complete. No further
> desktop command, deterministic rerun, provider probe/request, live Test-5
> attempt, cap increase, source repair, PR merge, branch deletion, or Agentic UI
> work is authorized.

## Verified deterministic result

Existing repository checkout:

```text
D:\pulseAIagent\PulseAIRepo
```

Result:

```text
Branch:              arena/01a03741-pulseairepo
Focused tests:       70 collected, 70 passed (26.43s)
Protocol tests:       7 collected, 7 passed (1.71s)
Protocol generation: current
Compilation:          PASS (6 modules)
Provider probes:      0
Provider requests:    0
Verdict:              DETERMINISTIC_PASS
```

Evidence directory:

```text
bench-results\test5-output-limit-repair-validation-windows\
```

This verifies deterministic Windows parity for finish-reason normalization,
bounded empty output-limit continuation, incomplete-tool rejection, bounded
telemetry, runner console/traceback handling, custom-base OpenRouter budget
recognition, bridge protocol generation, and compilation.

It does **not** establish a live runtime or product PASS. Attempt 10 remains
`RUNTIME_FAIL / PRODUCT_FAIL`.

## Independent evidence review

Arena confirmed:

- evidence commit `352099c1` contains only six new validation files;
- its parent is the instruction commit `0e56708c` and repair commit `0bb00413`
  is an ancestor;
- focused and protocol logs contain the reported 70/70 and 7/7 results;
- protocol generation reports current;
- all five hashes listed in `sha256sums.txt` match their committed files when
  the manifest's UTF-8 BOM is handled correctly; and
- the summary records zero provider probes and requests.

Receipt-quality qualifications, preserved rather than rewritten:

- quiet successful compilation produced no tracked `compile.log`; its zero exit
  code and six-module allowlist are recorded in `validation_summary.json`;
- no `monitor.log` was committed (the longest recorded command was 26.43s); and
- the summary start/end timestamps use inconsistent timezone offsets.

These qualifications do not change the deterministic test verdict, but the
evidence must not be overstated as live behavior.

## Preserve exactly

```text
C:\test5-ws-attempt6
C:\test5-ws-attempt8
C:\test5-ws-attempt9
C:\test5-ws-attempt10
bench-results\test5-5\
bench-results\test5-6\
bench-results\test5-8-desktop\
bench-results\test5-stream-parity-validation\
bench-results\test5-stream-parity-validation-followup\
bench-results\test5-9-desktop\
bench-results\test5-10-desktop\
bench-results\test5-output-limit-repair-validation-windows\
/home/user/test5-workspace-attempt7
bench-results/test5-7-arena/
```

`C:\test5-ws-attempt5` remains absent and must not be recreated. Attempt-10
failure evidence commit `e344bc00e6de2961a2695d4fc7cfa7401ad64c87` and the new
Windows validation evidence are immutable.

## Mandatory stop

- No provider traffic or probe.
- No deterministic rerun or evidence edit.
- No source repair or cap change.
- No PR merge or branch deletion.
- No Agentic UI work.
- Wait for explicit founder authorization.

```text
STOPPED — no live attempt authorized
```
