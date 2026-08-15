# Final regression receipt — 2026-08-14

## Result

```text
615 passed in 32.38s
```

## Command

```bash
.venv/bin/python -m pytest src/tests -v --no-header \
  --ignore=src/tests/test_session_engines.py \
  --basetemp=/home/user/pytest-pulse-final-commit
```

This is the README-equivalent project selection requested by the evaluator. It excludes `src/tests/test_session_engines.py` as documented. The run completed with process exit code 0 on Linux with Python 3.13.

The Test-4 final product verdict and autonomous-benchmark caveat remain separate: the repaired product passes static and 4/4 browser verification, while the one-run autonomous benchmark remains partial because intervention was required.
