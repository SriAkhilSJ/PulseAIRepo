# Attempt 11 Completion Repair — Windows Validation Review

Date: 2026-08-25

Evidence commit: `9ea6a078`

Repair tested: `aaeacc26e192db3ce55f8b7c0a5bb4e9d056ad4f`

## Evidence result

```text
Focused:             142/145 passed in 423.03s
Protocol:              7/7 passed
Protocol generation:  current
Compilation:           PASS
Diff check:            PASS
Provider probes:       0
Provider requests:     0
Verdict:               DETERMINISTIC_FAIL
```

The commit adds only the Windows validation directory. All eight files listed in
`sha256sums.txt` match their committed bytes. The repair commit is an ancestor
of the validated head.

## Failure classification

The desktop report's blanket classification of all three failures as
“Windows-specific, not code defects” is too broad.

### Test portability defects

Two tests constructed Python child-process commands using POSIX `shlex` quoting:

- `test_terminal_timeout_env_returns_pivot_message`
- `test_foreground_terminal_observes_session_cancel`

Under `cmd.exe`, the resulting command failed immediately with “filename,
directory name, or volume label syntax is incorrect,” so neither test reached
its timeout/cancellation condition. Tests now use
`subprocess.list2cmdline(argv)` on Windows and `shlex.join(argv)` on POSIX.

### Source false positive

`test_posix_guard_allows_windows_temp_inside_workspace` exposed a real source
problem. `_posix_violations` classified every `mkdir` token as POSIX-only, even
without `-p`. Bare `mkdir` is native cmd.exe syntax and is explicitly recommended
by Pulse's Windows guidance. The guard now permits bare `mkdir` while retaining
rejection of `mkdir -p`.

## Provider-free follow-up

The three failed boundaries plus the five completion-integrity regressions pass
8/8 after repair. The exact focused allowlist passes 145/145 on Arena. No
provider traffic was used.

## Evidence qualifications

- `focused-tests.log` is UTF-16 and contains the final retry output.
- `monitor.log` records a retry and multi-minute gaps, not 30-second heartbeat
  compliance.
- No tracked `git-diff-check.log` exists because successful output was empty;
  the zero exit code is retained in `validation_summary.json`.

## Status

The Windows evidence remains a valid `DETERMINISTIC_FAIL` receipt. It must not
be rewritten. The subsequent provider-free repair requires separate
authorization for any Windows rerun. No live provider attempt, merge, branch
deletion, or Agentic UI work is authorized.
