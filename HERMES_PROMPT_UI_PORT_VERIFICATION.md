# Hermes → Pulse: prompt engine + Agent UI, pinned copy, verified without a provider

**Branch:** `arena/01a0564d-pulseairepo` · **Base:** `86eaaae2`
**Upstream pin:** `NousResearch/hermes-agent @ a9c783f21995723c812dcb2f8ae58bc6a4323e2f` (2026-08-30)
**Method:** provider-free. **Zero LLM/provider tokens were spent.** Every number
below is reproducible with no API key, no runtime URL, and no network.

Scope requested: *"Prompt engineering and Agent UI — pin to pin copy. First on
copilot kit verification… Next changing same inside desktop fork. After all this
done I will verify all at once live using API key."*

---

## Short answer

**Both halves are done and green on the CopilotKit tier.**

- The prompt engine is a pinned copy of upstream's prompt text — 34 constants
  lifted verbatim into a corpus with per-file sha256s, loaded through Pulse's own
  gating, and emitted only after two documented maps (tool rename, brand rewrite).
  `67/67` port tests pass; the full backend suite is `1200 passed` with exactly
  the **6 pre-existing** failures that also fail on the pristine base.
- The Agent UI is ported into `pulse-webview/src/hermes-ui/` (42 files, 7 217
  lines) — tool runs, one-line ticker, expandable diffs, file-edit cards,
  approval strip, plan/verification ledger, timeline rail, DOM render budget —
  and it is bound to **Pulse's** backend (bridge protocol v2 frames, AG-UI
  messages, `ApprovalQueue`), not Hermes'. `48/48` webview tests pass,
  `npx tsc -b` exits 0, `vite build` succeeds, and the ported classes are present
  in the built stylesheet.
- **Branding:** nothing the model or the user can see names the upstream vendor.
  Enforced by tests on both sides — a leak guard over every emitted prompt string,
  and a rendered-`textContent` guard plus a source scan over the UI port.

What is *not* done, by design: the desktop fork change is next round, and the live
key run is yours.

---

## What was verified, and how

### 1. The copy is really a copy

Prompt text lives in exactly one file, `src/prompts/hermes/upstream_corpus.json`,
extracted by executing each upstream module with stubbed imports (AST-literal
extraction silently loses module-scope-computed constants — the ones gating
depends on). Parity is then asserted *byte-wise per constant*:

```python
assert pulse_text == guidance.localize(corpus[CONST])   # for all 12 guidance/steer blocks
```

`test_corpus_sha256_matches_the_pinned_checkout` re-hashes the three upstream
source files against the checkout and skips (never fails) if the pin is absent.

### 2. The copy is bound to Pulse, not to Hermes

| Check | Result |
|---|---|
| Blocks whose tools Pulse lacks are gated off (`memory`, `skill_view`, `skill_manage`, `kanban_*`) | ✅ asserted |
| No unbound tool name in the system prompt **or** the `/plan` and `/learn` turn prompts | ✅ phantom-tool regex guard |
| Tool gating read from `src/tools/toolsets.py` + `src/agents/runtime_profile.py` | ✅ `resolve_valid_tool_names` |
| Per-model guidance gating table (`gpt-5.2`, `grok-4`, `gemini-2.5-pro`, `gemma-3-27b`, `qwen3.6-27b`, `deepseek-v4` enforce; `claude-sonnet-4-5` none) | ✅ asserted |
| Three-band assembly (stable → context → volatile), identity first, timestamp only in volatile | ✅ asserted |
| Stable prefix byte-identical across sessions; `find_stable_prefix(stable + "\n" + volatile) == stable` | ✅ asserted |
| Context-file chain `PULSE.md > AGENTS.md > CLAUDE.md > .cursorrules`, single-winner, AGENTS.md injected once, frontmatter/BOM stripped, `20 000` cap with `70%+20%` head/tail truncation note | ✅ asserted |
| Injection pattern in a loaded file → `BLOCKED` | ✅ asserted |
| Cache plan marks the system prefix and never a tool-part marker on LiteLLM-shaped routes (`openai` → 3 markers on system/user/tool; `custom`+`http://localhost:4000` or Sarvam → 2 markers, `tool_part_markers: False`) | ✅ asserted |
| Session-once build: rebuild only on compression / reset; graph degradation cannot leak a per-turn prompt | ✅ asserted (10 tests) |

### 3. The UI paints, with no runtime

`pulse-webview/src/__tests__/hermes-ui-thread.test.tsx` mounts the real components
from a synthetic transcript built out of **Pulse's** real tool names and **Pulse's**
real event shapes (flat `tool_id` / `name` / `arguments` / `result` / `warning` /
`diff` frames; AG-UI `toolCalls[].id` pairing). 39 tests, including:

- grouping: activity collapses to a summary line, file edits and questions stay
  cards, order preserved, a lone call is not double-headed;
- render budget priced by **what mounts** (`read_file` settled = 1 unit, a diff
  pays per line, a silent tool = 0), `firstVisibleGroupIndex` keeps whole turns
  above the floor, "show earlier" spends the DOM page before the store window;
- the diff renderer drops git headers/hunk markers and keeps `oldNo`/`newNo` in
  order; paint is clamped at `MAX_TOOL_RENDER_CHARS` while Copy keeps the full text;
- normalization: tool results paired by `tool_call_id`, an unanswered call stays
  running, `turn_failed` renders as a failure and not a confident half answer,
  unknown frames are ignored (protocol is additive) — `toBe(state)` identity;
- approvals: the guarded set is Pulse's, the strip answers `once|session|deny`,
  `⌘/Ctrl+Enter` and `Esc` work, and a run blocked on approval stops collapsing
  into the ticker;
- a completed file edit with no diff to review is hidden; a **failed** one stays
  visible and error-toned;
- disclosure state persists across unmount, scoped per message, and a second
  message keeps its own answer;
- the transcript renders user + assistant turns, the `1 file changed` card with
  `+N −M`, and the plan/verification ledger a turn finished with.

```
Test Files  2 passed (2)
Tests      48 passed (48)          # 9 pre-existing + 39 port tests
npx tsc -b                          # exit 0
npx vite build                      # ok; pulse-* classes present in dist CSS
```

### 4. No regressions

`python3 -m pytest src/tests -q` → **1200 passed, 6 failed, 3 skipped**. The 6
failures are the pre-existing ones (`test_desktop_renderer_architecture.py` ×3 and
`test_ui_tool_catalog.py` ×2 reference the deleted `ui/` tree;
`test_ai_node_builds_expected_first_sarvam_request_without_provider_call` fails
identically on the pristine base — confirmed earlier by `git stash`). The port adds
67 tests and removes zero passes.

---

## What the fork gets (next round), and why this round needed no fork edit

The fork renders its agent by embedding this webview in an iframe. The ported UI is
fed by **either** transport and produces one view model, so the fork inherits
parity by pushing bridge frames:

```js
iframe.contentWindow.postMessage({ source: 'pulse-bridge', frame: {
  type: 'tool_call_start', tool_id: 'call_7', name: 'run_terminal',
  arguments: { command: 'pytest -q' } } }, '*');
```

and by answering the approval frame the UI hands back
(`{type:'safety_reply', tool_id, approved, always_allow}` — Pulse's actual inbound
shape, `src/bridge/__main__.py`). The two Pulse affordances that exist on bridge
sessions but not on the Copilot path today — the approval channel
(`approval_channel=True`) and steer/queue turn control — are therefore available to
the fork without new UI. Porting them *into* the fork (native renderer, not iframe)
is the next round's work.

---

## Known limits of what was verified here

1. **No live provider run.** Streaming through a real model (token cadence, cache
   hit rates, Sarvam/NVIDIA endpoint behavior) is deliberately left to the key
   run. This suite proves the prompt bytes, the gating, the cache plan and the DOM;
   it cannot prove a provider accepts the request.
2. **Pulse's Copilot path does not emit approvals today.** The approval strip is
   correct against the bridge contract and harmless otherwise, but it will not
   appear in the CopilotKit tier unless the runtime starts forwarding the request.
3. **Renderer simplifications are real gaps**, listed with reasons in
   `src/prompts/hermes/PROVENANCE.md` §7: no Shiki highlighting, no syntax-diff
   path, no codicons, no spring on `DiffCount`, no `MessageRenderBoundary`, no
   `content-visibility` virtualizer beyond the tail rule. The measurements and
   layout contracts are the upstream ones; the highlighter is not.
4. `vite build` proves nothing about types — `npx tsc -b` was run separately and is
   clean.

---

## Reproduce

```bash
python3 -m pytest src/tests/test_hermes_prompt_parity.py \
                  src/tests/test_hermes_prompt_session_cache.py -q
python3 -m pytest src/tests -q
cd pulse-webview && npm install && npm test && npx tsc -b && npx vite build
```

Raw transcripts of the run behind this commit:
`bench-results/hermes-prompt-ui-copilotkit-verification/` — `pytest.log`,
`webview.log`, `hashes.txt` (upstream per-file sha256 at the pin + sha256 of every
ported file, so a later reader can tell whether a file was touched after the copy).

Full provenance, symbol maps, the two allowed textual transforms, every deviation
and the NOT-PORTED list: `src/prompts/hermes/PROVENANCE.md`.
Related earlier rounds: `COPILOTKIT_VERIFICATION.md`, `AGENT_HANDOFF.md`,
`HERMES_ALIGNMENT_PLAN.md`.
