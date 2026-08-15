#!/usr/bin/env bash
set -u
cd "$(dirname "$0")/.."
LIVE="lab/test4_retest_live.log"; CONSOLE="lab/test4_retest_console.out"; WS="/home/user/test4_ws_retest"
rm -f "$LIVE" "$CONSOLE" lab/test4_retest_killed.txt
setsid env AGENT_ITERATION_BUDGET=8 AGENT_TOKEN_BUDGET=80000 \
  PULSEAI_PHASE_GUARD=on PULSEAI_DELIVERY_MAX_TOKENS=3072 \
  PULSEAI_LLM_STREAMING=1 PULSEAI_LLM_TIMEOUT=90 \
  PULSEAI_AUTO_APPROVE_WRITES=1 PULSEAI_TERMINAL_TIMEOUT=120 \
  PULSEAI_DISABLE_LONG_TERM_MEMORY=1 SUMMARIZER_LLM= PROVIDER_SAFE_LIMIT=6000 \
  PUPPETEER_CACHE_DIR=/home/user/.cache/puppeteer \
  .venv/bin/python lab/run_eval_test4_retest.py >"$CONSOLE" 2>&1 &
pid=$!; start=$(date +%s); last=0; stale=0
kill_run(){ echo "[WATCHDOG] KILL: $1"; echo "$1" > lab/test4_retest_killed.txt; kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true; sleep 3; kill -KILL -- "-$pid" 2>/dev/null || true; }
while kill -0 "$pid" 2>/dev/null; do
 sleep 30; elapsed=$(( $(date +%s)-start )); lines=$(wc -l <"$LIVE" 2>/dev/null || echo 0); tools=$(grep -c '"type": "tool.call"' "$LIVE" 2>/dev/null || true); ai=$(grep -c '"type": "message.agent.start"' "$LIVE" 2>/dev/null || true); files=$(find "$WS/src" -type f 2>/dev/null | wc -l || true); shots=$(find "$WS/screenshots" -type f -name 'test4-video-hero-*.png' 2>/dev/null | wc -l || true)
 phase=$(grep 'RUNTIME EXECUTION PHASE' "$CONSOLE" 2>/dev/null | tail -1 | sed -E 's/.*PHASE: ([A-Za-z_]+).*/\1/' || true)
 echo "[WATCHDOG] t=${elapsed}s events=${lines} ai_turns=${ai}/8 tool_calls=${tools} src_files=${files} screenshots=${shots}/4 phase=${phase:-unknown}"
 [ "$lines" -le "$last" ] && stale=$((stale+1)) || stale=0; last=$lines
 if [ "$ai" -gt 8 ]; then kill_run "provider-turn budget exceeded"; break; fi
 if [ "$elapsed" -ge 180 ] && [ "$files" -lt 8 ]; then kill_run "delivery source missing after 180 seconds"; break; fi
 if [ "$elapsed" -ge 180 ] && [ "$stale" -ge 5 ]; then kill_run "no new events for 150 seconds"; break; fi
 if [ "$elapsed" -ge 300 ] && [ "$shots" -lt 4 ]; then kill_run "four screenshots missing after 300 seconds"; break; fi
 if [ "$elapsed" -ge 330 ]; then kill_run "hard 330-second cap"; break; fi
done
wait "$pid" 2>/dev/null; rc=$?; echo "[WATCHDOG] process exit=$rc"; tail -n 220 "$CONSOLE" 2>/dev/null || true; exit "$rc"
