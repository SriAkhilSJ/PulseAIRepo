# Reviewer notes on the pushed diagnostics (`c558e5c7`)

Verdict accepted: all 5 Phase 1 extras predate the port (your base-worktree run proves it).

Corrections to the root-cause wording, now fixed on this branch:

- **4x `TestFeedbackStore`** — confirmed exactly as you said. `fb_home` set `HOME`; Windows resolves `~`
  from `USERPROFILE`, so the tests read and *appended* `C:\Users\Administrator\.pulseai\context_feedback.jsonl`.
  Fix: the fixture now pins `HOME` + `USERPROFILE` and clears `HOMEPATH`/`HOMEDRIVE`. Your 380-record detail is
  what made it obvious. Not fixed (owner's call, it is outside this port): `src/context/feedback_memory.py`
  ignores `PULSEAI_HOME` while `src/context/file_safety.py` honors it — the state dir has two sources of truth.
- **`test_foreground_terminal_observes_session_cancel`** — not "the signal never reaches the subprocess".
  The tool does see the cancellation (it polls every 0.2 s and kills), but on Windows `process.terminate()`
  stops only the `cmd.exe` wrapper; the real `python.exe` child survives holding the stdout/stderr handles, so
  the unguarded `communicate(timeout=5)` afterwards raised `TimeoutExpired`, which the outer handler reported
  as the **300 s timeout text** — visible in your own log's `result = ...timed out after 300s...` local.
  Fix: the cancel branch now tree-kills (`taskkill /F /T` on nt, `killpg` on POSIX) and drains bounded
  (`_CANCEL_DRAIN_TIMEOUT_S = 2.0`) and non-fatally. This is the bug its *timeout* branch had already been
  cured of; the cancel branch was left behind.
- **Process hygiene** — your logs are UTF-16LE (PS 5.1 `Tee-Object`). Not a failure, but they need decoding
  before diffing; the brief now prescribes `Out-File -Encoding utf8` and a BOM check.

Next: pull, re-run Phase 0 + Phase 1 (the gate is now a base-vs-ported SET DELTA, not my Linux list) and
continue into Phase 2. On your host the ported tree should now read **6** failures, not 11. Budget untouched:
you have spent ~0.1 credit.
