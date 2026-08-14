#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
LIVE="lab/test3_believe_visual2_live.log"; CONSOLE="lab/test3_believe_visual2_console.out"; WS="/home/user/test3_ws_believe"
rm -f "$LIVE" "$CONSOLE" lab/test3_believe_visual2_killed.txt
setsid env AGENT_ITERATION_BUDGET=8 PULSEAI_DISABLE_LONG_TERM_MEMORY=1 PULSEAI_AUTO_APPROVE_WRITES=1 PULSEAI_TERMINAL_TIMEOUT=120 SUMMARIZER_LLM= PROVIDER_SAFE_LIMIT=6000 PUPPETEER_CACHE_DIR=/home/user/.cache/puppeteer .venv/bin/python lab/run_eval_test3_believe_visual2.py >"$CONSOLE" 2>&1 &
pid=$!; start=$(date +%s); last=0; stale=0
kill_run(){ echo "[WATCHDOG] KILL: $1"; echo "$1" > lab/test3_believe_visual2_killed.txt; kill -TERM -- "-$pid" 2>/dev/null || true; sleep 3; kill -KILL -- "-$pid" 2>/dev/null || true; }
while kill -0 "$pid" 2>/dev/null; do
 sleep 30; elapsed=$(( $(date +%s)-start )); lines=$(wc -l <"$LIVE" 2>/dev/null || echo 0); tools=$(grep -c '"type": "tool.call"' "$LIVE" 2>/dev/null || true); shot=0; [ -s "$WS/screenshots/retest-visual-proof.png" ] && shot=1
 echo "[WATCHDOG] t=${elapsed}s events=${lines} tool_calls=${tools} screenshot=${shot}"
 [ "$lines" -le "$last" ] && stale=$((stale+1)) || stale=0; last=$lines
 if [ "$elapsed" -ge 120 ] && [ "$stale" -ge 3 ]; then kill_run "no events for 90 seconds"; break; fi
 if [ "$elapsed" -ge 180 ] && [ "$shot" -eq 0 ]; then kill_run "screenshot missing after 180 seconds"; break; fi
 if [ "$elapsed" -ge 240 ]; then kill_run "hard 240-second cap"; break; fi
done
wait "$pid" 2>/dev/null; rc=$?; echo "[WATCHDOG] process exit=$rc"; tail -n 120 "$CONSOLE" 2>/dev/null || true; exit "$rc"
