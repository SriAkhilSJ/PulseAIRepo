/*---------------------------------------------------------------------------------------------
 * Renderer-neutral catalog for canonical Pulse tools. Native hosts select a
 * disclosure body by family rather than hard-coding individual tool names.
 *--------------------------------------------------------------------------------------------*/

export type PulseAIToolRendererFamily =
	| 'control'
	| 'file-read'
	| 'file-write'
	| 'search'
	| 'terminal'
	| 'process'
	| 'code'
	| 'verification'
	| 'web'
	| 'browser'
	| 'session'
	| 'subagent'
	| 'scaffold'
	| 'generic';

export type PulseAIToolOpenPolicy = 'never' | 'running' | 'always' | 'preference';

export interface PulseAIToolPresentation {
	readonly title: string;
	readonly family: PulseAIToolRendererFamily;
	readonly icon: string;
	readonly defaultOpen: PulseAIToolOpenPolicy;
}

const tool = (title: string, family: PulseAIToolRendererFamily, icon: string, defaultOpen: PulseAIToolOpenPolicy = 'never'): PulseAIToolPresentation => ({ title, family, icon, defaultOpen });

	// Icon names are Hermes' own (`pulse-webview/src/hermes-ui/model/fallback-model.ts` TOOL_META,
	// which is a port of upstream's table), not the fork's earlier guesses: the native renderer and
	// the webview resolve a glyph by the same key, so the two surfaces cannot show different icons
	// for the same call. `browser/pulseAIIcons.ts` turns these names into filled SVGs where Hermes
	// has solid paths and falls back to the codicon font otherwise -- upstream's rule, verbatim.
export const PULSE_AI_TOOL_CATALOG: Readonly<Record<string, PulseAIToolPresentation>> = {
	think: tool('Think', 'control', 'brain'),
	verify: tool('Verify', 'verification', 'check', 'running'),
	ask_user: tool('Question', 'control', 'question', 'running'),
	session_search: tool('Search sessions', 'session', 'history'),

	read_file: tool('Read', 'file-read', 'file'),
	list_files: tool('List files', 'file-read', 'list'),
	search_code: tool('Search code', 'search', 'search'),
	discover_host_capabilities: tool('Discover editor capabilities', 'search', 'symbol-method'),
	invoke_host_capability: tool('Use editor intelligence', 'search', 'zap'),
	write_file: tool('Write', 'file-write', 'file-add', 'preference'),
	edit_file: tool('Edit', 'file-write', 'edit', 'preference'),
	copy_file: tool('Copy file', 'file-write', 'copy', 'preference'),

	run_terminal: tool('Terminal', 'terminal', 'terminal', 'always'),
	execute_code: tool('Execute code', 'code', 'terminal', 'running'),
	start_terminal: tool('Start process', 'process', 'terminal', 'running'),
	check_terminal: tool('Check process', 'process', 'terminal', 'running'),
	read_terminal_output: tool('Read process output', 'process', 'output', 'always'),
	stop_terminal: tool('Stop process', 'process', 'debug-stop'),
	list_terminal_processes: tool('List processes', 'process', 'list'),
	cleanup_terminal_processes: tool('Clean up processes', 'process', 'trash'),

	typecheck_workspace: tool('Typecheck', 'verification', 'check', 'running'),
	verify_ui_workspace: tool('Verify UI', 'verification', 'check', 'running'),
	verify_ui_routes: tool('Verify routes', 'verification', 'check', 'running'),
	scaffold_nextjs: tool('Scaffold Next.js', 'scaffold', 'add', 'running'),

	web_search: tool('Search web', 'web', 'search'),
	web_fetch: tool('Fetch page', 'web', 'globe'),

	browser_navigate: tool('Navigate', 'browser', 'globe', 'running'),
	browser_snapshot: tool('Browser snapshot', 'browser', 'globe'),
	browser_screenshot: tool('Screenshot', 'browser', 'file-media'),
	browser_click: tool('Click', 'browser', 'globe'),
	browser_type: tool('Type', 'browser', 'globe'),
	browser_hover: tool('Hover', 'browser', 'globe'),
	browser_select: tool('Select', 'browser', 'globe'),
	browser_evaluate: tool('Evaluate in browser', 'browser', 'globe'),

	delegate_to_subagent: tool('Delegate', 'subagent', 'rocket', 'running'),
	delegate_to_subagent_batch: tool('Delegate batch', 'subagent', 'rocket', 'running'),
};

const GENERIC = tool('Tool', 'generic', 'tools');
export function pulseAIToolPresentation(name: string | undefined): PulseAIToolPresentation {
	if (!name) { return GENERIC; }
	return PULSE_AI_TOOL_CATALOG[name] ?? GENERIC;
}
