# Desktop Agent Instructions — STOP after Windows Validation

**Updated:** 2026-08-25

**Required branch:** `arena/01a03741-pulseairepo`

**Validated repair:** `aaeacc26e192db3ce55f8b7c0a5bb4e9d056ad4f`

**Windows evidence commit:** `9ea6a078`

**Open PR:** #9 — do not merge

> The authorized provider-free Windows validation is complete and consumed. No
> deterministic rerun, provider probe/request, live turn, dependency install,
> source edit, cap increase, PR merge, branch deletion, or Agentic UI work is
> authorized.

## Recorded result

```text
Verdict:              DETERMINISTIC_FAIL
Focused tests:        142/145 passed
Protocol tests:       7/7 passed
Protocol generation:  current
Compilation:           PASS
Diff check:            PASS
Provider probes:       0
Provider requests:     0
```

Evidence:

```text
bench-results\test5-11-completion-repair-validation-windows\
9ea6a078
```

All eight SHA-256 entries in the evidence manifest match.

## Independent classification

The three failures are not all safely dismissible as “environment-specific”:

1. `test_terminal_timeout_env_returns_pivot_message` used POSIX `shlex` quoting
   to build a Windows `cmd.exe` command. This is a test-portability defect.
2. `test_foreground_terminal_observes_session_cancel` had the same quoting
   defect.
3. `test_posix_guard_allows_windows_temp_inside_workspace` exposed a source
   false positive: Pulse rejected native `mkdir temp_app`, despite recommending
   that exact cmd.exe form.

Arena has deterministically repaired both test command construction and the bare
Windows `mkdir` guard. The exact focused suite now passes 145/145 on Arena. That
follow-up is not authorized for another desktop run by this STOP handoff.

The evidence also does not prove 30-second monitoring compliance: `monitor.log`
contains multi-minute gaps and a focused-suite retry. Preserve this fact; do not
rewrite historical evidence.

## Preserve

- `C:\test5-ws-attempt11`
- `bench-results\test5-11-desktop\`
- `bench-results\test5-11-completion-repair-validation-windows\`
- Attempt-5 through Attempt-10 workspaces and evidence

Do not modify or “complete” generated/evidence workspaces.

## Mandatory stop

- No provider traffic.
- No deterministic rerun.
- No evidence edits.
- No source repair on desktop.
- No PR merge or branch deletion.
- No Agentic UI work.
- Wait for explicit founder authorization.

```text
STOPPED — Windows validation independently reviewed
```
