# Test this branch — skills, Plan Mode, MCP

Everything below is copy-paste. Branch: `arena/173f9f1b-pulseairepo`.
Every claim in this document has a command that prints the number it claims.

---

## 1. Pull it

```bash
git fetch origin
git checkout arena/173f9f1b-pulseairepo
git pull --ff-only origin arena/173f9f1b-pulseairepo
git log --oneline -1        # expect 2223ef72 or newer
```

If you are mid-work on another branch, use a worktree instead of switching:

```bash
git worktree add ../pulse-test arena/173f9f1b-pulseairepo
```

**Nothing was pushed to `main`.** This branch is a review target, not a merge.

---

## 2. Three minutes of offline proof (no keys, no network)

```bash
# deps, once
uv sync --group dev

# 2a. the library is structurally clean and actually good
uv run python scripts/audit_skills.py
```

Expect:

```
books: 220   violations: 0   clean: 220
  website-architect   n= 76  mean= 67.3  min= 56  max= 90
  cloud-and-devops    n= 36  mean= 64.8  min= 59  max= 76
  mobile              n= 28  mean= 64.1  min= 57  max= 77
  desktop             n= 20  mean= 64.0  min= 57  max= 80
  data-engineering    n= 29  mean= 62.7  min= 53  max= 76
  ai-ml               n= 31  mean= 62.1  min= 58  max= 74
```

`--strict` exits non-zero on any violation, so CI can use it.

```bash
# 2b. retrieval, both halves, one run
uv run python scripts/bench_skill_retrieval.py
```

Expect:

```
  0 calls           29/30 (97%)   planning prompt already had the book
  1 call bundle     30/30 (100%)  skill_bundle top 3
  1 call search     25/30 (83%)   skills_search top 1
latency             injection ~2 ms mean
MCP                 3 meta-tools, 564 tok of schema per turn (flat)
```

```bash
# 2c. the tests that gate all of it
uv run python -m pytest -q \
  src/tests/test_skill_library_conformance.py \
  src/tests/test_agent_skills_tree.py \
  src/tests/test_skill_library.py \
  src/tests/test_skill_injection_budget.py \
  src/tests/test_skill_completion_loop.py \
  src/tests/test_mcp_meta_tools.py \
  src/tests/test_mcp_session_pool.py \
  src/tests/test_mcp_phase_and_receipts.py \
  src/tests/test_skills_mcp_server.py
```

Expect `128 passed`, 0 failed (measured on this branch).

---

## 3. Prove the phase gate in a terminal (30 seconds, no IDE)

This is the bug the branch exists to fix — Plan Mode never fired.

```bash
CRUSORAI_SKILLS_DEBUG=1 uv run python -c "
from src.context.context_engine import _skills_text
print('PLAN  ->', len(_skills_text({'execution_mode':'plan'}, 'build a multi-tenant SaaS with billing')), 'chars')
print('BUILD ->', len(_skills_text({'execution_mode':'agent','plan':[{'description':'tenant isolation in the backend api'}]}, 'implement step 1')), 'chars')
print('IDLE  ->', len(_skills_text({'execution_mode':'agent'}, 'add retry to the bridge')), 'chars')
"
```

Expect:

```
[skills] plan kit: 12 book(s), ~52000 chars (~13700 tok): website-architect:, mobile-architect:, …
[skills] plan constraints: 7 book(s), ~1800 chars (~470 tok): website-architect, backend-development-architect, …
PLAN  -> 52xxx chars
BUILD -> ~1800 chars
IDLE  -> 0 chars
```

Three phases, three behaviours: Plan gets the stack, build gets the constraints of the
same books, an unplanned turn gets nothing.

---

## 4. In the desktop agent

Build the IDE once (first run only):

```bash
cd desktop/vscode && npm install && npm run compile && cd ../..
```

Launch with a workspace:

```bash
./crusor.sh /path/to/a/scratch/workspace      # Windows: crusor.bat <workspace>
```

Before the first turn, in the terminal that launches it:

```bash
export CRUSORAI_SKILLS_DEBUG=1     # prints what the skills layer injected
export CRUSORAI_MCP_DEBUG=1        # prints MCP catalog/approval/call lines
```

(Windows PowerShell: `$env:CRUSORAI_SKILLS_DEBUG = "1"`)

### Test 4a — Plan Mode fires (the core fix)

1. Toggle the agent to **Plan Mode**.
2. Send: `build a multi-tenant SaaS for field service teams with billing and offline mobile`
3. In the terminal, expect:

```
[skills] plan kit: 12 book(s), 52042 chars (~13695 tok): website-architect:, mobile-architect:,
frontend-development-architect:, backend-development-architect:, api-development-architect:,
database-engineering-architect: …
```

4. **The plan the agent writes must name concerns it was never told about** — tenant
   isolation, the API contract, migrations, auth, rollout. If the plan only talks about
   the features you listed, the kit did not reach it.

### Test 4b — the build turn carries the plan's constraints

1. Approve the plan, let it start executing.
2. Expect, per build turn:

```
[skills] plan constraints: N book(s), ~1800 chars (~470 tok): website-architect, backend-development-architect, …
```

3. Check that the code follows the constraints the plan stated (one writer per table,
   cursor pagination, expand/contract migrations) rather than drifting.

### Test 4c — a task with no plan gets no skills

Send `add retry to the bridge` in agent mode. Expect **no `[skills]` line at all**.

### Test 4d — task completion returns the books

When the turn finishes, the run state carries `skills_returned` (name, path, tier,
verification receipts per book). In a Python test of your own:

```bash
uv run python -c "
from src.agents.skill_manager import SkillManager
r = SkillManager().complete_task('build a multi-tenant SaaS for field service teams', [{'description':'billing'}])
print(r['count'], 'book(s)' )
for b in r['books'][:4]: print(' ', b['name'], '|', b['tier'], '|', (b['receipts'][0][:60] if b['receipts'] else '-'))
"
```

### Test 4e — MCP: three tools, any number of servers

The agent now always has `mcp_servers`, `mcp_tools`, `mcp_call`. Create
`<workspace>/.crusorai/mcp.json`:

```json
{
  "servers": {
    "skills": {
      "command": "python3",
      "args": ["<abs path to repo>/scripts/skills_mcp_server.py"],
      "enabled": true
    }
  }
}
```

Windows: `"command": "python", "args": ["D:/path/to/repo/scripts/skills_mcp_server.py"]`.

Then, in the agent:

1. `what MCP servers do I have?` → `mcp_servers` runs; expect `skills: live, 4 tools cached`
   on the second call.
2. `search the architect library for kafka consumer lag` → `mcp_call(skills, skills_search)`;
   expect `kafka-architect` with `why_matched: kafka, consumer, lag`, in ~100–150 ms cold.
3. Toggle **Plan Mode** and ask it to call a tool that is **not** read-only. Expect:

```
⛔ PHASE_DENIED — Plan Mode: <server>/<tool> is not declared read-only.
```

4. In agent mode the same call returns `APPROVAL REQUIRED` and **does not execute** until
   re-issued with `confirm=True`.

---

## 5. What "good" looks like vs what to send me

| Signal | Good | Send me this if broken |
|---|---|---|
| Plan Mode turn | `[skills] plan kit: 12 book(s)` | the `[skills]` line showing 0–3 books |
| Build turn | `[skills] plan constraints: N book(s)` | no line, or a 13 000-token kit |
| Unplanned task | no `[skills]` line | a kit on "add retry" |
| Plan content | names API, data, auth, rollout | only your feature list |
| `mcp_tools` | names only, no schemas | schemas dumped every turn |
| mutating MCP call | `APPROVAL REQUIRED` | it just ran |
| Plan Mode MCP call | `PHASE_DENIED` | it ran |

---

## 6. Honest limits of this branch

- Book quality is 62–67/100 against the library's own rubric; the rubric's target for a
  fully-templated book is ~85. Structurally clean, not yet dense.
- Retrieval search (`skills_search` top-1) is 83%, not 100%: it is precise-but-literal and
  falls back on a shelf crown. The 0-call and bundle paths are the fast ones.
- MCP is **stdio only**. No HTTP/SSE transport, no `notifications/progress` streaming,
  and `ttlMs`/`cacheScope` hints from servers are ignored (we use our own 300 s TTL).
- No third-party MCP *client* has been run against our server — only our own client.
- The three-model Velona evaluation is deliberately **not** part of this branch. The key
  itself is verified (`Verify provider key` workflow → issue #28).
