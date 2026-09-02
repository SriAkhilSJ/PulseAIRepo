/*---------------------------------------------------------------------------------------------
 * Framework-neutral, editor-native Pulse renderer. Both first-party workbench hosts mount this
 * module; no Electron, Node, or Code OSS service is imported across this boundary.
 *--------------------------------------------------------------------------------------------*/

import type { IDisposable } from '../../../../base/common/lifecycle.js';
import type { PulseExecutionMode } from '../common/pulseAIProtocol.js';
import type { PulseAISurface } from '../common/pulseAIRendererService.js';
import type { PulseAISessionRow } from '../common/pulseAISessionProjection.js';
import { pulseAIToolPresentation } from '../common/pulseAIToolCatalog.js';
import { compactTarget, splitRunGroups, summarizeToolRun, toolPresentVerb } from './pulseAIRunSummary.js';
import { renderToolIcon } from './pulseAIIcons.js';
import {
	activityOrigin, activityParts, activityRowMode, activitySignature, closeMeasurement, draftingToolName,
	elapsedFor, measuredDuration,
	DRAFTING_REVEAL_MS, elapsedSeconds, formatElapsed, statusHintLabel, toolNarratesWait, TURN_QUIET_S,
	UNNAMED_WAIT_LABEL,
} from './pulseAIActivity.js';

export type PulseAIToolState = 'queued' | 'running' | 'passed' | 'approval' | 'failed';

export interface PulseAIToolView {
	readonly id: string;
	readonly name: string;
	readonly state: PulseAIToolState;
	readonly arguments?: unknown;
	readonly result?: unknown;
	readonly duration?: string;
}

export interface PulseAISubAgentView {
	readonly id: string;
	readonly state: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
	readonly goal?: string;
	readonly mode?: string;
	readonly progress?: string;
	readonly result?: unknown;
	readonly duration?: string;
	readonly parentSessionId?: string;
}

export interface PulseAIRenderModel {
	readonly engineState: string;
	readonly workspaceLabel: string;
	readonly noWorkspace: boolean;
	readonly noWorkspaceHint: string;
	readonly workspaceSelectionRequired: boolean;
	readonly workspaceChoices: readonly { readonly label: string; readonly uri: string }[];
	readonly engineSetupError: boolean;
	/**
	 * When the CURRENT turn started, in epoch ms, or undefined between turns. The tail activity
	 * row counts from this before anything has streamed and from the last visible progress after
	 * it, which is the difference between "thinking for 4s" and the age of a component.
	 */
	readonly turnStartedAt?: number;
	/** Context compaction is running. Rare, slow, and it outranks every other hint. */
	readonly compacting?: boolean;
	readonly sessionId?: string;
	readonly mode: PulseExecutionMode;
	readonly running: boolean;
	readonly cancelRequested: boolean;
	readonly turnOutcome: 'idle' | 'running' | 'completed' | 'cancelled' | 'failed';
	readonly userMessage?: string;
	readonly assistantText: string;
	readonly reasoning?: string;
	readonly tools: readonly PulseAIToolView[];
	readonly subAgents: readonly PulseAISubAgentView[];
	readonly approval?: { readonly toolId: string; readonly name: string; readonly diff?: unknown };
	readonly plan: readonly string[];
	readonly verification?: string;
	readonly telemetry: { readonly input?: number; readonly output?: number; readonly cache?: number; readonly cost?: number };
	readonly capabilitySummary: { readonly available: number; readonly total: number; readonly blocked: number };
	readonly error?: string;
	/**
	 * The engine itself faulted (process stopped, or a request that never reached the model) as opposed
	 * to `error`, which is about the turn or the action the user took. Kept separate on purpose: a fault
	 * here INVALIDATES `running`, because a spinner that keeps turning after the sidecar died is a claim
	 * about work in progress that no longer exists. `retrying` reflects the same backoff the service uses
	 * (max 3, exponential), so the row cannot promise an automatic restart that was already given up on.
	 */
	readonly engineFault?: { readonly message: string; readonly retrying: boolean; readonly attempts: number };
	/**
	 * The manager's session list: a projection of IPulseAISessionStore, i.e. the same rows the
	 * workbench's own Agent Sessions list is fed. Absent means "the engine has not named a session
	 * yet", which the manager paints as a designed empty state; an empty array would be a claim
	 * that the user has no sessions, which nobody measured.
	 */
	readonly sessions?: readonly PulseAISessionRow[];
	readonly draft: string;
	readonly history: readonly {
		readonly userMessage?: string;
		readonly assistantText: string;
		readonly reasoning?: string;
		readonly tools: readonly PulseAIToolView[];
		readonly subAgents: readonly PulseAISubAgentView[];
		readonly turnOutcome: 'idle' | 'running' | 'completed' | 'cancelled' | 'failed';
		readonly plan: readonly string[];
	}[];
}

export interface PulseAIRenderHost {
	setDraft(value: string): void;
	setMode(mode: PulseExecutionMode): void;
	submitPrompt(text: string): void;
	cancel(): void;
	steer(text: string): void;
	replyToSafety(toolId: string, approved: boolean, alwaysAllow?: boolean): void;
	openDiff(toolId: string): void;
	revealFile(resource: string): void;
	restoreCheckpoint(hash: string): void;
	retryEngine(): void;
	selectWorkspace(uri: string): void;
	openFolder(): void;
	openEngineSettings(): void;
	openManager(): void;
}

export interface PulseAIRenderMount extends IDisposable {
	update(model: PulseAIRenderModel): void;
}

type Child = Node | string | undefined | false;

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, ...children: Child[]): HTMLElementTagNameMap[K] {
	const node = document.createElement(tag);
	if (className) { node.className = className; }
	for (const child of children) {
		if (typeof child === 'string') { node.append(document.createTextNode(child)); }
		else if (child) { node.append(child); }
	}
	return node;
}

/**
 * A row glyph. Hermes draws solid SVG for the names `pulseAIIcons.ts` covers and the outline
 * codicon font for everything else, because a font glyph has no fillable region -- the same
 * rule, keyed by the same names, so a row here shows the glyph the webview resolves.
 */
function icon(name: string): HTMLElement {
	return renderToolIcon(name);
}

function button(label: string, className: string, action: () => void, iconName?: string): HTMLButtonElement {
	const node = element('button', className, iconName ? icon(iconName) : undefined, label);
	node.type = 'button';
	node.addEventListener('click', action);
	return node;
}

function record(value: unknown): Readonly<Record<string, unknown>> | undefined {
	return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Readonly<Record<string, unknown>> : undefined;
}

function firstString(source: unknown, keys: readonly string[]): string | undefined {
	const value = record(source);
	for (const key of keys) {
		if (typeof value?.[key] === 'string' && value[key]) { return value[key] as string; }
		if (typeof value?.[key] === 'number') { return String(value[key]); }
	}
	return undefined;
}

function displayTarget(tool: PulseAIToolView): string {
	return firstString(tool.arguments, ['path', 'file_path', 'resource', 'command', 'query', 'url', 'goal', 'target']) ?? tool.name;
}

function boundedText(value: unknown, max = 12_000): string {
	let text: string;
	if (typeof value === 'string') { text = value; }
	else {
		try { text = JSON.stringify(value ?? {}, undefined, 2); }
		catch { text = String(value); }
	}
	if (text.length <= max) { return text; }
	return `... ${text.length - max} earlier characters omitted ...\n${text.slice(-max)}`;
}

function resultOutput(tool: PulseAIToolView): string {
	const value = record(tool.result);
	const parts = [value?.output, value?.stdout, value?.stderr].filter(part => typeof part === 'string' && part.length > 0) as string[];
	return boundedText(parts.length ? parts.join(parts.length > 1 ? '\n' : '') : tool.result);
}

function stateLabel(state: PulseAIToolState): string {
	if (state === 'passed') { return 'Passed'; }
	if (state === 'failed') { return 'Failed'; }
	if (state === 'approval') { return 'Approval'; }
	if (state === 'running') { return 'Running'; }
	return 'Queued';
}

function statusGlyph(state: PulseAIToolState): HTMLElement {
	if (state === 'running') { return element('span', 'pulseai-mini-spinner'); }
	const name = state === 'passed' ? 'pass-filled' : state === 'failed' ? 'error' : state === 'approval' ? 'shield' : 'circle-outline';
	return icon(name);
}

function labeledPayload(label: string, value: unknown): HTMLElement {
	return element('div', 'pulseai-tool-field', element('span', 'pulseai-tool-field-label', label), element('pre', 'pulseai-tool-pre', boundedText(value)));
}

function terminalBody(tool: PulseAIToolView, host: PulseAIRenderHost): HTMLElement {
	const args = record(tool.arguments);
	const result = record(tool.result);
	const command = firstString(args, ['command', 'script']) ?? 'Command details unavailable';
	const output = resultOutput(tool);
	const exit = firstString(result, ['exitCode', 'exit_code', 'status', 'code']) ?? (tool.state === 'running' ? 'running' : 'unknown');
	const duration = tool.duration ?? firstString(result, ['duration', 'elapsed']) ?? '\u2014';
	const body = element('div', 'pulseai-tool-body pulseai-terminal-body');
	body.append(
		element('div', 'pulseai-terminal-command', element('span', 'pulseai-terminal-prompt', '$'), element('code', undefined, command)),
		element('pre', 'pulseai-terminal-output', output || (tool.state === 'running' ? 'Waiting for output...' : 'No captured output')),
		element('div', 'pulseai-terminal-result', element('span', `pulseai-tool-state is-${tool.state}`, stateLabel(tool.state)), element('span', undefined, `exit ${exit}`), element('span', undefined, duration)),
	);
	const actions = element('div', 'pulseai-tool-actions');
	actions.append(button('Copy command', 'pulseai-link-button', () => void navigator.clipboard?.writeText(command), 'copy'));
	const cwd = firstString(args, ['cwd', 'path']);
	if (cwd) { actions.append(button('Reveal location', 'pulseai-link-button', () => host.revealFile(cwd), 'go-to-file')); }
	body.append(actions);
	return body;
}

function toolFields(rows: readonly (readonly [string, string])[]): HTMLElement {
	const wrap = element('div', 'pulseai-tool-fields');
	for (const [k, v] of rows) {
		const row = element('div', 'pulseai-tool-field-row', element('span', 'pulseai-tool-field-key', k), element('code', 'pulseai-tool-field-val', v));
		wrap.append(row);
	}
	return wrap;
}
function familyBody(tool: PulseAIToolView, host: PulseAIRenderHost): HTMLElement {
	const presentation = pulseAIToolPresentation(tool.name);
	if (presentation.family === 'terminal' || presentation.family === 'process') {
		return terminalBody(tool, host);
	}
	const args = record(tool.arguments);
	const result = record(tool.result);
	const body = element('div', `pulseai-tool-body pulseai-family-${presentation.family}`);
	body.dataset.rendererFamily = presentation.family;
	const target = displayTarget(tool);
	if (presentation.family === 'file-read') {
		const lines = firstString(result, ['lines', 'line_count']) ?? firstString(result, ['content'])?.split('\n').length?.toString() ?? '—';
		body.append(toolFields([['Path', target], ['Lines', lines], ['Encoding', 'UTF-8']]));
		const content = firstString(result, ['content']) ?? boundedText(tool.result, 800);
		body.append(element('pre', 'pulseai-tool-pre pulseai-code-preview', content.slice(0, 800)));
		body.append(element('div', 'pulseai-tool-actions', button('Open file', 'pulseai-link-button', () => host.revealFile(target), 'go-to-file'), button('Copy path', 'pulseai-link-button', () => void navigator.clipboard?.writeText(target), 'copy')));
	} else if (presentation.family === 'file-write') {
		const diff = firstString(result, ['diff']) ?? boundedText(result?.diff ?? tool.result, 600);
		// Counted from the diff that is actually here. The fallback here used to be a
		// literal invented line count (twelve added, four removed) printed whenever the
		// engine sent no `change` field -- a number the user could not tell apart from
		// a measurement. Absent data now renders as absent.
		const stats = diffStats(diff);
		const rows: [string, string][] = [['File', target], ['Change', stats ? `+${stats.added} −${stats.removed}` : (firstString(result, ['change']) ?? '—')]];
		// 'syntax valid' was a second always-true row; only surface a receipt the
		// tool actually reported.
		const receipt = firstString(result, ['receipt', 'syntax']);
		if (receipt) { rows.push(['Receipt', receipt]); }
		body.append(toolFields(rows));
		body.append(diffPreview(diff));
		body.append(element('div', 'pulseai-tool-actions', button('Open native diff', 'pulseai-link-button', () => host.openDiff(tool.id), 'diff'), button('Reveal file', 'pulseai-link-button', () => host.revealFile(target), 'go-to-file')));
	} else if (presentation.family === 'search') {
		body.append(toolFields([['Query', target], ['Scope', 'workspace'], ['Matches', firstString(result, ['matches', 'count']) ?? '—']]));
		const matches = result?.matches ?? result?.results;
		if (Array.isArray(matches) && matches.length) {
			const list = element('div', 'pulseai-search-results');
			for (const m of matches.slice(0, 5)) list.append(element('div', 'pulseai-search-row', element('code', undefined, typeof m === 'string' ? m : boundedText(m, 80)), element('span', undefined, '')));
			body.append(list);
		} else {
			body.append(element('pre', 'pulseai-tool-pre', boundedText(result ?? tool.arguments, 500)));
		}
		body.append(element('div', 'pulseai-tool-actions', button('Open Search', 'pulseai-link-button', () => host.revealFile(target), 'search')));
	} else if (presentation.family === 'verification') {
		body.append(element('div', 'pulseai-tool-checks',
			element('div', undefined, icon('pass-filled'), element('span', undefined, 'Typecheck'), element('strong', undefined, tool.state === 'passed' ? 'passed' : tool.state === 'running' ? 'running' : 'queued')),
			element('div', undefined, tool.state === 'running' ? element('span', 'pulseai-mini-spinner') : icon('circle-outline'), element('span', undefined, 'Browser callback'), element('strong', undefined, tool.state === 'passed' ? 'passed' : tool.state === 'running' ? 'running' : 'queued')),
			element('div', undefined, icon('circle-outline'), element('span', undefined, 'Destination assertion'), element('strong', undefined, 'queued')),
		));
		body.append(element('div', 'pulseai-tool-actions', button('Open evidence', 'pulseai-link-button', () => void 0, 'beaker')));
	} else if (presentation.family === 'web') {
		body.append(toolFields([['URL', target], ['Status', firstString(result, ['status']) ?? '200 OK'], ['Received', firstString(result, ['size']) ?? '—']]));
		body.append(element('pre', 'pulseai-tool-pre', boundedText(result ?? tool.arguments, 500)));
		body.append(element('div', 'pulseai-tool-actions', button('Open source', 'pulseai-link-button', () => host.revealFile(target), 'link'), button('Copy URL', 'pulseai-link-button', () => void navigator.clipboard?.writeText(target), 'copy')));
	} else if (presentation.family === 'browser') {
		body.append(toolFields([['Page', firstString(args, ['page']) ?? '—'], ['URL', target], ['Viewport', '1280 × 800']]));
		body.append(element('div', 'pulseai-browser-snapshot', element('div', undefined, element('span', undefined, 'document'), element('code', undefined, boundedText(result, 120).slice(0, 80)))));
		body.append(element('div', 'pulseai-tool-actions', button('Open screenshot', 'pulseai-link-button', () => host.revealFile(target), 'device-camera'), button('Open browser', 'pulseai-link-button', () => host.revealFile(target), 'browser')));
	} else if (presentation.family === 'session') {
		body.append(toolFields([['Query', target], ['Sessions', '2'], ['Model calls', '0']]));
		body.append(element('pre', 'pulseai-tool-pre', boundedText(result ?? tool.arguments, 400)));
	} else if (presentation.family === 'subagent') {
		body.append(toolFields([['Goal', target], ['Mode', firstString(args, ['mode']) ?? 'research'], ['Children', '2']]));
		body.append(element('div', 'pulseai-child-tool-list', element('div', undefined, icon('check'), element('span', undefined, 'Search code'), element('code', undefined, '3 matches'))));
		body.append(element('div', 'pulseai-tool-actions', button('Open sub-agent tab', 'pulseai-link-button', () => void 0, 'organization'), button('Cancel', 'pulseai-link-button', () => void 0, 'debug-stop')));
	} else if (presentation.family === 'code' || presentation.family === 'scaffold') {
		body.append(toolFields([['Runtime', 'Python 3.14'], ['Status', stateLabel(tool.state)]]));
		body.append(element('pre', 'pulseai-tool-pre pulseai-terminal-output', boundedText(result ?? tool.arguments, 600).slice(0, 700)));
	} else {
		body.append(labeledPayload('Details', { arguments: tool.arguments, result: tool.result }));
	}
	const fileTarget = firstString(tool.arguments, ['path', 'file_path', 'resource']);
	if (fileTarget && presentation.family !== 'file-read' && presentation.family !== 'file-write') {
		if (!body.querySelector('.pulseai-tool-actions')) body.append(element('div', 'pulseai-tool-actions', button('Open file', 'pulseai-link-button', () => host.revealFile(fileTarget), 'go-to-file')));
	}
	return body;
}

function toolRow(tool: PulseAIToolView, host: PulseAIRenderHost, openTools: Set<string>): HTMLDetailsElement {
	const presentation = pulseAIToolPresentation(tool.name);
	const isPending = tool.state === 'running' || tool.state === 'queued';
	const details = element('details', `pulseai-tool-row is-${tool.state}`);
	details.dataset.component = 'tool-trigger';
	details.dataset.toolId = tool.id;
	details.dataset.toolName = tool.name;
	const shouldDefaultOpen = presentation.defaultOpen === 'always' || (presentation.defaultOpen === 'running' && (tool.state === 'running' || tool.state === 'approval'));
	details.open = openTools.has(tool.id) || shouldDefaultOpen;

	const titleSpan = element('strong', isPending ? 'pulseai-shimmer' : undefined, presentation.title);
	const summary = element('summary', 'pulseai-tool-summary',
		statusGlyph(tool.state),
		icon(presentation.icon),
		titleSpan,
		element('span', 'pulseai-tool-target', displayTarget(tool)),
		tool.duration ? element('span', 'pulseai-tool-duration', tool.duration) : undefined,
		element('span', `pulseai-tool-state is-${tool.state}`, stateLabel(tool.state)),
		isPending ? undefined : icon('chevron-right'),
	);
	details.append(summary, familyBody(tool, host));
	details.addEventListener('toggle', () => details.open ? openTools.add(tool.id) : openTools.delete(tool.id));
	return details;
}

/**
 * Cards and runs, in order -- the same split the CopilotKit webview renders.
 *
 * A run of consecutive activity calls folds into one summary line, identified by its
 * FIRST tool call id (never by position, or a live stream would re-key the row every
 * time a call lands) and disclosed under the same key so opening one survives a
 * re-render. Anything that draws its own surface -- a file edit's diff, a question --
 * stays a card in place. `live` comes from the caller: a settled turn whose last call
 * never got a result must still read as finished, not as work in progress.
 */
function toolSection(tools: readonly PulseAIToolView[], host: PulseAIRenderHost, openTools: Set<string>, live: boolean): HTMLElement {
	const section = element('section', 'pulseai-tool-list');
	section.dataset.component = 'tool-list';
	section.append(element('div', 'pulseai-section-heading',
		element('span', undefined, 'Actions'),
		element('span', 'pulseai-section-count', String(tools.length)),
	));

	for (const group of splitRunGroups(tools)) {
		if (group.kind === 'card') {
			section.append(toolRow(group.tool, host, openTools));
			continue;
		}
		const runTools = group.tools;
		const key = runTools[0]?.id ?? `run-${group.start}`;
		const runLive = live && runTools.some(tool => tool.state === 'running' || tool.state === 'queued');
		const details = element('details', `pulseai-tool-run${runLive ? ' is-live' : ''}`) as HTMLDetailsElement;
		details.dataset.component = 'tool-run';
		details.dataset.runKey = key;
		details.open = runLive || openTools.has(key);
		details.addEventListener('toggle', () => {
			if (details.open) { openTools.add(key); } else { openTools.delete(key); }
		});
		const summary = element('summary', 'pulseai-tool-run-summary',
			runLive ? element('span', 'pulseai-mini-spinner') : icon('tools'),
			element('span', 'pulseai-tool-run-text', summarizeToolRun(runTools, runLive, tool => compactTarget(displayTarget(tool)) ?? tool.name)),
			element('span', 'pulseai-tool-run-count', String(runTools.length)),
		);
		details.append(summary);
		const body = element('div', 'pulseai-tool-run-body');
		for (const tool of runTools) { body.append(toolRow(tool, host, openTools)); }
		details.append(body);
		section.append(details);
	}
	return section;
}


function engineStatus(model: PulseAIRenderModel): HTMLElement {
	const state = model.engineState;
	const tone = state === 'ready' ? 'ready' : state === 'starting' ? 'running' : state === 'crashed' || state === 'degraded' ? 'failed' : 'idle';
	return element('span', `pulseai-engine-status is-${tone}`, element('span', 'pulseai-status-dot'), state === 'ready' ? 'Pulse ready' : `Engine ${state}`);
}

function planStrip(model: PulseAIRenderModel, open: boolean | undefined, onToggle: (open: boolean) => void): HTMLElement | undefined {
	if (!model.plan.length) { return undefined; }
	const details = element('details', 'pulseai-plan-strip') as HTMLDetailsElement;
	details.dataset.component = 'plan-strip';
	details.open = open ?? model.running;
	details.addEventListener('toggle', () => onToggle(details.open));
	const summary = element('summary', 'pulseai-plan-strip-summary',
		icon('list-ordered'),
		element('strong', undefined, 'Plan'),
		element('span', undefined, `${model.plan.length} steps`),
		model.running ? element('span', 'pulseai-plan-strip-state', element('span', 'pulseai-mini-spinner'), 'In progress') : undefined,
		icon('chevron-down'),
	);
	const list = element('ol', 'pulseai-plan-strip-list');
	for (const [index, step] of model.plan.entries()) {
		list.append(element('li', index === 0 && model.running ? 'is-active' : undefined,
			index === 0 && model.running ? element('span', 'pulseai-mini-spinner') : icon('circle-outline'),
			element('span', undefined, step),
		));
	}
	details.append(summary, list);
	return details;
}

/**
 * The tail activity row, with the timers it needs to behave.
 *
 * It is mount-scoped state, not model data: the row must survive every re-render of a streaming
 * turn while holding (a) the signature of the last visible progress, so a quiet spell is timed
 * from the moment the turn LAST showed something rather than from whenever this row mounted, and
 * (b) the reveal delay, so a tool whose arguments land in three frames never gets to flash a
 * label down the column. `tick` asks the mount to repaint, which is what advances the seconds.
 */
const thoughtKey = (model: PulseAIRenderModel): string => `thought:${model.sessionId ?? 'session'}`;

function createActivityState(tick: () => void) {
	let lastSignature = '';
	let quietSince: number | undefined;
	let verb = '';
	let revealed = false;
	let quietTimer: ReturnType<typeof setTimeout> | undefined;
	let revealTimer: ReturnType<typeof setTimeout> | undefined;
	let ticker: ReturnType<typeof setInterval> | undefined;

	return {
		sync(model: PulseAIRenderModel): void {
			const parts = activityParts(model);
			// Thinking is "active" while a thought is the newest thing the turn has produced.
			if (model.running && parts.at(-1)?.type === 'reasoning') { elapsedFor(thoughtKey(model), Date.now()); }
			else { closeMeasurement(thoughtKey(model), Date.now()); }
			const signature = activitySignature(parts);
			if (signature !== lastSignature) {
				lastSignature = signature;
				quietSince = undefined;
				if (quietTimer !== undefined) { clearTimeout(quietTimer); quietTimer = undefined; }
				if (model.running) {
					quietTimer = setTimeout(() => { quietSince = Date.now(); tick(); }, TURN_QUIET_S * 1000);
				}
			}
				const name = draftingToolName(model.tools);
			const next = name && !toolNarratesWait(parts) ? toolPresentVerb(name) : '';
			if (next !== verb) {
				verb = next;
				revealed = false;
				if (revealTimer !== undefined) { clearTimeout(revealTimer); revealTimer = undefined; }
				if (verb) { revealTimer = setTimeout(() => { revealed = true; tick(); }, DRAFTING_REVEAL_MS); }
			}
			if (model.running && ticker === undefined) { ticker = setInterval(tick, 1000); }
			if (!model.running && ticker !== undefined) { clearInterval(ticker); ticker = undefined; }
		},
		/**
		 * The row for this model, or nothing at all. Two shapes, one markup: before the tail
		 * message has produced anything this is the pre-first-token indicator counting from the
		 * turn's start; after it, it is the gap indicator counting from the last visible
		 * progress. Same classes either way, so the column reads as one continuous scaffolding
		 * instead of two competing widgets.
		 *
		 * It stays silent when a tool row is already narrating the wait (that row carries its
		 * own timer, and a second spinner would count the same seconds twice), and while the turn
		 * is paused on a question the user has not answered -- that is not the agent working.
		 */
		row(model: PulseAIRenderModel): HTMLElement | undefined {
			const parts = activityParts(model);
			const hint = model.cancelRequested ? 'Stopping safely' : statusHintLabel(model.compacting, verb, revealed);
			const slot = activityRowMode({
				parts,
				working: model.running,
				awaitingInput: model.approval !== undefined,
				toolNarrating: toolNarratesWait(parts),
				hint,
				quietSince,
			});
			if (!slot) { return undefined; }
			const seconds = elapsedSeconds(Date.now(), activityOrigin({ compacting: model.compacting, turnStartedAt: model.turnStartedAt, quietSince }));
			const row = element('div', 'pulseai-scaffold-status');
			row.dataset.conversationScaffold = '';
			row.dataset.slot = slot;
			row.setAttribute('aria-label', hint || UNNAMED_WAIT_LABEL);
			row.setAttribute('aria-live', 'polite');
			row.setAttribute('role', 'status');
			const breathe = element('span', 'pulseai-scaffold-pulse');
			breathe.setAttribute('aria-hidden', 'true');
			const meta = element('span', 'pulseai-scaffold-meta', element('span', undefined, formatElapsed(seconds)));
			row.append(breathe, ...(hint ? [element('span', 'pulseai-shimmer pulseai-scaffold-hint', hint)] : []), meta);
			return row;
		},
		/**
		 * How long the CURRENT turn's thinking ran, once it has stopped running. The measurement
		 * is armed while the last thing the turn produced is a thought and closed the moment the
		 * turn moves on, so the number survives every repaint of the row that watched it.
		 */
		thoughtSeconds(model: PulseAIRenderModel): number | undefined {
			return measuredDuration(thoughtKey(model));
		},
		dispose(): void {
			if (quietTimer !== undefined) { clearTimeout(quietTimer); quietTimer = undefined; }
			if (revealTimer !== undefined) { clearTimeout(revealTimer); revealTimer = undefined; }
			if (ticker !== undefined) { clearInterval(ticker); ticker = undefined; }
		},
	};
}


/**
 * What the model thought, behind a row -- Hermes' affordance, not a paragraph dumped into the
 * bubble. `think` receipts arrive as a `brain`-glyphed tool row upstream and streamed reasoning
 * folds into the same disclosure, so one component covers both. No leading chevron: the caret
 * sits to the RIGHT of the label and only the label is the hit target, which is why this is a
 * button-shaped summary over a content-width pill rather than a full-width bar.
 */
function thinkingBlock(reasoning: string, openTools: Set<string>, live: boolean, seconds?: number): HTMLElement {
	const key = 'thought';
	const details = element('details', 'pulseai-thought-row') as HTMLDetailsElement;
	details.dataset.component = 'disclosure';
	details.dataset.disclosureKey = key;
	// Open while the thinking is happening, so you can read it; folded afterwards, so a long
	// turn does not leave a wall of prose above the answer.
	details.open = live || openTools.has(key);
	details.addEventListener('toggle', () => {
		if (details.open) { openTools.add(key); } else { openTools.delete(key); }
	});
	details.append(
		element('summary', 'pulseai-disclosure-row',
			element('span', 'pulseai-disclosure-stack',
				icon('brain'),
				element('strong', live ? 'pulseai-shimmer' : undefined, live ? 'Thinking' : 'Thought'),
			),
			seconds !== undefined ? element('span', 'pulseai-scaffold-meta', formatElapsed(seconds)) : undefined,
			element('span', 'pulseai-disclosure-caret', '\u25be'),
		),
		element('div', 'pulseai-thought-body', element('p', undefined, reasoning)),
	);
	return details;
}

function transcript(model: PulseAIRenderModel, host: PulseAIRenderHost, openTools: Set<string>, liveThoughtSeconds?: number): HTMLElement {
	const scroll = element('div', 'pulseai-transcript-scroll');
	const lane = element('div', 'pulseai-transcript-lane');
	// History: previous turns (user → agent) preserved wireframe style, no breathing
	for (const turn of model.history) {
		if (turn.userMessage) lane.append(element('div', 'pulseai-user-message', turn.userMessage));
		if (turn.assistantText || turn.reasoning) {
			const response = element('section', 'pulseai-assistant-message');
			response.append(element('div', 'pulseai-assistant-label', icon('pulse'), element('strong', undefined, 'Pulse')));
			if (turn.reasoning) { response.append(thinkingBlock(turn.reasoning, openTools, false)); }
			response.append(element('p', 'pulseai-assistant-copy', turn.assistantText));
			lane.append(response);
		}
		if (turn.tools.length) {
			lane.append(toolSection(turn.tools, host, openTools, false));
		}
		if (turn.subAgents.length) {
			const subAgents = element('section', 'pulseai-subagent-list');
			subAgents.append(element('div', 'pulseai-section-heading', element('span', undefined, 'Sub-Agents'), element('span', 'pulseai-section-count', String(turn.subAgents.length))));
			for (const subAgent of turn.subAgents) {
				const row = element('div', `pulseai-subagent-row is-${subAgent.state}`, element('span', undefined, ''), element('span', 'pulseai-subagent-goal', subAgent.goal ?? 'Sub-agent task'), element('span', `pulseai-subagent-state is-${subAgent.state}`, subAgent.state));
				if (subAgent.duration) row.append(element('span', 'pulseai-subagent-duration', subAgent.duration));
				subAgents.append(row);
			}
			lane.append(subAgents);
		}
		if (turn.turnOutcome === 'completed' || turn.turnOutcome === 'cancelled' || turn.turnOutcome === 'failed') {
			const label = turn.turnOutcome === 'completed' ? 'Run completed' : turn.turnOutcome === 'cancelled' ? 'Run cancelled' : 'Run failed';
			const iconName = turn.turnOutcome === 'completed' ? 'pass-filled' : turn.turnOutcome === 'cancelled' ? 'circle-slash' : 'error';
			lane.append(element('div', `pulseai-turn-receipt is-${turn.turnOutcome}`, icon(iconName), element('span', undefined, label)));
		}
	}
	// Current turn (breathing when running)
	if (model.userMessage) {
		lane.append(element('div', 'pulseai-user-message', model.userMessage));
	}
	if (model.assistantText || model.reasoning || model.running) {
		const response = element('section', `pulseai-assistant-message${model.running ? ' pulseai-breathing-edge is-streaming' : ''}`);
		response.dataset.component = 'session-turn';
		response.append(element('div', 'pulseai-assistant-label', icon('pulse'), element('strong', undefined, 'Pulse'), model.running ? element('span', 'pulseai-stream-label', model.cancelRequested ? 'Stopping.' : 'Working') : undefined));
		if (model.reasoning) { response.append(thinkingBlock(model.reasoning, openTools, model.running, liveThoughtSeconds)); }
		// No assistant text means there is nothing to narrate. The line used to fall back to a sentence
		// claiming the agent was inspecting the workspace, which the turn had never done -- so a run that
		// died on a provider error still printed confident progress. The spinner and the 'Working' label
		// already say the only true thing: the turn is open.
		if (model.assistantText) {
			const copy = element('p', 'pulseai-assistant-copy', model.assistantText);
			copy.dataset.slot = 'session-turn-content';
			response.append(copy);
		}
		lane.append(response);
	}
	if (model.tools.length) {
		lane.append(toolSection(model.tools, host, openTools, model.running));
	}
	if (model.subAgents.length) {
		const subAgents = element('section', 'pulseai-subagent-list');
		subAgents.append(element('div', 'pulseai-section-heading', element('span', undefined, 'Sub-Agents'), element('span', 'pulseai-section-count', String(model.subAgents.length))));
		for (const subAgent of model.subAgents) {
			const state = subAgent.state;
			const row = element('div', `pulseai-subagent-row is-${state}`,
				element('span', 'pulseai-mini-spinner', undefined),
				element('span', 'pulseai-subagent-goal', subAgent.goal ?? 'Sub-agent task'),
				element('span', `pulseai-subagent-state is-${state}`, state),
			);
			if (subAgent.duration) {
				row.append(element('span', 'pulseai-subagent-duration', subAgent.duration));
			}
			if (subAgent.result) {
				row.append(element('div', 'pulseai-subagent-result', element('pre', 'pulseai-tool-pre', JSON.stringify(subAgent.result, null, 2).slice(0, 500))));
			}
			subAgents.append(row);
		}
		lane.append(subAgents);
	}
	if (model.turnOutcome === 'completed' || model.turnOutcome === 'cancelled' || model.turnOutcome === 'failed') {
		const label = model.turnOutcome === 'completed' ? 'Run completed' : model.turnOutcome === 'cancelled' ? 'Run cancelled' : 'Run failed';
		const iconName = model.turnOutcome === 'completed' ? 'pass-filled' : model.turnOutcome === 'cancelled' ? 'circle-slash' : 'error';
		lane.append(element('div', `pulseai-turn-receipt is-${model.turnOutcome}`, icon(iconName), element('span', undefined, label)));
	}
	if (model.engineFault) {
		const fault = model.engineFault;
		const followUp = fault.retrying
			? ` Retrying automatically (attempt ${fault.attempts + 1} of 3).`
			: ' Pulse stopped retrying on its own.';
		lane.append(element('div', 'pulseai-error-row is-engine-fault', icon('error'),
			element('span', undefined, fault.message + followUp),
			button('Retry engine', 'pulseai-link-button', host.retryEngine),
		));
	}
	if (model.error) {
		const setup = model.engineSetupError;
		lane.append(element('div', 'pulseai-error-row', icon(setup ? 'settings-gear' : 'warning'),
			element('span', undefined, setup ? `Pulse engine setup: ${model.error}` : model.error),
			setup
				? button('Open Settings', 'pulseai-link-button', host.openEngineSettings, 'settings-gear')
				: button('Retry', 'pulseai-link-button', host.retryEngine),
		));
	}
	scroll.append(lane);
	return scroll;
}

const STARTER_PROMPTS: readonly string[] = [
	'Review this workspace and tell me what it does',
	'Find where the safety approval flow lives and explain it',
	'Run the project tests and fix the first failure',
];

/**
 * Shown only when there is genuinely nothing to render and nothing is broken: engine
 * up, workspace chosen, no turn yet. Setup and workspace-selection states have their
 * own surfaces, and a starter grid layered over them reads as a bug.
 */
function emptyState(model: PulseAIRenderModel, host: PulseAIRenderHost): HTMLElement | undefined {
	if (model.running || model.history.length || model.userMessage || model.assistantText || model.tools.length) { return undefined; }
	if (model.engineSetupError || model.noWorkspace || model.workspaceSelectionRequired) { return undefined; }
	const wrap = element('section', 'pulseai-empty-state');
	wrap.dataset.component = 'empty-state';
	wrap.append(
		element('div', 'pulseai-section-heading', element('span', undefined, 'Pulse Agent')),
		element('p', 'pulseai-empty-copy', 'Ask for a change, or start from one of these. Every file write is consent-checked: git can undo it, so it just runs; git cannot, so it asks.'),
	);
	const grid = element('div', 'pulseai-starter-grid');
	for (const prompt of STARTER_PROMPTS) {
		grid.append(button(prompt, 'pulseai-starter-prompt', () => host.submitPrompt(prompt), 'arrow-right'));
	}
	wrap.append(grid);
	return wrap;
}

function approvalDock(model: PulseAIRenderModel, host: PulseAIRenderHost): HTMLElement | undefined {
	if (!model.approval) { return undefined; }
	const approval = model.approval;
	const dock = element('section', 'pulseai-approval-dock');
	dock.dataset.component = 'approval-dock';
	dock.append(
		element('div', 'pulseai-approval-copy', icon('shield'), element('div', undefined, element('strong', undefined, `${pulseAIToolPresentation(approval.name).title} needs approval`), element('span', undefined, displayTarget({ id: approval.toolId, name: approval.name, state: 'approval', arguments: approval.diff })) )),
		element('div', 'pulseai-approval-actions',
			approval.diff ? button('Review change', 'pulseai-button pulseai-button-secondary', () => host.openDiff(approval.toolId), 'diff') : undefined,
			hinted(button('Deny', 'pulseai-button pulseai-button-secondary pulseai-button-deny', () => host.replyToSafety(approval.toolId, false), 'close'),
				'Deny this call. The next write is asked about again.'),
			// The client protocol has carried `always_allow` since the start and the
			// bridge honours it (src/bridge/__main__.py:552 -> EventBus.resolveApproval),
			// but no control ever sent it: every ordinary write re-prompted for the rest
			// of the session, so the grant existed and was unreachable from the UI.
			hinted(button('Allow for session', 'pulseai-button pulseai-button-secondary pulseai-button-allow-session', () => host.replyToSafety(approval.toolId, true, true), 'pass-filled'),
				'Allow, and stop asking for ordinary workspace writes in this session. Secret paths and git-ignored files are still asked every time.'),
			hinted(button('Allow once', 'pulseai-button pulseai-button-primary pulseai-button-allow', () => host.replyToSafety(approval.toolId, true), 'check'),
				'Allow this call only.'),
		),
	);
	return dock;
}

/** A `title` hint for buttons built through `button()`, which has no options bag. */
function hinted<T extends HTMLElement>(control: T, hint: string): T {
	control.title = hint;
	return control;
}

export interface PulseAIDiffStats {
	readonly added: number;
	removed: number;
}

/**
 * Line counts for a unified diff, counted -- not assumed. Returns undefined when the
 * payload carries no +/- body at all, so callers can show '—' instead of a number.
 */
export function diffStats(diff: string | undefined): PulseAIDiffStats | undefined {
	if (!diff) { return undefined; }
	let added = 0;
	let removed = 0;
	for (const line of diff.split('\n')) {
		if (line.startsWith('+++') || line.startsWith('---')) { continue; }
		if (line.startsWith('+')) { added++; }
		else if (line.startsWith('-')) { removed++; }
	}
	return added || removed ? { added, removed } : undefined;
}

/** Lines are clamped for *paint*, never for correctness -- the count says what is hidden. */
const DIFF_PREVIEW_LINE_LIMIT = 40;

function diffPreview(diff: string): HTMLElement {
	const wrap = element('pre', 'pulseai-tool-pre pulseai-diff-preview');
	const lines = (diff || '').split('\n');
	for (const line of lines.slice(0, DIFF_PREVIEW_LINE_LIMIT)) {
		wrap.append(element('div', `pulseai-diff-line ${diffLineClass(line)}`, line.length ? line : ' '));
	}
	if (lines.length > DIFF_PREVIEW_LINE_LIMIT) {
		wrap.append(element('div', 'pulseai-diff-line is-truncated', `… ${lines.length - DIFF_PREVIEW_LINE_LIMIT} more line(s) — 'Open native diff' shows all of it`));
	}
	return wrap;
}

function diffLineClass(line: string): string {
	if (line.startsWith('@@') || line.startsWith('+++') || line.startsWith('---')) { return 'is-meta'; }
	if (line.startsWith('+')) { return 'is-added'; }
	if (line.startsWith('-')) { return 'is-removed'; }
	return 'is-context';
}

const executionModes: readonly { readonly id: PulseExecutionMode; readonly label: string; readonly description: string; readonly icon: string }[] = [
	{ id: 'agent', label: 'Agent', description: 'Build, change, and verify', icon: 'infinity' },
	{ id: 'plan', label: 'Plan', description: 'Design before execution', icon: 'list-ordered' },
	{ id: 'debug', label: 'Debug', description: 'Diagnose, fix, and retest', icon: 'debug-alt' },
	{ id: 'ask', label: 'Ask', description: 'Explain without using tools', icon: 'comment' },
];

function modePicker(model: PulseAIRenderModel, host: PulseAIRenderHost): HTMLElement {
	const selected = executionModes.find(mode => mode.id === model.mode) ?? executionModes[0];
	const details = element('details', 'pulseai-mode-picker') as HTMLDetailsElement;
	const summary = element('summary', 'pulseai-mode-summary', icon(selected.icon), element('span', undefined, selected.label), icon('chevron-down'));
	summary.setAttribute('aria-label', `Execution mode: ${selected.label}`);
	if (model.running) {
		summary.setAttribute('aria-disabled', 'true');
		summary.addEventListener('click', event => event.preventDefault());
	}
	const menu = element('div', 'pulseai-mode-menu');
	menu.setAttribute('role', 'menu');
	menu.setAttribute('aria-label', 'Execution mode');
	for (const mode of executionModes) {
		const item = element('button', mode.id === selected.id ? 'pulseai-mode-option is-selected' : 'pulseai-mode-option',
			icon(mode.icon),
			element('span', 'pulseai-mode-option-copy', element('strong', undefined, mode.label), element('small', undefined, mode.description)),
			mode.id === selected.id ? icon('check') : undefined,
		) as HTMLButtonElement;
		item.type = 'button';
		item.setAttribute('role', 'menuitemradio');
		item.setAttribute('aria-checked', String(mode.id === selected.id));
		item.addEventListener('click', () => {
			details.open = false;
			host.setMode(mode.id);
		});
		menu.append(item);
	}
	details.append(summary, menu);
	return details;
}

function composer(model: PulseAIRenderModel, host: PulseAIRenderHost, manager: boolean): HTMLElement {
	const input = element('textarea', 'pulseai-composer-input') as HTMLTextAreaElement;
	input.rows = manager ? 2 : 3;
	input.placeholder = manager ? 'Steer this agent or add context...' : 'Plan, @ for context, / for commands';
	input.value = model.draft;
	input.addEventListener('input', () => host.setDraft(input.value));
	const inputBlocked = model.noWorkspace || model.workspaceSelectionRequired;
	if (inputBlocked) { input.disabled = true; }
	const submit = () => {
		const value = input.value.trim();
		if (!value) { return; }
		if (manager && model.running) { host.steer(value); }
		else { host.submitPrompt(value); }
	};
	input.addEventListener('keydown', event => {
		if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
	});

	const running = model.running;
	const send = element('button', running ? 'pulseai-send-button pulseai-send-stop' : 'pulseai-send-button') as HTMLButtonElement;
	send.type = 'button';
	send.setAttribute('aria-label', running ? 'Stop' : 'Send');
	send.append(icon(running ? 'debug-pause' : 'arrow-up'));
	send.addEventListener('click', running ? host.cancel : submit);
	if (running && model.cancelRequested) { send.disabled = true; }
	if (inputBlocked) { send.disabled = true; }

	const toolbar = element('div', 'pulseai-composer-toolbar', modePicker(model, host), send);
	const hint = element('div', 'pulseai-composer-hint',
		model.noWorkspace
			? element('span', undefined, model.noWorkspaceHint)
			: model.workspaceSelectionRequired
				? element('span', undefined, 'Select a workspace folder to start a Pulse session.')
				: element('span', undefined, 'Enter to send'),
		element('span', undefined, model.noWorkspace ? '' : 'Shift+Enter for new line'),
	);
	if (model.noWorkspace) {
		hint.append(button('Open Folder', 'pulseai-link-button', host.openFolder, 'folder'));
	}
	return element('footer', 'pulseai-composer', element('div', 'pulseai-composer-box', input, toolbar), hint);
}


/**
 * The Agent chat column: plan, transcript, tail activity row, approvals -- in that order, from
 * one code path.
 *
 * Both surfaces used to assemble this list themselves, and only the pane had the plan strip, the
 * activity row and the empty state. That is how two views of one session drift: the Manager's
 * chat box kept the transcript and quietly dropped everything that tells you the agent is alive.
 * Returning nodes instead of a second copy of the layout is the whole point -- the surfaces
 * cannot disagree now, and the layout pin reads the call sites.
 */
interface PulseAIActivitySurface {
	row(model: PulseAIRenderModel): HTMLElement | undefined;
	thoughtSeconds(model: PulseAIRenderModel): number | undefined;
}

function agentColumn(model: PulseAIRenderModel, host: PulseAIRenderHost, openTools: Set<string>, activity: PulseAIActivitySurface, planOpen: boolean | undefined, setPlanOpen: (open: boolean) => void): HTMLElement[] {
	const nodes: HTMLElement[] = [];
	const plan = planStrip(model, planOpen, setPlanOpen);
	if (plan) { nodes.push(plan); }
	// An empty transcript is a designed surface, not a blank div -- the same rule the ported
	// webview follows (`hermes-ui/components/empty-state.tsx`). Exactly one of the two is
	// mounted, so a first-run view never shows an empty lane under a grid of starters.
	const empty = emptyState(model, host);
	nodes.push(empty ?? transcript(model, host, openTools, activity.thoughtSeconds(model)));
	const working = activity.row(model);
	if (working) { nodes.push(working); }
	const approval = approvalDock(model, host);
	if (approval) { nodes.push(approval); }
	return nodes;
}

function renderAgent(root: HTMLElement, model: PulseAIRenderModel, host: PulseAIRenderHost, openTools: Set<string>, planOpen: boolean | undefined, setPlanOpen: (open: boolean) => void, activity: PulseAIActivitySurface): void {
	const shell = element('div', 'pulseai-agent-shell');
	const header = element('div', 'pulseai-agent-header',
		element('span', 'pulseai-agent-header-title', 'Pulse Agent'),
		button('Manager', 'pulseai-agent-manager-button', () => host.openManager(), 'organization'),
	);
	shell.append(header);
	shell.append(...agentColumn(model, host, openTools, activity, planOpen, setPlanOpen));
	shell.append(composer(model, host, false));
	root.append(shell);
}

function inspector(model: PulseAIRenderModel): HTMLElement {
	const pane = element('aside', 'pulseai-manager-inspector');
	pane.append(element('header', 'pulseai-manager-pane-head', element('div', undefined, element('span', 'pulseai-eyebrow', 'LIVE EVIDENCE'), element('h2', undefined, 'Run inspector'))));
	const plan = element('section', 'pulseai-inspector-section', element('div', 'pulseai-inspector-title', element('span', undefined, 'Plan'), element('strong', undefined, `${model.plan.length} steps`)));
	const list = element('ol', 'pulseai-plan-list');
	for (const [index, step] of model.plan.entries()) { list.append(element('li', index === 0 ? 'is-active' : undefined, index === 0 ? element('span', 'pulseai-mini-spinner') : icon('circle-outline'), element('span', undefined, step))); }
	if (!model.plan.length) { list.append(element('li', 'is-muted', icon('circle-outline'), element('span', undefined, 'Plan appears when the run starts'))); }
	plan.append(list);
	const evidence = element('section', 'pulseai-inspector-section', element('div', 'pulseai-inspector-title', element('span', undefined, 'Verification'), element('strong', undefined, model.verification ?? 'Not started')),
		element('div', 'pulseai-evidence-row', icon(model.verification === 'passed' ? 'pass-filled' : 'circle-outline'), element('span', undefined, model.verification ? `Runtime reported ${model.verification}` : 'No evidence receipt yet')));
	const capabilities = element('section', 'pulseai-inspector-section', element('div', 'pulseai-inspector-title', element('span', undefined, 'Workbench capabilities'), element('strong', undefined, `${model.capabilitySummary.available}/${model.capabilitySummary.total}`)),
		element('div', 'pulseai-evidence-row', icon('plug'), element('span', undefined, `${model.capabilitySummary.available} available · ${model.capabilitySummary.blocked} blocked`)));
	const usage = element('section', 'pulseai-inspector-section pulseai-usage', element('div', 'pulseai-inspector-title', element('span', undefined, 'Usage'), element('strong', undefined, model.telemetry.cost === undefined ? '\u2014' : `$${model.telemetry.cost.toFixed(4)}`)),
		element('div', 'pulseai-usage-grid', element('span', undefined, 'Input'), element('strong', undefined, String(model.telemetry.input ?? 0)), element('span', undefined, 'Cache'), element('strong', undefined, String(model.telemetry.cache ?? 0)), element('span', undefined, 'Output'), element('strong', undefined, String(model.telemetry.output ?? 0))));
	pane.append(plan, evidence, capabilities, usage);
	return pane;
}

/**
 * The manager's session rows, drawn from the workbench's own session vocabulary: the lifecycle is
 * `ChatSessionStatus`'s (via the projection), the elapsed text follows the fork's list rules, and
 * the line an in-flight session shows is produced by `summarizeToolRun` -- the same call the
 * transcript lane makes, so one action can never read differently in the two surfaces.
 *
 * No row is invented here and none can be renamed: this is a render of `model.sessions`.
 */
function sessionList(model: PulseAIRenderModel): HTMLElement {
	const group = element('div', 'pulseai-workspace-group');
	group.append(element('div', 'pulseai-workspace-title', icon('chevron-down'), icon('folder'), element('strong', undefined, model.workspaceLabel)));
	const rows = model.sessions;
	if (!rows || !rows.length) {
		group.append(element('div', 'pulseai-session-row is-empty',
			element('span', 'pulseai-status-dot is-idle'),
			element('div', undefined, element('strong', undefined, 'No session yet'), element('span', undefined, 'A run appears here the moment the engine names one')),
		));
		return group;
	}
	const narration = summarizeToolRun(model.tools, model.running, tool => compactTarget(displayTarget(tool)) ?? tool.name);
	for (const row of rows) {
		const dot = row.statusName === 'inProgress' ? 'running'
			: row.statusName === 'needsInput' ? 'waiting'
				: row.statusName === 'failed' ? 'failed' : 'ready';
		const detail = row.isActive && narration ? narration
			: row.statusName === 'needsInput' ? 'Waiting for approval'
				: row.statusName === 'failed' ? 'Run failed'
					: row.changes ? `${row.changes.files} file(s) +${row.changes.insertions} −${row.changes.deletions}`
						: row.statusName === 'completed' ? 'Finished' : row.description;
		const state = row.elapsedLabel || (row.isActive ? (model.running ? 'Working…' : 'Ready') : '');
		const classes = ['pulseai-session-row'];
		if (row.isActive) { classes.push('is-active'); }
		if (row.statusName === 'needsInput') { classes.push('is-needs-input'); }
		if (row.needsAttention) { classes.push('is-attention'); }
		const button = element('button', classes.join(' '),
			element('span', `pulseai-status-dot is-${dot}`),
			element('div', undefined, element('strong', undefined, row.label), element('span', 'pulseai-session-detail', detail)),
			element('span', 'pulseai-session-state', state),
		) as HTMLButtonElement;
		// Steering another session needs `session_resume`, which this build does not wire yet, so
		// the row tells the truth instead of pretending: only the open one is actionable.
		button.type = 'button';
		button.disabled = !row.isActive;
		button.title = row.isActive ? 'Open in this panel' : 'Select it from the engine to steer it';
		group.append(button);
	}
	return group;
}

function renderManager(root: HTMLElement, model: PulseAIRenderModel, host: PulseAIRenderHost, openTools: Set<string>, activity: PulseAIActivitySurface, planOpen: boolean | undefined, setPlanOpen: (open: boolean) => void): void {
	const shell = element('div', 'pulseai-manager-shell');
	const sidebar = element('aside', 'pulseai-manager-sidebar',
		element('header', 'pulseai-manager-pane-head', element('div', undefined, element('span', 'pulseai-eyebrow', 'CONTROL PLANE'), element('h2', undefined, 'Workspaces')), button('', 'pulseai-icon-button', () => undefined, 'add')),
		element('div', 'pulseai-manager-search', icon('search'), element('span', undefined, 'Find workspace or agent')),
		sessionList(model),
		element('footer', 'pulseai-manager-sidebar-footer', icon('organization'), element('span', undefined, model.sessions?.length ? `${model.sessions.length} session(s) remembered · ${model.running ? '1 running' : 'none running'}` : 'No session yet')),
	);
	const main = element('main', 'pulseai-manager-main');
	main.append(
		element('header', 'pulseai-manager-titlebar', element('div', undefined, element('div', 'pulseai-manager-breadcrumb', model.workspaceLabel, ' / ', model.sessionId?.slice(0, 12) ?? 'new-session'), element('h1', undefined, model.userMessage || 'Pulse Manager')), engineStatus(model)),
		element('nav', 'pulseai-manager-tabs', element('button', 'is-active', icon('comment-discussion'), 'Session'), element('button', undefined, icon('terminal'), `Tools ${model.tools.length}`), element('button', undefined, icon('diff'), 'Changes')),
		...agentColumn(model, host, openTools, activity, planOpen, setPlanOpen),
		composer(model, host, true),
	);
	shell.append(sidebar, main, inspector(model));
	root.append(shell);
}

export function mountPulseAIRenderer(root: HTMLElement, surface: PulseAISurface, host: PulseAIRenderHost): PulseAIRenderMount {
	const openTools = new Set<string>();
	let planOpen: boolean | undefined;
	let planSession: string | undefined;
	let disposed = false;
	let lastModel: PulseAIRenderModel | undefined;
	// The activity row's timers outlive individual renders; a tick repaints from the last model,
	// which is what makes the seconds move while the engine is quiet.
	const activity = createActivityState(() => { if (!disposed) { tick(); } });
	const tick = (): void => { if (!disposed && lastModel) { paint(lastModel); } };
		const paint = (model: PulseAIRenderModel): void => {
			if (model.sessionId !== planSession) {
				planSession = model.sessionId;
				planOpen = undefined;
			}
			const previousScroll = root.querySelector<HTMLElement>('.pulseai-transcript-scroll');
			const scrollTop = previousScroll?.scrollTop ?? 0;
			const wasNearBottom = !previousScroll || previousScroll.scrollHeight - previousScroll.scrollTop - previousScroll.clientHeight < 32;
			const activeElement = document.activeElement;
			const activeComposer = root.contains(activeElement) && activeElement instanceof HTMLTextAreaElement ? activeElement : undefined;
			const selectionStart = activeComposer?.selectionStart;
			const selectionEnd = activeComposer?.selectionEnd;
			root.replaceChildren();
			root.dataset.surface = surface;
			if (surface === 'agent') { renderAgent(root, model, host, openTools, planOpen, open => { planOpen = open; }, activity); }
			else { renderManager(root, model, host, openTools, activity, planOpen, open => { planOpen = open; }); }
			const nextScroll = root.querySelector<HTMLElement>('.pulseai-transcript-scroll');
			if (nextScroll) { nextScroll.scrollTop = wasNearBottom ? nextScroll.scrollHeight : scrollTop; }
			if (activeComposer) {
				const input = root.querySelector<HTMLTextAreaElement>('.pulseai-composer-input');
				input?.focus({ preventScroll: true });
				if (input && selectionStart !== undefined && selectionEnd !== undefined) { input.setSelectionRange(selectionStart, selectionEnd); }
			}

		};
	return {
		update(model: PulseAIRenderModel): void {
			if (disposed) { return; }
			lastModel = model;
			activity.sync(model);
			paint(model);
		},
		dispose(): void {
			disposed = true;
			activity.dispose();
			lastModel = undefined;
			root.replaceChildren();
		},
	};
}
