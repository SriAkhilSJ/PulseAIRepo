/*---------------------------------------------------------------------------------------------
 * Renderer-neutral catalog for all 34 canonical Pulse tools. Native hosts select a
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

export const PULSE_AI_TOOL_CATALOG: Readonly<Record<string, PulseAIToolPresentation>> = {
	think: tool('Think', 'control', 'sparkle'),
	verify: tool('Verify', 'verification', 'verified', 'running'),
	ask_user: tool('Question', 'control', 'comment-discussion', 'running'),
	session_search: tool('Search sessions', 'session', 'search'),

	read_file: tool('Read', 'file-read', 'file'),
	list_files: tool('List files', 'file-read', 'folder-opened'),
	search_code: tool('Search code', 'search', 'search'),
	write_file: tool('Write', 'file-write', 'new-file', 'preference'),
	edit_file: tool('Edit', 'file-write', 'diff', 'preference'),
	copy_file: tool('Copy file', 'file-write', 'copy', 'preference'),

	run_terminal: tool('Terminal', 'terminal', 'terminal', 'always'),
	execute_code: tool('Execute code', 'code', 'code', 'running'),
	start_terminal: tool('Start process', 'process', 'terminal', 'running'),
	check_terminal: tool('Check process', 'process', 'terminal', 'running'),
	read_terminal_output: tool('Read process output', 'process', 'output', 'always'),
	stop_terminal: tool('Stop process', 'process', 'debug-stop'),
	list_terminal_processes: tool('List processes', 'process', 'list-tree'),
	cleanup_terminal_processes: tool('Clean up processes', 'process', 'trash'),

	typecheck_workspace: tool('Typecheck', 'verification', 'beaker', 'running'),
	verify_ui_workspace: tool('Verify UI', 'verification', 'beaker', 'running'),
	verify_ui_routes: tool('Verify routes', 'verification', 'beaker', 'running'),
	scaffold_nextjs: tool('Scaffold Next.js', 'scaffold', 'package', 'running'),

	web_search: tool('Search web', 'web', 'globe'),
	web_fetch: tool('Fetch page', 'web', 'link'),

	browser_navigate: tool('Navigate', 'browser', 'browser', 'running'),
	browser_snapshot: tool('Browser snapshot', 'browser', 'browser'),
	browser_screenshot: tool('Screenshot', 'browser', 'device-camera'),
	browser_click: tool('Click', 'browser', 'cursor'),
	browser_type: tool('Type', 'browser', 'edit'),
	browser_hover: tool('Hover', 'browser', 'move'),
	browser_select: tool('Select', 'browser', 'list-selection'),
	browser_evaluate: tool('Evaluate in browser', 'browser', 'code'),

	delegate_to_subagent: tool('Delegate', 'subagent', 'organization', 'running'),
	delegate_to_subagent_batch: tool('Delegate batch', 'subagent', 'organization', 'running'),
};

const GENERIC = tool('Tool', 'generic', 'tools');
export function pulseAIToolPresentation(name: string | undefined): PulseAIToolPresentation {
	if (!name) { return GENERIC; }
	return PULSE_AI_TOOL_CATALOG[name] ?? GENERIC;
}
