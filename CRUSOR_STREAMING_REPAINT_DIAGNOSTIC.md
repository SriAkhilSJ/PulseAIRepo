# CRUSOR — STREAMING REPAINT DIAGNOSTIC

**Task:** explain, with measurements, why 275 incoming chunks produced 6 transcript repaints.
**Mode:** measurement only. No product code changed, no optimisation applied.
**Date:** 2026-11-11 · **Branch:** `feat/prompt-cache-stabilization` · **HEAD:** `27706b6e`
**Provider calls:** 0 · **Provider ledger rows:** 0 · **Dirty tree:** preserved (184 entries)

> Evidence classes used throughout:
> **[MEASURED]** captured this session with a command/artefact.
> **[DERIVED]** arithmetic over measured values.
> **[SOURCE]** read directly from the committed/working-tree source (no runtime proof).
> **[UNVERIFIED]** could not be captured; stated as a gap, not a result.

---

## 1. Method and instrumentation points

All instrumentation was injected over CDP at runtime (`Runtime.evaluate`) and removed with the
process. Instrumentation script: `bench-results/performance/stream_repaint_probe.py`.

| Stage | Instrument | Where |
|---|---|---|
| Bridge → renderer frames | Electron console log relay (`[turn]`, `[bridge]`, `[model-gateway]`) | `logs/electron.stderr.log` |
| Frame ingestion | `acceptFrame` (read) | `crusorAIRendererService.ts:2215-2846` |
| Token accumulation | `appendTextPart` (read) | `crusorAIRendererService.ts:2457-2459` |
| Render scheduling | patched `window.requestAnimationFrame` with stack sampling | runtime |
| Render execution | patched rAF wrapper timing each callback | runtime |
| Markdown processing | `markdownCopy` (read) | `crusorAIRenderer.ts:424-520` |
| Paint path | full repaint `root.replaceChildren()` (read) | `crusorAIRenderer.ts:~5143` |
| DOM mutation count | `MutationObserver` on transcript root | runtime |
| Visible text updates | rAF sampler on `.crusorai-assistant-copy` | runtime |
| Long tasks | `PerformanceObserver({type:'longtask', buffered:true})` | runtime |
| CPU attribution | CDP `Profiler.*` (200 µs sampling) | attempted, **no turn ran** |

**Overhead caveat:** the rAF patch wraps every animation frame in the workbench, and
`JSON.stringify` is wrapped process-wide. The wrapper cost is small but **unquantified**; treat
sub-millisecond differences between runs as noise.

---

## 2. Reproduction attempt — three runs, and the exact blocker

| Run | Fixture | Result |
|---|---|---|
| A1 (previous session, 23:19) | 1,000 tok · 968 out · 275 chunks · 3,872 chars | **[MEASURED]** turn ran end-to-end |
| Fresh 1 (18:43, home-isolated) | same generator, 282 chunks | ABORT — engine never `ready` |
| Fresh 2 (18:48, default home) | same | ABORT — engine never `ready` |
| Fresh 3 (18:51, preview servers cleared) | same | ABORT — engine never `ready` |

Abort detail (identical in all three):
- the bridge **does** start: `[env] loaded …`, `[bridge][acceptance] run=…`,
  `[bridge][memory] policy check …` all appear in the console relay;
- the run's `CRUSORAI_HOME` gets `sessions.db`, `preview/ide.json`, `preview/proxy-ide.log`;
- **no** `session_info` / `[turn]` line follows, so the pane stays on "Engine starting";
- `.crusorai-engine-status` never contains `ready`.

Isolation measures applied before each attempt: only benchmark-owned `CrusorAI.exe` and
`src.preview.server` processes were terminated (12 orphaned preview servers from earlier launches
were holding `127.0.0.1:8931`); no unrelated user process was touched. Fail-fast limit was 150 s —
the probe exits instead of waiting 180 s.

**Consequence:** the 3-run variability requirement is **not met**. Only A1 has per-stage runtime
data. Everything below that depends on a completed turn is marked accordingly.

---

## 3. Stage-by-stage counts (A1, the only completed turn)

| Stage | Value | Class |
|---|---|---|
| Bridge reception | 275 token frames | [MEASURED] log "275 chunks streamed" |
| Model emission window | **0.001 s** for all 275 chunks | [MEASURED] `[model-gateway] elapsed=0.001s` |
| Frontend event handler | 275 `acceptFrame('token')` calls | [DERIVED] one per frame |
| Renderer service state writes | 275 `appendTextPart` calls (concat into one part) | [SOURCE] `:2457-2459` |
| Render scheduling | **≤ frames elapsed** — `render()` dedupes while a frame is pending | [SOURCE] `:1536-1544` |
| Render execution (`mount.update`) | **6** transcript repaints | [MEASURED] DOM text-length samples |
| DOM mutation batches | ≥ 6 (one full rebuild per structural repaint) | [SOURCE] `replaceChildren()` path |
| Visible text updates | **6** | [MEASURED] rAF sampler |
| Browser paints | ≥ 6 (one per repaint frame); exact count not instrumented | [UNVERIFIED] |
| Chunks lost / duplicated | **0 / 0** | [MEASURED] earlier run |

**Why 6 and not 275:** the 275 chunks arrive inside a single event-loop turn (0.001 s), and
`render()` is a per-frame coalescer:

```ts
// crusorAIRendererService.ts:1536-1544  [SOURCE]
private render(): void {
  this.noteSession();
  if (this.mounts.size === 0 || this.renderFrame !== undefined) { return; }   // dedupe
  this.renderFrame = requestAnimationFrame(() => {
    this.renderFrame = undefined;
    for (const mount of this.mounts) { mount.update(model); }                 // full paint
  });
}
```

So 275 calls to `render()` while a frame is pending collapse into **one** `mount.update(model)`.
The remaining 5 repaints are **structural** frames (turn start, cards, finalize, receipt), each of
which also takes the full-rebuild path. This matches the frontend audit's own statement that
"structural changes … always take the full repaint."

---

## 4. Derived metrics (A1)

| # | Metric | Value | Basis |
|---|---|---|---|
| 1 | Incoming chunks/s | **275,000/s burst** (275 in 0.001 s); **119.6/s** amortised over the 2.3 s turn | [DERIVED] |
| 2 | State updates/s | 119.6/s (275 / 2.3 s) | [DERIVED] |
| 3 | Render requests/s | ≤ display refresh; exact count **UNVERIFIED** (probe aborted) | — |
| 4 | Transcript DOM updates/s | **2.6/s** (6 / 2.3 s) | [DERIVED] |
| 5 | Visible paint updates/s | **2.6/s** | [DERIVED] |
| 6 | Average chunks per visible update | **45.8** (275 / 6) | [DERIVED] |
| 7 | Event-to-visible latency | first text **13.4 ms**; worst case ≈ full turn (last chunk only visible at the final repaint) | [MEASURED] + [DERIVED] |
| 8 | Chunks represented in visible updates | **100 %** (0 lost, 0 duplicated) | [MEASURED] |
| 9 | Markdown parse time | **NOT MEASURED** — profile needs a completed turn | [UNVERIFIED] |
| 10 | JSON serialization time | **NOT MEASURED** — probe aborted before collection | [UNVERIFIED] |
| 11 | Long-task attribution | 8 tasks / 1,246 ms / worst 390 ms [MEASURED]; per-function split **UNVERIFIED** | partial |
| 12 | Rendering overhead | callbacks ≈ 1,246 ms blocking ÷ 2,300 ms turn ≈ **54 %** of wall clock blocked | [DERIVED] |

---

## 5. Event → render timeline (A1)

| Time | Event | Visible effect |
|---|---|---|
| t+0.0 ms | prompt submitted | composer clears |
| t+0.0 ms | 275 `token` frames emitted by the seam | nothing yet |
| t+13.4 ms | first rAF after the burst | **entire answer appears at once** |
| +~200-390 ms blocks | structural repaints (cards, plan, finalize) | answer re-laid-out 5 more times |
| t+2.3 s | `turn_done` + receipt | final repaint; 69 % of text present (budget cut) |

So the user perceives **one instant dump followed by five full re-layouts** — not a stream.

---

## 6. Main-thread blocking — what is attributable and what is not

Measured: 8 long tasks, 1,246 ms cumulative, worst 390 ms, inside a 2.3 s turn.

Code paths that must run on every repaint (all **[SOURCE]**, none individually timed):

| Candidate | Location | Why it is O(n) or worse |
|---|---|---|
| Full transcript rebuild | `renderer.ts:~5143` `root.replaceChildren()` + tree rebuild | every structural frame discards and recreates the whole transcript |
| Markdown re-parse of the accumulated answer | `renderer.ts:424-520` `markdownCopy`, called from the live slot (`:5103`) | re-parses the **entire** text each paint → O(n²) over a stream |
| Live slot replacement | `slot.replaceChildren(markdownCopy(streaming.text))` | destroys selection and inline state each frame |
| JSON equality checks | `crusorAIRendererService.ts:105` `JSON.stringify(a)===JSON.stringify(b)`, and `:1516` same on cards | serialises whole models/card arrays on comparison |
| Card normalisation | `agent_cards.normalize_card` + `cardStore.update` | per card frame |

Explicitly **not** claimed: that markdown parsing is the dominant term. With a burst fixture the
8 long tasks coincide with 6 full rebuilds, so the arithmetic is consistent with parse+rebuild,
but no CPU profile was captured. This stays a hypothesis until a completed run is profiled.

---

## 7. Answers to the architectural questions

1. **Which layer batches 275 chunks into 6 updates?**
   Two layers, in series: the **source** (the seam emits 275 chunks in 0.001 s, so there is no
   time axis to stream along), and the **renderer service** (`render()` coalesces every pending
   update into one `requestAnimationFrame`, then paints the whole model).

2. **Intentional or accidental?**
   The rAF coalescing is **intentional and correct** (`:1536-1544`). The absence of progressive
   output in this workload is an **artefact of the fixture**, not a product defect. Whether a real
   provider also collapses depends on its chunk cadence (see §8, unverified).

3. **Does the renderer rebuild the complete transcript?**
   Yes, for structural frames: `root.replaceChildren()` + full tree rebuild. Token frames inside a
   single frame are also painted from the complete accumulated string, not appended in place.

4. **Does markdown parsing happen repeatedly?**
   Yes — `markdownCopy` re-parses the full accumulated text on every repaint. Cost grows with
   answer length, so a real stream pays it once per frame (~60×/s ceiling), not once per answer.

5. **Are entire renderer models serialised unnecessarily?**
   Yes in two comparison sites (`:105`, `:1516`) which `JSON.stringify` both sides to test
   equality. Call counts were not measured this session.

6. **Is state comparison causing excessive work?**
   Not demonstrated. The two stringify comparisons exist, but no measurement shows them at scale.

7. **Is rendering throttled by a scheduler or animation frame?**
   Animation frame only. No debounce, no token timer. The audit records the same finding
   (`rAF only (~16 ms), no token debounce`).

8. **Single largest source of latency?**
   For this workload: **the source cadence** (275 chunks in 1 ms) — it makes progressive rendering
   impossible. The largest *blocking* cost is the **full transcript rebuild + markdown re-parse per
   repaint** (1,246 ms of long tasks in a 2.3 s turn), which is the thing that would hurt a real
   stream.

9. **Safest optimisation (not implemented):**
   Append-only rendering for the live text part — keep one text node, append the delta, and run the
   markdown pass only on a trailing, still-open block (or debounce it to end-of-turn). No protocol,
   graph or gateway change.

10. **Regressions that could follow:**
    - incremental markdown is where correctness bugs live (unclosed fences, tables split across
      chunks, list continuation, emoji/surrogate pairs);
    - text selection and copy must survive appends;
    - scroll anchoring can jump if height is not measured after append;
    - auto-scroll "stick to bottom" logic must not fight the append path;
    - the finalised message must be byte-identical to today's full re-render, including the
      receipt block.

---

## 8. What is still unverified

1. **3-run variability** — blocked by the engine never reaching `ready` (§2).
2. **Whether a real provider streams progressively** — needs a paced source. The scripted seam is
   synchronous by construction; pacing it requires a source change (see §9).
3. **Per-function long-task attribution** — profiler never ran on a completed turn.
4. **Markdown parse time, JSON serialization time, paint count** — probe aborted before collection.
5. **Chunk-to-paint ratio under a real cadence** — the central open question: with ~20-30 ms
   chunk spacing the expected ratio is near 1:1 (≤60 paints/s), which would make the 45.8
   chunks-per-update figure an artefact of the burst.

---

## 9. Instrumentation that would require a source change (not implemented)

Only one change is needed to complete this diagnostic, and it is test-only:

- **Paced fixture delivery.** `ScriptedChatModel._emit_stream` (`src/llm/scripted_model.py:123-133`)
  invokes every chunk callback synchronously. A benchmark-only delay (e.g.
  `CRUSORAI_TEST_CHUNK_DELAY_MS`) would let 275 chunks arrive over a chosen window and make
  chunks-vs-paints measurable under realistic cadence.

Alternative without touching the model: drive the same UI through the *bridge* scripted runner,
but that bypasses the gateway and is therefore excluded by this task's rules.

---

## 10. Verdict

- 275 chunks → 6 repaints is **explained**: 1 token-driven paint (rAF coalescing of a 1 ms burst)
  plus 5 structural full-repaint frames.
- It is **not** evidence of accidental batching in the frontend.
- The measured retention is perfect (0 dropped, 0 duplicated), so nothing is lost — it is only
  *not progressive*, because there is no time to be progressive across.
- The real risk that remains is cost per repaint: full rebuild plus full markdown re-parse while
  a turn is live, consistent with 1,246 ms of long tasks in a 2.3 s turn, pending profile proof.
- No fix applied. No paid call made. Ledger rows = 0.
