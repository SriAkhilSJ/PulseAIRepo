/*---------------------------------------------------------------------------------------------
 * Renderer-neutral catalog for canonical Crusor tools. Native hosts select a
 * disclosure body by family rather than hard-coding individual tool names.
 *--------------------------------------------------------------------------------------------*/

export type CrusorAIToolRendererFamily =
	| 'control'
	| 'plan'
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

export type CrusorAIToolOpenPolicy = 'never' | 'running' | 'always' | 'preference';

export interface CrusorAIToolPresentation {
	readonly title: string;
	readonly family: CrusorAIToolRendererFamily;
	readonly icon: string;
	readonly defaultOpen: CrusorAIToolOpenPolicy;
}

const tool = (title: string, family: CrusorAIToolRendererFamily, icon: string, defaultOpen: CrusorAIToolOpenPolicy = 'never'): CrusorAIToolPresentation => ({ title, family, icon, defaultOpen });

	// Icon names are Hermes' own (`crusor-webview/src/hermes-ui/model/fallback-model.ts` TOOL_META,
	// which is a port of upstream's table), not the fork's earlier guesses: the native renderer and
	// the webview resolve a glyph by the same key, so the two surfaces cannot show different icons
	// for the same call. `browser/crusorAIIcons.ts` turns these names into filled SVGs where Hermes
	// has solid paths and falls back to the codicon font otherwise -- upstream's rule, verbatim.
export const CRUSOR_AI_TOOL_CATALOG: Readonly<Record<string, CrusorAIToolPresentation>> = {
	// Hermes ThinkingDisclosure: live reasoning is VISIBLE (open), a settled
	// thought collapses to one quiet row. 'running' gives exactly that.
	think: tool('Think', 'control', 'brain', 'running'),
	verify: tool('Verify', 'verification', 'check', 'running'),
	ask_user: tool('Question', 'control', 'question', 'running'),
	// The ask tool's runtime name is `clarify` (hermes CLARIFY_SCHEMA); the
	// ask_user row above is the same tool's legacy meta. A settled clarify
	// batch (answered or replayed) must still read as a Question card.
	clarify: tool('Question', 'control', 'question', 'running'),
	session_search: tool('Search sessions', 'session', 'history'),

	read_file: tool('Read', 'file-read', 'file'),
	list_files: tool('List files', 'file-read', 'list'),
	// Hermes-name primaries (engine commit b75cd4c6: the model binds and
	// calls `search_files`/`terminal`/`web_extract`) MUST resolve the same
	// families as their legacy crusor aliases — otherwise the field's most
	// common calls render as generic cards (no terminal body, no exit chip,
	// no diff/search treatment).
	search_files: tool('Search files', 'search', 'search'),
	search_code: tool('Search code', 'search', 'search'),
	discover_host_capabilities: tool('Discover editor capabilities', 'search', 'symbol-method'),
	invoke_host_capability: tool('Use editor intelligence', 'search', 'zap'),
	write_file: tool('Write', 'file-write', 'file-add', 'preference'),
	edit_file: tool('Edit', 'file-write', 'edit', 'preference'),
	copy_file: tool('Copy file', 'file-write', 'copy', 'preference'),

	terminal: tool('Terminal', 'terminal', 'terminal', 'always'),
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
	web_extract: tool('Extract page', 'web', 'globe'),
	web_fetch: tool('Fetch page', 'web', 'globe'),

	// The hermes browser surface (src/tools/browser_tools.py). The retired
	// puppeteer-era entries (hover/select/evaluate) are gone; console carries
	// the eval-expression surface now.
	browser_navigate: tool('Navigate', 'browser', 'globe', 'running'),
	browser_snapshot: tool('Browser snapshot', 'browser', 'globe'),
	browser_screenshot: tool('Screenshot', 'browser', 'file-media'),
	browser_click: tool('Click', 'browser', 'globe'),
	browser_type: tool('Type', 'browser', 'globe'),
	browser_scroll: tool('Scroll', 'browser', 'globe'),
	browser_back: tool('Browser back', 'browser', 'globe'),
	browser_press: tool('Press key', 'browser', 'globe'),
	browser_console: tool('Browser console', 'browser', 'globe'),
	browser_get_images: tool('Get images', 'browser', 'file-media'),

	delegate_to_subagent: tool('Delegate', 'subagent', 'rocket', 'running'),
	delegate_to_subagent_batch: tool('Delegate batch', 'subagent', 'rocket', 'running'),

	// The model's task list (field 2026-09-10: the card body painted the raw
	// {"steps":[...]} argument JSON). hermes hoists todo parts out of the
	// transcript into a status panel whose rows are glyph+text — the card
	// body ports those rows: dashed ring pending, live dot in_progress,
	// pass-filled done. todo_list is hermes' wire name (id-keyed, merge);
	// plan_update is the crusor-vocab sibling (description-keyed, replace-only).
	plan_update: tool('Plan Update', 'plan', 'list-ordered', 'running'),
	todo_list: tool('Todo list', 'plan', 'list-ordered', 'running'),
};

const GENERIC_ICON = 'tools';
export function crusorAIToolPresentation(name: string | undefined): CrusorAIToolPresentation {
	if (!name) { return tool('Tool', 'generic', GENERIC_ICON); }
	const known = CRUSOR_AI_TOOL_CATALOG[name];
	if (known) { return known; }
	// Hermes titleForTool (fallback-model.ts): unknown tools take the
	// title-cased name -- `plan_update` reads `Plan Update`, never a flat
	// `Tool`. Same rule the webview's toolMeta fallback already runs.
	const normalized = name.replace(/^browser_/, '').replace(/^web_/, '');
	const title = normalized.split('_').filter(Boolean)
		.map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ') || name;
	return tool(title, 'generic', GENERIC_ICON);
}
