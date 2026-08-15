#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
LIVE="lab/test4_direct_final_live.log"; CONSOLE="lab/test4_direct_final_console.out"; WS="/home/user/test4_ws_video_heroes"
rm -f "$LIVE" "$CONSOLE" lab/test4_direct_final_killed.txt
setsid env AGENT_ITERATION_BUDGET=6 AGENT_TOKEN_BUDGET=80000 PULSEAI_AUTO_APPROVE_WRITES=1 PULSEAI_TERMINAL_TIMEOUT=120 PULSEAI_DISABLE_LONG_TERM_MEMORY=1 SUMMARIZER_LLM= PROVIDER_SAFE_LIMIT=6000 PUPPETEER_CACHE_DIR=/home/user/.cache/puppeteer .venv/bin/python lab/run_eval_test4_direct_final.py >"$CONSOLE" 2>&1 &
pid=$!; start=$(date +%s); last=0; stale=0
kill_run(){ echo "[WATCHDOG] KILL: $1"; echo "$1" > lab/test4_direct_final_killed.txt; kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; sleep 3; kill -KILL -- "-$pid" 2>/dev/null || true; }
while kill -0 "$pid" 2>/dev/null; do
 sleep 30; elapsed=$(( $(date +%s)-start )); lines=$(wc -l <"$LIVE" 2>/dev/null || echo 0); tools=$(grep -c '"type": "tool.call"' "$LIVE" 2>/dev/null || true); ai=$(grep -c '"type": "message.agent.start"' "$LIVE" 2>/dev/null || true); files=$(find "$WS/src" -type f 2>/dev/null | wc -l || true); shots=$(find "$WS/screenshots" -type f -name 'test4-video-hero-*.png' 2>/dev/null | wc -l || true)
 echo "[WATCHDOG] t=${elapsed}s events=${lines} ai_turns=${ai} tool_calls=${tools} src_files=${files} screenshots=${shots}/4"
 [ "$lines" -le "$last" ] && stale=$((stale+1)) || stale=0; last=$lines
 if [ "$elapsed" -ge 180 ] && [ "$stale" -ge 6 ]; then kill_run "no events for 180 seconds"; break; fi
 if [ "$elapsed" -ge 210 ] && [ "$files" -lt 8 ]; then kill_run "deliverable source missing after 210 seconds"; break; fi
 if [ "$elapsed" -ge 300 ] && [ "$shots" -lt 4 ]; then kill_run "four screenshots missing after 300 seconds"; break; fi
 if [ "$elapsed" -ge 330 ]; then kill_run "hard 330-second cap"; break; fi
done
wait "$pid" 2>/dev/null; rc=$?; echo "[WATCHDOG] process exit=$rc"; tail -n 200 "$CONSOLE" 2>/dev/null || true; exit "$rc"
