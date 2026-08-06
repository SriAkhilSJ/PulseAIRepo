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

---

## 13. Round-13 Audit Follow-ups (2026-08-05)

Ninth pasted review — round-12 audit came back clean ("Ship this"), with
the reviewer honestly retracting both of their round-12 false claims (test
absence, proxy path). Three minor issues raised; verdicts:

| Claim | Verdict | Action |
|---|---|---|
| 1. `_safe_limit()` memoization race: two threads could both resolve on first use | 🟡 **REAL, proven**: barrier-gated resolve showed `calls == 2` under a controlled race. Harmless-but-wasteful (GIL makes the int write safe; both compute the same value) | ✅ Double-checked locking (`_limit_lock`); deterministic race test now pins `calls == 1` |
| 2. `_trim_to_limit` re-measures head+tail per binary iteration | ❌ **REJECTED as not-worth-churn**: runs only when already over the limit (rare), ~log2(n) iterations of a ms-scale function; even the reviewer graded it negligible. Risk of touching the guard's math > the gain | Documented here |
| 3. `RetryLLMProxy.model` getattr-chain can yield None | 🔴 **REAL — and *worse than the reviewer's "Low"***: in auto mode (`PSL=0`, the paid-tier path), model=None resolves the unknown-model 4,096 while the engine budgets the full discovered window. Production-shaped proof: **engine 126,976 vs proxy 4,096 — silent amputation, zero warnings** | ✅ Fallback to `settings.LLM_MODEL` (the factory's own source of truth) + loud log line; lockstep regression test |

Suite: **83/83 green** (3 new tests: deterministic race, extraction
fallback, engine↔proxy lockstep with hidden model attr).

---

## 14. Round-14 Nit (2026-08-05)

Tenth pasted review — round 13 verified clean, reviewer retracted their
round-12 "Low" grade in writing (correctly upgraded to High). One residual:

| Claim | Verdict | Action |
|---|---|---|
| `LLM_MODEL` fallback import sits in `try/except: pass` — could still exit silently with `model=None` | 🟡 **REAL (hygiene)**: settings is fully loaded at factory import time (module-level imports of its API keys), so the `except` could only ever mask a pathological failure INTO the silent state the whole feature exists to kill. House rule: never silent | ✅ `try/except` removed; final loud WARNING if model is still falsy; 2 new tests pin both the announce-fallback and announce-pathological paths |

Reviewer-confirmed non-issue: fresh `_limit_lock` per `bind_tools()` proxy
is correct by construction (per-instance memoization).

Suite: **85/85 green** (+2). Ten review rounds complete.

---

## 15. D1: Session-Scoped ContextEngines (2026-08-05, founder-prioritized)

The last big architecture debt. **Proven pre-fix:** the module-level
`context_engine` singleton shared `_layer_cache`, `_last_layers_sent`,
feedback history, and learned LAYER_RELEVANCE weights across every
dashboard session. Deterministic demonstration: session B's build between
A's build and A's `record_feedback` made A's feedback row carry B's exact
layer composition (A's `progress` layer gone from the record), and every
weight drift steered every other session.

**Shipped:**
- `_ENGINES` registry in chat_graph: memoized per `thread_id` (nodes pass
  their `RunnableConfig`; tools/tests may pass a raw key), `OrderedDict`
  LRU capped at 128, one lock for registry mutation.
- `finalize_node` / `recovery_limit_node` now declare `config` (LangGraph
  injects it) — previously they could not reach a session key at all.
- Per-engine `_api_lock` (RLock) wrapping `build_ai_messages` /
  `record_feedback`: same-session concurrent turns (dashboard double-fire)
  can't interleave mutations. Planner message builders audited and found
  PURE (zero self-mutation) — planner singleton correctly left alone;
  premature registry rejected.

**By-design boundary (documented, not a bug):** the feedback JSON file
stays a GLOBAL learning channel — new session engines bootstrap their
weights from accumulated history. Cross-session *learning* is the point of
the feature; cross-session *mutation* was the bug. True multi-tenant
isolation (per-user feedback files, per-user memory) is a product decision
for later, not an engineering defect today.

**Post-fix proof:** the exact pre-fix scenario now records A's own layer
composition (printed `True`), and 12-record failure drift on session A
leaves session B's weights byte-identical.

Suite: **94/94 green** (8 new tests: registry memoization, default bucket,
LRU eviction w/ exact order semantics, attribution + weight isolation,
8-thread same-session hammer, node config wiring, end-to-end recovery-limit
feedback on the right engine). One degraded-memory test updated for the new
`finalize_node(state, config)` signature.

---

## 16. D1 Follow-ups: Feedback-Store Race + Shared Classifier (2026-08-05)

Eleventh pasted review — D1 audit clean, three issues; verdicts:

| Claim | Verdict | Action |
|---|---|---|
| 1. Feedback file race: session engines full-rewrite the SAME `context_feedback.json` — last writer wins | 🔴 **REAL — and D1-promoted**: latent under the singleton (one practical writer), now N engines each holding own history. Proven pre-fix: interleave A→B→A and disk held only `[A, A2]` — **session B's row gone** | ✅ Append-only JSONL store (one line per record, O_APPEND — no writer ever overwrites another); defensive reader skips debris from theoretical cross-process tears; legacy `.json` auto-migrates to `.jsonl`; compaction at 2000→1000 lines via pid-tmp + `os.replace` |
| 2. Per-engine TaskClassifier warm-up | 🟡 **REAL — compute, not just memory as they graded**: every new session engine re-encoded ~25 prototypes at first build; classifier is read-only after init (verified) | ✅ One process-wide shared classifier (double-checked lock); regression test pins `a._classifier is b._classifier` |
| 3. Missing `thread_id` collapses sessions into `"default"` | 🟡 By-design SAFE degradation (isolation loss, never correctness — per-engine lock holds); dashboard always passes thread_id | ✅ One-time per-process loud notice — if plumbing ever regresses, it's visible at boot instead of silent session collapse |

Global feedback learning channel **kept by design** (§15): a fresh engine
still bootstraps from other sessions' records — now via the union of the
shared append-only file instead of racy rewrites.

Suite: **101/101 green** (7 new: the proven-loss reproduction as a
regression test, global history, debris tolerance, legacy migration,
compaction, 2× shared classifier). Two JSON-array readers updated to JSONL.

---

## 17. The 18-Issue Deep Review (2026-08-05)

Twelfth pasted review — a full-repo sweep. All 18 claims verified; 10
merged, 3 false/overstated, 1 rejected, 4 deferred as sized debts.

| # | Claim | Verdict | Action |
|---|---|---|---|
| 1 | Dashboard imports flask/flask_cors, deps list only fastapi/uvicorn | 🔴 **REAL, proven** (`ModuleNotFoundError` on the declared set — dashboard crashes on fresh install) | ✅ flask + flask-cors in pyproject |
| 2 | Sub-agent deadlock | 🟡 **Mechanism overstated** (same-thread serialized conn, distinct sub-* thread ids, WAL+busy_timeout), but recursion + parent-blocking real | ✅ Depth cap: sub-agents can't spawn sub-agents (caller thread_id via RunnableConfig; was hardcoded "main"). Full isolation → **debt D7** |
| 3 | Checkpointer single-conn thread-unsafe | ❌ **FALSE here**: empirical `journal_mode=wal, busy_timeout=5000`; CPython sqlite is threadsafe-serialized | Evidence documented |
| 4 | shell=True bypass | 🟡 Their example was **already caught** ("rm -rf" literal substring), but benign-payload substitution (`$(cat ~/.env)`) slipped through | ✅ ALL command substitution ($()/backticks) escalates to approval; guard documented as checkpoint-not-sandbox |
| 5 | Vector memory 500-row python scan | ✅ REAL, under-scale today | **Debt D8** (sqlite-vec migration, self-contained) |
| 6 | No LLM timeouts | 🔴 **REAL** (all 5 constructors bare) | ✅ 60s timeout on every provider (param names signature-verified: request_timeout for OpenAI/Groq, timeout for Gemini) |
| 7 | search_code brute force | 🟡 REAL, worse than stated: **zero skip logic** (.git/node_modules greps). Their FTS reroute **rejected** (substring-grep ≠ BM25 question) | ✅ Skip-dirs + 2MB file cap + 2k-file budget + 500-result cap |
| 8 | cl100k counting for Qwen default | 🟡 REAL, bounded | ✅ Margin rule upgraded: max(4096, 5% of window), one shared `usable_window_budget()` formula for engine AND proxy (deduplicated) |
| 9 | Dashboard zero input validation | 🔴 **REAL** | ✅ 10k-char message cap, strict thread_id regex (flows into registry keys + file paths), 1MB body cap + 413 handler; flask test-client suite |
| 10 | Tool→graph circular import | ✅ REAL | ✅ `src/utils/diff_utils.py` neutral module; file_tools no longer imports chat_graph |
| 11 | progress_node god node | 🟡 REAL | **Debt D9**: split only after golden behavior tests exist — 200-line node surgery without them is how regressions ship |
| 12 | compute_unified_diff fragile | ❌ **OVERSTATED** (parser reads difflib's own output; "\ No newline" line degrades to context) | ✅ Edge tests pin: empty file, no-trailing-newline, identical content |
| 13 | `add` math tool wastes a slot | 🔴 REAL | ✅ Removed from tool list (module kept for the scratch script) |
| 14 | is_plan_approval fooled by "yes, but..." | ❌ **FALSE**: exact full-message set membership, not substring | Evidence documented |
| 15 | AgentState total=False too permissive | ❌ **REJECTED**: LangGraph reducers return partial dicts — total=False is the idiom, total=True would break every node return | Rationale documented |
| 16 | repo_map singleton cross-workspace race | 🔴 **REAL — same class as D1**: two sessions on different workspaces flip-flop a full AST rebuild EVERY turn | ✅ Per-workspace registry + lock (same pattern as engines) |
| 17 | web_fetch regex HTML parsing | 🟡 REAL, gracefully degrading heuristic | **Debt D10** (bs4 swap, low value) |
| 18 | Placeholder pyproject description | 🔴 REAL | ✅ Real description |

**Process note (transparency):** the diff-utils move initially over-captured
via regex and amputated module code; caught by the suite (imports failed),
repaired with exact restoration from HEAD, and the incident is recorded
here because the harness catching me is the point of the harness.

Suite: **127/127 green** (+26: dashboard validation suite incl. 413/evil
thread_ids, guard substitution, timeouts per provider, repo_map registry,
diff edges, search skips, sub-agent depth cap, add-removal).

---

## 18. Reviewer Self-Verification of the 18-Issue Review (2026-08-05)

Thirteenth pasted artifact: the §17 reviewer "rigorously re-verified" their
own review — confirming 15 claims, retracting 1 (adopting this audit's FALSE
verdict on `is_plan_approval`), pivoting it to a new claim ("too narrow"),
and silently dropping 2 (#11 progress_node god-node, #12 compute_unified_diff
fragility — both remain attached to their §17 verdicts here). Every line
number they cite matches the PRE-patch tree; the round-12 bundle (upstream
`445073c`, `c48a42b`) landed between their review and their verification.

All 16 rows re-verified live against the post-patch tree:

| Their row | Verdict now | Fresh evidence (this turn) |
|---|---|---|
| Flask missing from deps | FALSE NOW | `pyproject.toml:11-12` flask + flask-cors |
| Sub-agent deadlock | **REFUTED BY REPRO** | Nested `graph.invoke` — same compiled graph, same `SqliteSaver`, same connection, same thread: 3 levels (`main → main/sub0 → main/sub1`) all execute, 0.010s, zero errors. Depth cap additionally shipped (`chat_graph.py:231`). Parent-blocking isolation stays in debt D7 |
| Shared checkpointer connection | FALSE — sharper proof + a real caveat (below) | `SqliteSaver` holds an internal `threading.Lock` (langgraph-checkpoint-sqlite :95); every cursor op runs `with self.lock:` / `with self.cursor(...)`; its docstring: *"check_same_thread=False is OK as the implementation uses a lock to ensure thread safety."* 4-thread concurrent-put hammer through the saver: **200/200 checkpoints, zero errors, zero loss** |
| `shell=True` injection vector | FALSE NOW as stated | `SafeToolNode(tools, SafetyGuard())` wraps ALL tools (`chat_graph.py:1538`), `run_terminal`/`start_terminal` included; round-12 escalation sends every `$()`/backtick to approval (`safety_guard.py:80`). "Guard is a checkpoint, not a sandbox" stays documented |
| Vector memory O(n) scan | STANDS → debt D8 | `vector_memory.py:89` LIMIT-500 scan, intentionally until sqlite-vec migration |
| No LLM timeouts | FALSE NOW | `factory.py:247-281`: 60s on all 5 provider constructors |
| `search_code` brute force | perf FIXED; FTS reroute REJECTED | `file_tools.py:11-18`: skip-dirs + 2MB/2k-file/500-result caps; substring-grep ≠ BM25 question-answering |
| Dashboard zero validation | FALSE NOW | `dashboard_server.py:43,54,58-60`: thread_id regex, 10k-char message cap, 1MB body cap + 413 handler |
| Circular imports in tools | FALSE NOW | Fresh-interpreter `import src.tools.file_tools` pulls **zero** graph/dashboard modules — `compute_unified_diff` (:374) and `event_bus` (:389) imports are both function-lazy; `event_bus.py` itself is a leaf (json/queue/threading/time only) |
| `add` math tool | FALSE NOW | gone from the tool list |
| `AgentState(total=False)` | REJECTION STANDS | LangGraph reducers return partial dicts; `total=True` would break every node return — idiom, not sloppiness |
| repo_map singleton race | FALSE NOW | `_repo_map_instance` symbol GONE; per-workspace registry + lock (`repo_map.py:369,382`) |
| `web_fetch` regex HTML | STANDS → debt D10 | low-traffic tool; bs4 swap sized |
| Placeholder description | FALSE NOW | `pyproject.toml:4` real description |
| cl100k fallback for Qwen | **PARTIALLY STANDS — honestly scoped** | `token_tracker.py:168-170` still falls back to `cl100k_base` for non-OpenAI models. The CONSEQUENCE is dead: budget safety moved to `usable_window_budget()` (margin = max(4096, 5%·window), shared by engine AND proxy, §17#8), so counting drift can no longer overflow/amputate context. Remaining residue = display/cost-accounting precision only. Their AutoTokenizer fix rejected: a heavy transformers dep for display math. Documented known limitation |
| Pivot: "approval matching too narrow" (yep/yeah/ok/sure) | **REJECTED AS UNSAFE DIRECTION** | approvals = {approve, approved, execute, execute plan, run plan, proceed, go ahead, continue, yes}. An approval gate must **fail closed**: false negative = retype "approve"; false positive = destructive plan executes on a non-approval. Fuzzy-NL approval is the exact anti-goal the gate exists for. Their factual basis ("ok/sure/yep don't match") is true — and that is the correct, now-pinned behavior |

**The hammer that bit me first (process honesty, same rule as §17):** my
first shared-connection stress test hammered the RAW `sqlite3.Connection`
with `conn.execute` from 8 threads and DID fail — `InterfaceError`, lost
rows (244/1600). That failure mode is real (CPython's own docs warn about
unsynchronized concurrent use of one connection object) — but it is *not the
pattern this codebase exercises*: every checkpointer access goes through
`SqliteSaver`'s internal lock. Recorded lesson: **never add bespoke raw-conn
writers to `_checkpoint_conn`** — go through the saver. Pragmas (my §17-era
evidence) were necessary but not sufficient proof; the saver lock is the
actual guarantee. The reviewer's claim stays false; my own method leveled
up. My first nested-invoke repro also had a bad assertion (expected the
outer invoke to return the innermost depth) — corrected, re-run, refutation
intact. Both corrections published here because the harness catching
ME is the point of the harness.

**Scorecard across both artifacts of this review (18 claims + 1 pivot):**
10 merged, 3 false/overstated on mechanism, 1 idiom rejection, 4 deferred
debts, 1 pivot rejected as unsafe. Suite: **130/130 green** (+3 pinned this
round: nested-invoke refutation, concurrent-session saver hammer,
fail-closed approval).

---

## 19. The Reviewer's Third Artifact: "Fresh Verification" (2026-08-05)

Fourteenth paste — the §17/§18 reviewer's "fresh" verification. It now
acknowledges 9 fixes (the §17 merges, plus round-7's atomic `edit_file`
and the §4-era per-workspace guard cache — noticed by them for the first
time). But its "still broken" list contains **zero new actionable items**,
and two of its three "priority fixes" recommend changes this audit already
disproved empirically:

| Their "still broken" row | Verdict | Evidence |
|---|---|---|
| `shell=True` CRITICAL → "shlex.split + shell=False" | **REJECTED (3rd time)** | Demo: `shlex.split("cat app.py \| grep TODO > t.txt && echo done")` makes `'|'`/`'>'` literal argv — pipes, redirects, `&&` silently break. An agent that can't run `npm run build && npm test` is not a coding agent. Control plane = SafeToolNode checkpointing ALL tools + `$()`/backtick escalation (§17#4). Same architecture as Claude Code/Cursor: shell + permission gate. The guard is documented as a checkpoint, not a sandbox |
| Sub-agent synchronous deadlock CRITICAL | **FALSE — refuted, now test-pinned** | Live repro (§18): nested `graph.invoke`, same graph/saver/conn/thread — all 3 levels execute in 0.010s, zero errors. Parent-blocking isolation remains = debt D7, which is a design task, not a deadlock |
| SQLite shared connection CRITICAL → "use `from_conn_string()`" | **FALSE — and their fix is broken** | `SqliteSaver.from_conn_string()` returns a `_GeneratorContextManager`, NOT a saver — disproven in §5(T1) *ten rounds ago*, re-recommended here as "priority fix #2". Real guarantee re-pinned: saver-internal `threading.Lock` + concurrent-put hammer in committed tests |
| VectorMemory O(n) scan | STANDS → **D8** | sized debt |
| `search_code` brute force | caps shipped; ChunkIndex reroute **REJECTED** | substring-grep ≠ BM25 question-answering (§17#7) |
| `AgentState(total=False)` | **REJECTED** | LangGraph idiom (§17#15) |
| repo_map "no lock on `_repo_map_instance`" | **THE SYMBOL IS DELETED** | `grep _repo_map_instance src/context/repo_map.py` → no match. Per-workspace registry + `_repo_maps_lock` at :369-382. The reviewer cites nonexistent code as evidence of a live race |
| `web_fetch` regex HTML | STANDS → **D10** | sized debt |
| Qwen tokenizer | residue only — display/cost precision; budget consequence dead via shared `usable_window_budget()` margin | §18 row 15 |
| `is_plan_approval` narrow matching | **REJECTED as unsafe** | approval gates fail closed; pinned by committed test (§18) |

**Reviewer meta-scorecard across its three artifacts:** (1) 18 claims → 10
merged, 3 false/overstated, 1 rejected, 4 debts. (2) 16 "confirmations" →
10 stale-tree, 1 pivot rejected as unsafe. (3) 10 "still broken" → 3
refuted by reproductions now committed as tests, 1 citing deleted code, 3
repeating rejected positions, 2 standing debts, 1 scoped documentation
note; its top 2 "priority fixes" were previously disproven by this audit.
Verdict on this reviewer as a source: **reliable idea generator,
unreliable verifier — it never executes the code it grades.** Keep feeding
its claims into the gauntlet; stop treating its severity ratings or its
"verified" stamps as signal.

---

## 20. D2: Process-Wide Embedding Cache (2026-08-06, founder "next")

The last debt item that touched every turn. **Measured pre-fix waste** on
a 16-layer turn: **60 vector encodes, every turn, none of them new work** —
1 task single + 16 layer singles (scoring) + 16 (dedup re-encoding the
SAME texts) + 27 ambiguity encodes (26 module-constant strings) + 1
classifier query. Session-scoped engines (D1) made it per-session: 128
sessions each re-encoded identical workspace texts independently.

**Shipped:** `src/context/embedding_cache.py` — content-addressed LRU
memoization. Key = sha256(embedder identity + normalize flag + text);
embeddings are a pure function of the key, so there is no TTL, no
invalidation, and no staleness by construction. Values stored as float32
(the backend's native precision — round-trip exact); 4096-entry cap ≈ 6MB;
shared process-wide like the TaskClassifier; compute outside the lock
(duplicate compute under a race is benign; serializing embedder work would
be self-inflicted latency). All four engine encode call-sites routed
through it (scoring, dedup, ambiguity, classifier query).

**Measured post-fix** (16-layer turns, counting embedder wired into the
real engine methods):

| Metric | OLD | NEW | Delta |
|---|---|---|---|
| encodes, cold turn (16 layers) | 60 | 43 | **-28%** |
| encodes, steady turn (unchanged state) | 60 | **0** | **-100%** |
| encodes, 2-turn sequence | 120 | 43 | **-64%** |
| encodes, 10-turn session | 600 | ~43 | **-93%** |
| encode() backend calls, cold scoring | 17 (1+N singles) | 1 batch | fewer API round trips |

Cross-site wins fall out for free: dedup rides scoring's vectors (0
encodes), ambiguity's task string rides scoring's (0), the classifier's
repeat query rides everything (0).

**Self-caught by the suite (process honesty, same rule as always):**
1. **`max_entries` edge bug proved by a test**: a batch larger than cache
   capacity got its own oldest entries evicted before results were read →
   `None` slots. Fixed: results are filled BEFORE eviction, plus a loud
   invariant raise (never a silently missing vector).
2. First ambiguity test demanded 27 encodes; got 26 — the cache correctly
   deduped my demo task ("make it better") against the ambiguous-string
   constant it collided with. Cache was right; test was wrong.
3. First fake embedder emitted all-positive components → everything looked
   similar (cos 0.66–0.90) → accidental dedup removals. Zero-centered
   components, because real embedders are mixed-sign.
4. The measurement harness itself had a bug (a `lambda: EmbeddingCache()`
   constructing a fresh cache per call masked all cross-call hits) —
   caught because the printed numbers contradicted the passing tests.

Suite: **140/140 green** (+10: warm-turn-zero, bit-identical cold/warm
scores, dedup-rides-scoring, consts-once, classifier-query-once,
order/duplicates, changed-only, LRU bound, identity-swap isolation,
8-thread hammer with zero corruption).

**Artifact-4 footnote (trail convention):** the fourth reviewer paste
("Fresh Verification — Aug 6") contained zero new technical claims; its
one new factual assertion (correct qwen pricing row) verified TRUE
(`token_tracker.py:42-43`). Adjudicated in-chat against §17–§19; recorded
here so every artifact's verdict lives in the trail.

Debt board: ~~D1~~ ~~D2~~ — next: D5/D7 (first real milestones), D8–D10,
P2.

---

## 21. D5 Milestone 1: Multi-Language Chunk Index via tree-sitter (2026-08-06, founder-directed)

Founder direction: *"continue D5 — use vscode fork apis if it's available."*

**The fork-APIs verdict (verified against the remote tree, not assumed):**
`desktop/` on GitHub IS a VS Code fork (`desktop/product.json`,
`desktop/src/bootstrap-fork.ts`). Its language APIs are (a) TextMate
grammars — regex tokenizers, no AST — and (b) LSP servers — out-of-process
daemons behind TypeScript extension-host IPC. **Neither is importable
from the Python backend**, and spawning Electron/node just to parse files
at index time is the wrong shape for a microsecond-scale in-process task.
The Python-consumable technology for exactly this job is tree-sitter
(error-tolerant concrete syntax trees, per-language grammar wheels) — the
same class of parser Cursor/Aider-style indexers use. Fork/extension APIs
pay off at **P2** as *integration* points (file-watch feeds → index
freshness, diagnostics → context), not as parsers. Direction applied
accordingly: D5 = tree-sitter.

**Shipped (milestone 1: JS/TS family — `.js/.jsx/.mjs/.cjs` +
`.ts/.tsx/.cts/.mts`):**
- **NEW `src/context/lang_extractors.py`** — tree-sitter extraction:
  functions, arrow/function-expression consts, classes (methods embedded
  into the class chunk, Python-parity), `export`/`export default`
  unwrapping, `/** */` and `//` doc comments (including above `export`),
  module header chunks, 2MB/50k-node safety valves, output schema
  byte-identical to the Python extractor's.
- Python keeps its stdlib-ast extractor (richer; verified for
  async/decorators). Dispatch via `extract_source_chunks()`.
- `_iter_py_files` → `_iter_source_files` with a **dynamic extension
  allowlist**: a grammar that fails to load drops out of the set
  (Python-only degrade, one loud notice per process) — a slim environment
  never walks files it cannot parse.
- File watcher is suffix-agnostic (same debounce/queue machinery).
- Diff fences now match the language (` ```javascript ` etc. — was
  hard-coded ``` ```python ``` on everything).
- **D2×D5 synergy:** `_embed_batch` rides the D2 embedding cache —
  re-syncing an edited file now re-embeds only chunks whose content
  actually changed (test-pinned: 4-chunk file + 1 appended function →
  ≤2 encodes instead of 5).

**Verified live end-to-end in sandbox:** mixed py/js/ts/tsx workspace
indexes per language; BM25 retrieval hits the right symbol in the right
language (`login`→session.js, `fetchUser`→api.ts, `Dashboard`→App.tsx,
`validate_password`→auth.py); production layer path (`get_index` registry)
serves a JS task the exact `logout` chunk under a `javascript` fence;
broken JS extracts a module chunk without crashing.

**Self-caught during build (process honesty):** JSDoc above
`export function` failed to attach — the comment is a sibling of the
*export statement*, not of the unwrapped declaration inside. Caught in
smoke testing; fixed via a doc-anchor parameter. One demo-layer `None`
was my harness bypassing the process-wide index registry (fresh DB), not
a product bug — re-proven through the real `get_index` path.

Suite: **151/151 green** (+11: JS/TS/TSX extraction shape, variable
ignores, interface/type ignores, JSDoc+line-comment docs, broken-source
tolerance, schema parity with Python, loud-once degradation, e2e
index/search/edit-sync/remove for JS, iter allowlist + skip-dirs,
re-embed-on-edit encode budget).

**Deferred by scope (honest):** more grammars (go/rust/java — config-level
adds once this pattern bakes in production); LSP-grade semantic info (P2
design space — that's where the extension APIs live).

Debt board: ~~D1~~ ~~D2~~ ~~D5(m1: JS/TS family)~~ — remaining: D5-2
(more grammars, as users demand), D7, D8, D9, D10, P2.

---

## 22. D5-2: Go / Rust / Java Grammars (2026-08-06, founder-directed)

Founder said "D5-2". The milestone-1 deferral ("more grammars, as users
demand") arrived same-day.

**Grammar-first process:** every node type used below was verified by
spiking the installed grammar wheels against real source files BEFORE
writing the extractor — tree-sitter grammars name things differently
per language, and docs drift:

| Language | Verified shapes (installed wheels) |
|---|---|
| Go 0.25.0 | `function_declaration`/`method_declaration` (both with `name` field); structs via `type_declaration → type_spec → name`; comments are `comment` |
| Rust 0.24.2 | `function_item`; `struct_item`/`trait_item` (named); `impl_item` has NO name — resolved as `impl <Type>` from its `type_identifier`; doc comments are `line_comment` containing `doc_comment`; methods live in `declaration_list` |
| Java 0.23.5 | `class_declaration`/`interface_declaration` (named); members in `class_body`/`interface_body` as `method_declaration`/`constructor_declaration`; javadoc is `block_comment` |

**Shipped:** `_walk_generic` — a config-driven walker (per-language node
sets + comment types + method containers + name-resolution strategy);
`_load_grammar` generalized to importlib over a kind→(module, attr) map;
`extract_chunks_ts_js` renamed `extract_chunks_treesitter` (it earns its
name now); fences `go`/`rust`/`java`; 3 wheels added to pyproject
(**uv sync required**). Python still stdlib-ast; JS/TS walk untouched.

**Granularity parity decisions (reviewable, not accidental):** Go receiver
methods are top-level chunks (they ARE top-level declarations in Go);
Rust impl methods embed in the `impl <Type>` class chunk (Python-class
parity); Java has no standalone method chunks (same parity); type-only
constructs (interfaces ARE class chunks — they're searchable and hold
signatures; Java enums, Go iota consts skipped by scope).

**Verified live:** all three languages extract names/lines/docs correctly
(module header, goto doc comments, JSDoc blocks); `impl Session` carries
its method list; broken .rs/.go sources tolerate; production
`build_relevant_chunks_layer` serves Rust and Go tasks with the right
fences; e2e index/search/edit-sync/remove per language green.

**Self-caught:** degrade test broke honestly — it only blocked the JS/TS
wheels, but go/rust/java grammars now load fine, so "Python-only" was no
longer python-only (assertion caught scope, code was right); iter test
lost a fixture line to my own edit (assertion caught the fumble).

Suite: **157/157 green** (+6: per-language extraction, broken-source
tolerance×2, extension allowlist, e2e trilingual workspace).

Debt board: ~~D1~~ ~~D2~~ ~~D5 (JS/TS + Go/Rust/Java)~~ — remaining: D7,
D8, D9, D10, P2. Adding more grammars (C/C++/C#/Ruby/PHP) is now a
~15-line config + wheel each, when users ask.

---

## 23. Second-Source Six-Pillar Review Adjudication (2026-08-06)

Founder pasted a "six pillars of context engineering" review scoring the
engine **5.8/10**. Reviewer's own preamble states method: *"I was able to
pull the repo metadata, README, architecture review, and dependency
manifest"* — **documents, not code**. Verified all ~20 checkable
assertions empirically against upstream `504e099` (the ref they saw).

**Killshot finding:** every "bug" this review reports as present-tense is
a **verbatim quote of §1 of this document** — the ORIGINAL review's fix
list (§1:41-45, §1:93) — read without its resolution column (§:128
"✅ Corrected", etc.). They quoted the problem half of the audit log and
stopped before the fix half. Same method failure as §19, second source.

| # | Reviewer claim | Verdict | Evidence |
|---|---|---|---|
| 1 | "No chunk-level code retrieval" | **FALSE** | `chunk_index.py` upstream since `ca3fd5c`: per-symbol module/function/class chunks; their quote of "Cursor's actual moat…" is §1:44, pre-fix text |
| 2 | "No BM25/lexical retrieval" (their P0) | **FALSE** | `chunk_index.py:6` sqlite-vec KNN + **FTS5 BM25** fused via RRF (`:186,:613,:620`); the P0 fix is already shipped |
| 3 | "MemorySaver checkpointer → state dies on restart" (their P1) | **FALSE** | `chat_graph.py:1810` `SqliteSaver(_checkpoint_conn)`, sessions at `~/.pulseai/sessions.db`; quote is §1:41, corrected per §:128 |
| 4 | "TaskClassifier re-instantiated every turn" | **FALSE** | process-shared singleton `_get_shared_classifier()` (`context_engine.py:153-159`, fixed `445073c`) |
| 5 | "LAYER_RELEVANCE class attribute mutated" | **FALSE** | per-instance `copy.deepcopy` (`context_engine.py:261`) |
| 6 | "record_feedback snapshots session cache, not per-turn layers" | **FALSE** | attributes `self._last_layers_sent` (`context_engine.py:1200`), cache is only the never-happens fallback |
| 7 | "No mtime-based cache invalidation" | **FALSE** | `repo_map._is_stale()` mtime check + auto-rebuild (`repo_map.py:354-357,:83-84`); chunk index per-file mtime re-insert (`chunk_index.py:329,:504`) |
| 8 | "No incremental re-indexing" | **FALSE** | watchdog-backed watcher + polling fallback + selective re-insert (`chunk_index.py:347-435`) |
| 9 | "~10.6K LOC" | WRONG NUMBER | 15,809 src LOC (`find src -name '*.py' | xargs wc -l`) |
| 10 | "repo_map capped at 1,200 tokens" | HALF | default is 1500 (`repo_map.py:76`); 1200 at the one engine call site |
| 11 | "No tool output truncation discipline" | OVERSTATED | per-tool caps exist: terminal head/tail split (`terminal_tools.py:163-172`), web `max_chars` (`web_tools.py:117`), search match cap (`file_tools.py:238`). TRUE part: no GLOBAL budget on cumulative tool output entering history → **D11** |
| 12 | "No graduated truncation / no binary-search fit" | OVERSTATED | `_compress_map` is two-stage (strip symbol details → truncate) and protects the import graph (`repo_map.py:293-327`). TRUE part: no per-symbol relevance ordering → folded into **D14** |
| 13 | "Vector memory = linear scan of 500 rows" | TRUE | `vector_memory.py:89` (code comment admits it); already **D8** |
| 14 | "No cross-encoder re-ranking" | TRUE | nothing in src/ — **D13** (new, P3) |
| 15 | "No observation masking / reference pointers" | TRUE | nothing in SmartCompressor — **D12** (new, P2) |
| 16 | "Import graph not traversed at retrieval" | TRUE | graph is rendered (top-20) into map text (`repo_map.py:148-149`), no edge-walk retrieval — **D15** (new, P2) |
| 17 | "No PageRank-style symbol ranking" | TRUE | — **D14** (new, P2) |
| 18 | "No headroom reservation for next tool result" | TRUE-ish | static ceiling only; folded into **D11** |
| 19 | 9 task types / SafeToolNode / tier routing (their praise) | TRUE | `TaskType` enum `context_engine.py:49-59` |
| 20 | PROVIDER_SAFE_LIMIT=6000 | TRUE | `settings.py:61`, env-overridable; model-aware budgets also live |

**Net new value extracted (this is what a review is FOR):** four real
gaps filed as debt — **D11** (global tool-output budget + headroom
reservation), **D12** (observation masking of aged tool outputs),
**D13** (cross-encoder re-rank of top-k), **D14** (PageRank-style symbol
ranking / binary-fit repo map), **D15** (graph-traversal retrieval
expansion over the existing import graph).

**Re-score on their own rubric, with evidence:** P1 4→**6.5** (chunk
index + repo map + import graph exist; PageRank/type info absent), P2
3→**7** (KNN+BM25+RRF exist; re-rank/graph-expansion absent), P3 5 (they
were mostly right; per-tool caps soften "no discipline"), P4 3→**4**, P5
4→**5.5** (attribution + persistence fixed), P6 3→**7** (mtime+watcher on
both indexes). ≈ **7/10** — the closure from their 5.8 to 7 was done by
this audit loop, reading this document. Irony noted.

**Process note:** no code changed this turn. The D2→D5-2 stack is still
unapplied upstream; D11/D12 are the next candidates **after** it lands —
not before. Piling more unapplied commits on the queue is how patches
rot.

---

## 24. Six-Pillar Round-2 Re-Review Adjudication (2026-08-06)

Same source as §23 returned after the D2→D5-2 stack landed upstream
(`504e099..955b636` — 5 commits since their c48a42b-era review; their
cited `517a771` is not in repo history, tooling-side ref). Re-rating:
5.8 → **7.2/10**. **This time they read code** — design-note quotes,
real constants (`BODY_HARD_CAP_CHARS=800`, 2-file cap, `top_k=3`,
`vec_distance_l2` on `FLOAT[384]`, batch commits, RRF-k=60): all
verified TRUE against the tree. Method upgraded mid-stream.

Two residual allegations re-verified empirically (pins in
`test_review12_reverify.py`, suite 157→**159**):

| Claim | Verdict | Evidence |
|---|---|---|
| "Feedback attribution STILL broken — `record_feedback` snapshots `self._layer_cache`" (their P0, "Low", gates 8.0) | **FALSE** | `:449-454` step 7b snapshots post-assembly layer NAMES every build — its comment pre-answers the criticism ("not the session-wide layer cache"); `:1200`'s cache expression is the documented no-build-yet fallback. Functional pin `test_feedback_attribution_names_sent_layers_not_session_cache`: injects a decoy cache key never sent → feedback row contains exactly the sent layers, decoy excluded. Reviewer quoted the fallback branch and never saw the primary one — same selective line-reading as §23's §1-quoting. Bug-fix scorecard corrects to **6/6** |
| "watch param exists but isn't wired into the main loop" | **FALSE** | `get_index(..., watch=True)` is the per-workspace production factory (chunk_index.py:769-, docstring: "production default… Tests pass watch=False"); the 16-layer builder goes through it + per-serve `sync_workspace()` (:807). Pin: `test_chunk_index_watcher_is_production_default` asserts the signature default |
| vector_memory linear scan remains for personal memory; code path bypasses it | TRUE | standing **D8** |
| Remaining gaps (re-rank, graph expansion, tool-output masking, adaptive compaction pipeline, cross-session playbook) | TRUE | D13/D15+D14, D11/D12, D9-adjacent, **D16 new** (playbook/`record_decision` — the only genuinely new debt this review) |
| Their P0 fix-list top item for 8.0+ | n/a | already shipped — the gate moves to D13/D15 |

**Meta-verdict update (supersedes §19 in part):** this source is now a
*reliable describer of what code says, unreliable auditor of what code
does* — every TRUE claim this round was a read claim; every FALSE claim
was a NOT-FIXED/wiring allegation requiring behavioral verification they
didn't run. Keep accepting their gap lists as debt candidates; keep
refusing their "still broken" verdicts without a reproduction. Rating
convergence noted: my independent §23 re-score (≈7.0) precedes their 7.2;
two evidence-based reconciliations landed within 0.2.

**Self-caught this round:** pin test first imported the factory as
`_index_for` (my guess) — collection ImportError caught it; real name is
`get_index`. Suite doing its job.

Debt board: ~~D1~~ ~~D2~~ ~~D5~~ — remaining: D7 (sub-agent isolation),
D8 (vector ANN), D9 (progress_node split), D10 (web_fetch soup),
D11 (tool-output budget), D12 (observation masking), D13 (re-rank),
D14 (symbol ranking), D15 (graph-expansion retrieval), D16 (cross-session
playbook), P2 (VS Code ext).

---

## 25. "Finish the Context Engine" — Round 1 (2026-08-06, founder-directed)

Founder order: finish the context engine completely before other task
types, in plain English. Round 1 shipped D8 and — more important —
**caught and revoked two debts I had filed wrongly in §23.**

**D11/D12 REVOKED (my §23 filing error, owning it):** "no observation
masking / no tool-output discipline" — FALSE, and the reviewers who
claimed it and I who seconded it all missed the same file:
`src/context/summarizer.py` (SmartSummarizer, per-tool-family compress
rules, free-heuristic-first, LLM only >8K chars), live on EVERY build at
`context_engine.py:457` (`_summarize_tool_messages` runs before
history trim). Coverage: any tool output >800 chars gets head/tail +
structure compression at assembly time; tool-side caps
(terminal/web/search) bound output at creation. Remaining sliver
(in-loop same-turn giant outputs, custom tools without caps) is
documented here as degenerate, not shipped as fake work. My error was
keyword-shaped searching ('mask', 'placeholder') instead of reading the
pipeline. The gauntlet catching the auditor is the system working.

**D8 SHIPPED (reframed by measurement):** vector_memory.py v3.
The §23 filing said "performance debt". Measured truth: the LIMIT-500
scan is O(500) FOREVER — it never gets slower; its disease is
CORRECTNESS (memories older than the newest 500 are silently
un-recallable). Shipped: vec0 derived index (blob column remains source
of truth; zero-migration backfill at boot; dual-write on add;
delete_old/clear keep tables in sync), legacy path preserved verbatim
when sqlite-vec is absent. Measured at 5,000 memories: legacy 38.2ms
searching 500 rows → new 4.4ms searching ALL 5,000 (+8.7x speed,
+10x recall — both real this time, both measured).

**Query-shape lesson (verified, generalizes):** vec0 search written as
`JOIN ... ORDER BY vec_distance_l2(...) LIMIT k` materializes the FULL
join — measured 155ms at 20K rows. The `embedding MATCH vec_f32(?)
AND k = ?` form + post-limit join is 13ms and tie-equivalent (verified
per-id: reported MATCH distances == directly-computed distances).
**chunk_index._search_vec_fast uses the slow shape** — fine at current
workspace sizes, now a measured suspicion on the board (C1), fix when
profiling bites. Also verified: vec0 reads raw bytes as float32 BLOB
(rejects the odd-length JSON BLOB — my first add() dual-write did
exactly this; tests caught it): feed JSON TEXT (or vec_f32()).

Suite: 159 → **164** (+5: KNN/legacy parity on gapped fixtures, the
beyond-500 recall bug test, dual-write sync, no-sqlite-vec fallback,
pre-v3 backfill). Tie physics: parity asserts order only above the
1e-5 noise floor — float32 vec0 storage turns exact-zero cosines into
~2e-7, and tie order is engine-defined (verified), never user-visible.

Debt board: ~~D1~~ ~~D2~~ ~~D5~~ ~~D8~~ — remaining: D7 (sub-agent
isolation), D9 (progress_node split), D10 (web_fetch soup), D13
(re-rank), D14 (symbol ranking), D15 (graph-expansion retrieval),
D16 (cross-session playbook), C1 (chunk_index KNN query shape —
measured 155ms@20K slow-shape pattern), P2 (VS Code ext).
~~D11~~ ~~D12~~ REVOKED (see above).
