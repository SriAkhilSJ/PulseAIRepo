# Agent Core — Status & Competitive Read (2026-10-31)

**Question asked:** *where is the Agent Core, and can it compete with the whales?*

**Short answer:** the **engineering** is genuinely competitive with open scaffolds;
the **evidence** is not competitive with anything yet. Right now this project has
no number that can be placed on the same axis as Codex CLI, Claude Code or
OpenHands. Until it does, "can it compete" is unanswerable in the only way that
matters — and every other strength in this document is preamble to that sentence.

---

## 1. What is actually built (measured on this commit, not from the docs)

| Fact | Value | How measured |
|---|---|---|
| Agent runtime | **151,074 LOC** across **489** Python files | `find src -name '*.py' \| xargs wc -l` |
| Tests | **62,523 LOC**, **245** test files, **3,108 passing / 0 failing** | full `pytest src/tests` run |
| Graph topology | **16 nodes** (14 functional + start/end) | `graph.get_graph().nodes` |
| Tools in the waist | **66** | `all_known_tool_names()` |
| Prompt layers | **17 ordered builders + 1 volatile tail = 18** | `layer_policy.BUILDER_ORDER` |
| Providers | 5 (`openai`, `gemini`, `groq`, `nvidia`, `custom` BYOK) | `src/providers/` |
| Surfaces | stdio NDJSON bridge, FastAPI AG-UI (`src/server.py`), CopilotKit webview, desktop fork | code + 2 CI workflows |
| MCP | client with session pool + **TestSprite MCP protocol-verified** (8 tools) + own MCP test server (PASS 5/5) | this session |
| Largest module | `chat_graph.py` — **8,033 lines** | `wc -l` |
| CI coverage | **5 test files**, not 3,108 | `.github/workflows/host-compatibility.yml` |

## 2. Scorecard — layer by layer

Grades are against *the best shipping thing*, not against a demo. "Parity" means
"you could not tell them apart in a code review of that layer."

| Layer | Grade | Reality |
|---|---|---|
| **Completion honesty** | **A — ahead of the field** | Completion is *derived* (`run_outcome` + `verification_status` + `specification_status` → `task_completed`), never model-claimed. Failed-check debt must be cleared by the *exact* check. Monotonic revision ledger invalidates stale receipts. I fixed the last hole in this on 2026-10-31 (three chains disagreeing). **No public leaderboard scores this.** |
| **Verification / evidence** | **A−** | AST gate before write, 4-state receipts, deliverable evidence bound to the workspace (CWD bug fixed 2026-10-30), verification-domain aggregation. Genuinely better than "run the tests and hope". |
| **Orchestration** | **B+** | Deterministic LangGraph supervisor, state-derived routing, bounded recovery/replan, parallel tools with conflict detection. This is the OpenHands/SWE-agent class of design, executed competently. |
| **Context engineering** | **B+** | 18 layers, prune-first compaction, turn-atomic trimming, cache-break detection with a latched receipt. Comparable to Hermes/OpenHands' condenser; ahead on cache-prefix discipline. |
| **Tooling** | **B** | 66 tools, 9-strategy fuzzy edit, MCP client, media sourcing. OpenHands ships browser + Jupyter + bash + editor in a sandbox; this ships a browser (CDP) and no notebook — close enough on breadth, behind on *isolation*. |
| **Sandboxing / multi-tenant safety** | **D** | Executes on the **host** with path containment, a dangerous-command taxonomy and fail-closed approvals. Codex CLI runs a kernel sandbox, OpenHands a Docker container per session. The repo's own 2026-08 audit scored security/multi-user readiness **2.5/10** — that has not changed. |
| **Maintainability** | **C** | 8,033-line `chat_graph.py`; 81 docs; CI runs 5 test files. One bad merge here is unrecoverable by a new contributor. OpenHands has ~490 contributors; this has effectively one. |
| **Evaluation evidence** | **F** | No SWE-bench, no Terminal-Bench, no independent number. The GatePulse "16/16 × 3 models" is an in-repo harness over a pinned task spec — real engineering, but not a comparison. Last full-stack run: **FAIL 4/5**. |

## 3. Where the whales actually are (public numbers, for scale)

| Agent | Terminal-Bench 2.0 | SWE-bench Verified |
|---|---|---|
| Codex CLI (GPT-5.5) | **82.2%** — best named CLI agent [1](https://ssojet.com/blog/best-cli-coding-agents-ranked) | — |
| Claude Code | 58% [2](https://wetheflywheel.com/en/guides/ai-coding-agent-benchmark-terminal-bench/) | 80.9% (Opus 4.6) [2](https://wetheflywheel.com/en/guides/ai-coding-agent-benchmark-terminal-bench/) |
| Best proprietary scaffold | — | 72.0% (Augment, Opus 4.6) [3](https://awesomeagents.ai/leaderboards/swe-bench-coding-agent-leaderboard/) |
| OpenHands CodeAct v3 (open, MIT, ~70k ★) | — | **68.4%** [3](https://awesomeagents.ai/leaderboards/swe-bench-coding-agent-leaderboard/) |
| SWE-agent v1 (open) | — | 43.2% [3](https://awesomeagents.ai/leaderboards/swe-bench-coding-agent-leaderboard/) |
| 39-model TB2.0 average | 56.4% [4](https://baeseokjae.github.io/posts/terminal-bench-2026-guide/) | — |

Two facts worth internalising:

1. **Scaffold spread is enormous.** With the *same* class of model, open
   scaffolds range 14.7% → 68.4% on SWE-bench Verified [3]. The harness is worth
   tens of points. That is the door this project is standing in.
2. **The ceiling is the model.** Every top score above is a frontier closed model
   behind a scaffold. No scaffold has ever beaten the model it wraps — and this
   repo ships 5 BYOK providers, so its ceiling moves with someone else's releases.

## 4. Where this genuinely beats the whales

Not consolation prizes — these are the reasons the thing is worth continuing:

1. **It refuses to lie about completion.** Codex/Claude/OpenHands will tell you a
   task is done and let you discover otherwise. Here `task_completed` is a
   *proof obligation*: execution outcome **and** fresh verification receipts
   **and** the named deliverables existing on disk **and** the spec being
   complete. Model self-certification is structurally impossible.
2. **Verification debt.** A failing check creates a hashed obligation that only
   the *same* check passing can clear — a weaker green command cannot launder it.
   I have not seen this in a shipping competitor.
3. **Provider-neutral + surface-neutral.** Bridge, AG-UI and the IDE all drive the
   same graph; TestSprite/filesystem/github MCP servers drop in with a JSON file.
   Whales are locked to their own model vendor or their own runtime.

## 5. Gaps that actually decide the fight

| Gap | Why it decides it |
|---|---|
| **No public benchmark number** | Every sales conversation, every hire, every "can it compete" question ends at "what's your SWE-bench?" — today the honest answer is "unmeasured" |
| **No sandbox** | Autonomous runs on a host FS are fine for one trusted user, disqualifying for enterprise/multi-tenant. Competitors made this table stakes |
| **One maintainer, 8k-line core** | Bus factor 1; the graph module is already beyond safe-change size |
| **CI doesn't run the suite** | 3,108 green tests prove nothing if 5 run before merge |
| **Unproven long horizon** | GatePulse tasks are minutes-scale; whales are being judged on multi-hour autonomous runs |

## 6. What "competitive" would require (measurable, in order)

1. **One public, reproducible number.** Run SWE-bench Verified-lite (say 100
   issues) and Terminal-Bench-style tasks on a frontier model through the bridge,
   publish *including failures*. Bar: **≥ 40% SWE-bench Verified** puts it in
   proven-scaffold territory (above Agentless 34%, below SWE-agent 43%).
2. **Sandbox the body.** Docker/namespace isolation for `terminal` + file tools,
   with the approval gates on top. Bar: an untrusted-repo run cannot touch
   `$HOME` or the network.
3. **CI runs everything, on every PR.** Bar: the 3,108-test suite is the merge
   gate; the suite must also stop writing into the repo tree.
4. **Split `chat_graph.py`.** Bar: no module > 2,000 lines; routing decisions
   stay in `gates.py`.
5. **Prove the honest niche.** Publish a "false-done rate" alongside pass rate —
   the one metric where this project can lead instead of follow.

## 7. Verdict

| Question | Answer |
|---|---|
| Is the architecture whale-class? | **Yes, at the scaffold layer.** The supervision, evidence and honesty machinery are better than most shipping harnesses. |
| Is the product whale-class? | **No.** No sandbox, no benchmark, bus factor 1, CI that skips its own suite. |
| Can it compete on *capability* today? | **Unproven — treat as 0 until measured.** Not a criticism of the code; a statement about evidence. |
| Can it find a wedge? | **Yes**: "the agent that never claims a false done" is a real, defensible, unoccupied position — and it is the one thing here that the leaders are structurally bad at. |
| Realistic tier | A strong **research-grade open scaffold with a differentiated honesty contract**, ~12 months of hardening from being a credible challenger on narrow task classes. Chasing general SWE-bench parity with one maintainer is not a plan; owning the false-done metric is. |

> Honesty note: no live model turn was executed for this assessment, and the
> TestSprite leg is protocol-verified only (no API key). Everything in §1 is
> measured; everything in §3 is cited; everything in §2 is judgement.
