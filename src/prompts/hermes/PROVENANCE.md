# Provenance — the Hermes pin this port was copied from

Everything under `src/prompts/hermes/` (prompt engine) and
`pulse-webview/src/hermes-ui/` (Agent UI) is a **pin-to-pin copy** of one specific
upstream checkout, remapped onto Pulse's own backend. This file is the record that
makes that claim checkable: the commit, the per-file hashes, the symbol map, the
*only* two textual transformations that are applied, every deliberate deviation,
and the list of upstream things that were **not** ported.

---

## 1. The pin

| | |
|---|---|
| Repo | `NousResearch/hermes-agent` |
| Commit | `a9c783f21995723c812dcb2f8ae58bc6a4323e2f` (`a9c783f`) |
| Commit date | `2026-08-30T22:20:18-07:00` |
| Local checkout used for the copy | `/home/user/.hermes-ref` |
| Extraction tool | `scripts/port_hermes_prompts.py` (265 lines, stdlib only) |
| Extracted at | `2026-08-31T05:48:02Z` |

Verify the pin and the hashes at any time:

```bash
git -C /home/user/.hermes-ref rev-parse HEAD          # a9c783f21995723c812dcb2f8ae58bc6a4323e2f
python3 - <<'PY'
import hashlib, json
from pathlib import Path
ref = Path('/home/user/.hermes-ref')
corpus = json.loads(Path('src/prompts/hermes/upstream_corpus.json').read_text())
for name, meta in corpus['files'].items():
    digest = hashlib.sha256((ref / name).read_bytes()).hexdigest()
    print('OK ' if digest == meta['sha256'] else 'DRIFT', name, digest[:16])
PY
```

`src/tests/test_hermes_prompt_parity.py::test_corpus_sha256_matches_the_pinned_checkout`
runs that same check in CI and **skips** (never fails) when the reference checkout
is absent, so the repo stays testable without the pin on disk.

### Upstream prompt files lifted, with their hashes at the pin

| Upstream file | Lines | Constants lifted | sha256 (first 16) |
|---|---|---|---|
| `agent/prompt_builder.py` | 2471 | 29 | `1fc4b6fc166caf09` |
| `agent/plan_prompt.py` | 103 | 2 | `78fcb5f923c91ff3` |
| `agent/learn_prompt.py` | 237 | 3 | `2ea8b518d9b3db2d` |
| **total** | | **34 constants** | |

Read for structure (not copied as text, because their text is a build algorithm,
not a string): `agent/system_prompt.py` (1164), `agent/prompt_caching.py` (633),
`agent/prompt_cache_boundary.py`, plus the upstream test files that the Pulse test
suites mirror:

| Upstream test | Lines | Mirrored into |
|---|---|---|
| `tests/agent/test_prompt_builder.py` | 1022 | `src/tests/test_hermes_prompt_parity.py` (640 L, 60 tests) |
| `tests/agent/test_system_prompt.py` | 721 | `src/tests/test_hermes_prompt_parity.py` |
| `tests/agent/test_prompt_caching.py` | 884 | `src/tests/test_hermes_prompt_session_cache.py` (178 L, 10 tests) |
| `tests/agent/test_prompt_cache_boundary.py` | 382 | `src/tests/test_hermes_prompt_session_cache.py` |
| `tests/agent/test_plan_prompt.py` / `test_learn_prompt.py` | 84 / 124 | `src/tests/test_hermes_prompt_parity.py` |

---

## 2. How the text was lifted (and why not by AST)

`scripts/port_hermes_prompts.py` **executes each upstream module with its imports
stubbed**, then reads the module namespace. An AST-literal-only extractor silently
drops any constant computed at module scope (a joined guidance block, a frozenset
of model prefixes), which is precisely the set that gating depends on. Tuples and
frozensets are tagged (`{"__tuple__": [...]}` / `{"__set__": [...]}`) so `in`
membership keeps working after a JSON round trip; without the tagging
`TOOL_USE_ENFORCEMENT_MODELS`-style gates silently degrade to "never".

The result, `src/prompts/hermes/upstream_corpus.json` (147 lines), is the *only*
place prompt text lives. It holds `provenance`, `files` (line count + sha256 per
source file), `constants` (the 34 lifted values, verbatim), and `excluded` (7
upstream constants deliberately left behind, each with its reason — see §6).

Because the text is data, `src/tests/test_hermes_prompt_parity.py` can assert the
strongest possible claim: for every localized constant,

```python
assert pulse_text == guidance.localize(corpus_constant_bytes)
```

12 guidance/steer blocks are asserted this way (`VERBATIM_PAIRS`), the identity
block by a self-name-swap diff (`test_identity_differs_only_in_the_self_name_sentence`),
the memory/user-profile pair additionally by `build_memory_guidance`'s composition
(both calls reproduce upstream's constants byte-for-byte), and both help-guidance
variants by `test_both_help_guidance_variants_are_upstream_bytes` — which also
asserts the localized text *differs* from upstream, so an emptied `BRAND_MAP`
could not pass by identity. Which variant a session gets is
`test_help_guidance_variant_follows_the_skills_index`. In all
cases: Pulse's emitted block is byte-equal to upstream's *after* exactly the two
documented maps and nothing else.

---

## 3. Symbol map — prompt engine

Upstream path is relative to the pin's repo root; Pulse path relative to this repo.

| Upstream | Pulse | Fidelity |
|---|---|---|
| `agent/prompt_builder.py::build_system_prompt` | `src/prompts/hermes/system_prompt.py::build_system_prompt_parts` → `{stable, context, volatile}` | verbatim mechanism, 3-band split |
| `agent/prompt_builder.py::build_system_prompt_parts` | `src/prompts/hermes/system_prompt.py` | verbatim |
| `agent/prompt_builder.py::_load_context_files` + priority chain | `src/prompts/hermes/context_files.py::_chain_candidate_paths` | verbatim, Pulse paths |
| `agent/prompt_builder.py::CONTEXT_FILE_MAX_CHARS` (20 000), head/tail 0.7/0.2, 4 chars/token, 0.06 window, 500 000 ceiling | `src/prompts/hermes/context_files.py` (same five numbers, loaded from the corpus) | verbatim constants |
| `agent/prompt_builder.py::_emit_status` truncation warning queue | `src/prompts/hermes/guidance.py::drain_truncation_warnings` | Pulse-adapted (queue → drain, no `_emit_status`) |
| `agent/prompt_builder.py` skills snapshot LRU 32 / `_SKILLS_SNAPSHOT_VERSION=2` | `src/prompts/hermes/skills_index.py` | verbatim numbers |
| `agent/prompt_builder.py::format_tools_for_system_message` | `src/prompts/hermes/guidance.py` | verbatim trajectory shape |
| `agent/system_prompt.py` session-once build + compression-only rebuild | `src/prompts/hermes/session.py` + `src/context/context_engine.py::compress/on_session_reset` | verbatim mechanism |
| `agent/prompt_caching.py` route gate + marker planning | `src/context/prompt_cache_plan.py` (`envelope_tool_part_cache_markers_supported`, `build_prompt_cache_plan(base_url=…, tool_part_markers=…)`) | verbatim, Pulse provider routes |
| `agent/prompt_cache_boundary.py::find_stable_prefix` | `src/context/prompt_cache_boundary.py::{register_stable_prefix,find_stable_prefix,clear_stable_prefixes}` | verbatim |
| `agent/plan_prompt.py` | `src/prompts/hermes/plan_learn.py::plan_turn_prompt` | verbatim, Pulse plan dir |
| `agent/learn_prompt.py` | `src/prompts/hermes/plan_learn.py::learn_turn_prompt` + `retarget_upstream_tools()` | verbatim + tool retarget (§5) |
| identity / `SOUL.md` | `src/prompts/hermes/view.py::PulsePromptView.identity` → `DEFAULT_AGENT_IDENTITY` | Pulse-bound (§4) |
| environment hints (WSL, Windows bash, media) | `src/prompts/hermes/environment.py::mode_hint` | verbatim text, Pulse modes |

### Upstream → Pulse binding points (the "must match Pulse backend" rule)

Every hook reads Pulse reality rather than Hermes' own subsystems:

| Hermes hook | Pulse source of truth |
|---|---|
| which tools exist for gating | `src/tools/toolsets.py::resolve_runtime_tool_names`, `all_known_tool_names`, `web_available`; `src/agents/runtime_profile.py` |
| which model is answering (per-model guidance gates) | `src/config/settings.py` + `src/llm/factory.py` |
| context window / char budgets | `src/context/model_budgets.py::model_window` |
| compression & session reset | `src/context/context_engine.py` |
| injection/threat policy on loaded files | `src/context/threat_patterns.py` |
| memory/skill surfaces | `src/agents/skill_manager.py`, `src/context/custom_instructions.py` |
| persona fallback when the engine emits nothing | `src/prompts/claude_persona.py::system_persona` |
| execution mode / plan mode | `src/graphs/state.py::execution_mode` |
| prompt cache write path | `src/llm/factory.py` + `cache_preservation.py` |
| UI transport | bridge protocol v2 (`src/bridge/protocol_v2.json`, `src/bridge/__main__.py`) and AG-UI via the Copilot Runtime |

A block whose tools Pulse does not have is **gated off**, never left dangling:
Pulse ships 32 `@tool`s and none of them is `memory`, `skill_view`, `skill_manage`
or `kanban_*`, so those guidance blocks do not render (and the test suite asserts
that no unbound tool name survives on *any* emitted surface — system prompt, plan
prompt and learn prompt alike).

---

## 4. The only textual transformations

Two maps, applied in `src/prompts/hermes/guidance.py::localize`, in this exact
order. **Order matters and is load-bearing**: a generic `Hermes Agent → Pulse
Agent` rule applied first defeats the sentence-level rules keyed off the original
sentence, and `HERMES_HOME` must precede `Hermes`.

`RENAME_MAP` — tool names, so guidance points at tools Pulse has:

| Upstream | Pulse |
|---|---|
| `search_files` | `search_code` |
| `delegate_task` | `delegate_to_subagent` |
| `web_extract` | `web_fetch` |
| `use terminal` | `use run_terminal` |
| `the terminal tool` | `the run_terminal tool` |
| `terminal/execute_code` | `run_terminal/execute_code` |
| `` `terminal` `` | `` `run_terminal` `` |

`BRAND_MAP` — branding, so **the model can never see a vendor name that is not
Pulse's** (this is a hard user requirement, not cosmetics):

| Upstream | Pulse |
|---|---|
| `You are Hermes Agent, built by Nous Research.` | `You are Pulse Agent.` |
| `You run on Hermes Agent (by Nous Research).` | `You run on Pulse Agent.` |
| `https://hermes-agent.nousresearch.com/docs` | `https://github.com/SriAkhilSJ/PulseAIRepo` |
| `skill_view(name='hermes-agent')` | `skill_view(name='pulse-agent')` |
| `HERMES_HOME` | `PULSE_HOME` |
| `HERMES_KANBAN` | `PULSE_KANBAN` |
| `.hermes/` | `.pulseai/` |
| `metadata.hermes.` | `metadata.pulse.` |
| `hermes-agent` | `Pulse Agent` |
| `Hermes-tool` | `Pulse-tool` |
| `Hermes tools` | `Pulse tools` |
| `Hermes Agent` | `Pulse Agent` |
| `Nous Research` | `Pulse` |
| `Hermes` | `Pulse` |

No bare `nous → pulse` rule exists on purpose — it corrupts "numerous" and
"dangerous". Instead the leak guard is a test: no upstream brand token may appear
in any emitted prompt, in the identity diff, or in the assembled /plan and /learn
turn prompts. `IDENTITY_SELFNAME_UPSTREAM` / `IDENTITY_SELFNAME_PULSE` make the
identity block's only difference assertable as a name swap.

`plan_learn.py` additionally owns `TOOL_EXAMPLE_REWRITES`, `_REFERENCE_BULLET_RE`,
`_PULSE_REFERENCE_BULLET` and `retarget_upstream_tools()`. The last one is applied
**only when** `skill_manage` / `skill_view` are unbound, replacing upstream's
4-line tool-enumeration bullet (a multi-line literal `str.replace` silently no-ops
on it, which is how `image_generate` once leaked into the learn prompt).

---

## 5. Documented deviations — prompt engine

Each one is a Pulse-backend requirement or a real bug fix, and each is pinned by a
test.

1. **`mode_hint` moved to the volatile band.** Upstream puts the environment hint
   in the stable tier. Pulse's stable prefix is *cached and byte-compared across
   sessions*, so a per-turn mode string there would break the cache in exactly the
   way §7's guard forbids. Test: tier-order (`Conversation started:` and the mode
   hint appear only in `volatile`; the `stable` band starts with the identity).
2. **`ContextEngine._invalidate_stable_prefix` prints instead of logging.**
   `src/context/context_engine.py` has no module-level `logger`; a `logger.warning`
   raised `NameError` inside the invalidation path. Followed that file's existing
   `print(f"[ContextEngine] …")` convention.
3. **Cache-invalidation tests count `build_system_prompt_parts` rebuilds, not
   `build_system_prompt` calls** — the forwarder would make every assertion
   vacuous. Also the graph-degradation test patches `build_system_prompt_parts` to
   raise (patching `system_prompt_for_session` bypasses the internal try/except it
   is meant to exercise).
4. **PULSE.md wins the project-instruction chain** (`PULSE.md > AGENTS.md >
   CLAUDE.md > .cursorrules`, single-winner), and `.pulseai/instructions.md` is
   deduped **by path** so AGENTS.md is injected exactly once.
5. **Plan files land in `.pulseai/plans/`** with upstream's filename grammar
   (`^\.\pulseai/plans/\d{4}-\d{2}-\d{2}_\d{6}-[a-z0-9-]+\.md$`).
6. **`custom` provider opt-in preserved.** `build_prompt_cache_plan` returns
   `{"enabled": False, "reason": "opt-in"}` for `custom` unless
   `PULSEAI_PROMPT_CACHE_CUSTOM=1` — that is pre-existing Pulse behavior, not a
   port bug; the route gate is layered on top of it.
7. **`PULSEAI_STABLE_PREFIX` kill switch** (upstream has none): `src/prompts/hermes/session.py`
   so the whole stable-prefix mechanism can be disabled by env without code edits.

---

## 6. NOT ported — and why

Deliberate absences, so nobody "helpfully" re-adds them later:

**Prompt engine**

| Upstream item | Why absent |
|---|---|
| `KANBAN_GUIDANCE` | Pulse has no kanban server and no `kanban_*` tool. |
| `PLATFORM_HINTS`, `TELEGRAM_RICH_MESSAGES_HINT`, `_LOCAL_CRON_DELIVERY_NOTE`, `hud_surface_note` | messenger/HUD/cron relay surfaces Pulse does not ship (IDE + CLI + CopilotKit webview only). |
| plugin-section framing (`## Plugin Context: <id>` + `<!-- …-chars:N -->`) | Pulse has no plugin-section registry; framing text without a registry would be a lie. |
| `build_memory_guidance` / `execution_guidance_text` as *public* upstream API | reimplemented in `guidance.py` against Pulse's tool gating (`build_memory_guidance(True, True|False, True)` reproduces both upstream constants byte-for-byte, which the test asserts). |
| `_MEDIA_NATIVE` list, cronjob/image/pet/MoA UI surfaces | no Pulse subsystem behind them. |
| `prompt_caching.py`: empty-carrier skipping; builder-declared stable-prefix split for `role:user` skill bodies | upstream-only plumbing (their carrier/skill-body builders do not exist in Pulse). |

**Agent UI** (same pin, `apps/desktop/src/…`)

| Upstream surface | Why absent |
|---|---|
| cronjob / image-generation / pet / MoA renderers, `embeds/*` provider registry (YouTube, Spotify, Twitter…), `clarify-tool`, `mcp-setup-tool`, `agent-delivery`, `preview-embeds`, `widget-shell`, `shiki-*`, `code-editor`, `json-document-editor`, `zoomable-image`, `skeletons`, `vibe-hearts`, `wordmark` | out of scope (the task is prompt engineering + the Agent transcript), or require subsystems Pulse does not have. |
| assistant-ui primitives, nanostores, radix, tailwind 4, shiki, motion | not in `pulse-webview`'s dependency set (React 19.2.8 + CopilotKit 1.69.3 + `@copilotkit/a2ui-renderer` + zod 3.25.76). The port re-expresses their markup and semantics; no new heavy dependency was added. |

---

## 7. The Agent UI port

Same pin, same rule: mechanisms copied 1:1, then bound to Pulse's backend
(`pulse/normalize.ts`) so a component never has to know which transport fed it.
42 files, 7 217 lines including the stylesheet.

| Upstream (`apps/desktop/src/…`) | Lines | Pulse (`pulse-webview/src/hermes-ui/…`) | Lines | Fidelity |
|---|---|---|---|---|
| `tool/fallback-model/types.ts` | 88 | `model/types.ts` | 81 | verbatim |
| `tool/fallback-model/format.ts` | 153 | `model/format.ts` | 156 | verbatim |
| `tool/fallback-model/targets.ts` | 74 | `model/targets.ts` | 79 | verbatim (formatting only) |
| `tool/fallback-model/index.ts` | 1501 | `model/fallback-model.ts` | 730 | reduced: Pulse result shapes; Hermes-only tool branches dropped |
| `tool/run-summary.ts` | 157 | `model/run-summary.ts` | 158 | verbatim |
| `tool/run-ticker.tsx` | 28 | `components/run-ticker.tsx` | 28 | verbatim |
| `tool/fallback.tsx` (`ToolEntry`, `ToolRun`, `ToolGroupSlot`, `splitRunItems`, `useToolRun`, `ToolRunHeader`, `ToolGlyph`, `ToolTitle`, `TerminalTranscript`, `SearchResultsList`, `ToolPayloadDisclosure`, `leadingStatus`) | 1044 | `components/tool-card.tsx` + `components/tool-run.tsx` | 509 + 261 | verbatim mechanisms, Pulse part source |
| `tool/approval.tsx` | 315 | `components/approval-row.tsx` | 170 | reduced: Pulse's `ApprovalQueue` contract |
| `thread/turn-activity.ts` | 60 | `model/turn-activity.ts` | 60 | verbatim |
| `thread/status.tsx` | 270 | `components/status-line.tsx` | 187 | verbatim mechanisms, props instead of session atoms |
| `thread/message-parts.tsx` | 356 | `components/tool-run.tsx` (dispatch) | — | reduced: Hermes-only tool cards dropped |
| `thread/changed-files.ts` + `changed-files-card.tsx` | 69 + 75 | `model/changed-files.ts` + `components/changed-files-card.tsx` | 63 + 78 | verbatim |
| `thread/content.ts` | 63 | `model/content.ts` | 73 | verbatim |
| `thread/timeline-data.ts` | 89 | `model/timeline-data.ts` | 90 | verbatim |
| `thread/transcript-window.tsx` | 34 | `components/transcript-window.tsx` | 35 | verbatim |
| `thread/list.tsx` (pure half: `buildGroups`, `firstVisibleGroupIndex`, `liveTailStart`, budgets) | 816 | `model/render-budget.ts` | 158 | verbatim (React half reduced) |
| `lib/render-weight.ts` | 218 | `model/render-weight.ts` | 179 | verbatim |
| `store/tool-view.ts` | 110 | `model/tool-view.ts` | 192 | ported onto `useSyncExternalStore` (no nanostores) |
| `components/chat/activity-timer.ts` | 115 | `model/activity-timer.ts` | 121 | verbatim, `useViewedInterval` → active-gated interval |
| `components/chat/{status-row,disclosure-row,expandable-block,stable-text,terminal-output,scaffold-row}.tsx` | 79/72/67/23/61/49 | `components/*` (same names) | 55/51/58/23/48/40 | verbatim |
| `components/chat/diff-lines.tsx` | 692 | `components/diff-lines.tsx` | 217 | reduced: color-only renderer (the Shiki path is not portable here) |
| `components/assistant-ui/markdown-text.tsx` | 723 | `components/markdown-text.tsx` | 245 | reduced: line-block parser, no react-markdown/shiki |
| `components/ui/empty-state.tsx` | 24 | `components/empty-state.tsx` | 15 | verbatim role |
| `lib/{tool-render-class,text,summarize-command}`, `hooks/use-resize-observer`, `lib/utils::cn` | — | `lib/*` | 37/28/217/31/7 | verbatim (`cn` is a join: this tier has no tailwind-merge) |
| *(no upstream equivalent — Pulse binding)* | | `pulse/{types,normalize,use-pulse-thread,render-tools}.ts(x)`, `styles/hermes-ui.css`, `index.ts` | 89/419/254/48/1463/63 | **new**: transports + theming + CopilotKit glue |

### UI deviations, numbered

1. **No assistant-ui store.** Rows and runs take `part` + `messageRunning` as
   props, so every component is renderable with zero runtime — which is exactly
   what makes the jsdom suite provider-free.
2. **Approvals answer Pulse's real contract.** Upstream's strip posts
   `approval.respond` over its gateway with a `once|session|always|deny` menu.
   Pulse's is `ApprovalQueue.resolve(tool_id, approved, always_allow, session_id)`
   fed by a flat `{type:'safety_reply', tool_id, approved, always_allow}` frame, so
   the port offers Run / Allow-for-session / Reject and **never** shows an
   "always allow forever" option the backend cannot honor. Delivery is delegated
   to the host (`postMessage` + `pulse:safety_reply` CustomEvent), because the
   queue is stdio-backed and a browser cannot reach it; Pulse also only opens the
   approval channel on bridge sessions today (`src/bridge/__main__.py`), so
   appearing in this tier at all is a runtime decision, not a UI promise.
3. **`APPROVAL_TOOLS` is Pulse's guarded set** — upstream `terminal|execute_code|
   patch|write_file` → `run_terminal|execute_code|write_file|edit_file|copy_file|
   scaffold_nextjs` (chat_graph's mutation set ∪ the shells it danger-guards).
4. **Bridge frames are read FLAT**, matching `BridgeServer._project_event`
   (`tool_id`, `name`, `arguments`, `status`, `result`, `warning`, `diff` at the top
   level), with `{type, payload}` still accepted because the durable journal is
   written that shape before projection. `session_info.events` (a resume) is
   replayed through the same reducer.
5. **No side-diff channel** (`$toolInlineDiff`): a tool card reads its diff from
   the tool result only. No `recordPreviewArtifact` composer feed: a previewable
   target renders as a link.
6. **No Tailwind/Shiki/Codicons/Motion.** Same numbers and same DOM structure live
   in `styles/hermes-ui.css` (7.5rem / 121px collapse, one-line ticker reel, 1ch
   cells, diff tints, hover-revealed trailing slot); icons collapse to the status
   glyph, diffs to the color-only renderer, `DiffCount` renders its integer
   directly instead of springing it.
7. **No `use-stick-to-bottom`, no virtualizer, no per-turn error boundary.** The
   port keeps the budget math (`RENDER_BUDGET=600`, `FIRST_PAINT_BUDGET=20`,
   `BACKFILL_STEP=290`, `MIN_VISIBLE_GROUPS=8`, `LIVE_TAIL_PARTS=40` clamped to
   `[2,6]`), `content-visibility` on off-tail groups, and a "follow only if the
   user was at the bottom" rule. `transcriptPaneBudget` / `shouldClampTranscriptBudget`
   are kept for a host that shows several embeds at once.
8. **Single transcript per tree.** Upstream resolves every signal through
   `useSessionView()` because the fork renders many sessions in parallel; here the
   same signals arrive as `RunSignals` props, and the one cross-tree preference
   (disclosure state) keeps upstream's storage cap and "a storage failure is not an
   error" rule under the key `pulse.webview.toolDisclosure.v1`.
9. **Branding, again at the UI layer.** Upstream strings that name the vendor were
   rewritten (`'Hermes is working'` → `'Pulse is working'`, storage keys
   `hermes.desktop.*` → `pulse.webview.*`, `~/.hermes` paths → `.pulseai/`).
   `pulse-webview/src/__tests__/hermes-ui-thread.test.tsx` has a two-part guard: no brand token outside
   provenance comments in any file in `hermes-ui/`, and no brand token in the
   `textContent` of a fully rendered transcript.

### Where it plugs into the webview

`pulse-webview/src/App.tsx` keeps the stock `CopilotChat` and adds a surface
toggle. `usePulseToolRenderer()` registers a wildcard (`useDefaultRenderTool`)
tool-call renderer, so **even the stock chat paints tool calls with the ported
row** — one tool call cannot look two different ways depending on the surface.
The desktop fork embeds this same webview in an iframe, so the fork gets parity by
feeding bridge frames over `postMessage({source:'pulse-bridge', frame})`; no fork
edit was needed for this round.

---

## 8. How to re-verify (all provider-free, zero tokens)

```bash
python3 -m pytest src/tests/test_hermes_prompt_parity.py \
                  src/tests/test_hermes_prompt_session_cache.py -q   # 70 passed
python3 -m pytest src/tests -q                                        # 1203 passed, 6 pre-existing failures
cd pulse-webview && npm test                                          # 48 passed
cd pulse-webview && npx tsc -b                                        # exit 0
cd pulse-webview && npx vite build                                    # ok
python3 scripts/dump_pulse_prompt.py --workspace . --out /tmp/tiers.json  # the live prompt bytes, 0 tokens
```

Evidence transcripts for the run behind this commit:
`bench-results/hermes-prompt-ui-copilotkit-verification/`
(`pytest.log`, `webview.log`, `hashes.txt`), narrative in
`HERMES_PROMPT_UI_PORT_VERIFICATION.md`.

The live end-to-end run with a real provider key is deliberately not taken here, so
nothing in this directory depends on a metered call. It is specified instead — budget,
gates, per-assertion expectations and the evidence manifest — in
`DESKTOP_AGENT_LIVE_VERIFICATION_PROMPT_UI.md`, which runs on top of the same
`scripts/dump_pulse_prompt.py` (zero-credit prompt bytes) and
`scripts/run_bridge_turn.py` (which owns the credit circuit-breaker).
