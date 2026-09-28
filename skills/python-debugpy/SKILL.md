---
name: python-debugpy
description: "Debug Python: pdb REPL + debugpy remote (DAP)."
version: 1.1.0
author: Hermes Agent, ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, python, pdb, debugpy, breakpoints, dap, post-mortem]
    related_skills: [systematic-debugging, node-inspect-debugger]
---

**Triggers:** pdb, debugpy, python debugger, python debug, breakpoint, post-mortem, step through

# Python Debugger (pdb + debugpy)

## Overview

Three tools, picked by situation:

| Tool | When |
|---|---|
| **`breakpoint()` + pdb** | Local, interactive, simplest. Add `breakpoint()` in the source, run normally, get a REPL at that line. Start here. |
| **`python -m pdb`** | Launch an existing script under pdb with no source edits. |
| **`debugpy`** | Remote / headless / attach to an already-running process. Talks DAP, scriptable, works for long-lived processes (the Crusor bridge, dashboard server). |

**Don't use for:** things `print()` / `logging.debug` solve in under a minute, or what `pytest -vv --tb=long --showlocals` already reveals.

## pdb Quick Reference

| Command | Action |
|---|---|
| `n` / `s` / `r` / `c` | next / step into / return / continue |
| `unt N` | continue until line N |
| `l` / `ll` | source around current line / full function |
| `w` | where (stack) |
| `u` / `d` | up / down the stack |
| `a` | args of current function |
| `p expr` / `pp expr` | print / pretty-print |
| `display expr` | auto-print on every stop |
| `b file:line` / `b func` | breakpoint (`b file:line, cond` conditional; `tbreak` one-shot; `cl N` clear) |
| `!stmt` | execute arbitrary Python (assignments) |
| `interact` | full REPL in current scope (Ctrl+D to exit) |
| `q` | quit |

`interact` is the most powerful — import anything, inspect objects, call methods. Mutate locals with `!x = 42`.

## Recipes

### 1. Local breakpoint

```python
def compute(x, y):
    result = some_helper(x)
    breakpoint()           # drops into pdb here
    return result + y
```

**Remove `breakpoint()` before finishing** — check with `run_terminal("rg -n 'breakpoint\\(\\)' --type py")`.

### 2. Script under pdb (no source edits)

```bash
python -m pdb path/to/script.py arg1 arg2
(Pdb) b path/to/script.py:42
(Pdb) c
```

### 3. Debug a failing pytest test

```bash
python -m pytest tests/test_x.py::test_y -vv --tb=long --showlocals   # first
python -m pdb -c "b tests/test_x.py:57" -c "c" -c "p payload" $(which pytest) tests/test_x.py::test_y
# or drop into post-mortem at the failure:
python -m pytest --pdb tests/test_x.py::test_y
```

### 4. Attach to a long-running process (debugpy)

```bash
pip install debugpy
python -m debugpy --listen 5678 --wait-for-client path/to/server.py   # from start
python -m debugpy --listen 5678 --pid <pid>                            # attach to running
```

Script the DAP session (non-interactive agent loop):

```python
import debugpy
debugpy.listen(("127.0.0.1", 5678))
debugpy.wait_for_client()
```

## With systematic-debugging

Breakpoint debugging is the instrument; the hypothesis loop is the method. State what you expect the value to be BEFORE you look — surprises are the bug signal.

## Integration notes

- Interactive pdb prompts don't fit agent loops well: prefer `--pdb` post-mortem via `run_terminal` with piped commands (`printf 'p locals().keys()\nc\nq\n' | python -m pdb script.py`), or add a temporary `breakpoint()` and pipe commands into the run.
- Never commit `breakpoint()` calls or debugpy listeners.
