---
name: node-inspect-debugger
description: "Debug Node.js via --inspect + Chrome DevTools Protocol CLI."
version: 1.1.0
author: Hermes Agent, ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, nodejs, node-inspect, cdp, breakpoints]
    related_skills: [systematic-debugging, python-debugpy]
---

**Triggers:** node inspect, node --inspect, node, node debugger, javascript debugger, cdp debugger, node breakpoint, v8 inspector, debug node

# Node.js Inspect Debugger

## Overview

When `console.log` isn't enough, drive Node's built-in V8 inspector from the terminal: real breakpoints, step in/over/out, call stacks, scope dumps, expression evaluation in the paused frame.

Two tools: **`node inspect`** (built-in, zero install, CLI REPL — prefer first) and **`--inspect` + CDP** (scriptable, for automating breakpoints or attaching to running dev servers like the Crusor webview's Vite server).

## When to Use

- A Node test fails and you need intermediate state
- A Vite/React dev server or Electron main process misbehaves and you can't reproduce with prints
- You need a value from a closure that `console.log` can't reach without patching
- Attach to a running process to capture a CPU profile or heap snapshot

**Don't use for:** things `console.log` solves in under a minute.

## `node inspect` REPL Quick Reference

Launch paused on the first line (all through `run_terminal`):

```bash
node inspect path/to/script.js
node --inspect-brk $(which tsx) path/to/script.ts   # TypeScript via tsx
```

| Command | Action |
|---|---|
| `c` / `n` / `s` / `o` | continue / step over / step into / step out |
| `sb('file.js', 42)` | breakpoint at file.js line 42 (`cb` clears) |
| `bt` | backtrace |
| `list(5)` | 5 lines of source around the current position |
| `watch('expr')` + `watchers` | evaluate expr on every pause |
| `repl` | REPL in current scope — read locals/closures (Ctrl+C to exit) |
| `exec expr` | evaluate once |
| `restart` / `kill` / `.exit` | restart / kill / quit |

## Attaching to a Running Process

```bash
kill -SIGUSR1 <pid>          # enable inspector on an existing Node process
node inspect -p <pid>        # attach the CLI
node --inspect script.js     # or start listening on 127.0.0.1:9229
node --inspect-brk script.js # listen AND pause on first line
```

## Scripted CDP (when the REPL is too slow)

```bash
npm i chrome-remote-interface
node -e "
const CDP = require('chrome-remote-interface');
(async () => {
  const client = await CDP({port: 9229});
  await client.Runtime.enable();
  // set breakpoints, step, evaluate — collect state across runs
  await client.Runtime.evaluate({expression: '1+1'});
})().catch(console.error);
"
```

Rule: prefer `node inspect` first; script CDP only when you need many breakpoints or non-interactive runs.

## With systematic-debugging

This skill is the *instrument*; `systematic-debugging` is the *method*. Form the hypothesis first, then use a breakpoint to prove/disprove it — don't fish.

## Integration notes

- Everything runs through `run_terminal` (guarded); interactive REPLs are awkward in agent loops — prefer `--inspect-brk` + CDP scripting, or `exec`/`watch` commands driven non-interactively via `printf 'sb(42)\nc\nwatchers\n' | node inspect script.js`.
- Never leave `--inspect` enabled in committed start scripts — it's a remote-code-execution port.
