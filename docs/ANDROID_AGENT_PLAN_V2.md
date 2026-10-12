# Android agent plan, v2 — revised after surveying the landscape

Written 2026-10-12 after querying the GitHub API for the current state of the
art. Supersedes the phase list in `ANDROID_AGENT_PLAN.md` §5. The evidence
contract in `ANDROID_EVIDENCE_CONTRACT.md` is unchanged and still load-bearing.

All numbers below were read from `api.github.com` on 2026-10-12, not recalled.

## 1. What the survey found

| Repo | Stars | License | Last push | What it actually is |
|---|---|---|---|---|
| `mobile-next/mobile-mcp` | 9,025 | Apache-2.0 | 2026-10-11 | MCP server, 33 tools, Android + iOS, emulators + real devices |
| `getsentry/MobileBuildMCP` | 6,475 | MIT | 2026-10-09 | **iOS/macOS only** — Xcode builds. Not Android. |
| `callstack/agent-device` | 4,978 | MIT | 2026-10-12 | CLI + MCP, 73 commands, ref-based, evidence-first |
| `minitap-ai/mobile-use` | 3,250 | Apache-2.0 | 2026-09-14 | **LangGraph-based** natural-language phone control |
| `takahirom/arbigent` | 650 | Apache-2.0 | 2026-10-02 | Kotlin AI testing framework, scenario decomposition |
| `mobile-dev-inc/Maestro` | ~16k | Apache-2.0 | — | Scripted UI testing engine; agent-device can export to it |

Four things in that table change the plan.

**MobileBuildMCP does not overlap with our build work.** Its README requires
macOS 14.5+ and Xcode 16.x; its topics are `xcode`, `xcodebuild`. There is no
Android build MCP of comparable maturity. So `scaffold_android` and
`verify_android_app` fill a real gap rather than duplicating a 6,000-star
project. But its *shape* is worth copying: one package, **CLI and MCP server
from the same codebase**, plus `init` that installs agent skills.

**mobile-mcp is bigger and broader than the tool I integrated.** It has 33
registered tools against agent-device's 73 CLI commands, and three of them
matter more than anything agent-device offers:

- `mobile_list_crashes` / `mobile_get_crash` — structured crash reports as a
  tool. This is *exactly* the "evidence, not screenshots" requirement, and it
  is stronger evidence than the logcat grep `verify_android_app` does today.
- `mobile_batch_commands` — several device actions in one call. Independent
  confirmation that the one-receipt design of `verify_android_app` is the right
  instinct, applied to the interactive layer too.
- `get_more_tools` — progressive tool disclosure, so the agent does not carry 33
  schemas it will not use.

**mobile-use is built on LangGraph** (topics: `langchain`, `langgraph`). That is
the same framework as `src/graphs/chat_graph.py`. It is the first project to
complete 100% of the AndroidWorld benchmark. Its graph structure is therefore
directly transferable rather than merely inspirational.

**arbigent names the real failure mode.** Its README: *"agents might open other
apps or click on the wrong button due to the complexity of the task."* Its
answer is decomposing a complex task into **smaller, dependent scenarios**. No
amount of evidence discipline fixes an agent that taps the wrong button; this is
the piece our plan was missing entirely.

## 2. What is confirmed, not changed

Three independent projects converged on the same rule, which is strong evidence
it is correct: **prefer the accessibility tree over screenshots.** mobile-mcp's
skill says prefer `mobile_list_elements_on_screen` because *"it is faster,
cheaper, and more reliable than screenshots"*; agent-device says agents should
read snapshots *"instead of reasoning over screenshots alone."* Our R9 (a
screenshot is never sole Tier-3 evidence) stands.

Also unchanged: the tier model, the four verdicts, the rule that a green exit
code with no artifact is a failure, and the allowlist discipline in
`android_device`. Nothing in the survey does evidence-tiering; that remains the
differentiator.

## 3. Revised plan

Ordered by value per unit of risk. Each item names what it borrows.

### Phase A — Add mobile-mcp as a second device backend

`src/tools/mcp_client.py` already reads `<workspace>/.crusorai/mcp.json` and
`skills_hub.connector_attach()` already writes it. So this is mostly
configuration plus a doctor row, not new plumbing.

`@mobilenext/mobile-mcp` (npm, Node >= 20, bin `mcp-server-mobile`) shells out
to a `mobilecli` platform binary from scoped packages — worth surfacing in
`android_doctor` so a missing binary is diagnosed before the first failure.

Deliverable: `android_doctor` reports mobile-mcp alongside agent-device, and a
skill row teaches the `mobile_*` tool names.

### Phase B — Crash reports as first-class evidence

Borrow `mobile_list_crashes` / `mobile_get_crash`. Extend
`verify_android_app` so that a Tier-2 run also collects a crash report if one
exists, and records it in the receipt with a hash. A crash dump naming the
exception and stack is Tier-3 evidence about a *specific* failure; a logcat grep
is not.

This is the single highest-value change for user trust.

### Phase C — Batch the interactive loop

Borrow `mobile_batch_commands`. Today the open → snapshot → tap → snapshot loop
costs a model turn per step. Grouping deterministic steps into one call is the
same argument that justified `verify_android_app`.

### Phase D — Scenario decomposition

Borrow arbigent. A UI test becomes a list of small named scenarios with explicit
dependencies, each independently verifiable, rather than one long instruction.
This is what makes agent-driven UI testing survive a real app's popups, A/B
tests and dynamic content.

### Phase E — Progressive tool disclosure

Borrow `get_more_tools`. The Android toolset is now 4 tools; it will not stay
that small. Disclose the long tail on demand instead of always.

### Phase F — Copy the distribution shape

One package, CLI + MCP from the same source, an `init` that installs skills.
Model: MobileBuildMCP.

## 4. What is still unproven

Unchanged and worth repeating: **none of this has run on a real device.** This
sandbox has no JDK, no Android SDK, no `adb`, no Node-based device tooling.
Everything shipped so far is verified against stubbed binaries. The version pins
in `scaffold_android` have never been exercised by a real Gradle build.

The first real run on a machine with the toolchain installed is the gate that
matters, and it has not happened.
