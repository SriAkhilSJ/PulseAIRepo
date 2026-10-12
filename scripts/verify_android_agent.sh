#!/usr/bin/env bash
# Verify the Android agent work compiles and its tests pass.
#
# Safe to run: it imports modules and runs pytest. It never builds an APK,
# never touches a device, and writes nothing outside the repo.
#
# Usage:  bash scripts/verify_android_agent.sh
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
fail=0

step() { printf '\n=== %s ===\n' "$1"; }
ok()   { printf '  OK   %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; fail=1; }

step "1. Branch and commit"
git rev-parse --abbrev-ref HEAD
git log --oneline -1

step "2. Python present"
PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then bad "no python interpreter found"; exit 1; fi
ok "$($PY --version 2>&1)"

step "3. Dependencies importable"
if $PY -c "import langchain_core, langgraph" 2>/dev/null; then
  ok "langchain_core + langgraph present"
else
  bad "missing deps — run: $PY -m pip install -r requirements.txt"
  echo "      (on Debian/Ubuntu add --break-system-packages)"
fi

step "4. The four Android tools import"
if $PY - <<'PYEOF' 2>/dev/null
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
  bad "an Android tool failed to import — see the traceback above"
  $PY -c "from src.tools.android_verify import verify_android_app"
fi

step "5. The agent graph binds them"
if $PY - <<'PYEOF'
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
$PY - <<'PYEOF'
from src.tools.toolsets import resolve_toolset_names as resolve
got = set(resolve("build and UI test my Android app"))
want = {"android_doctor", "scaffold_android", "verify_android_app", "android_device"}
print(f"  android task receives: {sorted(want & got)}")
assert want <= got, f"android task is missing {want - got}"
assert "android_device" not in resolve("build me a React dashboard")
PYEOF
[ $? -eq 0 ] && ok "Android tasks get the tools, web tasks do not" || bad "routing check failed"

step "7. Android test suite"
$PY -m pytest src/tests/test_android_capability.py \
              src/tests/test_android_scaffold.py \
              src/tests/test_android_verify.py \
              src/tests/test_android_device.py \
              src/tests/test_android_verification_evidence.py \
              -q -p no:randomly
[ $? -eq 0 ] && ok "android tests pass" || bad "android tests failed"

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
