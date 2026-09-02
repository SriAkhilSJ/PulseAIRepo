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

## Third live-round findings: their controls beat my theory

They ran the three controls I asked for and the answer is not the one I predicted.

- **The `run_terminal` hang was neither cmd.exe's grandchildren nor CPython 3.14.** `PULSEAI_CHECKPOINTS=off`,
  `PULSEAI_PARALLEL_TOOLS=off` and both-off all still hung, which killed my concurrent-`CreateProcess`
  handle-inheritance hypothesis cleanly. Their process chain (`bridge -> cmd.exe -> python ->
  Python311\python.exe`, all four alive at 25 s) named the real cause: both `Popen` sites in
  `src/tools/terminal_tools.py` set `stdout`/`stderr` and **never set `stdin`**, so the child inherits fd 0 —
  and under the bridge, fd 0 is the client's JSON-RPC pipe. Nothing to do with checkpoints (which already pass
  `stdin=DEVNULL`) or with parallel tools.
  Fix: `stdin=subprocess.DEVNULL` at **both** sites (foreground *and* `start_terminal`, where it is worse than
  a hang — an interactive persistent session inherits the ability to read the client's protocol frames).
  Pinned twice: `test_terminal_children_never_inherit_the_parents_stdin` dup2's an open, never-written pipe onto
  fd 0 and demands the child see an immediate EOF; on the unfixed code it fails with
  `stdin inheritance resurrected the hang after 5.0s` — their symptom, reproduced on Linux in five seconds.
  Plus `test_foreground_popen_passes_devnull_stdin`, a white-box pin on both call sites.
- **Their `test_foreground_cancel_answers_when_a_grandchild_holds_the_pipes` failure was my previous fix being
  incomplete, not host flake**: that test drives `run_terminal`, so it hit the same stdin hang.
- **Two of their three Phase 3 FAILs were my brief inventing interfaces.** `/plan` and `/learn` are not parsed
  at the bridge: `__main__.py:508` reads `frame["mode"]` against `EXECUTION_MODES = {agent, plan, debug, ask}`
  (`protocol.py:10`), and `chat_graph` branches on `ask` (`:798`) and `debug` (`:808`) only — while
  `build_plan_prompt` / `build_learn_prompt` have **no runtime caller** at all (exported at
  `src/prompts/hermes/__init__.py:23`, consumed only by tests). This port is prompt-layer, and the brief now
  says so instead of inviting a false FAIL; wiring it is a `chat_graph` change, deliberately not made here.
  `safety_guard.check_tool_call` inspects **only** `write_file`/`edit_file`/`run_terminal`/`start_terminal`
  (`:49,:67,:73`) and never the prompt text, so "read `.env`, expect BLOCKED" was my fabrication and their
  `search_code` "bypass" is by design. The `copy_file` asymmetry (approval-gated, not guard-gated) is recorded
  as an owner finding, not patched.
- **One repo-wide trap, from their two encoding complaints**: locale-encoded writes.
  `TestFeedbackStore::test_debris_lines_are_skipped_not_fatal` embedded an em-dash written through
  `Path.write_text()` (cp1252 on Windows) against a store that reads `encoding="utf-8"` strict — undecodable
  *only on Windows*, which is why 3 of the 4 FeedbackStore tests went green and this one stayed red. Same class
  as their Phase 5 blocker: `scripts/run_paid_pbr002_guarded.ps1` would not parse for an em-dash with no BOM
  under PS 5.1. Fixtures now write byte-explicit UTF-8 with `newline="\n"`; the `.ps1` carries a BOM.
- Their `Timed out waiting for Pulse Manager editor` was my gate contradicting itself (do not rebuild `.build`,
  yet run a validator that needs a current build). The brief allows exactly one `npm run compile` on that
  symptom, with a note in findings.md.

## Fourth finding: their "slow collection" was my test suite billing their host

Their full-suite run never finished, and the one file that exceeded the 60 s collection timeout was
`src/tests/test_agent_status_checkpoint.py` (every other file landed in 32 s or less). It was not a cold
interpreter and it was not scipy — **that file had no test functions in it at all**. Module scope held
`from src.graphs.chat_graph import get_agent_status, invoke_agent`, a `generated/` mkdir/unlink, and

    response = invoke_agent(message="Create generated/status_checkpoint_test.py ... Run it and verify the output.",
                            provider=LLM_PROVIDER, model=LLM_MODEL, workspace=".", execution_mode="agent")

followed by bare `assert`s. pytest runs module scope **during collection**, before `-k`/`-m` filters and
before any timeout guard, so collecting the suite executed a real multi-step agent turn. Viewed from outside,
that is indistinguishable from "the machine is slow at imports", which is how it was read — and my brief's
standing claim that Phase 1 is a "provider-free baseline (0 credits)" was, on a host healthy enough to have a
working `.env`, simply false. Their run aborted before it billed anything, so the credit ledger is still
correct; the *claim* was not, and that is mine.

Why I did not see it: on this Linux sandbox the same module failed in 0.34 s with
`ModuleNotFoundError: No module named 'langgraph.checkpoint.sqlite'`. The hazard only materialises on a machine
with the full dependency set **and** a configured provider — i.e. exactly the verifier's machine, never the
author's. Any test that is fast-or-erroring on the author's box is untested for the host that matters.

Fix, in that file (`src/tests/test_agent_status_checkpoint.py`): heavy imports moved inside a real
`def test_...`; the target moved to `tmp_path` so the checkout stops being a scratch pad; the thread id is now
unique per run, because a reused id let the *previous* run's checkpoint satisfy `trace_count > 0` on its own;
the duplicated trailing asserts are gone; and the whole test is gated by

    pytestmark = pytest.mark.skipif(os.environ.get("PULSEAI_ALLOW_LIVE_AGENT_TEST") != "1", reason=...)

A test that spends money is opt-in, always. Collection is now side-effect-free and the file is skipped, not
failed, when the gate is closed.

**The class of bug was repo-wide, and my attempt to forbid it lit up immediately.** `src/tests/test_no_import_time_agent_turns.py`
AST-parses every `src/tests/test_*.py` for module-level `invoke_agent`/`stream_agent`/`build_graph`/
`get_agent_status` calls. First run flagged 12 statements in 6 files, all present at base `86eaaae2`:
`test_plan_cancel.py` (3 turns + 1 checkpoint read), `test_plan_revision.py` (3), `test_plan_approval.py` (2),
`test_keep_recovery.py` (1), `test_plan_mode.py` (1), `test_replan_recovery.py` (1) — **11 of them billed
`invoke_agent`/`stream_agent` turns** (the twelfth, `test_plan_cancel.py:51`, is a provider-free
`get_agent_status` read). So `pytest src/tests` on a funded host fires ~11 live agent turns at collection,
*before* any test is selected, any filter applies, or any timeout guard is armed. I did not rewrite six owner-authored tests inside a
verification round. The pin is a **ratchet** instead: `KNOWN_IMPORT_TIME_TURNS` records those exact 6 files,
new offenders fail, and a second assertion pins the turn count at 11 / statement count at 12 and requires the
file set to match, so the debt can only shrink and each conversion must be declared. Both numbers were measured
with a per-file AST count after the fact — my first two drafts said 11 and then 12 for "live turns", having
counted a read-only `get_agent_status` as a turn and, before that, read a truncated `head -8`. An unverifiable
count in an evidence doc is a defect; the count is now derived from the same walk the test uses.

Also theirs-vs-mine: `test_terminal_children_never_inherit_the_parents_stdin` failed on their host for a reason
that was mine twice over. It built the child's command with `shlex.join`, whose single quotes `cmd.exe` reads
literally, so the child died on a quoting error before stdin was ever consulted; it now uses
`subprocess.list2cmdline` on nt and `shlex.join` elsewhere, matching the neighbouring test. And the behavioural
half is `skipif(os.name == "nt")` for a deeper reason: Windows children inherit the parent's *process handles*,
not its CRT file descriptors, so `os.dup2` onto fd 0 is invisible to a child there and the hang cannot be
reproduced on that platform by construction. `test_foreground_popen_passes_devnull_stdin` carries the contract
cross-platform by reading what both `Popen` sites pass. So the `stdin=DEVNULL` fix itself stands exactly as
verified on their host, and the single Windows-only excess failure was my test, not the product: **zero
regressions in the port.**

Totals at this commit, with the pin at `a9c783f2` and `HERMES_REF` reachable: **71 passed / 0 skipped** for the
two port suites; **121 passed / 1 skipped** across bridge transport + both port suites + runtime values +
session engines + the collection-safety pins, in 55 s — the one skip is the gated live turn, by design.
Without a reachable Hermes checkout, `test_corpus_hash_matches_a_pinned_checkout` skips and those read 70/1 and
120/2, which is why the brief names that test explicitly instead of demanding a bare count. Whole-suite
`--collect-only` on this host now finishes in under 2 s.

## Fifth change: the consent rule is now gitignore membership, not a basename list

The owner set the policy: **if git can restore the file, the agent goes alone; if git can't, it asks.** That
replaced my proposal (patch `_is_critical_path` for create-new + add a `copy_file` branch) — same hole, better
predicate. Upstream Hermes is the structural model, not the source of the rule:
`acp_adapter/edit_approval.py::should_auto_approve_edit` gates on the *resolved path* for every mutation tool
and keeps a sensitive-path veto that outranks even autonomous policies, with an `allow_session=False` class that
re-asks every time. `SafetyGuard` now mirrors that shape and swaps the hardcoded `SENSITIVE_AUTO_APPROVE_NAMES`
for the repo's own declaration of privacy.

    ignored by git            -> consent, every time (no session grant accepted)
    tracked / not-ignored     -> no prompt at all
    no git able to answer     -> the previous verdict, byte-for-byte

`git check-ignore` is the oracle (nested `.gitignore`, `.git/info/exclude`, `core.excludesFile`, `!` negations —
everything a hand-rolled matcher gets subtly wrong), and it is deliberately **not** `--no-index`: a
force-committed file is tracked, so git *can* restore it and the rule answers "go" for the right reason.

What got fixed, concretely:

- **The asymmetry is gone.** `write_file`'s critical-path test used to sit inside `if full_path.exists():` *and*
  inside the `PULSEAI_AUTO_APPROVE_WRITES` branch, so it fired in neither ordinary case — creating `.env` was
  free while editing it cost a prompt, i.e. the guard's strength depended on which tool the model picked.
  `copy_file` was never consulted at all, and `chat_graph.py:2816-2821` auto-approves a mutation when
  `approval_policy` is `session`/`workspace_session` *and* nothing flagged it — nothing could. Off the bridge
  there is no approval step either, so `copy_file` had no rail in either direction.
- **`copy_file` is now checked on both sides**, with side-aware wording: reading `.env` into `notes.txt` says
  "this moves the secret somewhere git will track", because a model handed a message about *editing* a file it
  is copying out of cannot route around a warning that mislabels the risk.
- **The D9 nag is deleted** — tracked `tsconfig.json` overwrites no longer interrupt, without the opt-in flag.
- **Autonomous eval keeps its freedom** for git-ignored-but-ordinary paths (`out/`, `dist/`, caches: no human is
  there to answer), while the named-secrets veto never relaxes. `PULSEAI_SAFETY_GITIGNORE=0` returns the whole
  guard to its previous behaviour; both of those are pinned by name in the new suite.

Measured on the current tree: `src/tests/test_safety_guard_consent.py` **18 passed** (real `git init` fixtures,
no mocks — a fixture that re-implemented ignore matching would have tested the fixture). Combined with the
guard's existing contracts — `test_parallel_tools.py` (D11), `test_engine_smoke.py`, `test_ptc.py`,
`test_benchmark_harness.py`, `test_no_import_time_agent_turns.py` — **112 passed / 1 failed**, and that one
failure (`test_autonomous_runtime_contract.py::test_ai_node_builds_expected_first_sarvam_request_without_provider_call`,
a message-ordering assert) reproduces **identically at base `86eaaae2`**, so it is not from this change.
One correction while I was in there: the brief asserted `copy_file` was approval-gated via
`APPROVAL_TOOLS` — that symbol does not exist anywhere in `src/`. The real gate is `mutation_names` at
`src/graphs/chat_graph.py:2812`, so the sentence was rewritten rather than left as a citation of an imaginary
constant (the same failure mode as naming a guard with three tools instead of four).

Cost of consulting git: **2.91 ms per consent check** (one spawned `git check-ignore`), ~30 ms on a
10-write turn; the repo root is cached, the ignore state is not, because a turn can create a `.gitignore`.

## Desktop Agent UI, actually run — engine → runtime → webview

The prompt work kept landing on `pytest`; the UI stayed at "48 jsdom tests + a CDP validator on the founder's
box". So I brought the real stack up here, in order, and verified every hop over HTTP.

| layer | how | result |
|---|---|---|
| engine (AG-UI) | `python -m uvicorn src.server:app --host 0.0.0.0 --port 8123` | up; a full turn streamed `RUN_STARTED → STEP_STARTED/FINISHED ×4 → STATE_SNAPSHOT ×5 → MESSAGES_SNAPSHOT → RUN_FINISHED`, 44 SSE frames, no `RUN_ERROR`, assistant text `## ✅ Finished: …` |
| provider | `scripts/stub_provider_server.py` on :8765, `LLM_PROVIDER=custom`, `CUSTOM_BASE_URL=http://127.0.0.1:8765/v1`, `AUX_LLM_PROVIDER=custom` | **0 credits, 0 keys** — no `.env` exists in this sandbox, and the stub is the only thing the engine could reach |
| runtime | `npm run runtime` (:8200) | `/api/copilotkit/info` → `version 1.69.3, mode sse, agents: pulse_agent, default` |
| webview | `npm run dev` (:5173, already `host: 0.0.0.0`, `allowedHosts: true`, `/api/copilotkit` proxied) | `index.html` + transformed `main.tsx` served; `hermes-ui.css` served (32 244 bytes; `content-type: text/javascript` because vite wraps CSS imports in dev — asserted on rule content, not just 200) |
| render suite | `npx vitest run` | **48 passed (2 files)** — 39 in `hermes-ui-thread.test.tsx`, 9 in `pulse-agent-render.test.tsx` |

What changed as a result of running it rather than reading it:

- **The vitest run had been silently tolerating a dead stack.** With nothing on :8200 it printed
  `connect ECONNREFUSED 127.0.0.1:8200` and `Agent pulse_agent not found` to stderr and **still passed 48/48** —
  correct for fixture tests, but it means a green `npm test` says nothing about integration. With the stack up
  the same run is 48/48 and that stderr is gone. `ui-stack-smoke.log` and `webview-vitest.log` next to this file
  are the two states of that same command.
- **New: `scripts/ui_stack_smoke.mjs`** — browser-free, provider-free, cross-platform (plain `node`, global
  `fetch`), 5 hops in request order, exit 1 with a `fix:` line. Negative controls run, not assumed: pointing
  `--web` at a dead port failed exactly the 3 webview hops (2/5), and pointing `--runtime` at the *engine*
  failed exactly the registration hop (4/5) — the proxy hop stayed green because it has its own target, which is
  the check proving it is not decoration.
- **`App.tsx` was read, not assumed.** It opens on `surface = "agent"` (ported `PulseAgentThread` +
  `PulseComposer`) with stock `CopilotChat` behind the header toggle, both sharing `usePulseToolRenderer` — so
  the Hermes surface is the default, and a claim that the port "isn't wired into the app" would have been wrong.
- **The brief's Phase 4 launch block was missing the key that blocked it.** `validate_pulse_ui_cdp.js:209,215`
  opens Pulse Manager via the command-center / custom title bar, so without `"window.commandCenter": true` +
  `"window.titleBarStyle": "custom"` in the test profile's `settings.json`, `.pulseai-manager-shell` can never
  appear and the phase reports a UI failure for a launch-config reason. Both keys are now in the brief's
  one-liner, with the command-palette route (`pulseai.openManager`) named as the fallback.

**Limit, stated plainly:** this sandbox has **no browser binary** (`which chromium google-chrome firefox` →
nothing) and `npx playwright install chromium` dies on `cdn.playwright.dev` with `ECONNRESET`, so I could not
paint a single pixel or screenshot the window — no `screens/NN-*.png` from me, and I am not going to describe one.
Everything above is DOM-level (jsdom) plus wire-level (SSE/HTTP). The founder's live preview on :5173 renders it
for real, and `scripts/validate_pulse_ui_cdp.js` remains the only pixel-exact gate.
**One trap that cost me a dead preview, so it is written down:** `npm run dev | tail -30` looks harmless and is
not. `tail` withholds output until EOF, so once the pipe buffer fills (~64 KB of vite's transform logs) the
dev server blocks on write and stops answering — the port stays listening while `GET /` returns nothing. It
looked like a broken app; it was my own launcher. Long-lived servers redirect to a file
(`npm run dev > vite.log 2>&1`) and you grep the file. `Tee-Object` in the PowerShell blocks above is fine
because it streams, but `| Select-Object -Last 30` is the same bug as `tail` — never wrap a server in it.

## Desktop-side permission handling, and what the fork's own pins were hiding

Asked whether this works on the laptop and not only in the sandbox, I read the fork contrib
(`desktop/vscode/src/vs/workbench/contrib/pulseai/`) instead of inferring from the webview, and the
written assessment is `DESKTOP_PERMISSION_HANDLING_QUALITY.md`. Highlights, including where I was
wrong mid-investigation:

- **`always_allow` was plumbed end to end and unreachable from the UI.** Protocol carries it,
  `src/bridge/__main__.py:552` honours it, `event_bus.py:145,152` stores it — and `approvalDock`
  sent only `true`/`false`. Every ordinary write re-prompted for the session because no control
  existed to grant it. Now: `Allow once` / `Allow for session` / `Deny`, token-derived green/red,
  icons, and a `title` per button.
- **Two numbers in the file-write card were invented**: a `+12 −4` fallback and an always-present
  `Receipt: syntax valid`. Replaced by counted stats (`diffStats`) and an omitted row. Diff preview
  went from one `<pre>` (no per-line colour possible) to per-line nodes tinted with the editor's own
  `diffEditor` tokens, clamped for paint with an explicit "N more lines" row.
- **`pulseAIViewPane.ts` hardcoded `src='http://localhost:5173'` at `height:50%`.** That is the
  answer to "works in sandbox, blank on my laptop": any packaged build, remote/WSL window, taken
  port, or unstarted dev server shows an empty frame while the native view still gives up half the
  pane. Now `pulseai.copilotWebview.enabled/.url/.height` (declared in `pulseAI.contribution.ts`) plus
  an in-pane unreachable notice with the fix and a Reload, with the watchdog cancelled on dispose.
- **`test_desktop_renderer_architecture.py` was red at base on three pins.** `Review change` and
  `function emptyState` were genuinely missing from the code (the native Agent view had *no* empty
  state) — both now implemented, and the pin's `ui/src` catalog comparison **skips with a stated
  reason** because that tree is not tracked in this repo, so it could never have compared anything.
  One assertion is left deliberately red as an owner decision (next bullet), with the reason inlined.
- **Manager exists twice.** The in-pane `Manager` button opens an **auxiliary window** with its own
  hand-built root (`pulseai-manager-editor`); the `pulseai.openManager` command opens the registered
  `PulseAIManagerEditor`, which is what carries `.pulseai-manager-shell` — the selector
  `validate_pulse_ui_cdp.js:218-239` waits for. A button-routed Phase 4 therefore times out on a UI
  that is really on screen. Popup-vs-tab is your call; I did not silently pick it.
- **A wrong claim, corrected in public:** I asserted the command was a no-op (created
  `PulseAIManagerInput`, never opened it). It isn't — `openEditor` is on `:201` and my `sed` window
  ended at 200. Same for `/plan`: it is *not* inert (`after_task_manager → planner`,
  `after_planner → plan_preview`); what is missing is only the ported `build_plan_prompt` *text*, which
  has no runtime caller. Both corrections are recorded here rather than quietly dropped.
- **Verification limit, stated:** the fork has no `node_modules` in this checkout, so the three edited
  TS files are transpile-clean (`ts.transpileModule`) but **not typechecked**, and there is no browser
  binary here, so no pixel was painted by me. `48/48` vitest, `134 passed / 1 skipped / 1 deliberate
  failure` on the python side, and `5/5` on `ui_stack_smoke` against the live stack are the evidence.

## Right panel inside the fork: activity runs (2026-09-02)

The Auxiliary-bar Agent view used to list one row per tool call. It now folds consecutive
same-category calls into a run with a present-tense clause, using a DOM-free port of the
webview's own model, and the pane switches between the two agent surfaces instead of stacking
them at 50/50.

```
src/tests/test_hermes_run_summary_parity.py                4 passed   (both surfaces bundled, run in node)
src/tests/test_desktop_renderer_architecture.py           11 passed, 1 xfailed, 1 skipped
src/tests/test_ui_tool_catalog.py                          1 passed, 1 skipped   (was: 2 errors)
the whole desktop/permission lane                          87 passed, 2 skipped, 1 xfailed
pulse-webview: npx vitest run                             48 passed  (no webview file changed)
```

The parity test is the interesting one: it does not compare text or fixtures, it **executes**
`pulseAIRunSummary.ts` and `pulse-webview/src/hermes-ui/model/run-summary.ts` side by side on
eight tool sequences and requires identical group kinds, keys, summaries and verbs — so the two
surfaces cannot drift into saying different things about the same run. Its 8th sequence and the
card-splitting probe check the rule's two non-obvious behaviours (a card breaks a run; a run is
keyed by its first call, not its position).

Full-suite run in this session: `20 failed, 1206 passed, 8 skipped, 1 xfailed` in 215s. All 20
are in the indexer/vision lanes (`test_lang_extractors.py`, `test_lab_fixes.py`,
`test_efficiency_receipts.py`, one `test_autonomous_runtime_contract.py` request-shape test) and
read no file this round touched — the sandbox is missing optional deps (`PIL`, per-language
extractors), which is what those assertions need. Nothing in the desktop, prompt, safety, or
bridge lanes regressed. Verbatim tail in `pytest.log`.

Un-verified, deliberately: this fork tree has no `desktop/vscode/node_modules`, so there is no
`yarn compile` and no paint. The three edited TS files are parse- and transpile-clean; the first
build in your fork is the gate.

## Manager's Agent chat box unified with the pane (2026-09-02, later)

Owner ask: the Agent chat box inside the Manager must render like the Agent UI in the fork —
Hermes desktop's rendering, breathing, thinking, SVGs, A to Z. Manager's chrome was left alone.

| lane | result |
|---|---|
| `src/tests/test_hermes_activity_parity.py` (new) | **8 passed** |
| desktop + permission lane, 10 files | **95 passed, 4 skipped, 1 xfailed** |
| `pulse-webview: npx vitest run` (no webview file changed) | **48 passed** |

The parity file executes rather than greps wherever behaviour is what matters: the fork's
`pulseAIActivity.ts` and the webview's `turn-activity.ts` / `activity-timer.ts` are both bundled with
the webview's esbuild and run under node on identical part fixtures (`activitySignature`,
`toolNarratesWait`, `formatElapsed`, `TURN_QUIET_S`), and the row's visibility rule is checked as an
executed truth table covering upstream's two components (pre-first-token indicator always on; gap
indicator waits for a name or 2s of quiet; suppressed while a tool row narrates or a question is
open). Two comparisons are literal on purpose — `DRAFTING_REVEAL_MS` / `COMPACTION_LABEL` are
compile-time constants, and `TOOL_ICON_PATHS` is copied SVG path data, which is either byte-identical
to hermes-agent's table at `$HERMES_REF` or it is a different icon. The glyph *keys* are compared
against the webview's `TOOL_META` (including its `browser_*` loop rule), so 36 tools resolve the same
glyph on both surfaces.

What the row actually says, from the fork module run over eight scenarios (`pytest.log`):

```
turn sent, provider not answering  [aui_response-loading]  0s
thinking, still quiet              [no row]
thinking, past 2s of quiet         [aui_turn-activity]  2s   (signature 1:28:0)
a read is in flight                [no row]
settled, gap after it              [aui_turn-activity]  2s   (signature 2:11:1)
shell call in flight               [no row]
paused on an approval              [no row]
stop requested                     [aui_turn-activity]  Stopping safely · 5s
```

Known gaps, stated not smoothed: the log file is a `-q` tail, not a full verbatim transcript (an
earlier round's label overclaimed "verbatim"); history thoughts carry no duration because a persisted
turn never recorded one; `compacting` is plumbed but has no producer in the engine; the thought
disclosure uses native `details` rather than the webview's measured 121px clamp; and nothing here was
compiled or painted — `desktop/vscode/node_modules` is empty, so the first `yarn compile` in the
laptop fork is the gate.

## The typecheck lane (confidence, no build required)

`desktop/vscode/src/tsconfig.pulseai-check.json` + `pulseai-typecheck.log`. The strict flags the fork
builds with, pointed only at Pulse's contribution; 0 errors in `vs/workbench/contrib/pulseai/**`,
363 elsewhere in the pulled-in graph, all of them the missing-`@types` signature (TS2503 121,
TS2307 61) clustered in `debug`/`terminal`/`notebook`/`editor`. Six shipped defects came out of the
first run and were fixed in the same commit that added the lane, which is the argument for keeping it:
it costs 40 s and it catches the class of breakage that eats a 20-minute `yarn compile` cycle.

## pulseai-registration-step1.log

What the Manager's registration step proved *in the sandbox*: the strict scoped typecheck lane
(`src/tsconfig.pulseai-check.json`) reports 0 errors under `vs/workbench/contrib/pulseai/**` with
26 Pulse files in the program — including the three chat contracts the new controller pulls in —
and the python lane reports 152 passed / 4 skipped / 1 xfailed, of which 8 tests execute
`common/pulseAISessionProjection.ts` in node over fixtures. It does **not** prove a build or a
paint: there is no `yarn install`, bundler, or chromium here. Those gates are the owner's, and
they are named at the bottom of the log.
