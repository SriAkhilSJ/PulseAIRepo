# OpenCode UI — captured verbatim (do not edit these copies)

Source: https://github.com/anomalyco/opencode @ `a8fc567c5c2a0af0b6069e6b87293d2d420cd668`
License: MIT (see `LICENSE` in this folder — keep it with any copied code).

These files are the **reference capture** of the chat-box UI the founder picked
(Shell box, Edit card, Thought row, task card, composer dock). They are NOT
built or shipped as-is: OpenCode's app is SolidJS + Electron + its own SSE
server; our right pane is the VS Code workbench renderer on Bridge Protocol v2.
The copy gives us the exact structure/CSS/event behaviour to wire to our
backend — the design is theirs verbatim, the plumbing is ours.

| Captured file | Drives (in the screenshot) |
|---|---|
| `session-ui/components/basic-tool.tsx` + `.css` | Every tool row: icon, human title, shimmer while pending, one-line submessage, chevron collapse |
| `session-ui/components/message-part.css` | The `bash-output` box (0.5px border, hover-reveal copy, scrollable `<pre>`), diff/write boxes, todos, task card |
| `session-ui/tools/tool-renderer.tsx` | Per-tool renderers: `shell`, `execute`, `edit`, `write`, `task`… (registry pattern — one shell, many tools) |
| `session-ui/tools/shell-output.ts` | Live output: cursor-paged polling per shell id, last-64KB tail, stops when complete/missing |
| `session-ui/components/dock-prompt.tsx` | Composer dock shell |

## Event wiring — their box events → our Bridge v2 backend

Everything in the box is an event our backend already emits, EXCEPT one gap
(last row). No OpenCode server, SDK, or protocol comes with the copy.

| Box UI event (captured) | Our Bridge v2 wire (exists today) |
|---|---|
| Timeline parts in arrival order (text/thought/tools interleaved) | `token`, `reasoning`, `tool_call_start`, `tool_call_end` — already our `parts` model |
| Thought row expand/collapse, "3s" | `reasoning` part + duration |
| Tool row shimmer while pending | tool state `running` from `tool_call_start` |
| Collapsed row shows command's first line | `tool_call_start.arguments.command` |
| "Writing command…" while args form | ⚠️ partial — v2 sends arguments whole at start; the shimmer covers the same moment, wording adapts |
| ✓ / exit code / timed out / cancelled | `tool_call_end.status` + result exit parsing (already in `terminalBody`) |
| Copy button (hover, check-flash) | `host.copyToClipboard` (exists) |
| Collapse state survives re-render | `openTools` set (exists) |
| Task card → open sub-agent | `host.navigateToSession` (exists) |
| Composer: send / stop / mode / Think level | `prompt`, `cancel`, `steer`, `prompt{mode, reasoning_effort}` (exist) |
| **Live output lines spawning while the command runs** | ⚠️ **GAP — the one new wire.** v2 delivers the terminal result whole at `tool_call_end`; nothing streams mid-run. Wiring this box event for real needs one small engine addition: stream shell output chunks during the run (their cursor-paging is the model). Until then the box shows output at completion — never fake-spawned. |

## Rules for anyone wiring this

1. Copy structure + CSS from these files; translate SolidJS → our renderer's
   plain DOM the way `crusorAIRenderer.ts` already works. Keep human labels —
   never a raw tool id.
2. Colours come from the live workbench theme (forced-black product defaults),
   never from OpenCode's `--v2-*` values. Green/amber/red only when earned.
3. Keep the MIT LICENSE with derived code.
4. If an event has no v2 wire, say so (like the gap above) — do not fake it.
