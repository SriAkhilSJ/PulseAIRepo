#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
LIVE="lab/test3_believe_live.log"; CONSOLE="lab/test3_believe_console.out"
WS="/home/user/test3_ws_believe"
rm -f "$LIVE" "$CONSOLE" lab/test3_believe_killed.txt
setsid env AGENT_ITERATION_BUDGET=20 PULSEAI_AUTO_APPROVE_WRITES=1 \
  PULSEAI_TERMINAL_TIMEOUT=120 SUMMARIZER_LLM= PROVIDER_SAFE_LIMIT=6000 \
  PUPPETEER_CACHE_DIR=/home/user/.cache/puppeteer \
  .venv/bin/python lab/run_eval_test3_believe.py >"$CONSOLE" 2>&1 &
pid=$!; start=$(date +%s); last_lines=0; stale=0
kill_run(){ echo "[WATCHDOG] KILL: $1"; echo "$1" > lab/test3_believe_killed.txt; kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; sleep 3; kill -KILL -- "-$pid" 2>/dev/null || true; }
while kill -0 "$pid" 2>/dev/null; do
  sleep 30; elapsed=$(( $(date +%s)-start )); lines=$(wc -l <"$LIVE" 2>/dev/null || echo 0); tools=$(grep -c '"type": "tool.call"' "$LIVE" 2>/dev/null || true)
  hero=0; demo=0; shot=0; [ -s "$WS/src/components/ui/hero-futuristic.tsx" ] && hero=1; [ -s "$WS/src/components/ui/demo.tsx" ] && demo=1; [ -s "$WS/screenshots/retest-visual-proof.png" ] && shot=1
  echo "[WATCHDOG] t=${elapsed}s events=${lines} tool_calls=${tools} hero=${hero} demo=${demo} screenshot=${shot}"
  [ "$lines" -le "$last_lines" ] && stale=$((stale+1)) || stale=0; last_lines=$lines
  repeated=$(.venv/bin/python - "$LIVE" <<'PY'
import json,sys,collections
# Only identical observational reads indicate the dangerous no-progress loop.
# Verification may legitimately repeat after each code change.
c=collections.Counter()
try:
 for l in open(sys.argv[1]):
  try:e=json.loads(l)
  except:continue
  if e.get('type')=='tool.call':
   p=e.get('payload') or {}; n=p.get('tool_name')
   if n in {'list_files','read_file','search_code'}:
    c[(n,json.dumps(p.get('tool_args'),sort_keys=True,default=str))]+=1
except OSError:pass
print(max(c.values(),default=0))
PY
)
  if [ "${repeated:-0}" -ge 4 ]; then kill_run "same observational read repeated ${repeated} times"; break; fi
  if [ "$elapsed" -ge 120 ] && [ "$stale" -ge 3 ]; then kill_run "no new events for 90 seconds"; break; fi
  if [ "$elapsed" -ge 240 ] && { [ "$hero" -eq 0 ] || [ "$demo" -eq 0 ]; }; then kill_run "named deliverables missing after 240 seconds"; break; fi
  if [ "$elapsed" -ge 420 ] && [ "$shot" -eq 0 ]; then kill_run "required screenshot missing after 420 seconds"; break; fi
  if [ "$elapsed" -ge 480 ]; then kill_run "hard 480-second cap"; break; fi
done
wait "$pid" 2>/dev/null; rc=$?; echo "[WATCHDOG] process exit=$rc"; tail -n 140 "$CONSOLE" 2>/dev/null || true; exit "$rc"
