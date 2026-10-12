#!/usr/bin/env bash
# Verify the Android agent work compiles and its tests pass.
#
# Safe to run: it imports modules and runs pytest. It never builds an APK,
# never touches a device, and writes nothing outside the repo.
#
# Usage:  bash scripts/verify_android_agent.sh
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
fail=0

step() { printf '\n=== %s ===\n' "$1"; }
ok()   { printf '  OK   %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; fail=1; }

step "1. Branch and commit"
git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "  (not a git checkout)"
git log --oneline -1 2>/dev/null || true

# ---------------------------------------------------------------------------
# Interpreter discovery.
#
# This must RUN each candidate, not merely check that it exists. On Windows the
# Microsoft Store ships `python3.exe` as an "App Execution Alias" stub that sits
# on PATH, so `command -v python3` succeeds — and then every real invocation
# dies with "Python was not found". An existence check picks that stub and the
# whole script fails five steps later with no clue why.
# ---------------------------------------------------------------------------
step "2. Python interpreter"
PY=()
for candidate in "python3" "python" "py -3"; do
  # shellcheck disable=SC2086
  if $candidate -c "import sys; sys.exit(0)" >/dev/null 2>&1; then
    # shellcheck disable=SC2206
    PY=($candidate)
    break
  fi
done

if [ ${#PY[@]} -eq 0 ]; then
  bad "no working Python interpreter found"
  echo "      Tried: python3, python, py -3"
  echo "      Install Python 3.11+ from https://www.python.org/downloads/"
  echo "      On Windows, untick 'App execution aliases' for python.exe in"
  echo "      Settings > Apps > Advanced app settings, or install from python.org."
  printf '\nRESULT: FAIL — cannot proceed without an interpreter.\n'
  exit 1
fi

PYVER="$("${PY[@]}" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>&1)"
if [ -z "$PYVER" ]; then
  bad "interpreter ran but reported no version"
else
  ok "${PY[*]} -> Python $PYVER"
  # pyproject.toml declares requires-python = ">=3.11"
  if ! "${PY[@]}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    bad "Python $PYVER is below the 3.11 required by pyproject.toml"
  fi
fi

step "3. Dependencies importable"
if "${PY[@]}" -c "import langchain_core, langgraph" >/dev/null 2>&1; then
  ok "langchain_core + langgraph present"
else
  bad "missing deps — install the project with: ${PY[*]} -m pip install -e ."
  echo "      (dependencies are declared in pyproject.toml; there is no requirements.txt)"
  echo "      (on Debian/Ubuntu add --break-system-packages)"
fi

step "4. The four Android tools import"
if "${PY[@]}" - <<'PYEOF'
from src.tools.android_tools import android_doctor
from src.tools.android_scaffold import scaffold_android
from src.tools.android_verify import verify_android_app
from src.tools.android_device import android_device
assert all(callable(t.invoke) for t in
           (android_doctor, scaffold_android, verify_android_app, android_device))
PYEOF
then
  ok "all four tools import and expose .invoke"
else
  bad "an Android tool failed to import — traceback above"
fi

step "5. The agent graph binds them"
if "${PY[@]}" - <<'PYEOF'
from src.graphs.chat_graph import _TOOLS_BY_NAME
from src.tools.toolsets import all_known_tool_names
need = {"android_doctor", "scaffold_android", "verify_android_app", "android_device"}
missing = need - set(_TOOLS_BY_NAME)
phantom = set(all_known_tool_names()) - set(_TOOLS_BY_NAME)
assert not missing, f"not bound: {missing}"
assert not phantom, f"toolset names a tool the graph lacks: {phantom}"
print(f"  bound tools: {len(_TOOLS_BY_NAME)}")
PYEOF
then
  ok "all four are wired into the agent"
else
  bad "wiring check failed"
fi

step "6. Android task routing"
if "${PY[@]}" - <<'PYEOF'
from src.tools.toolsets import resolve_toolset_names as resolve
got = set(resolve("build and UI test my Android app"))
want = {"android_doctor", "scaffold_android", "verify_android_app", "android_device"}
print(f"  android task receives: {sorted(want & got)}")
assert want <= got, f"android task is missing {want - got}"
assert "android_device" not in resolve("build me a React dashboard")
PYEOF
then
  ok "Android tasks get the tools, web tasks do not"
else
  bad "routing check failed"
fi

step "7. Android test suite"
if "${PY[@]}" -m pytest src/tests/test_android_capability.py \
              src/tests/test_android_scaffold.py \
              src/tests/test_android_verify.py \
              src/tests/test_android_device.py \
              src/tests/test_android_verification_evidence.py \
              -q -p no:randomly; then
  ok "android tests pass"
else
  bad "android tests failed"
fi

step "8. What this did NOT prove"
echo "  No APK was built and no device was touched."
echo "  For that, run android_doctor inside Crusor and fix what it lists."

printf '\n'
if [ "$fail" -eq 0 ]; then
  echo "RESULT: PASS — code compiles, tools are wired, tests green."
else
  echo "RESULT: FAIL — see the FAIL lines above."
fi
exit "$fail"
