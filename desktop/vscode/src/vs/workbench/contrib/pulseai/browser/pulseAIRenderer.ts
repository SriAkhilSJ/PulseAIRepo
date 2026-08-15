/*---------------------------------------------------------------------------------------------
 * Framework-neutral, editor-native Pulse renderer. Both first-party workbench hosts mount this
 * module; no Electron, Node, or Code OSS service is imported across this boundary.
 *--------------------------------------------------------------------------------------------*/

import type { IDisposable } from '../../../../base/common/lifecycle.js';
import type { PulseAISurface } from '../common/pulseAIRendererService.js';
import { pulseAIToolPresentation } from '../common/pulseAIToolCatalog.js';

export type PulseAIToolState = 'queued' | 'running' | 'passed' | 'approval' | 'failed';

export interface PulseAIToolView {
	readonly id: string;
	readonly name: string;
	readonly state: PulseAIToolState;
	readonly arguments?: unknown;
	readonly result?: unknown;
	readonly duration?: string;
}

export interface PulseAIRenderModel {
	readonly engineState: string;
	readonly workspaceLabel: string;
	readonly sessionId?: string;
	readonly running: boolean;
	readonly cancelRequested: boolean;
	readonly turnOutcome: 'idle' | 'running' | 'completed' | 'cancelled' | 'failed';
	readonly userMessage?: string;
	readonly assistantText: string;
	readonly reasoning?: string;
	readonly tools: readonly PulseAIToolView[];
	readonly approval?: { readonly toolId: string; readonly name: string; readonly diff?: unknown };
	readonly plan: readonly string[];
	readonly verification?: string;
	readonly telemetry: { readonly input?: number; readonly output?: number; readonly cache?: number; readonly cost?: number };
	readonly capabilitySummary: { readonly available: number; readonly total: number; readonly blocked: number };
	readonly error?: string;
	readonly draft: string;
}

export interface PulseAIRenderHost {
	setDraft(value: string): void;
	submitPrompt(text: string): void;
	cancel(): void;
	steer(text: string): void;
	replyToSafety(toolId: string, approved: boolean, alwaysAllow?: boolean): void;
	openDiff(toolId: string): void;
	revealFile(resource: string): void;
	restoreCheckpoint(hash: string): void;
	retryEngine(): void;
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

function icon(name: string): HTMLElement {
	const node = element('span', `codicon codicon-${name}`);
	node.setAttribute('aria-hidden', 'true');
	return node;
}

function brandMark(): SVGSVGElement {
	const namespace = 'http://www.w3.org/2000/svg';
	const svg = document.createElementNS(namespace, 'svg');
	svg.classList.add('pulseai-brand-mark');
	svg.setAttribute('viewBox', '0 0 32 32');
	svg.setAttribute('aria-hidden', 'true');
	const shell = document.createElementNS(namespace, 'rect');
	shell.setAttribute('x', '1');
	shell.setAttribute('y', '1');
	shell.setAttribute('width', '30');
	shell.setAttribute('height', '30');
	shell.setAttribute('rx', '8');
	const pulse = document.createElementNS(namespace, 'path');
	pulse.setAttribute('d', 'M5 17h5l2.5-7 4.2 13 3.1-9 2.1 3H27');
	const node = document.createElementNS(namespace, 'circle');
	node.setAttribute('cx', '27');
	node.setAttribute('cy', '17');
	node.setAttribute('r', '1.7');
	svg.append(shell, pulse, node);
	return svg;
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
	return `… ${text.length - max} earlier characters omitted …\n${text.slice(-max)}`;
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
	const duration = tool.duration ?? firstString(result, ['duration', 'elapsed']) ?? '—';
	const body = element('div', 'pulseai-tool-body pulseai-terminal-body');
	body.append(
		element('div', 'pulseai-terminal-command', element('span', 'pulseai-terminal-prompt', '$'), element('code', undefined, command)),
		element('pre', 'pulseai-terminal-output', output || (tool.state === 'running' ? 'Waiting for output…' : 'No captured output')),
		element('div', 'pulseai-terminal-result', element('span', `pulseai-tool-state is-${tool.state}`, stateLabel(tool.state)), element('span', undefined, `exit ${exit}`), element('span', undefined, duration)),
	);
	const actions = element('div', 'pulseai-tool-actions');
	actions.append(button('Copy command', 'pulseai-link-button', () => void navigator.clipboard?.writeText(command), 'copy'));
	const cwd = firstString(args, ['cwd', 'path']);
	if (cwd) { actions.append(button('Reveal location', 'pulseai-link-button', () => host.revealFile(cwd), 'go-to-file')); }
	body.append(actions);
	return body;
}

function familyBody(tool: PulseAIToolView, host: PulseAIRenderHost): HTMLElement {
	const presentation = pulseAIToolPresentation(tool.name);
	if (presentation.family === 'terminal' || presentation.family === 'process') {
		return terminalBody(tool, host);
	}
	const body = element('div', `pulseai-tool-body pulseai-family-${presentation.family}`);
	if (presentation.family === 'file-write') {
		body.append(labeledPayload('Change', record(tool.result)?.diff ?? tool.result ?? tool.arguments));
	} else if (presentation.family === 'file-read') {
		body.append(labeledPayload('Content', record(tool.result)?.content ?? tool.result ?? tool.arguments));
	} else if (presentation.family === 'verification') {
		body.append(labeledPayload('Evidence', tool.result ?? { status: stateLabel(tool.state) }));
	} else if (presentation.family === 'search' || presentation.family === 'web' || presentation.family === 'session') {
		body.append(labeledPayload('Results', tool.result ?? tool.arguments));
	} else if (presentation.family === 'browser') {
		body.append(labeledPayload('Browser action', { request: tool.arguments, result: tool.result }));
	} else if (presentation.family === 'subagent') {
		body.append(labeledPayload('Delegation', { request: tool.arguments, result: tool.result }));
	} else {
		body.append(labeledPayload('Details', { arguments: tool.arguments, result: tool.result }));
	}
	const target = firstString(tool.arguments, ['path', 'file_path', 'resource']);
	const actions = element('div', 'pulseai-tool-actions');
	if (presentation.family === 'file-write') { actions.append(button('Review change', 'pulseai-link-button', () => host.openDiff(tool.id), 'diff')); }
	if (target) { actions.append(button('Open file', 'pulseai-link-button', () => host.revealFile(target), 'go-to-file')); }
	if (actions.childElementCount) { body.append(actions); }
	return body;
}

function toolRow(tool: PulseAIToolView, host: PulseAIRenderHost, openTools: Set<string>): HTMLDetailsElement {
	const presentation = pulseAIToolPresentation(tool.name);
	const details = element('details', `pulseai-tool-row is-${tool.state}`);
	details.dataset.toolId = tool.id;
	details.dataset.toolName = tool.name;
	const shouldDefaultOpen = presentation.defaultOpen === 'always' || (presentation.defaultOpen === 'running' && (tool.state === 'running' || tool.state === 'approval'));
	details.open = openTools.has(tool.id) || shouldDefaultOpen;
	const summary = element('summary', 'pulseai-tool-summary',
		statusGlyph(tool.state),
		icon(presentation.icon),
		element('strong', undefined, presentation.title),
		element('span', 'pulseai-tool-target', displayTarget(tool)),
		tool.duration ? element('span', 'pulseai-tool-duration', tool.duration) : undefined,
		element('span', `pulseai-tool-state is-${tool.state}`, stateLabel(tool.state)),
		icon('chevron-right'),
	);
	details.append(summary, familyBody(tool, host));
	details.addEventListener('toggle', () => details.open ? openTools.add(tool.id) : openTools.delete(tool.id));
	return details;
}

function engineStatus(model: PulseAIRenderModel): HTMLElement {
	const state = model.engineState;
	const tone = state === 'ready' ? 'ready' : state === 'starting' ? 'running' : state === 'crashed' || state === 'degraded' ? 'failed' : 'idle';
	return element('span', `pulseai-engine-status is-${tone}`, element('span', 'pulseai-status-dot'), state === 'ready' ? 'Pulse ready' : `Engine ${state}`);
}

function transcript(model: PulseAIRenderModel, host: PulseAIRenderHost, openTools: Set<string>): HTMLElement {
	const scroll = element('div', 'pulseai-transcript-scroll');
	const lane = element('div', 'pulseai-transcript-lane');
	if (model.userMessage) {
		lane.append(element('div', 'pulseai-user-message', model.userMessage));
	}
	if (model.assistantText || model.reasoning || model.running) {
		const response = element('section', 'pulseai-assistant-message');
		response.append(element('div', 'pulseai-assistant-label', icon('pulse'), element('strong', undefined, 'Pulse'), model.running ? element('span', 'pulseai-stream-label', model.cancelRequested ? 'Stopping…' : 'Working') : undefined));
		if (model.reasoning) { response.append(element('div', 'pulseai-reasoning', model.reasoning)); }
		response.append(element('p', 'pulseai-assistant-copy', model.assistantText || 'Inspecting workspace context…'));
		lane.append(response);
	}
	if (model.tools.length) {
		const tools = element('section', 'pulseai-tool-list');
		for (const tool of model.tools) { tools.append(toolRow(tool, host, openTools)); }
		lane.append(tools);
	}
	if (model.turnOutcome === 'completed' || model.turnOutcome === 'cancelled' || model.turnOutcome === 'failed') {
		const label = model.turnOutcome === 'completed' ? 'Run completed' : model.turnOutcome === 'cancelled' ? 'Run cancelled' : 'Run failed';
		const iconName = model.turnOutcome === 'completed' ? 'pass-filled' : model.turnOutcome === 'cancelled' ? 'circle-slash' : 'error';
		lane.append(element('div', `pulseai-turn-receipt is-${model.turnOutcome}`, icon(iconName), element('span', undefined, label)));
	}
	if (!model.userMessage && !model.assistantText && !model.tools.length) {
		lane.append(element('div', 'pulseai-empty', icon('pulse'), element('h3', undefined, 'Work with Pulse'), element('p', undefined, 'Ask about the active editor, change code, run native tests, or inspect the workspace.')));
	}
	if (model.error) {
		lane.append(element('div', 'pulseai-error-row', icon('warning'), element('span', undefined, model.error), button('Retry', 'pulseai-link-button', host.retryEngine)));
	}
	scroll.append(lane);
	return scroll;
}

function approvalDock(model: PulseAIRenderModel, host: PulseAIRenderHost): HTMLElement | undefined {
	if (!model.approval) { return undefined; }
	const approval = model.approval;
	return element('section', 'pulseai-approval-dock',
		element('div', 'pulseai-approval-copy', icon('shield'), element('div', undefined, element('strong', undefined, `${pulseAIToolPresentation(approval.name).title} needs approval`), element('span', undefined, displayTarget({ id: approval.toolId, name: approval.name, state: 'approval', arguments: approval.diff })) )),
		element('div', 'pulseai-approval-actions',
			approval.diff ? button('Review', 'pulseai-button pulseai-button-secondary', () => host.openDiff(approval.toolId)) : undefined,
			button('Deny', 'pulseai-button pulseai-button-secondary', () => host.replyToSafety(approval.toolId, false)),
			button('Allow', 'pulseai-button pulseai-button-primary', () => host.replyToSafety(approval.toolId, true)),
		),
	);
}

function composer(model: PulseAIRenderModel, host: PulseAIRenderHost, manager: boolean): HTMLElement {
	const input = element('textarea', 'pulseai-composer-input') as HTMLTextAreaElement;
	input.rows = manager ? 2 : 3;
	input.placeholder = manager ? 'Steer this agent or add context…' : 'Ask Pulse…';
	input.value = model.draft;
	input.addEventListener('input', () => host.setDraft(input.value));
	const submit = () => {
		const value = input.value.trim();
		if (!value) { return; }
		if (manager && model.running) { host.steer(value); }
		else { host.submitPrompt(value); }
	};
	input.addEventListener('keydown', event => {
		if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); submit(); }
	});
	const stop = model.running ? button(model.cancelRequested ? 'Stopping' : 'Stop', 'pulseai-icon-button', host.cancel, 'debug-stop') : undefined;
	if (stop && model.cancelRequested) { stop.disabled = true; }
	const controls = element('div', 'pulseai-composer-controls',
		button('@ Context', 'pulseai-composer-pill', () => { input.value += '@'; host.setDraft(input.value); input.focus(); }),
		stop,
		button(manager && model.running ? 'Steer' : 'Send', 'pulseai-send-button', submit, 'send'),
	);
	return element('footer', 'pulseai-composer', input, controls);
}

function selector(label: string, values: readonly string[]): HTMLLabelElement {
	const select = element('select', 'pulseai-native-select') as HTMLSelectElement;
	select.setAttribute('aria-label', label);
	for (const value of values) {
		const option = element('option', undefined, value);
		option.value = value;
		select.append(option);
	}
	return element('label', 'pulseai-selector', element('span', undefined, label), select);
}

function renderAgent(root: HTMLElement, model: PulseAIRenderModel, host: PulseAIRenderHost, openTools: Set<string>): void {
	const shell = element('div', 'pulseai-agent-shell');
	const header = element('header', 'pulseai-agent-header',
		element('div', 'pulseai-agent-brand', brandMark(), element('strong', undefined, 'Pulse')),
		engineStatus(model),
	);
	const controls = element('div', 'pulseai-agent-selectors', selector('Mode', ['Agent', 'Plan', 'Ask']), selector('Model', ['Pulse Auto', 'Claude', 'GPT']), selector('Approval', ['Confirm edits', 'Always ask', 'Read only']));
	shell.append(header, controls, transcript(model, host, openTools));
	const approval = approvalDock(model, host);
	if (approval) { shell.append(approval); }
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
	const usage = element('section', 'pulseai-inspector-section pulseai-usage', element('div', 'pulseai-inspector-title', element('span', undefined, 'Usage'), element('strong', undefined, model.telemetry.cost === undefined ? '—' : `$${model.telemetry.cost.toFixed(4)}`)),
		element('div', 'pulseai-usage-grid', element('span', undefined, 'Input'), element('strong', undefined, String(model.telemetry.input ?? 0)), element('span', undefined, 'Cache'), element('strong', undefined, String(model.telemetry.cache ?? 0)), element('span', undefined, 'Output'), element('strong', undefined, String(model.telemetry.output ?? 0))));
	pane.append(plan, evidence, capabilities, usage);
	return pane;
}

function renderManager(root: HTMLElement, model: PulseAIRenderModel, host: PulseAIRenderHost, openTools: Set<string>): void {
	const shell = element('div', 'pulseai-manager-shell');
	const sidebar = element('aside', 'pulseai-manager-sidebar',
		element('header', 'pulseai-manager-pane-head', element('div', undefined, element('span', 'pulseai-eyebrow', 'CONTROL PLANE'), element('h2', undefined, 'Workspaces')), button('', 'pulseai-icon-button', () => undefined, 'add')),
		element('div', 'pulseai-manager-search', icon('search'), element('span', undefined, 'Find workspace or agent')),
		element('div', 'pulseai-workspace-group',
			element('div', 'pulseai-workspace-title', icon('chevron-down'), icon('folder'), element('strong', undefined, model.workspaceLabel)),
			element('button', 'pulseai-session-row is-active', element('span', `pulseai-status-dot is-${model.running ? 'running' : 'ready'}`), element('div', undefined, element('strong', undefined, model.userMessage || 'New Pulse session'), element('span', undefined, model.sessionId ?? 'Local workspace')), element('span', 'pulseai-session-state', model.running ? 'Working' : 'Ready')),
		),
		element('footer', 'pulseai-manager-sidebar-footer', icon('organization'), element('span', undefined, model.sessionId ? '1 active session' : 'No active sessions')),
	);
	const main = element('main', 'pulseai-manager-main');
	main.append(
		element('header', 'pulseai-manager-titlebar', element('div', undefined, element('div', 'pulseai-manager-breadcrumb', model.workspaceLabel, ' / ', model.sessionId?.slice(0, 12) ?? 'new-session'), element('h1', undefined, model.userMessage || 'Pulse Manager')), engineStatus(model)),
		element('nav', 'pulseai-manager-tabs', element('button', 'is-active', icon('comment-discussion'), 'Session'), element('button', undefined, icon('terminal'), `Tools ${model.tools.length}`), element('button', undefined, icon('diff'), 'Changes')),
		transcript(model, host, openTools),
	);
	const approval = approvalDock(model, host);
	if (approval) { main.append(approval); }
	main.append(composer(model, host, true));
	shell.append(sidebar, main, inspector(model));
	root.append(shell);
}

export function mountPulseAIRenderer(root: HTMLElement, surface: PulseAISurface, host: PulseAIRenderHost): PulseAIRenderMount {
	const openTools = new Set<string>();
	let disposed = false;
	return {
		update(model: PulseAIRenderModel): void {
			if (disposed) { return; }
			const previousScroll = root.querySelector<HTMLElement>('.pulseai-transcript-scroll');
			const scrollTop = previousScroll?.scrollTop ?? 0;
			const wasNearBottom = !previousScroll || previousScroll.scrollHeight - previousScroll.scrollTop - previousScroll.clientHeight < 32;
			const activeElement = document.activeElement;
			const activeComposer = root.contains(activeElement) && activeElement instanceof HTMLTextAreaElement ? activeElement : undefined;
			const selectionStart = activeComposer?.selectionStart;
			const selectionEnd = activeComposer?.selectionEnd;
			root.replaceChildren();
			root.dataset.surface = surface;
			if (surface === 'agent') { renderAgent(root, model, host, openTools); }
			else { renderManager(root, model, host, openTools); }
			const nextScroll = root.querySelector<HTMLElement>('.pulseai-transcript-scroll');
			if (nextScroll) { nextScroll.scrollTop = wasNearBottom ? nextScroll.scrollHeight : scrollTop; }
			if (activeComposer) {
				const input = root.querySelector<HTMLTextAreaElement>('.pulseai-composer-input');
				input?.focus({ preventScroll: true });
				if (input && selectionStart !== undefined && selectionEnd !== undefined) { input.setSelectionRange(selectionStart, selectionEnd); }
			}
		},
		dispose(): void {
			disposed = true;
			root.replaceChildren();
		},
	};
}
