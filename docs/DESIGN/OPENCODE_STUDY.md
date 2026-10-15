# OpenCode study — captured from source (anomalyco/opencode @ a8fc567, cloned 2026-10-15)

Research only. Nothing here is implemented. Adoption rule (founder): do NOT copy
their environment — take only what helps OUR environment (native VS Code pane,
Bridge Protocol v2, A2UI Catalog v1) and adapt it.

## 1. Their stack (why blind copying is impossible)

- Desktop = **Electron** shell (`packages/desktop`, electron-vite/electron-builder)
  around a **SolidJS** web app (`packages/app`). We ship a **VS Code fork**
  (TypeScript workbench renderer, theme tokens from the workbench). Their
  components literally cannot run in our pane; only their *patterns* transfer.
- UI system: shared `packages/session-ui` (Solid components + CSS custom
  properties, `--v2-*` design tokens, `data-component`/`data-slot` attributes),
  `packages/ui` primitives, `packages/theme` token sets.

## 2. Agentic chat look — how a turn is built

- A turn is a **timeline of message parts** (text / reasoning / tool / shell /
  file …) rendered in arrival order — same `parts` discipline our renderer
  already has. Streaming text goes through a markdown worker
  (`markdown-stream.ts`) so paint never blocks input.
- Tool cards all share one shell, **`BasicTool`** (`session-ui/src/components/
  basic-tool.tsx` + `.css`, 418+462 lines): collapsible row, icon, title
  (shimmer-animated while pending via `TextShimmer`), one-line subtitle of
  what the tool is doing, chevron. Each tool type registers a renderer in
  `tools/tool-renderer.tsx` (2,434 lines: shell, execute, edit, write, task…).
- Consecutive quiet tools fold into **tool groups** with counts; cards that
  draw their own surface (diffs, questions) stay in place. Same grouping rule
  our `splitRunGroups` already implements.

## 3. The shell/terminal card — exact anatomy (their flagship card)

From `tool-renderer.tsx` (`shell` + `execute` registrations) and
`message-part.css:425`:

- Trigger row: console icon, title **“Shell”** (shimmer while streaming/
  running), and — when collapsed — a **submessage**: the command's first line,
  width-animated in as it streams. While the model is still writing the
  command, subtitle reads “Writing command…”.
- Body = **one** output box (`data-component="bash-output"`): 0.5px border
  (`--v2-border-border-base`), 6px radius, transparent background. Inside,
  a single scrollable `<pre>`: the **command** span followed by the
  **result** span — there are NO “COMMAND”/“STDOUT” labels.
- Copy button lives **inside** the box, absolute top-right, **invisible until
  hover** (opacity 0 → 1), swaps to a check for 2s after copy.
- Streaming (`tools/shell-output.ts`): output is **cursor-paged** — the client
  polls the shell by id with a byte cursor, keeps only the **last 64 KB**
  (`SHELL_OUTPUT_TAIL_BYTES`), remembers progress per shell across remounts,
  and stops asking once the shell is complete/missing. Exit≠0 / timeout /
  killed surface as error text (“Shell exited with code N”, timed out,
  cancelled) — earned colour, never decoration.

## 4. Protocols — what they actually implement

- **No AG-UI. No A2UI. No ACP** (searched the tree: zero hits). Anyone claiming
  opencode is an AG-UI/A2UI reference is wrong.
- Their contract is **their own**: a local HTTP server + **SSE event stream**,
  typed SDK generated from `packages/protocol/src/groups/*` (`event.ts`,
  `message.ts`, `mcp.ts`, `agent.ts`, `fs.ts`, …) into `@opencode/client`.
  Events are fine-grained part updates (message/part deltas) — conceptually
  the same shape as our Bridge v2 `token` / `tool_call_start` / `tool_call_end`
  frames, carried over HTTP instead of local IPC.
- **MCP**: yes, full client (`packages/core/src/mcp`: stdio + OAuth) — tools
  from external servers are first-class. (We have skills/hub; MCP client is a
  separate later decision, not a UI one.)
- Extensibility: plugins (`packages/plugin`) hook the agent loop.

## 5. What helps OUR environment (adapt, never copy)

| Their pattern | Our adaptation |
|---|---|
| `BasicTool` one-shell-many-tools | Already our `toolRow` + `familyBody` shape — keep, tighten trigger anatomy (icon + human title + live submessage) |
| Collapsed card shows command's first line | New for us: collapsed terminal row echoes the command, replacing the target-repeat we currently drop |
| Cursor-paged tail streaming, 64 KB cap | Our terminal body already tail-windows; adopt cursor/remount discipline when Bridge v2 streams shell output |
| Copy inside box, hover-reveal, check-flash | Our copy buttons exist; hover-reveal inside the output box is cleaner than our header copy |
| Shimmer title while pending | We have `crusorai-shimmer` + breathing — same idea, keep ours |
| No COMMAND/STDOUT labels; command+result in one `<pre>` | **Conflicts with the founder's approved reference** (two labeled boxes). Founder decides — see questions |
| SSE + generated SDK | Skip entirely: Bridge v2 over IPC is lower-latency on desktop and already a superset (our locked Decision 1) |
| AG-UI/A2UI | They have neither; our AG-UI-edge + A2UI-catalog track stays as planned |

## 6. Status

- Clone: `/home/user/opencode-study` (outside the repo; never committed).
- Terminal-card blueprint (`wireframes/terminal-card.html`) still awaits
  founder yes/no; the answer to Q1 below may revise it before lock.
