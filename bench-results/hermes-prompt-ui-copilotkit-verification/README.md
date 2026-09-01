# Hermes prompt engine + Agent UI → Pulse: verification evidence

Provider-free run. Zero LLM/provider tokens. No API key present in this
environment, so nothing here depends on a metered call.

**Upstream pin:** `NousResearch/hermes-agent @ a9c783f21995723c812dcb2f8ae58bc6a4323e2f`
**Pulse base:** `86eaaae2` (branch `arena/01a0564d-pulseairepo`)
**Run:** 2026-08-31 (UTC) — see the header of each log for the exact timestamp.

## Files

| File | Contents |
|---|---|
| `pytest.log` | the two port suites (57 + 10 tests), then the full backend suite, verbatim output |
| `webview.log` | `npx tsc -b`, `npm test`, `npx vite build`, plus a CSS smoke check against the built stylesheet |
| `hashes.txt` | upstream per-file sha256 at the pin, and sha256 of every ported file (prompt engine, tests, UI, stylesheet) |
| `README.md` | this file |

## Results

### Prompt engine — `src/prompts/hermes/` (9 modules, 2 683 lines of module code)

```
src/tests/test_hermes_prompt_parity.py          59 passed
src/tests/test_hermes_prompt_session_cache.py   10 passed
both, together                                  70 passed (0 skipped; needs $HERMES_REF for the corpus-hash test)
```

What the 59 assert, grouped:

- **fidelity** — 12 guidance/steer blocks (memory, user profile, session search,
  skills, task completion, parallel calls, tool-use enforcement, OpenAI/Google
  execution guidance, the three steer-channel constants) equal
  `localize(upstream_bytes)` and nothing else;
  the identity block differs from upstream only by the self-name swap;
  `CONTEXT_FILE_MAX_CHARS = 20_000`, head/tail `0.7 / 0.2` are upstream's numbers;
  the corpus re-hashes clean against the pinned checkout (skips if absent).
- **branding** — no upstream vendor token anywhere in the corpus, in the assembled
  prompt, or in the emitted plan/learn turn prompts.
- **assembly** — three bands in order, identity first, `Conversation started:` only
  in the volatile band, stable bytes identical across sessions, mode hint volatile.
- **gating** — memory/user-profile/session-search/skills/steer/task-completion/
  parallel blocks follow the *bound* tool set; the per-model table behaves; the
  `execution_guidance` override accepts `"auto" | True | False | list`; a guidance
  line naming an unbound tool is dropped rather than left dangling.
- **context files** — priority chain, single-winner per directory, AGENTS.md
  injected exactly once, frontmatter/BOM stripped, truncation notice text,
  `# Project Context` frame, threat pattern → `BLOCKED`.
- **cache** — `find_stable_prefix(stable + tail) == stable`; the plan marks the
  system prefix and, on LiteLLM-shaped routes, never a tool-part marker.
- **/plan and /learn** — headers, `.pulseai/plans/` filename grammar, task
  inference from context, the skill-tool vs `write_file` branch.

What the 10 session-cache tests assert: the prompt is built **once per session**, a
second turn reuses the identical string, compression and session reset invalidate,
a degraded graph path cannot leak a per-turn prompt, and the kill switch
(`PULSEAI_STABLE_PREFIX=0`) turns the mechanism off without changing the text.

### Backend suite — regression check

```
1203 passed, 6 failed, 3 skipped in 248.35s
```

The 6 failures are pre-existing and unrelated (they reference the deleted `ui/`
tree, plus one Sarvam-request test that fails identically on the pristine base —
verified earlier by `git stash`). The port added 69 tests and removed zero passes.

### Agent UI — `pulse-webview/src/hermes-ui/` (42 files, 7 217 lines incl. stylesheet)

```
npx tsc -b        exit 0
npm test          48 passed (2 files)   # 9 pre-existing + 39 ported-UI tests
npx vite build    ok
CSS smoke         pulse-tool-ticker__reel=1  pulse-scaffold-label=1
                  pulse-diff-line--add=1  pulse-approval__run=1
                  pulse-stable-text__cell=1     (counts inside dist/assets/*.css)
```

The 39 ported-UI tests are provider-free: they mount the real components with a
synthetic transcript and assert DOM — grouping and collapse rules, the
render-cost budget, diff parsing and clamping, bridge-frame replay (flat
`tool_id`/`name`/`arguments`/`result`/`warning`/`diff`, plus `safety_resolved`
clearing a request and unknown frames being no-ops), approval binding to Pulse's
`ApprovalQueue` contract, per-message disclosure persistence, the changed-files
card, and the branding guard over a fully rendered `textContent`.

## What this does **not** claim

- No live provider call was made, so nothing here measures real cache-hit rates or
  streaming cadence against a model. That is the key run.
- Pulse only enables the approval channel on bridge sessions today
  (`approval_channel=True` in `src/bridge/__main__.py`); the ported approval strip
  is verified against that contract, not against a Copilot-tier emission.
- The desktop fork is untouched this round: it inherits the same webview through
  its iframe, which is why no fork edit was needed for parity.
- Renderer gaps that are documented rather than hidden (no Shiki, no codicons, no
  side-diff channel, no Motion spring on `DiffCount`): see
  `src/prompts/hermes/PROVENANCE.md` §7.

## Reproduce

```bash
python3 -m pytest src/tests/test_hermes_prompt_parity.py \
                  src/tests/test_hermes_prompt_session_cache.py -q
python3 -m pytest src/tests -q
cd pulse-webview && npm install && npm test && npx tsc -b && npx vite build
```

Narrative write-up: `../../HERMES_PROMPT_UI_PORT_VERIFICATION.md`.
Provenance, symbol maps, allowed transforms, deviations, NOT-PORTED list:
`../../src/prompts/hermes/PROVENANCE.md`.

## Post-review host findings (same evidence dir, later commits)

The Windows live round (`c558e5c7`) opened Phase 1 with 11 failures where this sandbox showed 6. Baseline at
the pre-port commit `86eaaae2` on that machine showed the same 11, so the port was not implicated — but two
of the host-shaped problems were worth fixing rather than allowing:

- `fb_home` in `src/tests/test_session_engines.py` moved `HOME` only. Windows resolves `~` from
  `USERPROFILE` (then `HOMEDRIVE`+HOMEPATH), so 4 `TestFeedbackStore` tests read *and appended* the real
  user profile's global feedback history. The fixture now pins every home variable, so `~` means `tmp_path`
  on every host.
- `run_terminal`'s **cancel** branch killed only the shell wrapper and then read the pipes unguarded, so a
  surviving grandchild holding stdout/stderr turned a cancellation into the timeout message. Its timeout
  branch had already been cured of exactly this; the cancel branch now tree-kills and drains bounded
  (`_CANCEL_DRAIN_TIMEOUT_S`) and non-fatally.

`src/tests/test_hermes_runtime_values.py::test_foreground_cancel_answers_when_a_grandchild_holds_the_pipes`
emulates the Windows shape anywhere: 5.40s + timeout text before the fix, 0.88s + cancel text after.

**Gate consequence:** a hard-coded "known failures" list is host-specific. Phase 1 of
`DESKTOP_AGENT_LIVE_VERIFICATION_PROMPT_UI.md` now diffs the failure SET against `86eaaae2` on the verifying
machine (read-only `git worktree`, never a stash). Applying that rule to this sandbox after it lost its venv:
`1169 passed / 25 failed / 6 skipped`, of which **19 fail identically at `86eaaae2`** (missing tree-sitter
grammars + PIL) — verified by worktree here, and recorded rather than quietly divided out.

## Second live-round findings (from `c99342df`), and what changed here

Phase 2's prompt-engine checks all PASSed on the real Windows host with the real key: tiers `stable 5074 /
context 184 / volatile 148` chars, marker once in the context tier, `BRAND_HITS: none`, `Platform: ide`, and
**identical stable bytes across two independent dumps** — the session-scoped prefix claim, observed on a live
engine rather than asserted from a fixture.

Two things that round reported as PARTIAL were my brief's fault, not the port's:

- **Phase 2.4 cache plan.** They read `markers=1, tool_part_markers=None` off the LangChain-side metadata for a
  tool-less turn and were told to expect `2 / False` from the *plan* function. Different objects, different
  numbers. `scripts/dump_cache_plan.py` now prints both counters per shape per route with `tool_part_markers`
  left to derive, and the gate is the **flip** (`custom`+base URL → `False`, plain `openai` → `True`), not a
  wire-count difference — measured `stats_markers=3 / wire_markers=2` on *both* routes for those shapes, so
  expecting 3-vs-2 would have been another invented number. Pinned by
  `test_cache_plan_route_gate_is_derived_and_dumpable` (parity suite is 61 tests, suites total 71).
- **Bridge hang.** Their `q.join()` hang was real and is a product bug, not a prompt one: `EventBus.clear()`
  drained subscriber queues with `get_nowait()` and there was **no `task_done` accounting anywhere in that
  module**, so every removed event left `Queue.join()` waiting on a slot that would never come — and
  `_run_turn` emitted `turn_done` *after* that unbounded join. Fixed at both layers: `EventBus._release`
  pairs every removal, and `_flush_events(q, _EVENT_FLUSH_TIMEOUT_S)` makes the flush bounded so no future leak
  can swallow a terminal frame again (it reports `runtime_degraded: event queue flush incomplete: N` instead).
  Caveat, stated plainly: `clear()` is the only unpaired removal I could find in-tree, and it is called from
  dashboard preflight/mock_agent — not obviously from a standalone `python -m src.bridge`, so I have not proven
  that this is the exact producer their host hit. What is proven: the accounting bug exists (a 60 s hang
  reproduced here, then instant `join()` after the fix), and a stranded queue can no longer eat `turn_done`.
  `PULSEAI_BRIDGE_DIAGNOSTICS=1` is now prescribed for live turns, so if any strand remains the 60 s
  faulthandler dump names the producer for free.

Pre-fix control note, so nobody over-reads the tests: on the unpatched tree
`test_turn_done_survives_a_undrained_event_queue` fails *fast* (it asserts on a constant the old module does
not define), not by hanging; the hang evidence is the two `clear()` accounting tests plus my direct repro.
