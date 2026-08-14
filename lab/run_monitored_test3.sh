#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
LIVE="lab/test3_final_live.log"
CONSOLE="lab/test3_final_console.out"
WS="/home/user/test3_ws_final"
rm -f "$LIVE" "$CONSOLE" lab/test3_final_killed.txt

# Hard cost cap: at most 12 agent iterations, no auxiliary-model summaries.
setsid env \
  AGENT_ITERATION_BUDGET=12 \
  PULSEAI_AUTO_APPROVE_WRITES=1 \
  PULSEAI_TERMINAL_TIMEOUT=60 \
  SUMMARIZER_LLM= \
  PROVIDER_SAFE_LIMIT=6000 \
  .venv/bin/python lab/run_eval_test3_final.py >"$CONSOLE" 2>&1 &
pid=$!
start=$(date +%s)
last_lines=0
stale_checks=0
reason=""

kill_run() {
  reason="$1"
  echo "[WATCHDOG] KILL: $reason"
  printf '%s\n' "$reason" > lab/test3_final_killed.txt
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  sleep 3
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
}

while kill -0 "$pid" 2>/dev/null; do
  sleep 30
  now=$(date +%s); elapsed=$((now-start))
  lines=$(wc -l < "$LIVE" 2>/dev/null || echo 0)
  tools=$(grep -c '"type": "tool.call"' "$LIVE" 2>/dev/null || true)
  hero=0; demo=0
  [ -s "$WS/src/components/ui/hero-futuristic.tsx" ] && hero=1
  [ -s "$WS/src/components/ui/demo.tsx" ] && demo=1
  echo "[WATCHDOG] t=${elapsed}s events=${lines} tool_calls=${tools} hero=${hero} demo=${demo}"

  if [ "$lines" -le "$last_lines" ]; then stale_checks=$((stale_checks+1)); else stale_checks=0; fi
  last_lines=$lines

  repeated=$(.venv/bin/python - "$LIVE" <<'PY'
import json,sys,collections
c=collections.Counter()
try:
    for line in open(sys.argv[1],encoding='utf-8'):
        try: e=json.loads(line)
        except Exception: continue
        if e.get('type')=='tool.call':
            p=e.get('payload') or {}
            key=(p.get('tool_name'),json.dumps(p.get('tool_args'),sort_keys=True,default=str))
            c[key]+=1
except OSError: pass
print(max(c.values(),default=0))
PY
)
  if [ "${repeated:-0}" -ge 3 ]; then
    kill_run "same tool call repeated ${repeated} times"
    break
  fi
  if [ "$elapsed" -ge 90 ] && [ "$stale_checks" -ge 2 ]; then
    kill_run "no new events for 60 seconds"
    break
  fi
  if [ "$elapsed" -ge 180 ] && { [ "$hero" -eq 0 ] || [ "$demo" -eq 0 ]; }; then
    kill_run "named deliverables still missing after 180 seconds"
    break
  fi
  if [ "$elapsed" -ge 300 ]; then
    kill_run "hard 300-second cap reached"
    break
  fi
done

wait "$pid" 2>/dev/null
rc=$?
echo "[WATCHDOG] process exit=$rc"
tail -n 80 "$CONSOLE" 2>/dev/null || true
exit "$rc"
