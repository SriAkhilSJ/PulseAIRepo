# Agent Core Backend — Verification & Hardening Pass (2026-10-31)

**Scope:** the Python Agent Core backend only — `src/graphs/` (LangGraph topology,
gate routing, finalize verdict), `src/runtime/` (status contract, verification
ledger), `src/prompts/` (system prompt assembly), `src/tools/` (terminal
contract), plus the `src/tests/` suite that pins them.

**Out of scope (deliberately):** the vendored desktop fork's TypeScript
surfaces, live provider turns (no keys in this sandbox), and any benchmark
re-run that would need network/provider spend.

> **Tooling note — TestSprite MCP.** The TestSprite *connector* is not offered to
> this session, but TestSprite ships its MCP server as an open npm package, so the
> server was installed and driven directly through **Agent Core's own MCP
> client**: `initialize` → `tools/list` (8 tools) → `tools/call`
> (`testsprite_check_account_info`, which answered `Invalid TestSprite API Key`
> for the placeholder key — a real round-trip). See
> [`TESTSPRITE_MCP.md`](TESTSPRITE_MCP.md) and `scripts/testsprite_mcp_smoke.py`.
> **No TestSprite test was executed**: that needs a real API key, which this
> environment does not have. Nothing here is a TestSprite result.
>
> The verification below was done with the repository's own engine: the full
> pytest suite, direct execution of the graph's finalize/verdict paths against
> constructed states, import-level probes of the compiled graph, MCP smoke runs
> against both TestSprite and `scripts/mcptest_server.py`, and a differential read
> of `bench-results/`/renderer sources for the remaining pins. Reproducible with
> the commands in §6.

---

## 1. Result

| Measurement | Before | After |
|---|---|---|
| Full suite (`pytest src/tests`) | **21 failed**, 3090 passed, 24 skipped, 1 xfailed | **0 failed**, 3108 passed, 29 skipped, 1 xfailed |
| Runtime | 373 s | 363 s |
| New tests | — | +3 verdict-integrity pins (`test_verdict_honesty.py`), 1 obsolete test retired |
| Code defects fixed | — | 3 (one of them a self-contradicting completion frame) |
| Stale/unsatisfiable pins realigned or skipped | — | 12 across 10 files |

Environment for these numbers: Python 3.11.2 venv, `pip install -e .`, no
provider keys, no `sentence-transformers`, no node/pyright. The suite is
deliberately provider-free; the numbers are environment-shaped but the
**failure count is now zero in that environment**, which is the honest target
(it was not zero before, and several of those failures were not "environment" —
see §3).

---

## 2. Defect 1 — the completion frame contradicted itself

**Where:** `src/graphs/chat_graph.py::finalize_node` (verdict + contract synthesis).

`finalize_node` publishes five overlapping truth fields plus a nested
`status_contract`:

```
task_completed, task_status, run_outcome, verification_status, specification_status
```

They were derived by **three independent chains**: an `elif` chain for
`run_outcome`, a separate branch for `verif_status`, a separate branch for
`spec_status`, and then a fourth chain for `verdict` that recomputed the same
question from the raw locals. `synthesize_status_contract` then applied a
safeguard (`not_required` → `unverified` when code deliverables were produced)
that only the nested contract saw.

Observed (real, reproduced before the fix) for a turn that wrote
`app/page.tsx` and ran no receipt:

```
task_completed      = False        <- from the protected contract
task_status         = "completed"  <- from the raw chain
verification_status = "not_required"   <- pre-safeguard (contradicts the contract)
run_outcome         = "completed"
specification_status= "complete"
```

Same turn, two different answers depending on which field a caller reads — the
bridge (`turn_done.completed`), the AG-UI mapping, the receipt row, and the UI
badge all read different ones.

**Fix:** one derivation. `code_produced` is computed once; the verification
branch consults it; the contract's own safeguard is applied *before* anything is
published; `run_outcome` is reconciled against the other two dimensions; and
`verdict` is read off the contract instead of recomputed beside it.

```python
code_produced = _produced_code_deliverable(state)
...
verif_status = safeguard_verification_status(verif_status, code_produced)

if run_outcome == "completed":
    if verif_status in {"unverified", "failed", "stale"}:
        run_outcome = "failed"; failure_reason = verif_status
    elif spec_status != "complete":
        run_outcome = "failed"; failure_reason = "specification_incomplete"

verdict = ...                # read from run_outcome / verif_status / contract
task_succeeded = contract["task_completed"] and verdict == "completed"
```

**Pinned by** `src/tests/test_verdict_honesty.py`:

- `test_frame_written_code_without_receipt_is_unverified_not_completed` — the
  exact shape that used to lie;
- `test_frame_named_deliverable_missing_is_specification_incomplete` — a run
  that names a deliverable and never lands it (`flutter create flutterdemo`,
  nothing on disk);
- `test_frame_verified_code_run_is_completed_on_every_field` — the green
  direction; and a shared `_assert_frame_is_self_consistent()` helper that every
  one of them runs (top level vs nested contract vs `derive_legacy_completed`).

Behaviour change worth naming: a run whose interest mode is `answer`/`social` but
which *did* produce code no longer reports `specification_status="complete"` —
requirement fulfilment is `unknown` until verification speaks. That is the
tri-dimensional contract's stated rule, finally applied uniformly.

---

## 3. Defect 2 — the production mandate named a tool that does not exist

**Where:** `src/prompts/hermes/system_prompt.py` (`PRODUCTION_ENGINEERING_MANDATE`).

Step 4 of the mandatory delivery sequence told the model to start the server with
`execute_code` *or* **`run_command`** — a name that is not in the tool waist
(`all_known_tool_names()`: 66 tools; the terminal family is `run_terminal`,
`start_terminal`, `read_terminal_output`, `check_terminal`, `stop_terminal`, …).

The waiver did not repair it: the model calls the phantom name, the runtime
spends a repair round-trip, and (on a strict allowlist lap) can burn the whole
delivery phase on it. Two long-standing pins caught this —
`test_no_phantom_tool_names_in_the_assembled_prompt` and
`test_prompt_engineer_never_names_a_tool_the_waist_lacks` — and both were red.

**Fix:** the mandate now names `start_terminal` (background server) and
`run_terminal` (one-shot check), matching how the delivery gate actually
verifies a server. Both pins green; no prompt text was otherwise rewritten.

---

## 4. Defect 3 — the two timeout paths told the model different stories

**Where:** `src/tools/terminal_tools.py` (captured-process timeout path).

`run_terminal` has two timeout paths. The `subprocess.TimeoutExpired` path says
*"this is an ENVIRONMENT failure — do NOT retry the same interactive command,
pivot to non-interactive flags / start_terminal"*. The newer captured-process
path (the one a foreground command actually takes) said only *"Retry only with a
justified longer timeout"* — the wrong lesson for a blocked/interactive prompt,
and it omitted the environment-pivot guidance the model is trained on.

**Fix:** both paths now carry the same pivot guidance (non-interactive flags, a
justified longer timeout up to the 600 s foreground cap, or `start_terminal` +
`read_terminal_output`). Pinned by `test_lab_fixes.py::test_terminal_timeout_env_returns_pivot_message`.

Honesty note: this text is **model-facing guidance**. It is not a marker in
`graphs/verification_helpers.classify_env_failure` — that classifier keys on
`command not found` / `no such file or directory` / `exit code: 127` / …, and a
timeout is separately recognised as *flaky* (`timed out after`) so it is not
converted into durable verification debt. The earlier draft of this note claimed
the ledger read the sentence; it does not.

---

## 5. Stale and unsatisfiable pins (12)

Every one of these was red for a reason *other* than the three defects above.
They are recorded with the decision taken, so the next reader does not have to
re-derive it.

### 5.1 Pins that had drifted from an intentional code change (7 — realigned)

| Pin | Drift | Decision |
|---|---|---|
| `test_reasoning_effort_threading::test_openai_compatible_reasoning_effort` | `build_model_kwargs_for_reasoning` stopped sending top-level `reasoning_effort` to non-OpenAI models on custom/cheap gateways (Velona / LiteLLM / vLLM / OpenRouter answer it with HTTP 400) | Pin the **current** wire contract in both directions: OpenAI-family models *do* get `reasoning_effort`; foreign models (GLM/DeepSeek/Qwen) get the effort as `thinking.budget_tokens`; native OpenAI still gets both |
| `...::test_disabled_thinking_across_all_providers` | Same change: for custom/cheap, "Think: Off" is enforced by **omitting** the foreign parameter, not by sending a suppression payload | Pin omission (`{}`) for gateways and the suppression payload for native OpenAI/Groq/Gemini |
| `test_finalize_chat_turn::test_successful_work_run_stamps_nothing` | Was a "successful work run" with no verification receipt — under the contract that run is *unverified* | Keep the test's real subject (no finalize prose) and give it the passing `typecheck_workspace` receipt that makes it genuinely successful |
| `test_finalize_chat_turn::test_acting_after_the_nudge_still_completes` | Asserted `completed=True` for a run whose named deliverable never landed | Re-pin the **nudge marker**: acting after the nudge clears `failure_reason="ended_mid_task"`, and the un-acted twin still carries it (both asserted) |
| `test_grace_summary_hermes_law` (×2) | Receipt accounting was refactored: `turn_model_wall()` → `pop_turn_model_accounting()` (read-and-clear) with sub-agent seconds attributed separately | Pin the current call with the real thread id (`sid`), the "non-model" split, and the separate sub-agent line; also pin that the cumulative read is gone |
| `test_hermes_prompt_session_cache::test_session_stats_report_the_tier_split` | "stable must dominate volatile" is environment-shaped: with the skills **index** on, the volatile tail is ~77 k chars vs ~11 k stable — legitimately | Assert the size relation with the index off, and assert the property that matters in the shipped default: tiers reported separately, `static_bytes == stable_chars`, stable band byte-identical on rebuild |
| `test_review_autopsy_fixes::test_d28_write_file_protects_existing_python_only` | Expected a brand-new `.py` with placeholder syntax (`def todo(...) -> ...:`) to be written; the 2026-10-29 universal AST gate refuses non-compiling Python on creation | Pin the gate (rejected, no file on disk) **and** that a valid stub is still allowed — skeleton authoring survives |
| `test_hermes_runtime_values::test_foreground_cancel_answers_when_a_grandchild_holds_the_pipes` | Monkeypatched `_CANCEL_DRAIN_TIMEOUT_S`, unified into `_TERMINAL_DRAIN_TIMEOUT_S` | Patch the current constant |
| `test_copilot_parity_permission_diff::test_approval_dock_renders_inline_diff_and_warning` | The permission dock dropped its inline diff block; the diff now opens in the editor behind a `Review change` action (`host.openDiff(toolId)`) | Pin the current dock: one hint, `crusorai-approval-dock`, review action → editor diff, keyboard badges, and the rejected amber design staying gone |
| `test_hermes_activity_parity::test_both_surfaces_mount_the_same_column_and_teardown_the_timers` | Exact-literal count of `agentColumn(...)` broke on a purely additive signature change (`closedTools`), and the thinking row's glyph moved to `renderToolIcon(name)` | Pin the *contract* instead: exactly two spread mount sites, identical argument lists; thinking row resolves through the shared icon table with the Thinking/Thought labels |

### 5.2 Tests that can never pass in a fresh checkout (5 — now skip, with a reason)

`bench-results/` is `.gitignore`d (line 94), yet
`test_api_contract_parity` (3) and `test_model_failure_reproduction` (2) assert on
files inside it. In a clean clone they fail with `FileNotFoundError`, which says
nothing about the code. They now **skip** with a message naming the missing
artifact and why it is missing. Where the artifacts *do* exist the assertions are
unchanged and still strict — the certification claim is not weakened, only made
honest about where evidence lives.

### 5.3 Retired (1)

`src/tests/test_scaffold_layout_normalization.py` imported
`src.tools.scaffold_tools`, a module that another pin
(`test_scaffold_tools_are_deleted_everywhere`) asserts was deleted everywhere
("terminal does the job", founder 2026-10-18). A test for a deleted subsystem
cannot pass; the file is removed rather than left as permanent red.

---

## 6. How to reproduce

```bash
python -m venv .venv
.venv/bin/pip install -e . pytest pytest-asyncio

# full suite (provider-free, ~6 min)
.venv/bin/python -m pytest src/tests -q --no-header --basetemp=/tmp/pt

# MCP surfaces (real stdio servers, through src/tools/mcp_client.py)
.venv/bin/python scripts/testsprite_mcp_smoke.py --workspace .   # exit 2 = no key
.venv/bin/python -m pytest src/tests/test_mcp_client.py src/tests/test_mcp_session_pool.py \
    src/tests/test_mcp_meta_tools.py src/tests/test_mcptest_server.py -q --no-header

# the three defect pins
.venv/bin/python -m pytest src/tests/test_verdict_honesty.py \
    src/tests/test_hermes_prompt_parity.py \
    src/tests/test_lab_fixes.py -q --no-header
```

---

## 7. What is still NOT verified

Say it plainly, in this repository's tradition:

- **No live model turn was run.** Nothing here re-validates the GatePulse
  16/16 / 9-of-9 browser claims, and the 2026-10-27 full-stack benchmark status
  remains **FAIL / not revalidated**. This pass changes verdict derivation and
  prompt text; both deserve one live headless run before any PASS claim.
- **No TestSprite test run** — the MCP server is installed, wired and
  protocol-verified (8 tools, live `tools/call`), but executing a TestSprite
  suite needs their API key (see the tooling note and `TESTSPRITE_MCP.md`).
- **Desktop TS surfaces** were touched only through stale pins; the desktop fork
  was not recompiled (`gulp compile` / `tsc -b` need a node toolchain this
  sandbox does not have).
- **Embeddings / long-term memory** remain unexercised (not installed).
- The finalize change alters what a caller sees for *unverified* runs
  (`task_status="unverified"`, `run_outcome="failed"`, `specification_status`
  no longer `complete` for code-producing answer-mode turns). Consumers were
  audited (`src/bridge/__main__.py` reads `result.completed`, which comes from
  `task_completed`, so it stays consistent), but a live UI pass should confirm
  the badge wording is what the owner wants for "worked, unproven".
