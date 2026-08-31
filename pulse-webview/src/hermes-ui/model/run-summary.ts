// Port of hermes-agent `assistant-ui/tool/run-summary.ts` @ a9c783f2 — the
// clause machinery, ordering and copy are upstream's; the tool→category tables
// are bound to Pulse's registry.

import { summarizeShellCommand } from '../lib/summarize-command';
import { firstStringField } from '../lib/text';
import { fileEditBasename, isFileEditTool, parseMaybeObject } from './fallback-model';

/**
 * The little a summary needs from a tool call, stated structurally so both
 * shapes of tool part satisfy it — the stored part and the live one the agent
 * subscription hands to a renderer.
 */
export interface ToolCallLike {
  args?: unknown;
  result?: unknown;
  toolCallId?: string;
  toolName: string;
}

export function isToolCallPart<T extends { type: string }>(part: T): part is Extract<T, { type: 'tool-call' }> {
  return part.type === 'tool-call';
}

type RunCategory = 'delegate' | 'edit' | 'explore' | 'other' | 'run';

// Clause order is fixed so the same run always reads the same way, whichever
// category happens to be live.
const CATEGORY_ORDER: readonly RunCategory[] = ['edit', 'explore', 'run', 'delegate', 'other'];

const CATEGORY_COPY: Record<RunCategory, { noun: [string, string]; past: string; present: string }> = {
  delegate: { noun: ['task', 'tasks'], past: 'Delegated', present: 'Delegating' },
  edit: { noun: ['file', 'files'], past: 'Edited', present: 'Editing' },
  explore: { noun: ['file', 'files'], past: 'Explored', present: 'Exploring' },
  other: { noun: ['tool', 'tools'], past: 'Used', present: 'Using' },
  run: { noun: ['command', 'commands'], past: 'Ran', present: 'Running' },
};

// Pulse's read-only surface: what the agent looks at rather than changes.
const EXPLORE_TOOLS = new Set([
  'list_files',
  'read_file',
  'search_code',
  'session_search',
  'web_fetch',
  'web_search',
  'discover_host_capabilities',
  'read_terminal_output',
  'check_terminal',
  'list_terminal_processes',
  'typecheck_workspace',
  'verify_ui_routes',
  'verify_ui_workspace',
]);

function toolCategory(toolName: string): RunCategory {
  if (isFileEditTool(toolName)) {
    return 'edit';
  }

  if (toolName === 'run_terminal' || toolName === 'execute_code' || toolName.startsWith('start_terminal')) {
    return 'run';
  }

  if (toolName.startsWith('delegate_to_subagent')) {
    return 'delegate';
  }

  if (EXPLORE_TOOLS.has(toolName) || toolName.startsWith('browser_')) {
    return 'explore';
  }

  return 'other';
}

function isPending(tool: ToolCallLike): boolean {
  return tool.result === undefined;
}

/**
 * How a tool reads while it is happening — "Editing", "Exploring". Shared with
 * the status line that covers the gap before a tool starts, so the same run is
 * described in the same words from the moment the model drafts it.
 */
export function toolPresentVerb(toolName: string): string {
  return CATEGORY_COPY[toolCategory(toolName)].present;
}

/** The thing a tool acted on, as the header should name it. */
function toolTarget(tool: ToolCallLike): string {
  const args = parseMaybeObject(tool.args);

  if (toolCategory(tool.toolName) === 'run') {
    return summarizeShellCommand(firstStringField(args, ['command', 'code']));
  }

  const path = firstStringField(args, ['path', 'file', 'file_path', 'filepath']);

  return path ? fileEditBasename(path) : firstStringField(args, ['query', 'url', 'pattern']);
}

/**
 * One clause per category. A category holding a single thing says what it was
 * ("Edited wiring.tsx"); anything else counts ("explored 3 files"). A settled
 * command is the exception — "ran 5 commands" is the useful reading, and a
 * command line only earns its space while it's the thing you're waiting on.
 */
function clause(category: RunCategory, tools: ToolCallLike[], live: boolean): string {
  const copy = CATEGORY_COPY[category];
  const verb = live ? copy.present : copy.past;
  const target = tools.length === 1 ? toolTarget(tools[0] as ToolCallLike) : '';

  if (target && (live || category !== 'run')) {
    return `${verb} ${target}`;
  }

  return `${verb} ${tools.length} ${copy.noun[tools.length === 1 ? 0 : 1]}`;
}

function lowerFirst(text: string): string {
  return text.charAt(0).toLowerCase() + text.slice(1);
}

/**
 * Collapse a run of tool calls into the single grey line that stands in for it
 * — "Explored 3 files, ran 5 commands". While the run is live, the category
 * holding its most recent call speaks in the present tense so the line reads
 * as work in progress rather than work already done.
 *
 * Whether the run is `live` is the caller's to say, not something readable off
 * the calls: a call can be left without a result by a turn that ended or an
 * agent that moved on, and a run like that has to read as finished.
 */
export function summarizeToolRun(tools: readonly ToolCallLike[], live: boolean): string {
  const narrating = live ? (tools.find(isPending) ?? tools.at(-1)) : undefined;
  const liveCategory = narrating ? toolCategory(narrating.toolName) : null;

  const byCategory = new Map<RunCategory, ToolCallLike[]>();

  for (const tool of tools) {
    const category = toolCategory(tool.toolName);
    const group = byCategory.get(category);

    if (group) {
      group.push(tool);
    } else {
      byCategory.set(category, [tool]);
    }
  }

  const clauses = CATEGORY_ORDER.flatMap(category => {
    const group = byCategory.get(category);

    return group ? [clause(category, group, category === liveCategory)] : [];
  });

  return clauses.map((text, index) => (index === 0 ? text : lowerFirst(text))).join(', ');
}
