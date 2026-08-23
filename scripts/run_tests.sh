#!/usr/bin/env bash
# PulseAI hermetic test runner (adopted from hermes-agent's run_tests.sh).
#
# ALWAYS run tests through this wrapper — not bare pytest. It enforces the
# environment parity that keeps "works locally" equal to "works anywhere":
#
#   1. PROVIDER KEYS UNSET — no test can ever make a paid API call.
#   2. FRESH HOME per run — ~/.pulseai state (sessions.db, runtime_events.db,
#      code indexes, memories) can never leak between runs or into the
#      developer's real machine. This kills the cross-run pollution class at
#      the TEST level (the benchmark measured it live at the product level:
#      7->11->14->17 calls from one reused session id).
#   3. TZ=UTC, LANG=C.UTF-8 — time- and locale-sensitive tests are deterministic.
#
# Opt-outs (deliberate, explicit):
#   PULSEAI_TEST_REAL_HOME=1   keep the real HOME (e.g. warm tiktoken cache)
#   PULSEAI_TEST_KEEP_KEYS=1   keep provider keys (integration scripts ONLY)
#
# Usage:
#   scripts/run_tests.sh                          # full suite
#   scripts/run_tests.sh src/tests/test_bridge.py # one file
#   scripts/run_tests.sh -k workspace             # passthrough pytest args
set -euo pipefail
cd "$(dirname "$0")/.."

# 1. Hermetic credentials (unless explicitly kept for integration work).
if [[ "${PULSEAI_TEST_KEEP_KEYS:-0}" != "1" ]]; then
  unset OPENAI_API_KEY GROQ_API_KEY GEMINI_API_KEY NVIDIA_API_KEY \
        CUSTOM_API_KEY CUSTOM_BASE_URL SARVAM_API_KEY ANTHROPIC_API_KEY \
        2>/dev/null || true
  export LLM_PROVIDER="${LLM_PROVIDER:-}"   # neutral if inherited
fi

# 2. Fresh HOME per run (the pollution guard). Absolute template: the dir is
#    created under TMPDIR (never the repo) and mktemp returns an absolute
#    path, so HOME is valid on GNU and BSD mktemp alike.
if [[ "${PULSEAI_TEST_REAL_HOME:-0}" != "1" ]]; then
  export PULSEAI_TEST_HOME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/pulseai-test-home-XXXXXX")"
  export HOME="$PULSEAI_TEST_HOME_DIR"
  # Keep git usable (some tests call `git ls-files`).
  export GIT_CONFIG_GLOBAL="$HOME/.gitconfig"
fi

# 3. Deterministic environment.
export TZ=UTC
export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONUNBUFFERED=1

cleanup() {
  if [[ -n "${PULSEAI_TEST_HOME_DIR:-}" && -d "$PULSEAI_TEST_HOME_DIR" ]]; then
    rm -rf "$PULSEAI_TEST_HOME_DIR"
  fi
}
trap cleanup EXIT

# Default selection: the engine suite (documented selection excludes the
# procedural legacy files via conftest). Explicit args replace the defaults.
PY="${PULSEAI_TEST_PYTHON:-python}"
if [[ $# -gt 0 ]]; then
  exec "$PY" -m pytest "$@"
fi
exec "$PY" -m pytest -q --no-header src/tests
