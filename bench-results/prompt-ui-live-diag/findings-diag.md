## Diagnostic: 5 non-baseline Phase 1 failures

### Root cause verdict: ALL 5 ARE PRE-EXISTING HOST-DEPENDENT FAILURES

Confirmed by worktree comparison at base commit `86eaaae2` — same 5 failures, same symptoms, same local variable values.

### Root cause details

**4× TestFeedbackStore** (`test_session_engines.py`):
The `fb_home` fixture sets `monkeypatch.setenv("HOME", str(tmp_path))`, but on Windows `os.path.expanduser("~")` ignores the `HOME` env var and returns `C:\Users\Administrator` (via `USERPROFILE`). The `ContextEngine` reads from `~/.pulseai/context_feedback.jsonl` which resolves to the real user home, not the test's temp dir. Tests expect to see only their seeded data but instead see the accumulated global feedback history (380+ real task records).

**1× test_foreground_terminal_observes_session_cancel** (`test_hermes_runtime_values.py`):
The test cancels a session after 0.15s, but the terminal tool's 300s timeout fires first on Windows (process wait semantics differ from Linux). The cancellation signal never reaches the subprocess before the timeout fires.

### Evidence files

| File | Content |
|------|---------|
| `fail-test_foreground_terminal_observes_session_cancel.log` | Full traceback with local vars |
| `fail-TestFeedbackStore.log` | All 4 FeedbackStore failures with local vars |
| `base-86eaaae2.log` | Same 5 failures at base commit — confirms pre-existing |
| `ported-full-env.log` | Same 5 failures with Phase 0/1 env |
| `ported-clean-env.log` | Same 5 failures with env stripped — env not the cause |
| `host.txt` | Python 3.14.4, Windows 10.0.26200, NTFS, core.autocrlf=true |
| `blame.txt` | Last 3 commits touching these test files |
| `imports.txt` | Import lines from both test files |
