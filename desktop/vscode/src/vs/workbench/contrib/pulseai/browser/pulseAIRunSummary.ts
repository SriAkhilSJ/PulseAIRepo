/*---------------------------------------------------------------------------------------------
 * Activity runs: the grouping rule and the summary clause machinery, mirrored from the
 * CopilotKit webview's `hermes-ui/model/run-summary.ts` and `components/tool-run.tsx`
 * (themselves ports of hermes-agent @ a9c783f2). Kept in its own module with no DOM
 * imports so the rule can be executed by a test instead of only grep-checked -- see
 * src/tests/test_hermes_run_summary_parity.py.
 *
 * Why the native right-panel view needs it at all: it used to render every tool call as
 * a flat "Actions" list, so the same turn read as a dense one-line summary in the
 * CopilotKit surface and as a dozen rows here. Two surfaces, one agent, two stories.
 *--------------------------------------------------------------------------------------------*/

export type PulseRunCategory = 'delegate' | 'edit' | 'explore' | 'other' | 'run';

export interface PulseRunSummaryTool {
	readonly id?: string;
	readonly name?: string;
	readonly result?: unknown;
}

export type PulseRunGroup<T extends PulseRunSummaryTool> =
	| { readonly kind: 'card'; readonly tool: T }
	| { readonly kind: 'run'; readonly start: number; readonly end: number; readonly tools: T[] };

/** Clause order is fixed so the same run always reads the same way. */
const CATEGORY_ORDER: readonly PulseRunCategory[] = ['edit', 'explore', 'run', 'delegate', 'other'];

const CATEGORY_COPY: Record<PulseRunCategory, { readonly noun: readonly [string, string]; readonly past: string; readonly present: string }> = {
	delegate: { noun: ['task', 'tasks'], past: 'Delegated', present: 'Delegating' },
	edit: { noun: ['file', 'files'], past: 'Edited', present: 'Editing' },
	explore: { noun: ['file', 'files'], past: 'Explored', present: 'Exploring' },
	other: { noun: ['tool', 'tools'], past: 'Used', present: 'Using' },
	run: { noun: ['command', 'commands'], past: 'Ran', present: 'Running' },
};

/** The webview's tables, copied rather than re-derived: names Pulse actually registers. */
const FILE_EDIT_TOOL_NAMES = new Set(['write_file', 'edit_file', 'copy_file', 'scaffold_nextjs']);

const CARD_TOOL_NAMES = new Set(['ask_user', 'display_pulse_task', 'invoke_host_capability', 'delegate_to_subagent', 'delegate_to_subagent_batch']);

const SILENT_TOOL_NAMES = new Set(['think']);

const EXPLORE_TOOLS = new Set([
	'list_files', 'read_file', 'search_code', 'session_search', 'web_fetch', 'web_search',
	'discover_host_capabilities', 'read_terminal_output', 'check_terminal',
	'list_terminal_processes', 'typecheck_workspace', 'verify_ui_routes', 'verify_ui_workspace',
]);

export function isFileEditTool(toolName: string): boolean {
	return FILE_EDIT_TOOL_NAMES.has(toolName);
}

/** Tools that draw their own surface and must never fold into a summary: the thing on
 *  screen IS the point (a diff, a question, a sub-agent card). */
export function isCardTool(toolName: string): boolean {
	return CARD_TOOL_NAMES.has(toolName) || isFileEditTool(toolName);
}

/** Renders nothing of its own -- `think` receipts already surface as reasoning. */
export function isSilentTool(toolName: string): boolean {
	return SILENT_TOOL_NAMES.has(toolName);
}

export function runCategory(toolName: string | undefined): PulseRunCategory {
	const name = toolName ?? '';
	if (isFileEditTool(name)) { return 'edit'; }
	if (name === 'run_terminal' || name === 'execute_code' || name.startsWith('start_terminal')) { return 'run'; }
	if (name.startsWith('delegate_to_subagent')) { return 'delegate'; }
	if (EXPLORE_TOOLS.has(name) || name.startsWith('browser_')) { return 'explore'; }
	return 'other';
}

/** How a tool reads while it is happening -- "Editing", "Exploring", not "Reading". */
export function toolPresentVerb(toolName: string | undefined): string {
	return CATEGORY_COPY[runCategory(toolName)].present;
}

export function categoryCopy(category: PulseRunCategory): { readonly noun: readonly [string, string]; readonly past: string; readonly present: string } {
	return CATEGORY_COPY[category];
}

function isPending(tool: PulseRunSummaryTool): boolean {
	return tool.result === undefined;
}

/**
 * A target has to fit on one grey line inside a 380px panel: collapsed whitespace and a
 * hard clamp, the same shape the webview applies (`compactPreview` / `timelinePreview`).
 * Clamped for *display* only -- the row behind it still carries the whole command.
 */
export function compactTarget(value: string | undefined, max = 48): string | undefined {
	if (!value) { return undefined; }
	const collapsed = value.replace(/\s+/g, ' ').trim();
	if (!collapsed.length) { return undefined; }
	return collapsed.length <= max ? collapsed : `${collapsed.slice(0, max - 1).trimEnd()}\u2026`;
}

function lowerFirst(text: string): string {
	return text.charAt(0).toLowerCase() + text.slice(1);
}

/**
 * Split a range of calls into cards and the runs of activity between them.
 *
 * Order is preserved rather than sorted: a turn that reads, edits, then reads again
 * shows a summary, the diff, then a second summary, in the sequence it happened. A
 * name that is empty is not a tool call at all and passes through as its own card.
 */
export function splitRunGroups<T extends PulseRunSummaryTool>(tools: readonly T[]): readonly PulseRunGroup<T>[] {
	const items: PulseRunGroup<T>[] = [];
	let run: { kind: 'run'; start: number; end: number; tools: T[] } | null = null;

	tools.forEach((tool, index) => {
		const name = tool.name ?? '';
		if (!name || isCardTool(name)) {
			run = null;
			items.push({ kind: 'card', tool });
			return;
		}
		if (run) {
			run.end = index;
			run.tools.push(tool);
		} else {
			run = { kind: 'run', start: index, end: index, tools: [tool] };
			items.push(run);
		}
	});

	return items;
}

function clause(category: PulseRunCategory, tools: readonly PulseRunSummaryTool[], live: boolean, target: string | undefined): string {
	const copy = CATEGORY_COPY[category];
	const verb = live ? copy.present : copy.past;
	if (target && tools.length === 1 && (live || category !== 'run')) {
		return `${verb} ${target}`;
	}
	return `${verb} ${tools.length} ${copy.noun[tools.length === 1 ? 0 : 1]}`;
}

/**
 * Collapse a run into the one grey line that stands in for it -- "Explored 3 files,
 * ran 5 commands". While the run is live, the category holding its most recent
 * unfinished call speaks in the present tense. `live` is the caller's to say: a call
 * left without a result by an ended turn must still read as finished.
 *
 * `targetOf` is injected because the fork's target extraction lives with the renderer
 * (it reads per-family payloads); the clause rules -- when a target earns the space
 * and when counting wins -- are the ones shared with the webview.
 */
export function summarizeToolRun<T extends PulseRunSummaryTool>(
	tools: readonly T[],
	live: boolean,
	targetOf: (tool: T) => string | undefined,
): string {
	if (!tools.length) { return ''; }
	const narrating = live ? (tools.find(isPending) ?? tools.at(-1)) : undefined;
	const liveCategory = narrating ? runCategory(narrating.name) : null;

	const byCategory = new Map<PulseRunCategory, T[]>();
	for (const tool of tools) {
		const category = runCategory(tool.name);
		const group = byCategory.get(category);
		if (group) { group.push(tool); } else { byCategory.set(category, [tool]); }
	}

	const clauses: string[] = [];
	for (const category of CATEGORY_ORDER) {
		const group = byCategory.get(category);
		if (!group) { continue; }
		clauses.push(clause(category, group, category === liveCategory, group.length === 1 ? targetOf(group[0] as T) : undefined));
	}
	return clauses.map((text, index) => (index === 0 ? text : lowerFirst(text))).join(', ');
}
