#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
LIVE="lab/test3_visual_recovery_live.log"; CONSOLE="lab/test3_visual_recovery_console.out"
WS="/home/user/test3_ws_visual"
rm -f "$LIVE" "$CONSOLE" lab/test3_visual_recovery_killed.txt
setsid env AGENT_ITERATION_BUDGET=18 PULSEAI_AUTO_APPROVE_WRITES=1 \
  PULSEAI_TERMINAL_TIMEOUT=90 SUMMARIZER_LLM= PROVIDER_SAFE_LIMIT=6000 \
  .venv/bin/python lab/run_eval_test3_visual_recovery.py >"$CONSOLE" 2>&1 &
pid=$!; start=$(date +%s); last_lines=0; stale=0
kill_run(){ echo "[WATCHDOG] KILL: $1"; echo "$1" > lab/test3_visual_recovery_killed.txt; kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; sleep 3; kill -KILL -- "-$pid" 2>/dev/null || true; }
while kill -0 "$pid" 2>/dev/null; do
  sleep 30; elapsed=$(( $(date +%s)-start )); lines=$(wc -l <"$LIVE" 2>/dev/null || echo 0); tools=$(grep -c '"type": "tool.call"' "$LIVE" 2>/dev/null || true)
  hero=0; demo=0; shot=0; [ -s "$WS/src/components/ui/hero-futuristic.tsx" ] && hero=1; [ -s "$WS/src/components/ui/demo.tsx" ] && demo=1; [ -s "$WS/screenshots/retest-visual-proof.png" ] && shot=1
  echo "[WATCHDOG] t=${elapsed}s events=${lines} tool_calls=${tools} hero=${hero} demo=${demo} screenshot=${shot}"
  [ "$lines" -le "$last_lines" ] && stale=$((stale+1)) || stale=0; last_lines=$lines
  repeated=$(.venv/bin/python - "$LIVE" <<'PY'
import json,sys,collections
c=collections.Counter()
try:
 for l in open(sys.argv[1]):
  try:e=json.loads(l)
  except:continue
  if e.get('type')=='tool.call':
   p=e.get('payload') or {}; c[(p.get('tool_name'),json.dumps(p.get('tool_args'),sort_keys=True,default=str))]+=1
except OSError:pass
print(max(c.values(),default=0))
PY
)
  if [ "${repeated:-0}" -ge 4 ]; then kill_run "same tool call repeated ${repeated} times"; break; fi
  if [ "$elapsed" -ge 90 ] && [ "$stale" -ge 2 ]; then kill_run "no new events for 60 seconds"; break; fi
  if [ "$elapsed" -ge 180 ] && { [ "$hero" -eq 0 ] || [ "$demo" -eq 0 ]; }; then kill_run "named deliverables missing after 180 seconds"; break; fi
  if [ "$elapsed" -ge 300 ] && [ "$shot" -eq 0 ]; then kill_run "required screenshot missing after 300 seconds"; break; fi
  if [ "$elapsed" -ge 360 ]; then kill_run "hard 360-second cap"; break; fi
done
wait "$pid" 2>/dev/null; rc=$?; echo "[WATCHDOG] process exit=$rc"; tail -n 120 "$CONSOLE" 2>/dev/null || true; exit "$rc"
