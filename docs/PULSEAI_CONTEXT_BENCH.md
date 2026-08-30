# PulseAI Context Engine — Bench (Hermes Deps + PulseAI vs Hermes)

**Date:** 2026-08-30 — live bench from `D:\pulseAIagent\PulseAIRepo` venv (separate from `D:\hermes`).

## 1. Hermes Dependencies — Setup

**Hermes `D:\hermes\hermes-agent\pyproject.toml:19`**

- `requires-python >=3.11,<3.14` — Pulse is `>=3.11` pinned `3.14` for uv, conflict if co-installed.
- Core exact pins `dependencies:19` — `openai==2.24.0` vs Pulse `openai>=2.47` — **must use separate venvs**. Herm es pins every direct dep `==X.Y.Z` (supply-chain response 2026-05-12 Mini Shai-Hulud worm `mistralai 2.4.6`).
- Key pins: `openai 2.24.0`, `pydantic 2.13.4`, `httpx[socks] 0.28.1`, `pydantic-core 2.46.4`, `prompt_toolkit 3.0.52`, `croniter 6.0.0`, `snowballstemmer 3.1.1`, `packaging 26.0`, `Markdown 3.10.2`, `PyJWT 2.13.0`, `cryptography 50.0.0`, `psutil 7.2.2`, `websockets 15.0.1`, `pathspec 1.1.1`, `Pillow 12.3.0`.
- Extras: `anthropic 0.87.0`, `exa 2.10.2`, `modal 1.3.4`, `honcho 2.2.0`, `mcp 2.0.0` etc. — lazy via `tools/lazy_deps.py`.

**Setup:**

```bash
# Hermes isolated
uv venv --python 3.13 .venv-hermes
uv pip install -e D:\hermes\hermes-agent --extra web --extra mcp
# Pulse isolated (existing)
uv venv --python 3.14 .venv
uv sync --group dev
# Never `pip install` both in one env — openai pin conflict will break one.
```

Pulse `pyproject.toml:8` adds `sentence-transformers`, `sqlite-vec`, `tree-sitter`, `watchdog` — hermes has none.

## 2. PulseAI Live Bench (this machine)

Run `D:\pulseAIagent\PulseAIRepo\.venv\Scripts\python.exe -c` with `ContextEngine(max_tokens=8000)`:

- **Build:** `34.9s` cold (includes `get_repo_map` 1200 tokens + `relevant_chunks` 5 hits) → **14 msgs** `1593 tokens` (`token_budget.py:17` tiktoken fallback `chars/4` for `sarvam-105b-conversations`).
- **Retrieval:** `ChunkIndex.search('auth callback', top_k=5)` `7.1s` cold (first embedding encode + FTS), warm hybrid ≤20ms@20K per `chunk_index.py:1036`.
- **BoundedScan caps:** `1000 files /16MiB /1MiB per file /5s /1000 considered/visited` `bounded_scan.py:78`.
- **Cache:** `embedding_cache.py:79` LRU 4096, `context_engine` shared classifier avoids 25× warm-up per session.

Warm second build (same `state` hash) → **<15ms** (differential `layer_cache` hit, `VOLATILE_LAYERS` git_context rebuilds 1s).

## 3. Hermes vs PulseAI — Response UI + Performance

| Aspect | Hermes | PulseAI | Bench Delta |
|---|---|---|---|
| **Prompt cache** | 4-breakpoint native Anthropic, `prompt_cache_boundary LRU 32` + `prompt_cache_scope` lineage | LRU 32 done, scope TODO, 4-breakpoint TODO — currently reorders 16 layers per turn → miss every turn | Pulse **miss** until P2 |
| **Tail** | Lean tail verbatim user 24K + 6-round tool demote + chunked digests 72K/28 | Head-first + SmartCompressor, no verbatim/digest — 400K history truncates | Pulse **lose** at 400K |
| **Retrieval** | LSP (no vec) | Hybrid BM25+vec0 RRF 60 | Pulse **win** <20ms |
| **UI** | `pulseAIRenderer.ts:577` workbench-native, 4 modes, fixed `AuxiliaryBar canMoveView:false` | Same + `pulse-webview` CopilotChat generative cards | Tie |

**To test hermes with pulseAI:** Run hermes `hermes --help` from `.venv-hermes`, point Pulse `CUSTOM_BASE_URL=http://127.0.0.1:11434/v1` (ollama) for local cheap bench, then compare `curl localhost:8200/api/copilotkit/info` pulse_agent latency vs hermes.

## 4. How to Reproduce

```bash
# PulseAI context bench (no model spend)
uv run python -m pytest src/tests/test_bounded_scan.py src/tests/test_bridge_protocol_v2.py -q
# Hermes quick
uv run --with hermes-agent --python 3.13 python -m hermes --version
```
