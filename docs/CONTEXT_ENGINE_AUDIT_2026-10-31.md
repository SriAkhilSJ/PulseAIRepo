# Context Engine Audit — "is it perfect?"
**Date:** 2026-10-31 · **Scope:** `src/context/` (19,105 LOC) with `context_engine.py` (2,704) + `layer_policy.py` (497) read line-by-line · **Method:** static read

---

## Verdict

**No — and it's closer than the rest of the core.** This is the second-best-organised subsystem in the repo after `budget.py`. On *selection* it beats Aider and Cline outright. On *measurement* it has one systematic error that silently degrades every single turn, and one advertised mechanism that doesn't actually run in production.

**Score: 8.5 / 10.** The missing 1.5 is concentrated in two defects (C1, C2 below), not spread thin.

---

## What is genuinely best-in-class (do not touch)

| Mechanism | Where | Why it beats the field |
|---|---|---|
| **Hybrid retrieval** | `chunk_index.py` — sqlite-vec KNN + FTS5 BM25, fused by **Reciprocal Rank Fusion**, then re-scored with cheap zero-LLM features | Aider has no embedding retrieval at all (repo map only); Cline greps. RRF is the correct fusion — ranks are comparable, BM25's raw scores are not. |
| **`compress_layer` convergence** | `layer_policy.py` — proportional shrink → 3 attempts → **binary search on prefix length, re-measured every step** | Almost every implementation assumes a constant chars-per-token and silently drops the layer when it can't fit. The comment says exactly that happened here and it was fixed properly. This is careful engineering. |
| **Usage pressure from REAL tokens** | `usage_pressure.py` + `_apply_usage_pressure` — pressure from the provider's reported prompt, **anti-thrash: re-arms only after relax to ≤60%** | Everyone else compacts on an estimate. You compact on the truth, and you don't oscillate. |
| **Volatile tail contract** | `layer_policy.py:44–64` — `VOLATILE_LAYERS={git_context}`, emitted dead last behind a **constant** preamble | Byte-stable prefix by construction. Zero competitors do this deliberately. |
| **Content-addressed embedding cache** | `embedding_cache.py` — one batch encode serves scoring *and* dedup | Avoids the classic double-encode per turn. |
| **Fail-open everywhere** | layer builders, tokenizer, embeddings — all degrade with `warn_once` | Correct priority ordering: a turn must not die on context plumbing. |

---

## The two defects that matter

### C1 — The advertised scoring model does not run in production
`layer_policy.score_and_sort_layers` documents **"60% task-type prior + 30% semantic similarity + 10% recency"**. In production:

- `allow_embedding_compute` defaults `False` (`context_engine.py:502`) and the comment is explicit: *"a turn never encodes here… a cache miss must never trigger inference."* Correct decision — but it means the **30% semantic term is dead code in the live path**.
- The deterministic fallback is `rel * 0.9 + recency * 0.1`.
- And `recency = i / max(len(layers) - 1, 1)`, where **`i` is the index in the `builders` dict** — `repo_map`(0), `relevant_chunks`(1), `git_context`(2), `task`(3), `plan`(4) … `skills`(17). It is *insertion order*, not time.

**Consequence:** the live scoring is "90% prior + 10% which-key-I-typed-first", and the 10% term is maximally **negative on the only two layers that carry actual source code** (`repo_map`, `relevant_chunks` are indices 0 and 1 of 17), and maximally positive on `skills` and `reflections`.

**Fix (pick one, 10 lines):**
- **Delete it.** `score = rel * 1.0` is honest and removes an arbitrary bias.
- **Or make it real recency:** `plan` step index / `workspace_revision` / `last_verified_revision` — signals that mean "recently relevant", not "appended late".

Either way, rename `recency` → `position` in the meantime so nobody reads the docstring and believes it.

### C2 — Every token count is a cl100k count, and every budget derives from it
`token_budget.count_tokens()`: `tiktoken.encoding_for_model(model)` → on failure `cl100k_base` → on failure chars/4 heuristic. **`cl100k_base` is OpenAI's tokenizer.** Your production models (per `README`) are Velona/GLM, Groq-hosted Llama, Gemini, NVIDIA. Gemini is SentencePiece; Llama-family has its own BPE. Errors are not random — they are **systematic per family**, typically 10–25% on code-dense text.

That error propagates into *every* sizing decision:
- `allocate_budget` → the 9 task-type splits
- `_assemble_hierarchical` → which layers fit
- `compress_layer` → the truncation target (`target_chars = len * (max_tokens/orig_tokens) * 0.9`)
- `deduplicate_layers` → the near-duplicate threshold

And the ground truth is already in the building: **`update_from_response` stores the provider's real `prompt_tokens`** — used only for *pressure*, never to *calibrate the estimator*.

**Fix (~35 lines, and it's the highest-value change in the whole subsystem):**
```
on every response:
    est  = count_tokens(prompt_messages, model)      # what we thought we sent
    real = usage["prompt_tokens"]                    # what the provider billed
    ratio = real / est
    chars_per_token[model] = EMA(chars_per_token[model], ratio, α=0.2)
    persist in the model_budgets cache (already exists, already disk-cached)
then: count_tokens(...) *= chars_per_token.get(model, 1.0)
```
You already have `model_budgets._cache_path/_read_cache/_write_cache` — the persistence layer is done. This makes your budgeting *measured* instead of *assumed*, which is a real edge over Aider (static tokenizer table) and everyone else (chars/4).

### C2b — free calibration signal being discarded
`compress_layer` already measures the layer's **own** real chars-per-token (`len(content) * (max_tokens / orig_tokens)`) to compute its target, then throws the measurement away. Its own comment notes code runs ~2.5 chars/token against an assumed 3.5. That per-layer ratio is exactly the calibration input C2 wants. Two lines to surface it.

---

## The three smaller ones

### C3 — `hist_ratio` is computed and never used
```python
ctx_ratio, hist_ratio = ratios.get(task_type, (0.40, 0.60))
ctx = int(max_tokens * ctx_ratio)
return ctx, max_tokens - ctx          # hist_ratio never read
```
It's correct *only because every pair happens to sum to 1.0*. Add a ratio pair that doesn't and the split silently exceeds the window. One-line fix + an `assert ctx_ratio + hist_ratio == 1.0`, or just delete the unused name.

### C4 — differential cache invalidates coarsely, but less often than it looks
One `_HASHED_STATE_KEYS` hash covers all 18 layers; any change → `_layer_cache.clear()`. Fair enough (the docstring calls per-layer dependency hashing a deliberate non-goal). **Correcting my own first read:** `iteration_used` and `tool_failures` are *not* hashed, and `steps_completed`/`plan` change per plan step — so the cache genuinely survives most laps of a turn and busts at step boundaries. This is **acceptable, not a defect**. Per-layer hashing would still be a real win on 45-lap runs, but it is not urgent.

### C5 — fresh-workspace blindness compounds the repo-map defect
`_relevant_chunks_layer` returns `None` on any failure *by design* ("index still building"). `repo_map` extracts symbols only for `.py` (`repo_map.py:335/452/490`). So on a **brand-new JS/TS workspace** the first several laps have **zero source visibility**: chunks not indexed yet, map structurally blind to `.tsx`. This is the compounding path to the Milestone Lock-in Trap — the agent's "what exists here" view is literally empty of frontend.
**Fix:** the `.py` → `lang_extractors.source_extensions()` change from the main diagnosis closes this from the map side; additionally, have `_relevant_chunks_layer` emit a one-line *degraded* layer ("index building: N files queued") instead of `None`, so the model knows it's blind rather than assuming the codebase is small.

---

## Answering the question directly

| Claim | Verdict |
|---|---|
| "Perfect" | **No.** 8.5/10. Two defects (C1, C2) degrade *every* turn silently. |
| Better than Aider's context handling? | **Yes, on selection and retrieval.** Aider has no hybrid retrieval and no real-token pressure loop. Aider wins only on the repo map's language coverage. |
| Better than Cline / OpenCode? | **Yes, clearly.** Neither has layer policy, relevance scoring, or usage-pressure from real tokens. |
| Better than Codex? | **Yes on assembly, no on sandbox.** Different axes; not comparable. |
| Is it "the organ you should be proudest of"? | **No — that's `budget.py` and `gates.py`.** The context engine is the best *architecture*; the governor is the best *discipline*. |

**Do C2 first.** It is 35 lines, it makes every other budget decision correct rather than approximately correct, and you already built the persistence layer it needs.
