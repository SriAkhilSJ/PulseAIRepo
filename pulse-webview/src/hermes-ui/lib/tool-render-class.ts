// Which surface a tool call renders as — port of hermes-agent
// apps/desktop/src/lib/tool-render-class.ts @ a9c783f2, with the tool sets
// bound to Pulse's registry (src/tools/) instead of Hermes's.
//
// Two consumers have to agree on this and they sit on opposite sides of the
// app: the transcript decides what to draw, and the render budget decides how
// much of it to mount. The classification therefore lives on its own rather
// than inside either one.

/** Renders a diff — the deliverable of the turn, and the one card whose cost scales. */
const FILE_EDIT_TOOL_NAMES = new Set(['write_file', 'edit_file', 'copy_file', 'scaffold_nextjs']);

export function isFileEditTool(toolName: string): boolean {
  return FILE_EDIT_TOOL_NAMES.has(toolName);
}

// Tools that draw their own surface and must never be folded into a run's
// summary: the thing on screen IS the point.
//   - File edits are the deliverable, not scaffolding.
//   - `ask_user` is a question the user must answer; the Pulse task card (A2UI)
//     and the host-capability prompt are the same kind of thing.
// Folding any of those into "Using 2 tools" hides the buttons.
const CARD_TOOL_NAMES = new Set(['ask_user', 'display_pulse_task', 'invoke_host_capability', 'delegate_to_subagent', 'delegate_to_subagent_batch']);

export function isCardTool(toolName: string): boolean {
  return CARD_TOOL_NAMES.has(toolName) || isFileEditTool(toolName);
}

// Activity tools that render nothing of their own: Pulse's `think` receipts are
// hoisted into the reasoning disclosure, and `verify` is reported on the
// verification strip. Both still render when they FAIL — that is a bounded
// error row either way.
const SILENT_TOOL_NAMES = new Set(['think']);

export function isSilentTool(toolName: string): boolean {
  return SILENT_TOOL_NAMES.has(toolName);
}
