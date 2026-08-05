# PulseAI — Codebase Architecture Review & Strategic Roadmap

**Reviewer:** Context-engineering analysis, 2026-08-04
**Repo:** SriAkhilSJ/PulseAIRepo @ `517a771`
**Verdict up front:** The engine is the product. Fork VSCode *last*, not first.

---

## 1. What PulseAI actually is today

A Python/LangGraph autonomous coding agent (~10.6K LOC + a 65KB dashboard) with a
genuinely above-average context layer for an OSS project. Component inventory:

| Module | Lines | Role | Maturity |
|---|---|---|---|
| `src/graphs/chat_graph.py` | 2,069 | Full agentic loop: task manager → planner → plan preview/approval → AI node → SafeToolNode → progress → finalize/recovery/replan | Solid concept, monolithic file |
| `src/context/context_engine.py` | 1,239 | 16-layer task-aware context assembly: classification, relevance scoring, dedup, budgeted hierarchical packing, differential cache, feedback loop | Best-in-repo; has fixable bugs |
| `src/context/repo_map.py` | 388 | AST repo map + import graph (verified: handles async/decorators) | Good, capped 1200 tokens |
| `src/context/vector_memory.py` | 137 | SQLite-persisted vector memory (`~/.pulseai/vector_memory.db`) | Persistent but **linear scan of 500 rows** — not an index |
| `src/agents/planner.py` | 524 | Plan create/replan/revise/finalize, ambiguity check | Works |
| `src/agents/cost_router.py` | 138 | Tier-based model routing (cheap/standard/premium) | Real differentiator, underused |
| `src/tools/terminal_tools.py` | 408 | Background processes w/ lifecycle (start/check/stop/list/cleanup) | Strong: many OSS agents lack this |
| `src/tools/file_tools.py` | 260 | read/list/write/search/edit w/ workspace path resolution | Whole-file granularity |
| `dashboard.html` + `dashboard_server.py` | ~1,000 | FastAPI SSE stream, tool approval UI, live token/cost stats | Real product surface |
| `src/tests/` | ~1,000 | 13 regression tests (scripts, not pytest) | Present but not CI-gated |

### Verified strengths
- 16-layer context engine with 60/30/10 relevance scoring (task-type prior / semantic sim / recency), embedding dedup at cosine > 0.88, hierarchical budget fit, differential caching. This is meaningfully better than "stuff everything in" OSS scaffolding.
- Recovery **and** replanning with separate limits (3 / 2), plus attempt-history lesson injection.
- Human-in-the-loop approval for destructive tools (`SafeToolNode`).
- Persistent memory across restarts (JSON memories + SQLite vector store + reflections + skills).
- Pre-send token guard (`PROVIDER_SAFE_LIMIT=6000`) to survive provider 503s.
- The README's self-assessment is unusually honest — that is a cultural asset. Keep it.

### Verified weaknesses (found in code, not just README)

**Bugs / correctness:**
1. **`TaskClassifier` is re-instantiated on every `build_ai_messages` call** (`context_engine.py:308`) → re-encodes ~25 prototype embeddings *every turn*. Should be a singleton/lazy module-level instance.
2. **`LAYER_RELEVANCE` is a class attribute mutated at runtime** (`context_engine.py:1009-1011`) → learned weights leak across all engine instances in the process (and across dashboard sessions/threads). Deep-copy per instance in `__init__`.
3. **Feedback attribution is broken as designed** — `record_feedback` snapshots `self._layer_cache`, which is the *session-wide* cache, not the layers actually sent this turn. `build_ai_messages` should return/record the exact layer list per call.
4. **`MemorySaver` checkpointer** (`chat_graph.py:1754`) → all conversation state dies on restart. Use `SqliteSaver` under `~/.pulseai/` — you already built that persistence for memory, do it for sessions.

**Architecture gaps (the real competition gap):**
5. **No chunk-level code retrieval.** Context is whole-layer granularity (whole repo map, whole memory blocks). Cursor's actual moat is per-symbol/chunk embeddings + hybrid BM25/vector retrieval, incrementally refreshed. Your own README says this is the next milestone. It is.
6. **Vector memory = linear scan** of latest 500 rows in Python. Fine at 500, dead at 50K. Use `sqlite-vec` or `hnswlib`; keep stdlib fallback.
7. **Dedup + scoring re-encode every layer every turn** — no content-hash cache on embeddings. Latency compounds with turn count.
8. **Tool payload bypasses the pre-send guard** — `bind_tools` definitions ride along untracked (README caveat 6). Trim tool defs or select tools per task type.
9. Session state is single-workspace, cwd-bound. No multi-repo, no git-aware context.
10. Tests are print-based scripts, not pytest → no CI gate. Add GitHub Actions; run on PR.
11. `requires-python >=3.14` (`pyproject.toml`) — shrinks your contributor pool; target 3.11+.
12. `generated/` and `logs/` committed to git — gitignore them.

---

## 2. The strategic question: VSCode fork — right plan? Do it first?

### Is the plan right? **Yes, directionally.** Forking Code OSS/VSCodium is exactly what Cursor did (its editor is a VSCode fork), and the VSCode API surface gives you everything your roadmap lists as gaps:

| VSCode API | What it unlocks for PulseAI |
|---|---|
| `workspace.onDidChangeTextDocument` / file watchers | **Incremental index refresh** (your staleness problem solved) |
| LSP client / language extensions | Go-to-def, references, diagnostics → AST-accurate context (upgrade over your 20-file import graph) |
| `InlineCompletionItemProvider` | Tab autocomplete — Cursor's #2 killer feature |
| Webviews | `dashboard.html` embeds as-is, zero rewrite |
| Terminal API | Your strongest tool module becomes native |
| Source Control API | Git-aware context (on your gap list) |
| CodeLens / CodeActions | "Fix with PulseAI" inline affordances |

### Should you do it first? **No. Doing the fork first is the classic startup sequencing mistake.**

**Why:**
1. **The fork is distribution; the engine is the moat.** Cursor wins on its codebase index, apply-model, and Tab — not on Electron plumbing. A fork with a weak agent is a reskin nobody switches to.
2. **Forking Code OSS = 3–6 months of non-differentiating work**: Electron builds for 3 platforms, extension-host compat, auto-update infra, marketplace legalities (MS marketplace ToS forces Open VSX), signing. Your 1-person runway burns while the agent engine stays exactly as weak.
3. **Every API in the table above is available to a plain VSCode extension** — same capabilities, ~10% of the effort, and you ship inside the editor where users already are. You only need the fork when you must change core UI/UX deeply (Cursor-level polish) or own distribution/branding.

### Correct sequence

| Phase | Work | Why this order |
|---|---|---|
| **P0 — Engine moat** (now, 4–6 wks) | Chunked code index + hybrid BM25/vector retrieval + incremental refresh; fix bugs #1–4; sqlite-vec; per-turn layer attribution | Closes the single biggest verified gap vs Cursor. Your README already names it. Until this exists, an editor shell is premature. |
| **P1 — Harness quality** (2–4 wks) | pytest + CI; SWE-bench-lite-style eval harness; unified-diff apply with fuzzy matching (you already have `compute_unified_diff` — wire it into `edit_file`); auto-run-tests self-heal loop | You need evals to prove improvement, and a reliable edit/apply format is what separates toy agents from tools. |
| **P2 — VSCode extension** (3–4 wks) | Package PulseAI as an extension against *stock* VSCode: webview chat (reuse dashboard.html), file-change feed → index refresh, diagnostics → context, inline completions later | 90% of the VSCode APIs' value, 10% of fork cost. Real users, real feedback, zero Electron tax. |
| **P3 — Fork** (only when proven) | Fork Code OSS/VSCodium when (a) retention proves the engine AND (b) extension API limits are the actual blocker | Fork from strength, with users and metrics — not from speculation. |

**Wedge advice:** don't fight Cursor head-on as "another AI IDE." Your codebase's DNA (local free embeddings, cost router, persistent private memory, honest benchmarks) points at a sharper position: **the private/cost-transparent agent** — fully local embeddings, multi-provider routing, on-prem friendly. That's a winnable lane for a startup; "general Cursor clone" is not.

---

## 3. Immediate next actions (concrete, this week)

1. Fix `TaskClassifier` singleton + per-instance `LAYER_RELEVANCE` deep copy (2-line-ish fixes, real bugs).
2. `build_ai_messages` → return layers-sent; wire into `record_feedback` (true attribution).
3. Swap `MemorySaver` → `SqliteSaver` (~/.pulseai/sessions.db).
4. Start P0 index: chunk files (tree-sitter or AST spans) → embed once → sqlite-vec + BM25 (`rank_bm25`) → retrieve top-k chunks into a new `code_context` layer with relevance=1.0 for DEBUG/REFACTOR.
5. Convert tests to pytest; add GitHub Actions CI.
6. `git rm -r --cached generated/ logs/` and gitignore them.
7. Lower `requires-python` to ≥3.11 unless a 3.14-only feature is required.

---

## 4. GPT Response Verdict (2026-08-04, applied)

The pasted 5-bug review was verified claim-by-claim against `main` @ `517a771`:

| GPT Claim | Verdict | Action |
|---|---|---|
| B1: `factory.py` missing `RetryLLMProxy`/`EmbeddingFactory` | **FALSE** — both exist (lines 19/213, file is 239 lines). GPT read a stale/truncated copy. | None |
| B2: `SafeToolNode` recreates `SafetyGuard` | **MISDIAGNOSED** — real code smell, but NOT critical (guard is stateless, rebuild is ~µs). GPT's `guard = self._guard` fix would cause a **workspace-rooting regression** (injected guard is bound to import-time cwd; per-call guard uses session workspace from config). | Fixed *correctly*: per-workspace guard cache |
| B3: `tool_calls` pydantic `.get()` crash | **FALSE** — LangChain `ToolCall` is a **TypedDict**; `.get()` is legal. Same pattern runs live in `SafeToolNode` today. | None (rejected defensive churn) |
| B4: `record_feedback` snapshot | **REAL** (flagged here first). GPT's patch was unmergeable (`SystemMessage.name` is `None`; referenced an undefined var — would log `[None×N]`). | Fixed *correctly*: snapshot layer names via `_infer_layer_name` on the post-budget message list |
| B5: state hash in loop | **REAL** (low) | Fixed: hash computed once per build |

**Landed (verified by live smoke test):** true layer attribution, hash-once loop,
per-workspace guard cache — plus two fixes from this review the GPT missed:
`TaskClassifier` singleton (was re-encoding every turn) and per-instance
`LAYER_RELEVANCE` (was leaking learned weights across all sessions).
Meta-lesson: this review style is the process — **verify, then merge.**
2 of 5 GPT claims were false and 1 of its patches was a regression in disguise.

---

## 5. Cleanup Batch Verdict (2026-08-04, shipped)

Second pasted task list ("5 cleanup tasks") — verified and shipped with corrections:

| GPT Task | Verdict | Shipped |
|---|---|---|
| T1: `MemorySaver` → `SqliteSaver` via `from_conn_string` | **Direction right, code broken** — `from_conn_string()` returns a `_GeneratorContextManager` (empirically verified), not a saver; also omitted the required `langgraph-checkpoint-sqlite` package | ✅ Corrected: direct `sqlite3.connect(check_same_thread=False)` + `SqliteSaver(conn)` + `setup()`, sessions at `~/.pulseai/sessions.db` |
| T2: purge `generated/`, gitignore | **Right** (only task usable verbatim). `logs/` was already ignored; `generated/` was not | ✅ `git rm --cached` both + expanded `.gitignore` |
| T3: `requires-python >=3.10` | **Right idea, dated floor** — 3.10 hits EOL ~Oct 2026 (weeks away); no `tomllib` usage found in repo | ✅ Set `>=3.11` |
| T4: pin `sentence-transformers >=2.5,<3.0` | **FALSE premise** — `>=3.0.0` already declared (line 23); pinning v2 contradicts the repo, and a version pin doesn't stop the 100MB runtime weights download anyway | ✅ Kept v3, added sane bound `>=3.0.0,<4.0.0` |
| T5: add pytest config — "existing tests now run under pytest" | **Dangerous as written** — all 14 files are procedural scripts that fire live LLM calls at import; pytest collection imports modules. Also missing `pythonpath = .` (imports would fail) | ✅ pytest config with `pythonpath`, `conftest.py` isolating the 14 script-tests, 5 new pure CI-safe smoke tests (green), corrected `scripts/verify_cleanup.sh` |

**Found by verification, not on the list (bug #6):** `VectorMemory` raises when the
embedder backend is missing, and `MemoryManager()` is constructed at `chat_graph`
import time → **the whole agent crashed on import in slim environments** (fresh CI,
small containers) — contradicting the README's "graceful degrade by design" claim.
Fixed: boot now degrades to `memory_manager=None` with a loud warning, matching the
ContextEngine's existing fallback pattern.

---

## 6. P0 Shipped: Chunked Code Index (2026-08-04) — the Cursor-gap closer

Third pasted artifact: a twice-reviewed `chunk_index.py` spec + a "4 remaining bugs"
review + a "4-line patch". Verdict: **highest-quality paste yet — but it would not
have run.** Empirical verification (sqlite-vec v0.1.9):

| Claim | Verdict |
|---|---|
| Spec's sqlite-vec syntax (`vec_f32`, `vec_distance_l2`, `MATCH + k`) | ✅ Correct (verified live) — rare win |
| Review Bug 1: FTS5 external-content + manual inserts drift; never deleted on re-index | ✅ REAL — shipped standalone FTS5 + `chunk_id UNINDEXED`, managed in the same transaction |
| Review Bug 2: `max_dist` normalization divides by zero on exact match | ✅ REAL (exact match = 0.0 confirmed) — shipped exact cosine `1 − L2²/2` for unit vectors |
| Review Bug 3: dead `_rrf_fuse` calling nonexistent `_static_conn()` | ✅ REAL — removed; single fuse method |
| Review Bug 4: `last_insert_rowid()` fragility | ✅ REAL — eliminated by the Bug 1 fix |
| **My finding A: background indexing thread shares a default sqlite connection** | 🔴 REAL — `ProgrammingError` cross-thread (proven). Shipped `check_same_thread=False` + `RLock` |
| **My finding B: `index_workspace` never commits** | 🔴 REAL — fresh connection sees `COUNT=0` (proven); index would vanish on exit. Shipped batched commits |
| **My finding C: raw task text → FTS5 `MATCH` syntax error** | 🔴 REAL — shipped tokenize + quote-OR sanitizer (can never produce invalid FTS syntax) |
| **My finding D: per-call `ChunkIndex` construction + shared default DB** | ⚠️ Shipped process-wide per-workspace index cache + per-workspace DB (no cross-repo contamination) |

**Shipped:** `src/context/chunk_index.py` (AST extraction → sqlite-vec KNN +
FTS5 BM25 → RRF position fusion, background first-run indexing, atomic
incremental sync); wired into ContextEngine as `relevant_chunks` (relevance
0.95 DEBUG/CREATE/REFACTOR) with `repo_map` demoted on coding tasks (kept at
1.0 for EXPLORE); 9 pure CI tests (no model download) mapping one-to-one to
the fixes above — **14/14 suite green**; live demo over `src/context/`
(43 chunks) returns `ContextEngine` as top hit in BM25-only degraded mode.

Meta-score on pasted AI code to date: **specs now carry good architecture, but
every single one failed on at least one empirically-provable runtime fact.
Verification is not optional.**

---

## 7. P1 Shipped: edit_file upgrade (2026-08-04) — verified against BOTH reviews

Fourth paste: a P1 spec ("wire compute_unified_diff into edit_file's whole-file
rewrites") + a counter-review calling out the P1 spec's false premise. This time
the *counter-review* was the sharp one — and it still had bugs to catch.

**Counter-review claims (all verified TRUE against the repo):**
1. `edit_file` already did find-and-replace — P1's premise was false. ✅ True.
2. P1 spec dropped `config: RunnableConfig` → workspace-sandbox regression. ✅ True.
3. P1 renamed `old_text`→`old_string` → breaks tool schema/history. ✅ True.
4. Redundant `content` mode (write_file exists) + fragile line-range mode. ✅ True.
5. P1's "atomic" claim was a plain `write_text`. ✅ True.
6. Event format mismatch risk with the dashboard's flat `{"file","lines"}` shape. ✅ True.

**Bugs the counter-review's own code had (caught here, not shipped):**
- Fuzzy fallback replaced only the FIRST matched line with new_text's first
  line → would corrupt multi-line edits. Shipped instead: whitespace-normalized
  block-span matcher (threshold 0.88) that replaces the whole original span.
- Atomic write lost file permissions (mkstemp = 0600). Shipped: mode preserved.
- Double-emitted `files.changed` with a synthetic messageId. Shipped: only
  `diff.show` from the tool; `files.changed` stays owned by progress_node.
- Persona "add guidance" was stale — the preference already existed (line 93);
  strengthened in place.

**Shipped in `src/tools/file_tools.py`:** unchanged signature
`(path, old_text, new_text, config)`; exact → block-span fuzzy fallback;
tempfile+`os.replace` atomic write (perms preserved, temp files cleaned);
`compute_unified_diff` wired (lazy import — avoids the circular import with
chat_graph); `diff.show` emitted in the dashboard's existing flat shape; diff
preview returned for the agent's verify() loop; "no change" is a true no-op.
10 pure tests — **24/24 suite green**; graph boots; tool schema unchanged.

---

## 8. SmartCompressor Turn-Atomicity + Lock Hygiene (2026-08-05)

Fifth pasted review ("Context Engine Verification Report" scoring itself 72/100
— vanity score ignored; claims verified individually):

| Claim | Verdict | Action |
|---|---|---|
| SmartCompressor per-message scoring breaks turns | 🔴 **REAL — worse than stated**: could emit a ToolMessage without its tool_call AIMessage (protocol-invalid → provider HTTP 400s) | ✅ Rewritten turn-atomic: group → score=max member → budget-fit per turn → protocol-sanitize output (7 new tests) |
| A: `sync_workspace` lock batching | 🟡 True but overstated (waste, not corruption) | ✅ One lock around the sweep |
| B: drop read lock on `_search_vec_fast` | ❌ **REJECTED — unsafe fix**: "WAL allows concurrent reads" holds for SEPARATE connections, not concurrent cursors on ONE shared connection object. Single-lock serialization is the correct design | Documented rationale in code instead |
| C: lock missing on `_rrf_fuse`/`get_neighbors`/`_is_index_empty` | ✅ Real — inconsistent with own shared-connection discipline | ✅ All locked |
| D: layer swallows exceptions silently | ✅ Real (ironic: same sin I fixed in the engine) | ✅ Loud warning, `None` degrade |
| E: `_iter_py_files` materializes list | ✅ Hygiene | ✅ Generator |
| F: differential cache is all-or-nothing | 🟡 Known coarse invalidation, not a bug | Documented as deliberate |
| H: `_infer_layer_name` header coupling | 🟡 Fair | ✅ Regression test: no layer may infer "unknown" |
| I: feedback fallback to session cache | 🟡 Known-low (pre-build failures only) | Commented |

Suite: **34/34 green**. Live proof: undersized budget now drops a whole turn
atomically instead of leaving an orphaned 800-token ToolMessage.

---

## 9. Pasted "Part 1 Foundation" Plan — Model Budgets / File Watcher / Git Layer (2026-08-05)

Sixth pasted review. Direction solid; specifics dangerous as usual. Every
claim tested against the repo before merging:

| Pasted item | Verdict | Action |
|---|---|---|
| "Hardcoded 8000 cap wastes big-context models" | ✅ **REAL** (`chat_graph.py` + engine default) | ✅ `src/context/model_budgets.py` + engine auto-detect |
| Its `rsplit("-",1)[0]` prefix matcher | 🔴 **BUG, proven**: `"gpt-4o".rsplit("-",1)[0]` == `"gpt"` → `gpt-4-0613` gets **128,000** (real: 8,192) — a 16x overshoot → provider 400 | ✅ Rewrote: provider-prefix strip → date-suffix strip → **longest** proper-prefix match; regression tests pin `gpt-4-0613 → 8,192` |
| Its model table | 🔴 **BUG, proven**: repo's own default `qwen/qwen3.6-27b` and even `openai/gpt-4o` fall through to 8,192 (no provider-prefix handling); current Groq model `llama-3.3-70b-versatile` missing, dead `mixtral`/llama-3.1-70b entries | ✅ Fixed table + normalization |
| Spec blind spot: `RetryLLMProxy` | 🔴 **Spec would cause a regression**: proxy trims input to `PROVIDER_SAFE_LIMIT=6000` **middle-out** — engine-built context layers die first. Raising the engine cap alone = self-amputation | ✅ Engine auto-budget = `min(usable_budget(model), PROVIDER_SAFE_LIMIT)`, floor 4,096; raise `PROVIDER_SAFE_LIMIT` on paid tier to unlock scale |
| File watcher (watchdog) | ✅ Real need (freshness between turns) | ✅ watchdog observer + polling fallback, debounced queue, idempotent start; `watchdog>=4,<7` dep |
| "Remove per-turn `sync_workspace()` call" | ❌ **REJECTED**: watcher batch-drains at ~2s — a save→ask faster than that reads stale chunks; the per-turn mtime sweep is milliseconds | Kept BOTH (comment in code explains why) |
| Spec blind spot: deleted files | 🔴 **Pre-existing gap the spec missed**: nothing ever removed deleted files' chunks — FTS kept retrieving ghosts | ✅ `remove_file()` (all four stores) + watcher's `on_deleted`/`on_moved` + prune pass inside `sync_workspace` |
| Spec blind spot: two-process DB | 🟡 Dashboard + CLI can hold the same per-workspace DB; WAL doesn't save writer-writer | ✅ `PRAGMA busy_timeout=5000` |
| Git context layer | ✅ Real value | ✅ `src/context/git_context.py` — read-only subprocesses, 3s timeouts, char-capped, `None` outside repos |
| Spec blind spot: layer cache | 🔴 Git state isn't in `_hash_state` → cached layer serves **stale branch/stage info across turns** | ✅ `VOLATILE_LAYERS` set: git layer rebuilds every turn, never cached |
| Spec blind spot: attribution | 🟡 `_infer_layer_name` would label it "unknown" (feedback loop corruption) | ✅ `"=== GIT CONTEXT"` header mapped |

**Behavior proof** (default `PROVIDER_SAFE_LIMIT=6000`): `gpt-4o` → budget
6,000 (capped, not trimmed mid-flight); `gpt-4-0613` → 4,096 (the pasted code
said 124,032); raise the env cap and known models scale automatically.
Unknown models deliberately stay conservative — undershoot costs context,
overshoot costs the request.

Suite: **60/60 green** (26 new pure tests). `chat_graph` + engine + index
compile clean; explicit `max_tokens=` override path unchanged (tests rely on it).

---

## 10. Dynamic Context-Window Discovery (2026-08-05, founder request)

Founder ask: "the model context window should be dynamic — it should only
get to know its context window and act according to it." Correct instinct:
the §9 static table can never know every model (the repo's own default
`qwen/qwen3.6-27b` isn't in anyone's hardcoded list), so guessing was the
wrong long-term design.

**Shipped: a priority chain in `resolve_context_window()`** —
`LLM_CONTEXT_WINDOW` env override → fresh on-disk cache
(`~/.pulseai/model_windows.json`, 7-day TTL) → static table (zero network
for known models) → **live provider probe** (Groq `/models`.`context_window`,
Gemini `inputTokenLimit`, OpenRouter `context_length`; 2.5s hard timeout,
then cached) → stale cache → conservative default.

Design decisions, and why:
- **Static-before-probe**: known models (gpt-4o, Claude) never touch the
  network. OpenAI/Anthropic don't publish windows in their APIs anyway —
  for them the table IS the authoritative source.
- **Provider name comes from `src.config.settings`**, not raw env: my first
  cut read `LLM_PROVIDER` from os.environ, which silently disabled probing
  whenever the env var was unset — while the settings default of `groq`
  happily powered the LLM factory. Caught in demo, fixed, regression-tested.
- **Probes are read-only GETs, failure-degrading**: any error → next rung,
  never a crash. Worst case: one 2.5s cold-boot stall, then a week of cache.
- **Engine logs the source on every auto init** (`[ContextEngine] context
  window 131,072 for 'qwen/qwen3.6-27b' (source: groq-api); ...`) — budget
  provenance must be observable, not magic.
- `PROVIDER_SAFE_LIMIT` still caps the operational budget — dynamic
  discovery sizes the *model*, the proxy cap guards the *tier*.

Live demo (fake provider payload through the real chain): cold boot probes
`groq-api` → 131,072 for the repo's default model; warm boot answers from
`cache` with zero network; `gpt-4o` → `static-table` (probe_never called);
`LLM_CONTEXT_WINDOW=64000` → `env-override`.

Suite: **68/68 green** (8 new pure tests; cache isolated to tmp HOME, HTTP
seam monkeypatched — no network in CI).

---

## 11. Commit-Verification Report on My Own Work (2026-08-05, founder-escalated)

Seventh pasted review — this one audited MY commits (`ca3fd5c`, `30f15f7`)
and the founder called the findings shameful. Fair. Verdicts, as always,
empirical:

| Claim | Verdict | Action |
|---|---|---|
| 1. `_infer_layer_name` is brittle header-string sniffing | 🔴 **REAL, proven**: `== GIT CONTEXT` (one `=` short) → `unknown` → 0.5 relevance + corrupted feedback attribution | ✅ **Identity tags**: every engine-built layer stamped `response_metadata["layer"]` at build; inference is tag-first, header chain demoted to fallback; tags propagate through `_compress_layer`. Verified `response_metadata` never enters provider payloads (`convert_to_openai_messages` output) |
| 2. `PROVIDER_SAFE_LIMIT` caps everything at 6K — "discovery is observational" | 🔴 **REAL**: engine logged 131K but used 6K with no path forward | ✅ **AUTO mode**: `PROVIDER_SAFE_LIMIT=0` → both the engine budget AND the `RetryLLMProxy` guard resolve the identical `discovered_window − 4,096` (proxy memoizes: no per-invoke disk/network). Default stays 6000 — safe out of the box, one env var unlocks paid tiers. Boot log now prints the hint: `— set PROVIDER_SAFE_LIMIT=0 to unlock 126,976` |
| 3. Watcher/index is `.py`-only | 🟡 **REAL but scope, not a bug**: the extractor is stdlib `ast` — Python by construction. Multi-language = tree-sitter grammars, a milestone of its own | Deferred as **debt D5** (after D1 session-scoping, D2 embed cache). Not shipping a regex-chunker — that's a quality downgrade wearing a feature's clothes |
| 4. Probes read raw `os.getenv` for API keys | 🟡 **REAL** (latent): worked by accident — resolve() imports settings first, whose `load_dotenv()` populates os.environ. Inconsistent with the provider fix I had just made | ✅ `_settings_key()`: settings-first, env fallback; regression tests pin both paths |
| (self-found) `_compress_layer` generic truncation assumed 3.5 chars/token | 🔴 **REAL, worse than any pasted claim this round**: code-dense text runs ~2.5 chars/token, so the truncation branch produced candidates ~42% over budget and **silently returned None → layer dropped** — for every code-dense layer, always | ✅ Measured per-message ratio + proportional fit with shrink retry (≤3 attempts). Found by my own failing test, fixed same commit |

**Demo proof:** default tier caps at 6,000 with printed unlock hint; auto
tier budgets 126,976 and `proxy._safe_limit()` returns the **identical
number** — engine and guard in lockstep. All layers carry identity tags.

Suite: **78/78 green** (10 new pure tests incl. a new `test_retry_proxy.py`).

---

## 12. Verification of Round 11 + Compression Convergence (2026-08-05)

Eighth pasted review — audited round 11 with partial visibility (their
GitHub fetches failed, so several claims were "unverified"). All resolved
empirically:

| Claim | Verdict | Action |
|---|---|---|
| "Proxy side of auto-mode unverified — lockstep claim may be false" | ✅ **VERIFIED REAL**: `_safe_limit()` ships as claimed (`PSL>0` → explicit; `PSL=0` → resolve discovered window − margin, memoized); `test_retry_proxy.py` has explicit/auto/memo/trim-end-to-end tests | Evidence printed in-session; no code change needed |
| "No test for tag survives compression" | ❌ **FALSE**: `test_compress_layer_preserves_identity_tag` + `test_layer_tags_are_invisible_to_providers` exist since round 11; reviewer couldn't fetch the test files | Pointed at the test names |
| `_compress_layer` can still return None after 3 proportional iterations, dropping a fittable layer | 🔴 **REAL, fuzz-proven**: 2/284 adversarial mixed-density cases (prose + CJK + emoji) returned None while a fitting prefix existed (budget=200, 443-token layer, 106-char prefix fits) | ✅ Binary-search fallback after the proportional fast path: converges whenever a fitting prefix exists; returned candidate always re-measured (BPE seam wobble can't phantom-fit). Re-run harness: **0 unjustified-None, 0 over-budget in 284 cases** |
| Their suggested fix: "return the smallest candidate anyway, the pre-send guard trims it" | ❌ **REJECTED**: deliberately shipping over-budget context = re-introducing the amputation roulette the whole guard architecture exists to prevent | Convergence instead of roulette |
| `None` when even suffix doesn't fit | ✅ Correct as-is (genuinely unfittable) | Regression-pinned in a test |

Suite: **80/80 green** (2 new property tests with a brute-force oracle).
