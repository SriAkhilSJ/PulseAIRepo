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
