#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
LIVE="lab/test4_video_heroes_live.log"; CONSOLE="lab/test4_video_heroes_console.out"; WS="/home/user/test4_ws_video_heroes"
rm -f "$LIVE" "$CONSOLE" lab/test4_video_heroes_killed.txt
setsid env AGENT_ITERATION_BUDGET=10 AGENT_TOKEN_BUDGET=100000 \
  PULSEAI_AUTO_APPROVE_WRITES=1 PULSEAI_TERMINAL_TIMEOUT=120 \
  PULSEAI_DISABLE_LONG_TERM_MEMORY=1 SUMMARIZER_LLM= PROVIDER_SAFE_LIMIT=6000 \
  PUPPETEER_CACHE_DIR=/home/user/.cache/puppeteer \
  .venv/bin/python lab/run_eval_test4_video_heroes.py >"$CONSOLE" 2>&1 &
pid=$!; start=$(date +%s); last=0; stale=0
kill_run(){ echo "[WATCHDOG] KILL: $1"; echo "$1" > lab/test4_video_heroes_killed.txt; kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; sleep 3; kill -KILL -- "-$pid" 2>/dev/null || true; }
while kill -0 "$pid" 2>/dev/null; do
  sleep 30; elapsed=$(( $(date +%s)-start )); lines=$(wc -l <"$LIVE" 2>/dev/null || echo 0); tools=$(grep -c '"type": "tool.call"' "$LIVE" 2>/dev/null || true); ai=$(grep -c '"type": "message.agent.start"' "$LIVE" 2>/dev/null || true)
  files=$(find "$WS/src" -type f 2>/dev/null | wc -l || true); shots=$(find "$WS/screenshots" -type f -name 'test4-video-hero-*.png' 2>/dev/null | wc -l || true)
  echo "[WATCHDOG] t=${elapsed}s events=${lines} ai_turns=${ai} tool_calls=${tools} src_files=${files} screenshots=${shots}/4"
  [ "$lines" -le "$last" ] && stale=$((stale+1)) || stale=0; last=$lines
  repeated=$(.venv/bin/python - "$LIVE" <<'PY'
import json,sys,collections
c=collections.Counter()
try:
 for line in open(sys.argv[1]):
  try:e=json.loads(line)
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
  if [ "$elapsed" -ge 180 ] && [ "$files" -lt 5 ]; then kill_run "showcase source still missing after 180 seconds"; break; fi
  if [ "$elapsed" -ge 270 ] && [ "$shots" -lt 4 ]; then kill_run "four browser screenshots missing after 270 seconds"; break; fi
  if [ "$elapsed" -ge 300 ]; then kill_run "hard 300-second cap"; break; fi
done
wait "$pid" 2>/dev/null; rc=$?; echo "[WATCHDOG] process exit=$rc"; tail -n 160 "$CONSOLE" 2>/dev/null || true; exit "$rc"
