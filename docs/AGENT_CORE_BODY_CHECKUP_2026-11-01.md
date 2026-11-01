# Agent-core body checkup — every pipeline

**Date:** 2026-11-01 · **Method:** `scripts/agent_core_checkup.py` · **Mode:** offline, keyless, provider-free
**Result:** 13 pipelines, 54 behavioural probes, **4 real defects found and fixed**, 2 standing warnings.

Run it yourself — no API key, no credit, ~5 seconds:

```bash
python scripts/agent_core_checkup.py            # table + failures
python scripts/agent_core_checkup.py --md out.md --json out.json
```

---

## 1. Why a probe harness and not a read-through

The last three "all good" results were all wrong, and each was wrong the same way:
**a status value was trusted instead of the record behind it** — a `turn_done` frame
with `completed=false`, a green unit suite over a server that would not boot, a `402`
classified `unknown`. Reading 227 modules and forming an opinion is how those happen.

So this checkup **executes each pipeline stage with synthetic input** and records what
came back. A probe that raises is a FAIL with the exception text, not a paragraph.

| Verdict | Meaning |
| :--- | :--- |
| PASS | the stage did the documented thing on the input given |
| WARN | it works, but a real failure would fall into the hole it leaves |
| FAIL | it did the wrong thing, or could not run at all |

---

## 2. The body, pipeline by pipeline

| # | Pipeline | What it owns | Checks | Verdict |
| ---: | :--- | :--- | ---: | :--- |
| 1 | **Ingress** | frame encode/decode, malformed input, protocol version | 3 | healthy |
| 2 | **Session** | id uniqueness, `thread_id == session_id` (resume), workspace re-bind | 3 | healthy |
| 3 | **Prompt assembly** | project instructions → prompt, system-message sources, git context | 3 | healthy |
| 4 | **Context engine** | unknown-model window, usable budget, cache prefix split, token attribution | 4 | healthy |
| 5 | **Compaction** | stale-reasoning prune, transcript salvage, lock contention, fence, wiring | 6 | healthy |
| 6 | **Model call** | factory, output cap, one-shot ceiling, arg normalisation, secret redaction, orphan tool result, degenerate output | 7 | healthy |
| 7 | **Failure recovery** | terminal vs transient classification, compression routing, single billing predicate, transport drops | 5 | **was broken → fixed** |
| 8 | **Tools** | toolset resolution, unknown names, transaction wrapper, write guard, order preservation | 6 | healthy |
| 9 | **Loop control** | budget legs named, iteration vs token not confused, no-tool loops, duplicate guards, finish gate | 6 | healthy |
| 10 | **Verification** | evidence refuses a missing manifest, status derived from receipts, failed run ⇒ `completed=false`, contracts execute | 4 | healthy |
| 11 | **Persistence** | sqlite checkpoint round-trip, unpaired tool call detected, watchdog, ledger | 4 | healthy |
| 12 | **Finalize** | terminal frame carries an outcome, budget reason, error surface reaches the client, cancellation | 4 | **was broken → fixed** |
| 13 | **Hygiene** | keyless import of 154 core modules, orphan modules, missing-package imports | 4 | 2 warnings |

---

## 3. The four defects

### 3.1 A dead API key was retried as a transient failure — in 5 of 7 vendors

The message fallback in `classify_api_error` exists for wrapped exceptions whose
`status_code` did not survive a shim. Probed with the body each vendor actually
returns for a bad key:

| Vendor | Body | Before | After |
| :--- | :--- | :--- | :--- |
| OpenAI | `Incorrect API key provided: sk-…` | `unknown`, **retryable** | `auth`, rotate |
| Anthropic | `invalid x-api-key` | `unknown`, **retryable** | `auth`, rotate |
| Gemini | `API key not valid. Please pass a valid API key.` | `unknown`, **retryable** | `auth`, rotate |
| OpenRouter | `No auth credentials found` | `unknown`, **retryable** | `auth`, rotate |
| Groq | `Invalid API Key` | `auth` | `auth` |
| custom | `Authentication failed: …` | `auth` | `auth` |

A dead credential cannot heal itself. `unknown/retryable` walks the full retry ladder
against a key that will never work, and never rotates to the one that would.
Fixed in `src/llm/error_classifier.py`; pinned by 7 parametrised tests plus three
"still transient" cases so the fix cannot swallow real blips.

### 3.2 A connection reset **crashed the classifier**

```python
from agent.reasoning_timeouts import get_reasoning_stale_timeout_floor   # unconditional
```

`agent.reasoning_timeouts` does not exist in this repository — it came over from
hermes. It sat inside the branch for *server disconnects with no status code*, which
is exactly what a dropped stream looks like. So classifying the single most common
transient failure raised `ModuleNotFoundError` **from inside the classifier the retry
loop depends on**: a recoverable network blip became an unclassified crash.

After: `connection reset by peer` → `timeout`, retryable, no compression.

### 3.3 The dashboard error surface returned `None` for every API failure

`src/dashboard/error_surface.py` imported `agent.error_classifier` — again a package
that does not exist here — and the function's catch-all `except Exception: return None`
turned the resulting `ModuleNotFoundError` into silence:

```
402 -> None          (before: no surface, no code, no retryable flag — the user sees nothing)
402 -> {'layer': 'billing', 'code': 'billing', 'retryable': False}   (after)
```

This is why a ₹0.00 wallet reads as "the agent did nothing" rather than "your account
is out of credit". A wrong import inside a bare `try/except` is silence, not safety.

### 3.4 A core module needed credentials merely to be imported

`src/graphs/basic_graph.py` built its model client at import time, so
`import src.graphs.basic_graph` — and anything walking the package, including test
collection and health checks — died with a provider credential error on a machine
without a key. The client is built lazily now; the package imports keyless.

---

## 4. Two standing warnings (not fixed — they are decisions, not bugs)

| Warning | Detail | Why it matters |
| :--- | :--- | :--- |
| **5 orphan modules** | `src/providers/{custom,openai,gemini,groq,nvidia}_provider.py` are imported by nothing. Each also constructs a client at import time. | They are the *old* provider layer; the real path is `src/llm/factory.py`. Untested and unreachable code that still looks authoritative — delete, or fold into the factory. |
| **5 guarded imports of a missing package** | `hermes_state.is_disk_full_error` (2×), `agent.errors.MoAPresetNotFoundError`, `agent.reasoning_timeouts`. All fail open. | The guards stop the crash but the *features are dead*: disk-full is never classified as disk-full, and MoA preset drift is never recognised. The fallback path is the real code, and nobody has been testing it as such. |

---

## 5. What this checkup does **not** cover

Coverage is not a vibe; here is the boundary.

| Area | Status | Why |
| :--- | :--- | :--- |
| Live model call, streaming, retry ladder in anger | **not exercised** | Wallet is at ₹0.00. Everything above is offline by design. |
| Real tool execution (file/terminal/browser) | **not exercised** | Probed at the guard and normaliser level only. |
| MCP (`mcp_client`, `mcp_skills`), LSP (10 modules), preview proxy, voice, A2UI | **not covered** | Separate surfaces; they need a live session or a host process. |
| Subagents (`agents/*` lifecycle, permissions, registry) | **import-checked only** | Behaviour needs a real turn. |
| 154 of 227 core modules | **import-checked** | Behavioural probes concentrate on the single-turn critical path. |

That is the honest line: **the critical path is now probed offline; everything past it
is unverified until the wallet is topped up.**

---

## 6. Standing receipts

- `scripts/agent_core_checkup.py` — 54 probes, exits non-zero on any FAIL.
- `src/tests/test_agent_core_checkup.py` — pins the four defects and asserts the
  checkup keeps reporting zero failures and ≥45 checks across ≥12 pipelines.
- `.github/workflows/agent-core-checkup.yml` — runs keyless on every push touching
  `src/`, writes the table to the job summary, uploads `checkup.json`.
- Targeted suite after the fixes: **117 passed** (`test_agent_core_checkup`,
  `test_billing_wallet_detection`, `test_long_session_driver`,
  `test_token_budget_provenance`, `test_verification_channel_detection`,
  `test_termination_diagnosability`, `test_retry_proxy`,
  `test_attempt11_product_delivery_boundary`).
