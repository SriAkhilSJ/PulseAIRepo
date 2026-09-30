# Hermes Prompt Engineering — Principles, Crusor Parity, and Gaps

Study of `NousResearch/hermes-agent` prompt assembly (`agent/prompt_builder.py`,
`SOUL.md`, `agent/learn_prompt.py`, `agent/AGENTS.md`) mapped against Crusor's
port (`src/prompts/hermes/`). Written after the skills/media/skill-tools
implementation rounds (Sept 2026). Upstream corpus pin:
`a9c783f2` (2026-08-30) — see `src/prompts/hermes/upstream_corpus.json` provenance.

## 1. The load-bearing laws (hermes AGENTS.md "Message-flow invariants")

1. **The system prompt is byte-stable for the life of a conversation.** Never
   alter past context, change toolsets, reload memories, or rebuild the
   system prompt mid-conversation. The ONLY sanctioned context mutation is
   compression — everything else rides a **user message or tool result**.
2. **Strict role alternation**, with one documented-legal pattern:
   `assistant(tool_calls) → tool → user` for mid-turn user injections
   (steering). Never smear steering onto the persisted tool row.
3. **Prompt cost is paid once and amortized by prefix caching** — universal
   guidance blocks are kept deliberately tight because they ship in the
   cached prefix of every session.
4. **Never let guidance name a tool that is not bound** (hermes #39797: a
   hard "use web_search" dangled in a session without web tools). Guidance
   must match the session's actual toolset.

## 2. Hermes techniques inventory

| Technique | Where | What it does |
|---|---|---|
| SOUL.md identity contract | `SOUL.md`, `load_soul_md` | ~5 lines: directness, no filler, reply length matches ask weight, "finished work gets a short report of what changed, what's verified, what's left". Loads from `~/.hermes/SOUL.md`; user-editable; anti-injection scanned. |
| Universal cached blocks | `prompt_builder.py:383-440` | `TASK_COMPLETION_GUIDANCE` ("Finishing the job" — deliverables are working artifacts backed by real tool output; **never fabricate output**; honest blockers beat invented results). `PARALLEL_TOOL_CALL_GUIDANCE` (batch independent calls — documented cost rationale: one-call-per-turn multiplies resent context). |
| Model-family-conditioned blocks | `prompt_builder.py:348-374` | `TOOL_USE_ENFORCEMENT_GUIDANCE` ("every response = tool calls that progress, or a final result; never end a turn with a promise") only for families that show the failure mode (gpt/codex/gemini/grok/qwen/glm/deepseek/muse…). `OPENAI_MODEL_EXECUTION_GUIDANCE` (no prose math, read-back after external writes, no identifier "repair", verification-gated completion) for another set. Gemini gets its own operational block. **Claude gets none** — conditioning avoids paying tokens where unnecessary and avoids degrading well-behaved models. |
| Skills pull model | `prompt_builder.py:1334+`, `skills_index.py` | Compact `<available_skills>` index (name + ≤60-char description) rides the system prompt; the FULL body loads on demand via `skill_view(name)`; `skill_manage` writes new skills; the curator archives unused agent-created skills. |
| `[SKILL_PRUNED]` compression markers | `SKILLS_GUIDANCE` | When compression drops a skill body, the placeholder says so and the model is told to re-pull with `skill_view` before acting on it. Compression failure becomes recoverable. |
| Skill authoring HARDLINE | `learn_prompt.py` | One `/learn` prompt turns any source into a skill. The 60-char description rule is justified mechanistically: "the index truncates at 60 chars and loads every session — anything past char 60 never routes. COUNT the characters; do not ship a sentence and hope." Anti-hallucination: "NEVER invent flags/paths/APIs — if you didn't see it in the source, don't write it." |
| Context-file discovery + injection scan | `prompt_builder.py:1736+` | AGENTS.md/CLAUDE.md/.cursorrules chain from CWD at startup, head/tail-truncated, capped. Content is **scanned for prompt injection: install-tree files are BLOCKED on a hit, user-authored files WARN and load** — trust-tier-aware. |
| Steer markers | `prompt_builder.py:546-597` | Mid-turn user messages are framed `[OUT-OF-BAND USER MESSAGE]…[/OUT-OF-BAND]` so the model doesn't mistake them for its own reasoning; delivered as a standalone user row. |
| Subdirectory hints | `agent/subdirectory_hints.py` | Per-folder AGENTS.md hints append to the tool result when the agent touches files in that folder (32k cap) — monorepo conventions arrive exactly when relevant. |

## 3. Crusor parity status

| Hermes piece | Crusor port | Status |
|---|---|---|
| Byte-stable prompt discipline | `system_prompt.py::build_system_prompt_parts` (stable/tool/context parts) | ✅ ported |
| SOUL.md identity | `context_files.py::load_soul_md` + `system_prompt.py:96-115` | ✅ ported |
| Universal guidance blocks | `guidance.py` via `upstream_corpus.json` (verbatim + rename map) | ✅ ported |
| Model-conditioned blocks | `guidance.py::needs_tool_use_enforcement/needs_execution_guidance` + `CRUSORAI_TOOL_USE_ENFORCEMENT` env | ✅ ported |
| Skills index (two-layer cache, platform gating) | `skills_index.py` | ✅ ported, extended (user-skill merge, `_skills_lead` pull-vs-inject sentence) |
| `skill_view` / `skills_list` (pull) | `tools/skill_tools.py` | ✅ this branch (laptop round) |
| `skill_manage` (write / learning loop) | `tools/skill_tools.py` | ✅ **this round — was a dangling-guidance gap** |
| D39 curator lifecycle | `agents/skill_manager.py::curator_run` | ✅ pre-existing |
| `[SKILL_PRUNED]` handling | `context/compaction.py:665` | ✅ ported |
| Context files + injection scan | `context_files.py::_scan_context_content` | ✅ ported |
| Steer markers | `guidance.py:258-278` | ✅ ported |
| `/learn` | `prompts/hermes/plan_learn.py` | ✅ ported |
| Subdirectory hints | — | ❌ **not ported** (see gaps) |
| Eager trigger injection | `context/context_engine.py::_skills_layer` (Layer 14) | ⚠️ Crusor-only addition (hermes has no eager injection) |

## 4. Gaps found this round

### GAP 1 — dangling `skill_manage` guidance (FIXED)
`SKILLS_GUIDANCE` (shipped verbatim in the system prompt) tells the model to
"record it with skill_manage for future reuse" — but Crusor only had the read
tools, so the guidance named an unbound tool (hermes law #4 violation, their
#39797 bug class). **Fix:** `skill_manage` implemented in
`src/tools/skill_tools.py` (create/patch/archive; agent-created provenance so
the D39 curator governs lifecycle; bundled repo skills read-only; validation
errors as strings per D17; >60-char descriptions stored in full with a
house-style note). The `_skills_lead` PATCH sentence activates automatically
now that the tool is bound.

### GAP 2 — eager injection vs pull (OBSERVATION, no change)
`_skills_layer` injects matched skill bodies per turn, keyed on
`current_task`. Hermes deliberately does NOT eager-inject: the index rides the
stable prompt and bodies are pulled on demand. Eager injection keyed on a
per-turn task string is (a) prompt-cache pressure as the task text varies,
and (b) redundant once `skill_view` is always bound. Recommendation: keep
eager injection for now (it fires only on trigger matches and the
cache-break audit watches regressions), but the end state hermes-style is
index-in-prompt + pull, with eager injection demoted to at most the single
highest-confidence match — or removed once telemetry (`view_count` vs
`use_count`) shows the pull path is being used.

### GAP 3 — subdirectory hints (FUTURE)
Hermes appends per-directory `AGENTS.md` hints to tool results when the agent
touches files under that directory (head+tail truncated, 32k cap, paths
outside the working dir rejected). For an IDE this is high-value: monorepo
folders carry their own conventions and the agent learns them exactly when
editing there. Port target: a hook in the file/terminal tool result path +
`context_files.py` discovery. Not done this round (touches the tool-result
contract pinned by `test_event_safety.py`).

### GAP 4 — corpus freshness (PROCESS)
`upstream_corpus.json` pins upstream at 2026-08-30. Hermes iterates prompt
text constantly (execution-guidance model lists grow after agentic-eval
traces). Re-run `scripts/port_hermes_prompts.py` against a fresh upstream pin
periodically; the provenance block makes drift auditable.

## 5. Checklist for any future Crusor prompt edit

- Does the byte-stable system prompt stay byte-stable? (No per-turn mutation.)
- Does any guidance sentence name a tool that might not be bound? (Gate the
  sentence on the toolset, like `_skills_lead` does.)
- Is the block universal (keep ≤ ~10 lines, it rides every cached prefix) or
  model-conditioned (gate it on the failure mode, not on habit)?
- Are failure recoveries taught in the prompt (`[SKILL_PRUNED]`-style), not
  just enforced in code?
- Are counts/limits in guidance justified mechanistically (the 60-char rule),
  so the model complies instead of paraphrasing?
