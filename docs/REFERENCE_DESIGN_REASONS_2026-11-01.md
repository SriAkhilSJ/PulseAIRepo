# Why Aider, OpenCode and Void are built the way they are

Field 2026-11-01. Source-read, not summarised from blog posts. Each design below is a
**consequence of a constraint** that repo accepted. Copying the artifact without the
constraint is how a plan becomes 50/50: every option looks plausible because nothing
is anchored to a reason.

---

## Aider — "any model, text only"

**Constraint:** it must work with *every* LLM, including models with no function
calling, and it takes a diff on the first try.

**What that forces**

| Decision | Why (from source) |
|---|---|
| **Zero tool schemas** | `aider/website/docs/unified-diffs.md`: *"I explored many other approaches including … OpenAI's function/tool calling capabilities"* — and rejected it. *"Even though OpenAI provides extensive support for structured formats like json and function calls, GPT is worse at editing code if you use them."* |
| **SEARCH/REPLACE + unified diffs** | Stuffing source code into JSON is escape-hell: `print("On Windows use \"C:\\\"")` as valid JSON. *"GPT's code is often syntactically incorrect when it's unpacked from JSON."* Diffs survive; JSON does not. |
| **350 tokens of few-shot examples** | Teaching by worked example, because the format is the product. Their ablation: without "high level diff" prompting, **editing errors rise 30–50%**; without flexible patching, **9×**. Examples are not decoration, they are the error-prevention mechanism. |
| **Repo map, 1,024 → 8,192 tok** | They can't read files mid-turn — no tools — so the *whole repo* must arrive in the prompt, compressed to 1k–8k of ranked symbols. The map is a **substitute for tool calls**, not an extra. |
| **3 reflections max** | `base_coder.py:101 max_reflections = 3`. With no agent loop, a wrong edit is re-asked, not investigated. Bounded because each retry is a full-file context. |

**What it implies for us:** the "0 tool schemas" number is *not* frugality we can copy —
we need tools (browser, device, preview, delegate). But the reason behind it is
transferable: **for file editing, a text diff beats a JSON tool call**, measured.

**And the uncomfortable one:** `unified-diffs.md` reports that emotional-appeal prompts
("you are blind, has no hands, will tip $2000") produced **worse** scores. Our persona
carries 8 × NEVER, 5 × ALWAYS, 2 × MUST. That is the same category of prompt engineering
they benchmarked and found counter-productive.

---

## OpenCode — "many providers, long sessions, cache first"

**Constraint:** it runs against dozens of providers and models, sessions live for hours,
and the prompt cache is the single largest cost lever.

**What that forces**

| Decision | Why (from source) |
|---|---|
| **189-token base prompt** | `session/runner/prompt/system.txt`. The harness supplies behaviour; the prompt only states posture. Per-model quirks live in **plugins** (`plugin/system-prompt/*.txt`), appended on demand by `optimize.ts` after a substring match on the model id. Thin core + composable deltas, because one text cannot fit 40 models. |
| **5 graded compaction levels** | `compaction.ts:141-148`. Whole → outputs clipped → outputs removed → user-only → omitted. The comment: *"exchanges are shortened oldest first, one level at a time … every exchange reaches a level before any reaches the next, so detail is lost from the oldest history first."* Cheap levels are free (no LLM call); a summary is the last resort. |
| **Precompute at 85%, hold, don't apply** | `compaction.ts:332-337`: *"summarizes everything before the latest response **in the background** … the summary request reads it from the prompt cache. The summary is held, not applied: swapping it in now would **rewrite the prefix and throw away the cache** for every step until compaction is actually due."* **This is our bug, named by someone else, with our fix.** |
| **`PRECOMPUTE_MIN_TOKENS = 64_000`** | *"Measured prompt tokens below which a background summary is not worth its cost."* An explicit break-even gate before spending. |
| **`TRANSCRIPT_CLIP = 2_000` per end** | Old tool output is kept as head + tail, never re-sent whole. |
| **`grep`/`glob` deleted per model family** | The plugin exists but: *"disabled intentionally until we can figure out a good ux"*. An unfinished experiment, not a principle. |
| **"Prefer dedicated tools over shell"** | Injected into the system prompt when shell is bound. They use the terminal *and* dedicated search; the terminal is the fallback, not the strategy. |

**What it implies for us:** our compaction is the anti-pattern they explicitly avoided.
Rewrite-in-place destroys the prefix; holding a precomputed summary preserves it.

---

## Void — "an editor first, local models included"

**Constraint:** it is a VS Code fork that must drive frontier *and* local models, and the
user is watching the screen while it works.

**What that forces**

| Decision | Why (from source) |
|---|---|
| **XML tool definitions, not JSON Schema** | `convertToLLMMessageService.ts:373`: `if (!specialToolFormat) { // XML tool behavior }`. XML is the fallback path for providers with **no native tool wire format** (local/Ollama/custom). Terseness is a side effect of writing tool docs as prose a model can read. |
| **~20 tok per tool description** | Measured avg 83 chars. Written for a generic small model, so every word has to earn itself. Not a token optimisation — a compatibility decision. |
| **File tree in the system message** | `MAX_DIRSTR_CHARS_TOTAL_BEGINNING = 20_000`, sent **once at the start** (the `TOOL` variant is for on-demand listing). It removes a discovery round-trip at t=0, and being a stable prefix it caches. They pay tokens to buy **one fewer cycle**. |
| **15 tools, 3 of them search** | `search_pathnames_only`, `search_for_files`, `search_in_file`. Their terminal description says *"You can use this tool to run any command: sed, grep, etc."* — and they still ship dedicated search, because structured results are smaller and cheaper to read than raw `grep` output. |
| **ONE tool call per response** | `prompts.ts`: *"You are only allowed to output ONE tool call, and it must be at the END of your response."* Because the UI **streams** each result into a diff zone as it lands (`DiffZone` + `llmCancelToken`). One call = visible, cancellable progress. Latency design, not a token design. |
| **Apply in-editor (Fast Apply)** | `VOID_CODEBASE_GUIDE.md`: *"This is what allows Void to quickly apply code even on 1000-line files. It's the same as asking the LLM to press Ctrl+F."* The file stays in the editor; the model never round-trips it. Fast Apply = SEARCH/REPLACE; Slow Apply = rewrite the whole file. Two modes for two file sizes. |

**What it implies for us:** we are also an IDE (`desktop/vscode`, `crusorai-diff`,
`MAX_INLINE_DIFF_CHARS = 512_000`). The in-editor apply reason applies to us **exactly**.

---

## The synthesis

Three repos, three different optima, because three different constraints:

| | Aider | OpenCode | Void | **us** |
|---|---|---|---|---|
| models | any, incl. no tool calling | dozens of providers | frontier + local | **one** (`glm-5.3-flash`) |
| delivery | terminal / CLI | headless server | **IDE** | **IDE** |
| session | one request at a time | hours, many turns | interactive, streamed | interactive, up to 45 cycles |
| binding cost | edit correctness | **prompt cache** | **perceived latency** | ??? |

That last cell is the problem. We inherited Aider's edit ideas, OpenCode's provider
plumbing and Void's UI ambitions, but named no constraint of our own — so every lever
looked equally valid.

### Our constraint, stated once

**One model, native tool calling, an IDE we own, and interactive turns.**
That makes the binding costs, in order:

1. **Fixed preamble re-sent per cycle** — highest leverage (13,660 × 104 = 48% of the session).
2. **Cycle count** — 84% of spend dies on cut turns.
3. **Prompt cache stability** — 53% → 39% decay, caused by rewriting the prefix.
4. **Perceived latency** — masked today because we batch tool calls *and* execute them serially.

### Therefore

| Decision | Reason, sourced |
|---|---|
| Terse descriptions (≤90 chars) | Void's are 83; ours average 570. The *reason* is compatibility with weak models — brevity is the robust choice. |
| Keep dedicated search tools, terminal as fallback | OpenCode states it; Void ships both. My earlier "terminal replaces 20 tools" was wrong. |
| Text diff for edits, not a JSON tool call | Aider measured function calling to be *worse* for code editing. |
| One worked example per tool family | Aider: 350 tok of examples prevents 30–50% more editing errors. Cheaper than one retry cycle (~25k tok). |
| Compaction: hold a precomputed summary, never rewrite the prefix | OpenCode's own comment describes exactly our failure. |
| Stream each tool result; run eligible batches concurrently | Void's one-call rule exists for streaming; we can have batching *and* visible progress. |

**Not copied, and the reason is a constraint, not taste:** repo map (adds fixed cost;
substitute for tools we already have), six per-model prompts (one model), one-call-per-
response (we stream instead), 20k-char file tree (we have a live editor).
