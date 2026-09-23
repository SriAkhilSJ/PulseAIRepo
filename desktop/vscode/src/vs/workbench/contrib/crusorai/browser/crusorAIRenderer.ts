/*---------------------------------------------------------------------------------------------
 * Framework-neutral, editor-native Crusor renderer. Both first-party workbench hosts mount this
 * module; no Electron, Node, or Code OSS service is imported across this boundary.
 *--------------------------------------------------------------------------------------------*/

import type { IDisposable } from '../../../../base/common/lifecycle.js';
import type { CrusorClarifyQuestion, CrusorExecutionMode, CrusorTodoItem } from '../common/crusorAIProtocol.js';
import { reasoningEffortLabel } from '../common/crusorAIReasoningEffort.js';
import type { CrusorReasoningEffortValue } from '../common/crusorAIReasoningEffort.js';
import { separateGluedReasoningBlocks } from './crusorAIReasoningBlocks.js';
import type { CrusorAISurface } from '../common/crusorAIRendererService.js';
import type { CrusorAISessionRow } from '../common/crusorAISessionProjection.js';
import { crusorAIToolPresentation } from '../common/crusorAIToolCatalog.js';
import { deriveChangedFiles, hasAnsiCodes, parseAnsi, parseDiff, stripTerminalEnvelope, windowedTailLines } from './crusoraiCardFormat.js';
import { compactTarget, splitRunGroups, summarizeToolRun, toolPresentVerb } from './crusorAIRunSummary.js';
import { renderToolIcon } from './crusorAIIcons.js';
import {
	activityOrigin, activityParts, activityRowMode, activitySignature, closeMeasurement, draftingToolName,
	elapsedFor, measuredDuration,
	DRAFTING_REVEAL_MS, elapsedSeconds, formatElapsed, statusHintLabel, toolNarratesWait, TURN_QUIET_S,
	UNNAMED_WAIT_LABEL,
} from './crusorAIActivity.js';

export type CrusorAIToolState = 'queued' | 'running' | 'passed' | 'approval' | 'failed';

/** One plan step as the model wrote it: text plus its OWN status. Hermes'
 *  TodoPanel and the desktop composer status both render each item's real
 *  state (`[x] [>] [ ]` glyphs); flattening plan_updated to strings threw
 *  that away and the strip guessed "active" from the row index. */
export interface CrusorAIPlanStepView {
	readonly text: string;
	readonly status: 'pending' | 'in_progress' | 'completed' | 'failed';
}

export interface CrusorAIToolView {
	readonly id: string;
	readonly name: string;
	readonly state: CrusorAIToolState;
	readonly arguments?: unknown;
	readonly result?: unknown;
	readonly duration?: string;
}

/**
 * One entry in the turn's ordered timeline — hermes' message.parts contract
 * (apps/desktop message-parts.tsx walks the parts array in arrival order, so
 * text and tool rows interleave exactly as the model produced them). Tool
 * BODIES keep living in the `tools` map; a tool part only pins the position
 * where its card paints. Without this the turn collapsed into one text blob
 * painted above a block of cards, so a model that works-then-answers showed
 * its final wording at the TOP and every tool call beneath it — arrival order
 * inverted.
 */
export type CrusorAITurnPart =
	| { readonly kind: 'text'; readonly text: string }
	| { readonly kind: 'tool'; readonly toolId: string }
	/** Index into the parallel reasoningParts array; used to preserve the chronological
	 * position of a reasoning block relative to text and tool parts. */
	| { readonly kind: 'reasoning'; readonly reasoningIndex: number };

export interface CrusorAISubAgentView {
	readonly id: string;
	readonly state: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
	readonly goal?: string;
	readonly description?: string;
	readonly mode?: string;
	readonly agentName?: string;
	readonly progress?: string;
	readonly result?: unknown;
	readonly duration?: string;
	readonly parentSessionId?: string;
	readonly childThreadId?: string;
	readonly background?: boolean;
	readonly toolCalls?: number;
}

export interface CrusorAIRenderModel {
	readonly engineState: string;
	/** Engine build ("<sha> <date>"), from session_info. A stale engine is
	 * visible on the status chip — the "not fixed" reports traced twice to a
	 * build that never reached the engine process. */
	readonly engineBuild?: string;
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
	/**
	 * Last context-engine status message (compaction progress or the overflow warning). NOT
	 * `error`: an overflow warning is about the NEXT model call, this turn is still alive.
	 * The activity row names the compaction via `compacting`; this carries the words.
	 */
	/**
	 * Result of a voice_transcribe round trip (Floor 5): the panel shows what
	 * the mic heard (or why it failed) BEFORE the prompt is submitted, so the
	 * user can see the transcription is right instead of trusting a black box.
	 */
	readonly voiceHeard?: { readonly ok: boolean; readonly text: string; readonly error?: string };
	/** Live provider-call status (llm.request/llm.response): names the model being asked. */
	readonly llmStatus?: { readonly model: string; readonly attempt: number };
	/** The turn's live activity IS the Thinking card (reasoning streaming
	 * during a provider call): the tail row must not narrate the same wait
	 * twice — one thought, one surface. */
	readonly llmReasoningLive?: boolean;
	/** Bounded anatomy of the live request: role + head per message. */
	readonly llmHeads?: readonly { readonly role: string; readonly head: string }[];
	/** Hermes session-states.ts port: busy but silent for the 5-min watchdog
	 * window. A presentation hint (hollow dot, honest row text) — never an
	 * error, never a claim the turn died. */
	readonly stalled?: boolean;
	/** Degradation receipt (runtime_degraded): honest bounded-scan note, never a fatal card. */
	readonly degraded?: string;
	readonly contextStatus?: { readonly message: string; readonly severity: 'info' | 'warning'; readonly phase: string; readonly usagePercent?: number };
	readonly sessionId?: string;
	readonly mode: CrusorExecutionMode;
	/** Selected Think level; '' = inherit the engine default (REASONING_EFFORT). */
	readonly reasoningEffort?: string;
	readonly running: boolean;
	readonly cancelRequested: boolean;
	readonly turnOutcome: 'idle' | 'running' | 'completed' | 'cancelled' | 'failed';
	readonly userMessage?: string;
	readonly assistantText: string;
	/** Ordered timeline (hermes message.parts): text segments and tool calls in arrival order. */
	readonly parts: readonly CrusorAITurnPart[];
	readonly reasoningParts: readonly { readonly text: string; readonly completedAt?: number }[];
	readonly tools: readonly CrusorAIToolView[];
	readonly subAgents: readonly CrusorAISubAgentView[];
	readonly isChild?: boolean;
	readonly parentSessionId?: string;
	readonly parentMap?: ReadonlyMap<string, string>;
	readonly approval?: { readonly toolId: string; readonly name: string; readonly diff?: unknown; readonly warning?: string };
	/** Pending hermes clarify batch (the ask tool) awaiting this panel's answer. */
	readonly clarify?: {
		readonly requestId: string;
		readonly title: string;
		readonly toolId?: string;
		readonly questions: readonly CrusorClarifyQuestion[];
	};
	/** Live hermes todo_list state ({todos, revision} — reconciles atomically). */
	readonly todos: readonly CrusorTodoItem[];
	readonly todoRevision: number;
	readonly plan: readonly CrusorAIPlanStepView[];
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
	 * The manager's session list: a projection of ICrusorAISessionStore, i.e. the same rows the
	 * workbench's own Agent Sessions list is fed. Absent means "the engine has not named a session
	 * yet", which the manager paints as a designed empty state; an empty array would be a claim
	 * that the user has no sessions, which nobody measured.
	 */
	readonly sessions?: readonly CrusorAISessionRow[];
	readonly draft: string;
	readonly history: readonly {
		readonly userMessage?: string;
		readonly assistantText: string;
		readonly parts: readonly CrusorAITurnPart[];
		readonly reasoningParts: readonly { readonly text: string; readonly completedAt?: number }[];
		readonly tools: readonly CrusorAIToolView[];
		readonly subAgents: readonly CrusorAISubAgentView[];
		readonly turnOutcome: 'idle' | 'running' | 'completed' | 'cancelled' | 'failed';
		readonly plan: readonly CrusorAIPlanStepView[];
	}[];
}

export interface CrusorAIRenderHost {
	setDraft(value: string): void;
	setMode(mode: CrusorExecutionMode): void;
	/** Think level for the NEXT turns (hermes reasoning-effort scale). */
	setReasoningEffort(value: CrusorReasoningEffortValue): void;
	submitPrompt(text: string): void;
	cancel(): void;
	steer(text: string): void;
	replyToSafety(toolId: string, approved: boolean, alwaysAllow?: boolean): void;
	/** Hermes ask-tool reply: answers per qid; timedOut=true is an explicit skip-all. */
	replyToClarify(requestId: string, answers: Record<string, string | readonly string[]>, timedOut?: boolean): void;
	openDiff(toolId: string): void;
	revealFile(resource: string): void;
	/** A loadable src for a workspace-relative or absolute resource path
	 * (screenshots, recordings) — undefined when it cannot be resolved.
	 * Implementations own the file->browser-URI translation so this file
	 * stays free of workbench URI services. */
	resourceSrc(resource: string): string | undefined;
	restoreCheckpoint(hash: string): void;
	retryEngine(): void;
	selectWorkspace(uri: string): void;
	openFolder(): void;
	openEngineSettings(): void;
	openManager(): void;
	/** Real clipboard via the workbench service (webview navigator.clipboard
	 * is permission-blocked in the field). Implementations own the fallback. */
	copyToClipboard(text: string): void;
	/** OpenCode parity: navigate to child/parent session */
	navigateToSession?(sessionId: string): void;
	isChildSession?(): boolean;
}

export interface CrusorAIRenderMount extends IDisposable {
	update(model: CrusorAIRenderModel): void;
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
 * A row glyph. Hermes draws solid SVG for the names `crusorAIIcons.ts` covers and the outline
 * codicon font for everything else, because a font glyph has no fillable region -- the same
 * rule, keyed by the same names, so a row here shows the glyph the webview resolves.
 */
function icon(name: string): HTMLElement {
	return renderToolIcon(name);
}

// ---------------------------------------------------------------------------
// Minimal markdown rendering for the transcript (pure DOM, zero deps).
// The panel used to print assistant text as one plain text node, so every
// legitimate markdown line -- the model's "###" headers, the finalize stamp's
// bullets and sign-offs -- leaked as literal hash/asterisk soup. This renders
// the small dialect we actually emit (headings, bullets, hr, fenced code,
// bold/italic/inline-code) using element()/createTextNode ONLY -- never
// innerHTML -- so nothing the model sends can inject markup. Anything outside
// the dialect renders as plain text, which is the honest fallback.
// ---------------------------------------------------------------------------

function mdInline(target: HTMLElement, text: string): void {
	for (const part of text.split(/(\*\*[^*\n]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\)|<https?:\/\/[^>\s]+>)/)) {
		if (!part) { continue; }
		const linkMd = /^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/.exec(part);
		if (linkMd) {
			const a = element('a', 'crusorai-md-link', linkMd[1]) as HTMLAnchorElement;
			a.href = linkMd[2];
			a.target = '_blank';
			a.rel = 'noopener noreferrer';
			target.append(a);
			continue;
		}
		if (/^<https?:\/\/[^>\s]+>$/.test(part)) {
			const url = part.slice(1, -1);
			const a = element('a', 'crusorai-md-link', url) as HTMLAnchorElement;
			a.href = url;
			a.target = '_blank';
			a.rel = 'noopener noreferrer';
			target.append(a);
			continue;
		}
		if (!part) { continue; }
		if (part.length > 4 && part.indexOf('**') === 0 && part.lastIndexOf('**') === part.length - 2) {
			target.append(element('strong', undefined, part.slice(2, -2)));
		} else if (part.length > 2 && part.charCodeAt(0) === 96 && part.charCodeAt(part.length - 1) === 96) {
			target.append(element('code', 'crusorai-md-code', part.slice(1, -1)));
		} else if (part.length > 2 && part.indexOf('*') === 0 && part.lastIndexOf('*') === part.length - 1) {
			target.append(element('em', undefined, part.slice(1, -1)));
		} else {
			target.append(element('span', undefined, part));
		}
	}
}

// Some endpoint models leak their NATIVE tool-call dialect into CONTENT
// instead of emitting API tool_calls (field 2026-09-07 1:34 PM:
// <dots_function_call><exec><command>... painted as chat prose). The engine
// correctly declines to execute unparseable text; the renderer's job is to
// not PAINT it as the agent's voice. Hermes' equivalents are the toolset
// availability paint and the unverified verdict — the raw dialect itself is
// model-specific, so it is shown collapsed and labeled, never parsed.
// Two model dialects land as raw text: XML-ish tool tags and (field
// 2026-09-10, the grace summary) single-line JSON objects keyed by
// "action"/"tool" — the model kept "calling" tools textually after the
// toolless summary request. Both collapse into the labeled disclosure
// instead of painting raw JSON into the answer.
const RAW_TOOL_MARKUP = /^\s*(?:<\/?\s*(?:dots_function_call|exec|invoke|command|tool_call|function_call)\b|\{\s*"(?:action|tool|tool_call|function)"\s*:)/i;
// Workbench freshness stamp — bump with EVERY workbench UI round. The engine
// chip proves the PYTHON engine only; field round 2026-09-08 ran engine
// de0dbbae on a base-era compiled workbench (lab-era browser cards, reveal-
// URL ERRs) and nothing on screen could tell. This constant lives in this
// source file, so any compile of current source carries it while a stale
// out/ shows an older date; engineStatus() flags engine-newer skew as STALE.
const CRUSORAI_UI_STAMP = '2026-09-11';

function markdownCopy(text: string, slot?: string): HTMLElement {
	const root = element('div', 'crusorai-assistant-copy crusorai-md');
	if (slot) { root.dataset.slot = slot; }
	let list: HTMLUListElement | null = null;
	let code: HTMLPreElement | null = null;
	// Consecutive raw tool-markup lines collapse into ONE labeled disclosure.
	// They are buffered and flushed on the next non-markup line (or at the
	// end of the text) — the old loop-carried rawBlock/rawPre pair hit a TS
	// circular-narrowing error (append on never) AND could crash at runtime
	// on a consecutive markup line (stale pre reference).
	const rawLines: string[] = [];
	const flushRawMarkup = () => {
		if (!rawLines.length) { return; }
		const details = element('details', 'crusorai-raw-call');
		details.append(element('summary', undefined, 'Unparsed tool-call markup (model dialect, not executed)'));
		const pre = element('pre', 'crusorai-raw-call-pre');
		pre.append(document.createTextNode(`${rawLines.join('\n')}\n`));
		details.append(pre);
		root.append(details);
		rawLines.length = 0;
		list = null;
	};
	for (const raw of text.split(/\r?\n/)) {
		const line = raw.replace(/\s+$/, '');
		if (code) {
			if (line.trim() === '```') { code = null; }
			else { code.append(document.createTextNode(raw + '\n')); }
			continue;
		}
		if (RAW_TOOL_MARKUP.test(line)) {
			rawLines.push(raw);
			continue;
		}
		flushRawMarkup();
		if (line.trim() === '```') {
			code = element('pre', 'crusorai-md-pre');
			root.append(code);
			continue;
		}
		const heading = /^(#{1,6})\s+(.*)$/.exec(line);
		if (heading) {
			list = null;
			const h = element('div', `crusorai-md-h crusorai-md-h${heading[1].length}`);
			mdInline(h, heading[2]);
			root.append(h);
			continue;
		}
		if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
			list = null;
			root.append(element('hr', 'crusorai-md-hr'));
			continue;
		}
		const bullet = /^\s*[-*]\s+(.*)$/.exec(line);
		if (bullet) {
			if (!list || list.tagName !== 'UL') { list = element('ul', 'crusorai-md-ul') as HTMLUListElement; root.append(list); }
			const li = element('li') as HTMLLIElement;
			mdInline(li, bullet[1]);
			list.append(li);
			continue;
		}
		const ordered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
		if (ordered) {
			// hermes markdown-text: ordered lists keep their own element so a
			// numbered "1. 2. 3." answer doesn't collapse into one paragraph.
			if (!list || list.tagName !== 'OL') { list = element('ol', 'crusorai-md-ol') as HTMLOListElement; root.append(list); }
			const li = element('li') as HTMLLIElement;
			mdInline(li, ordered[1]);
			list.append(li);
			continue;
		}
		const quote = /^>\s?(.*)$/.exec(line);
		if (quote) {
			// hermes compact-markdown: a quote is its own quiet block.
			list = null;
			const q = element('blockquote', 'crusorai-md-quote');
			mdInline(q, quote[1]);
			root.append(q);
			continue;
		}
		if (/^\s*\|.*\|\s*$/.test(line) && line.includes('|', 1)) {
			// hermes markdown-table: a pipe-table body renders as a real table.
			const cells = line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
			if (cells.every(c => /^:?-{2,}:?$/.test(c))) { continue; } // separator row
			let table = root.querySelector<HTMLTableElement>('table.crusorai-md-table:last-of-type');
			if (!table || table.dataset.closed === 'true') {
				table = element('table', 'crusorai-md-table') as HTMLTableElement;
				table.dataset.closed = 'false';
				root.append(table);
			}
			const tr = element('tr') as HTMLTableRowElement;
			const kind = table.rows.length === 0 ? 'th' : 'td';
			for (const cell of cells) {
				const td = element(kind) as HTMLTableCellElement;
				mdInline(td, cell);
				tr.append(td);
			}
			table.append(tr);
			continue;
		}
		if (!line.trim()) {
			list = null;
			// a blank line closes an open table (hermes table scope)
			for (const t of root.querySelectorAll('table.crusorai-md-table')) { (t as HTMLTableElement).dataset.closed = 'true'; }
			continue;
		}
		list = null;
		const para = element('div', 'crusorai-md-p');
		mdInline(para, line);
		root.append(para);
	}
	flushRawMarkup();
	return root;
}

// Hermes-pattern message action: a quiet Copy control under each completed
// answer -- the "Run completed" green check told the user what they had just
// watched happen; a copy button does something they actually want. Clipboard
// write never throws into the panel (best-effort), and the label flashes
// Copied so the click is confirmed without a dialog.
// Hermes port (components/chat/activity-timer.ts): seconds tick on a 1s
// heartbeat WITHOUT re-rendering the panel -- the ticker surgically updates
// only .crusorai-elapsed nodes in place, so a full transcript rebuild (which
// would reset scroll and disclosure state) never happens on a clock tick.
function formatElapsedSeconds(seconds: number): string {
	return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

let elapsedTicker: number | undefined;

function elapsedSpan(originMs?: number): HTMLElement {
	const span = element('span', 'crusorai-scaffold-meta crusorai-elapsed');
	const origin = typeof originMs === 'number' && originMs > 0 ? originMs : Date.now();
	datasetSet(span, 'origin', String(origin));
	span.textContent = formatElapsedSeconds(Math.max(0, Math.floor((Date.now() - origin) / 1000)));
	if (elapsedTicker === undefined) {
		elapsedTicker = window.setInterval(() => {
			for (const node of document.querySelectorAll<HTMLSpanElement>('span.crusorai-elapsed')) {
				const nodeOrigin = Number(node.dataset.origin || '0');
				if (nodeOrigin > 0) {
					node.textContent = formatElapsedSeconds(Math.max(0, Math.floor((Date.now() - nodeOrigin) / 1000)));
				}
			}
		}, 1000);
	}
	return span;
}

function datasetSet(node: HTMLElement, key: string, value: string): void {
	node.dataset[key] = value;
}

function copyButton(text: string, host?: CrusorAIRenderHost): HTMLElement {
	// Hermes port (ui/copy-button.tsx): an ICON action, not a text line --
	// copy glyph, tooltip title, 1.5s check-flash on success, error state on
	// denial. With a host, clipboard goes through the workbench service
	// (navigator.clipboard is permission-blocked in the webview — field
	// proof); without one, the async-API fallback path.
	const btn = element('button', 'crusorai-icon-action') as HTMLButtonElement;
	btn.type = 'button';
	btn.title = 'Copy';
	btn.setAttribute('aria-label', 'Copy');
	btn.append(icon('copy'));
	const reset = () => {
		btn.replaceChildren(icon('copy'));
		btn.title = 'Copy';
	};
	const flash = () => {
		btn.replaceChildren(icon('check'));
		btn.title = 'Copied';
		setTimeout(reset, 1500);
	};
	const fail = () => {
		btn.replaceChildren(icon('error'));
		btn.title = 'Copy failed';
		setTimeout(reset, 1500);
	};
	btn.addEventListener('click', () => {
		if (host) {
			try {
				host.copyToClipboard(text);
				flash();
			} catch {
				fail();
			}
			return;
		}
		try {
			void copyTextToClipboard(text).then(flash, fail);
		} catch {
			fail();
		}
	});
	return btn;
}

function button(label: string, className: string, action: () => void, iconName?: string): HTMLButtonElement {
	const node = element('button', className, iconName ? icon(iconName) : undefined, label);
	node.type = 'button';
	node.addEventListener('click', action);
	return node;
}

// Webview clipboard can be permission-blocked (field: NotAllowedError on
// writeText). Degrade honestly: async API first, hidden-textarea fallback,
// real failure surfaced by the caller's UI either way.
function copyTextToClipboard(text: string): Promise<void> {
	if (navigator.clipboard?.writeText) {
		return navigator.clipboard.writeText(text).catch(() => copyViaExecCommand(text));
	}
	return new Promise<void>((resolve) => { copyViaExecCommand(text); resolve(); });
}
function copyViaExecCommand(text: string): void {
	const textarea = document.createElement('textarea');
	textarea.value = text;
	textarea.setAttribute('readonly', 'true');
	textarea.style.position = 'fixed';
	textarea.style.opacity = '0';
	document.body.append(textarea);
	textarea.select();
	try { document.execCommand('copy'); } finally { textarea.remove(); }
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

function resultRecord(value: unknown): Readonly<Record<string, unknown>> | undefined {
	// The tool_call_end frame carries `result` RAW (bridge _project_event):
	// structured tools ship json.dumps envelopes as strings, other paths may
	// deliver parsed objects. Cards read keys off the parsed shape — without
	// this, navigate/console/click render em-dashes even on a healthy run.
	if (typeof value === 'string') {
		try { return record(JSON.parse(value)); } catch { return undefined; }
	}
	return record(value);
}

function displayTarget(tool: CrusorAIToolView): string {
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

function resultOutput(tool: CrusorAIToolView): string {
	const value = record(tool.result);
	const parts = [value?.output, value?.stdout, value?.stderr].filter(part => typeof part === 'string' && part.length > 0) as string[];
	return boundedText(parts.length ? parts.join(parts.length > 1 ? '\n' : '') : tool.result);
}

function stateLabel(state: CrusorAIToolState): string {
	if (state === 'passed') { return 'Passed'; }
	if (state === 'failed') { return 'Failed'; }
	if (state === 'approval') { return 'Approval'; }
	if (state === 'running') { return 'Running'; }
	return 'Queued';
}

function statusGlyph(state: CrusorAIToolState): HTMLElement {
	if (state === 'running') { return element('span', 'crusorai-mini-spinner'); }
	const name = state === 'passed' ? 'pass-filled' : state === 'failed' ? 'error' : state === 'approval' ? 'shield' : 'circle-outline';
	return icon(name);
}

function labeledPayload(label: string, value: unknown): HTMLElement {
	return element('div', 'crusorai-tool-field', element('span', 'crusorai-tool-field-label', label), element('pre', 'crusorai-tool-pre', boundedText(value)));
}

// Hermes port (components/chat/expandable-block.tsx): cap a collapsed output
// block at 7.5rem with a bottom fade + one chevron; expanded caps at 40dvh and
// scrolls. Measured on the next frame so short output carries no chrome at all
// (their ResizeObserver discipline: never a sync scrollHeight read per mount).
function expandableOutput(content: HTMLElement): HTMLElement {
	const wrap = element('div', 'crusorai-expandable is-collapsed');
	const clip = element('div', 'crusorai-expandable-clip', content);
	const toggle = element('button', 'crusorai-expandable-toggle', icon('chevron-down')) as HTMLButtonElement;
	toggle.type = 'button';
	toggle.setAttribute('aria-expanded', 'false');
	toggle.setAttribute('aria-label', 'Expand output');
	toggle.addEventListener('click', () => {
		const collapsed = wrap.classList.toggle('is-collapsed');
		toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
	});
	const fade = element('div', 'crusorai-expandable-fade', toggle);
	wrap.append(clip, fade);
	window.requestAnimationFrame(() => {
		if (clip.scrollHeight <= 121) {
			wrap.classList.remove('is-collapsed');
			wrap.classList.add('is-fits');
		}
		// Hermes terminal-output.tsx: jump straight to the LATEST output
		// on first delivery — boundedText keeps the tail, so the end of
		// the stream is the payload (dir listings end at the current
		// entries). First delivery only; a later resize must not yank
		// the user while they scroll up reading earlier output.
		const pre = clip.querySelector<HTMLElement>('.crusorai-terminal-output');
		if (pre && !pre.dataset.tailed && pre.scrollHeight > pre.clientHeight) {
			pre.dataset.tailed = 'true';
			pre.scrollTop = pre.scrollHeight;
		}
	});
	return wrap;
}

// hermes status-row.tsx todo glyphs, ported: pending = dashed ring,
// in_progress = live dot, completed = pass-filled, failed = error,
// cancelled = circle-slash. Rows speak the WRITTEN list, never arg JSON.
//
// User disclosure choices survive re-renders — the same law toolRow's
// openTools set serves one level up, here keyed by the owning tool id.
const openPlanLists = new Set<string>();

// hermes DESKTOP status stack (apps/desktop composer/status-stack +
// components/chat/status-section.tsx) — NOT the TUI TodoPanel. The desktop
// chrome: chevron-right caret (rotates 90deg open, 150ms), the `checklist`
// codicon, the en.ts label `Tasks ${done}/${total}`, the todo group is the
// ONLY group expanded by default (defaultCollapse = type !== 'todo'), and a
// spinner rides the header while an item is in_progress/running (hidden
// once open, pure CSS). Rows keep the status-row glyph grammar.
function planListBody(tool: CrusorAIToolView, result: Readonly<Record<string, unknown>> | undefined, args: Readonly<Record<string, unknown>> | undefined): HTMLElement {
	const rows = planStepsFrom(result, args);
	if (!rows.length) {
		const empty = element('div', 'crusorai-plan-list');
		empty.append(element('div', 'crusorai-plan-empty', 'No task list written'));
		return empty;
	}
	const done = rows.filter(s => s.status === 'completed').length;
	const running = rows.some(s => s.status === 'in_progress');
	const details = element('details', 'crusorai-plan-details') as HTMLDetailsElement;
	// Desktop defaultCollapse: the todo group is expanded by default; the
	// user's toggle wins and survives re-renders (openPlanLists).
	details.open = !openPlanLists.has(tool.id);
	details.addEventListener('toggle', () => details.open ? openPlanLists.delete(tool.id) : openPlanLists.add(tool.id));
	details.append(element('summary', 'crusorai-plan-head',
		element('span', 'crusorai-plan-caret', icon('chevron-right')),
		element('span', 'crusorai-plan-icon', icon('checklist')),
		element('span', 'crusorai-plan-title', `Tasks ${done}/${rows.length}`),
		running ? element('span', 'crusorai-mini-spinner crusorai-plan-spinner') : undefined,
	));
	const wrap = element('div', 'crusorai-plan-list');
	for (const step of rows) {
		const status = step.status;
		const row = element('div', `crusorai-plan-row is-${status}`);
		const glyph = element('span', 'crusorai-plan-glyph');
		if (status === 'completed') { glyph.append(icon('pass-filled')); }
		else if (status === 'failed') { glyph.append(icon('error')); }
		else if (status === 'cancelled') { glyph.append(icon('circle-slash')); }
		// pending (dashed ring) and in_progress (live dot) are pure CSS
		row.append(glyph, element('span', 'crusorai-plan-text', step.description));
		wrap.append(row);
	}
	details.append(wrap);
	return details;
}

function planStepsFrom(result: Readonly<Record<string, unknown>> | undefined, args: Readonly<Record<string, unknown>> | undefined): readonly { description: string; status: string }[] {
	const raw = (result && planStepsOf(result, 'steps'))
		?? planStepsOf(result, 'todos')
		?? planStepsOf(args, 'steps')
		?? planStepsOf(args, 'todos')
		?? [];
	const rows: { description: string; status: string }[] = [];
	for (const item of raw) {
		if (!item || typeof item !== 'object') { continue; }
		const rec = item as Record<string, unknown>;
		const description = String(rec.description ?? rec.content ?? '').trim();
		// hermes items are id-keyed; an id-only row (schema-forbidden but
		// seen in the field) reads as "Item <id>", never "(no description)".
		if (!description) {
			const id = String(rec.id ?? '').trim();
			if (!id) { continue; }
			rows.push({ description: `Item ${id}`, status: String(rec.status ?? 'pending') });
			continue;
		}
		rows.push({ description, status: String(rec.status ?? 'pending') });
	}
	return rows;
}

function planStepsOf(source: Readonly<Record<string, unknown>> | undefined, key: string): unknown[] | undefined {
	if (!source) { return undefined; }
	let raw = source[key];
	if (typeof raw === 'string') {
		try { raw = JSON.parse(raw); } catch { return undefined; }
	}
	return Array.isArray(raw) ? raw : undefined;
}

function terminalBody(tool: CrusorAIToolView, host: CrusorAIRenderHost): HTMLElement {
	const args = record(tool.arguments);
	const result = resultRecord(tool.result);
	const command = firstString(args, ['command', 'script']) ?? 'Command details unavailable';
	// The engine wraps terminal results in a STDOUT:/STDERR: envelope; hermes'
	// card shows the raw output. The Exit-code trailer is parsed from the RAW
	// text above (exitSource) before this strip.
	const output = stripTerminalEnvelope(resultOutput(tool));
	const exitSource = typeof tool.result === 'string' ? tool.result : '';
	let exit = firstString(result, ['exitCode', 'exit_code', 'status', 'code']);
	if (exit === undefined && exitSource) {
		// run_terminal appends "Exit code: N" as the last line of its envelope
		// (and the output cap keeps the tail), so the real exit code is
		// recoverable even when the result is a plain string. Timeout
		// envelopes carry their own marker instead.
		const sentinel = /Exit code: (-?\d+)\s*$/.exec(exitSource);
		if (sentinel) { exit = sentinel[1]; }
		else if (exitSource.includes('terminal timed out') || exitSource.includes('run_terminal timed out')) { exit = 'timeout'; }
	}
	exit ??= (tool.state === 'running' ? 'running' : 'unknown');
	const duration = tool.duration ?? firstString(result, ['duration', 'elapsed']) ?? '\u2014';
	const body = element('div', 'crusorai-tool-body crusorai-terminal-body');
	body.append(
		element('div', 'crusorai-terminal-command', element('span', 'crusorai-terminal-prompt', '$'), element('code', undefined, command)),
		expandableOutput(terminalOutputContent(output, tool.state === 'running')),
		// One meta line (hermes scaffold grammar): state word + exit code
		// + duration, plain text — the colored glyph in the header already
		// carries the state, so no second PASSED pill here.
		element('div', 'crusorai-terminal-result', element('span', undefined, `${stateLabel(tool.state)} · exit ${exit}`), element('span', 'crusorai-tool-duration', duration)),
	);
	const actions = element('div', 'crusorai-tool-actions');
	actions.append(copyButton(command, host));
	const cwd = firstString(args, ['cwd', 'path']);
	if (cwd) { actions.append(button('Reveal location', 'crusorai-link-button', () => host.revealFile(cwd), 'go-to-file')); }
	body.append(actions);
	return body;
}

function toolFields(rows: readonly (readonly [string, string])[]): HTMLElement {
	const wrap = element('div', 'crusorai-tool-fields');
	for (const [k, v] of rows) {
		const row = element('div', 'crusorai-tool-field-row', element('span', 'crusorai-tool-field-key', k), element('code', 'crusorai-tool-field-val', v));
		wrap.append(row);
	}
	return wrap;
}
// OpenCode parity: agent color hash for task cards
function agentColor(name: string): string {
	const palette = ['#0b6bcb', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];
	let hash = 0;
	for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
	return palette[hash % palette.length];
}

function taskToolCard(tool: CrusorAIToolView, host: CrusorAIRenderHost): HTMLElement {
	const args = record(tool.arguments) ?? {};
	const resultRec = resultRecord(tool.result);
	// Extract from args: description, prompt, subagent_type, mode, background
	const description = firstString(args, ['description', 'goal', 'prompt', 'task']) ?? 'Sub-agent task';
	const agentName = firstString(args, ['subagent_type', 'agent_name', 'mode']) ?? 'general';
	const isBackground = Boolean((args as any).background ?? (resultRec as any)?.background ?? false);
	// sessionId metadata may be in result or tool metadata fields (bridge now emits child_thread_id)
	const childId = firstString(resultRec ?? {}, ['sessionId', 'session_id', 'child_thread_id', 'subagent_id']) 
		?? firstString(args, ['sessionId', 'child_thread_id']) 
		?? (resultRec as any)?.child_thread_id
		?? (resultRec as any)?.sessionId;
	const toolCalls = (resultRec as any)?.toolCalls ?? (resultRec as any)?.tool_calls ?? (args as any).toolCalls;
	const state = tool.state;
	const running = state === 'running' || state === 'queued';

	const card = element('div', 'crusorai-task-tool-card');
	card.dataset.component = 'task-tool-card';
	card.style.setProperty('--task-agent-color', agentColor(agentName));
	// Always clickable — even while sub-agent is still starting (childId not yet in result)
	const navId = childId ?? (tool as any).toolCallId ?? tool.id;
	card.dataset.sessionId = String(navId);
	card.classList.add('is-clickable');
	card.tabIndex = 0;
	card.setAttribute('role', 'button');
	card.setAttribute('aria-label', `Open sub-agent ${description}`);
	console.log('[CrusorAI] taskToolCard render', { description, agentName, childId, navId, state });
	const navigate = () => {
		console.log('[CrusorAI] taskToolCard click -> navigateToSession', { description, childId, navId, target: childId ?? navId });
		const target = childId ?? navId;
		if (host.navigateToSession && target) host.navigateToSession(String(target));
		else console.warn('[CrusorAI] navigateToSession not available or no target', { host: !!host.navigateToSession, target });
	};
	card.addEventListener('click', navigate);
	card.addEventListener('keydown', (e: KeyboardEvent) => {
		if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(); }
	});

	const surface = element('div', 'crusorai-task-tool-surface');
	const iconWrap = element('span', running ? 'crusorai-task-tool-spinner' : 'crusorai-task-tool-icon');
	iconWrap.append(running ? element('span', 'crusorai-mini-spinner') : icon('robot'));
	surface.append(iconWrap);
	surface.append(element('span', 'crusorai-task-tool-title', agentName.charAt(0).toUpperCase() + agentName.slice(1)));
	const subtitleText = description + (isBackground ? ' (background)' : '') + (toolCalls ? ` · ${toolCalls} calls` : '');
	surface.append(element('span', 'crusorai-task-tool-subtitle', subtitleText));
	// Breathing when sub-agent is running — main shows live process
	if (running) {
		const breath = element('span', 'crusorai-scaffold-crusor');
		breath.style.marginLeft = '6px';
		surface.append(breath);
	}

	card.append(surface);
	// Show full task prompt below subtitle so user can see what the sub-agent is doing (was only short "Research")
	const fullTask = firstString(args, ['prompt', 'task', 'description', 'goal']) ?? '';
	if (fullTask && fullTask !== description) {
		card.append(element('div', 'crusorai-task-tool-task', fullTask.slice(0, 500)));
	} else if (fullTask) {
		card.append(element('div', 'crusorai-task-tool-task', fullTask.slice(0, 500)));
	}
	if (childId) {
		const action = element('div', 'crusorai-task-tool-action', icon('arrow-up-right'));
		card.append(action);
	}

	return card;
}

function familyBody(tool: CrusorAIToolView, host: CrusorAIRenderHost): HTMLElement {
	const presentation = crusorAIToolPresentation(tool.name);
	if (presentation.family === 'terminal' || presentation.family === 'process') {
		return terminalBody(tool, host);
	}
	const args = record(tool.arguments);
	const result = resultRecord(tool.result);
	const body = element('div', `crusorai-tool-body crusorai-family-${presentation.family}`);
	body.dataset.rendererFamily = presentation.family;
	const target = displayTarget(tool);
	if (presentation.family === 'file-read') {
		const lines = firstString(result, ['lines', 'line_count']) ?? firstString(result, ['content'])?.split('\n').length?.toString() ?? '—';
		body.append(toolFields([['Path', target], ['Lines', lines], ['Encoding', 'UTF-8']]));
		const content = firstString(result, ['content']) ?? boundedText(tool.result, 800);
		body.append(element('pre', 'crusorai-tool-pre crusorai-code-preview', content.slice(0, 800)));
		body.append(element('div', 'crusorai-tool-actions', button('Open file', 'crusorai-link-button', () => host.revealFile(target), 'go-to-file'), copyButton(target, host)));
	} else if (presentation.family === 'file-write') {
		const rawText = firstString(result, ['diff']) ?? boundedText(result?.diff ?? tool.result, 600);
		const diff = rawText.includes('Diff preview:\n') ? rawText.split('Diff preview:\n')[1] : rawText;
		const receiptMatch = /lines added:\s*(\d+),\s*removed:\s*(\d+)/i.exec(typeof tool.result === 'string' ? tool.result : '');
		const stats = (receiptMatch ? { added: Number(receiptMatch[1]), removed: Number(receiptMatch[2]) } : undefined) ?? diffStats(diff);
		const rows: [string, string][] = [['File', target], ['Change', stats ? `+${stats.added} −${stats.removed}` : (firstString(result, ['change']) ?? '—')]];
		// 'syntax valid' was a second always-true row; only surface a receipt the
		// tool actually reported.
		const receipt = firstString(result, ['receipt', 'syntax']);
		if (receipt) { rows.push(['Receipt', receipt]); }
		body.append(toolFields(rows));
		body.append(diffPreview(diff));
		body.append(element('div', 'crusorai-tool-actions', button('Open native diff', 'crusorai-link-button', () => host.openDiff(tool.id), 'diff'), button('Reveal file', 'crusorai-link-button', () => host.revealFile(target), 'go-to-file')));
	} else if (presentation.family === 'search') {
		body.append(toolFields([['Query', target], ['Scope', 'workspace'], ['Matches', firstString(result, ['matches', 'count']) ?? '—']]));
		const matches = result?.matches ?? result?.results;
		if (Array.isArray(matches) && matches.length) {
			const list = element('div', 'crusorai-search-results');
			for (const m of matches.slice(0, 5)) list.append(element('div', 'crusorai-search-row', element('code', undefined, typeof m === 'string' ? m : boundedText(m, 80)), element('span', undefined, '')));
			body.append(list);
		} else {
			body.append(element('pre', 'crusorai-tool-pre', boundedText(result ?? tool.arguments, 500)));
		}
		body.append(element('div', 'crusorai-tool-actions', button('Open Search', 'crusorai-link-button', () => host.revealFile(target), 'search')));
	} else if (presentation.family === 'verification') {
		body.append(element('div', 'crusorai-tool-checks',
			element('div', undefined, icon('pass-filled'), element('span', undefined, 'Typecheck'), element('strong', undefined, tool.state === 'passed' ? 'passed' : tool.state === 'running' ? 'running' : 'queued')),
			element('div', undefined, tool.state === 'running' ? element('span', 'crusorai-mini-spinner') : icon('circle-outline'), element('span', undefined, 'Browser callback'), element('strong', undefined, tool.state === 'passed' ? 'passed' : tool.state === 'running' ? 'running' : 'queued')),
			element('div', undefined, icon('circle-outline'), element('span', undefined, 'Destination assertion'), element('strong', undefined, 'queued')),
		));
		body.append(element('div', 'crusorai-tool-actions', button('Open evidence', 'crusorai-link-button', () => void 0, 'beaker')));
	} else if (presentation.family === 'web') {
		body.append(toolFields([['URL', target], ['Status', firstString(result, ['status']) ?? '200 OK'], ['Received', firstString(result, ['size']) ?? '—']]));
		body.append(element('pre', 'crusorai-tool-pre', boundedText(result ?? tool.arguments, 500)));
		body.append(element('div', 'crusorai-tool-actions', button('Open source', 'crusorai-link-button', () => host.revealFile(target), 'link'), copyButton(target, host)));
	} else if (presentation.family === 'browser') {
		// Hermes backend receipts (browser_tools.py): honest per-tool fields.
		// The lab-era rows (a Page field and a hardcoded viewport — puppeteer
		// shapes of a backend that never ran on user machines), the fake
		// 'document' line, and the reveal-on-URL buttons are retired:
		// visible testing (owner 2026-09-07) shows the EVIDENCE here — the
		// screenshot image, the session recording, the ref the agent acted on.
		if (tool.name === 'browser_screenshot') {
			const raw = typeof tool.result === 'string' ? tool.result : '';
			const saved = /Screenshot saved:\s*([^\s(]+)/.exec(raw)?.[1];
			body.append(toolFields([
				['Saved', saved ?? '—'],
				['Quality', /visual quality passed/i.test(raw) ? 'passed' : tool.state === 'running' ? 'running' : tool.state === 'failed' ? 'failed' : '—'],
			]));
			if (saved) {
				const src = host.resourceSrc(saved);
				if (src) {
					const img = element('img', 'crusorai-browser-screenshot');
					img.src = src;
					img.alt = `Screenshot ${saved}`;
					body.append(img);
				}
				body.append(element('div', 'crusorai-tool-actions',
					button('Reveal screenshot', 'crusorai-link-button', () => host.revealFile(saved), 'device-camera'),
					copyButton(saved, host)));
			}
		} else if (tool.name === 'browser_navigate') {
			const recording = firstString(result, ['recording']);
			body.append(toolFields([
				['URL', firstString(args, ['url']) ?? target],
				['Title', firstString(result, ['title']) ?? '—'],
				['Elements', firstString(result, ['element_count']) ?? '—'],
			]));
			const snapshot = firstString(result, ['snapshot']);
			if (snapshot) { body.append(element('pre', 'crusorai-tool-pre', boundedText(snapshot, 600))); }
			if (recording) {
				// The visible-testing artifact (hermes record start/stop): one
				// click to watch what the agent did in the window.
				body.append(element('div', 'crusorai-tool-actions',
					button('Watch session recording', 'crusorai-link-button', () => host.revealFile(recording), 'device-camera'),
					copyButton(recording, host)));
			} else {
				body.append(element('div', 'crusorai-tool-actions',
					copyButton(firstString(args, ['url']) ?? target, host)));
			}
		} else if (tool.name === 'browser_click' || tool.name === 'browser_type' || tool.name === 'browser_press') {
			body.append(toolFields([
				['Element', firstString(args, ['ref']) ?? firstString(args, ['key']) ?? '—'],
				['Text', firstString(args, ['text']) ?? '—'],
				['Done', firstString(result, ['clicked', 'typed', 'pressed']) ?? (tool.state === 'passed' ? 'yes' : tool.state === 'failed' ? 'no' : '…')],
			]));
		} else if (tool.name === 'browser_console') {
			body.append(toolFields([
				['Expression', firstString(args, ['expression']) ?? '—'],
				['Messages', firstString(result, ['total_messages']) ?? '—'],
				['JS errors', firstString(result, ['total_errors']) ?? '—'],
			]));
			const evaluated = firstString(result, ['result']);
			if (evaluated) { body.append(element('pre', 'crusorai-tool-pre', boundedText(evaluated, 400))); }
		} else {
			body.append(toolFields([
				['URL', firstString(args, ['url']) ?? target],
				['Detail', firstString(result, ['count', 'scrolled', 'url', 'success']) ?? '—'],
			]));
			body.append(element('pre', 'crusorai-tool-pre', boundedText(result ?? tool.arguments, 400)));
		}
	} else if (presentation.family === 'plan') {
		// Field 2026-09-10: the body painted the raw {"steps":[...]} argument
		// JSON. hermes hoists todo parts into a status panel whose rows are
		// glyph+text (status-row.tsx: dashed ring pending, live dot
		// in_progress, pass-filled done, circle-slash cancelled) — the card
		// body ports those rows from the WRITTEN state (the tool result's
		// normalized list) with the call args as fallback.
		body.append(planListBody(tool, resultRecord(tool.result), args));
	} else if (presentation.family === 'session') {
		body.append(toolFields([['Query', target], ['Sessions', '2'], ['Model calls', '0']]));
		body.append(element('pre', 'crusorai-tool-pre', boundedText(result ?? tool.arguments, 400)));
	} else if (presentation.family === 'subagent' || tool.name.startsWith('delegate_to_subagent')) {
		// OpenCode parity: task-tool-card clickable navigation
		return taskToolCard(tool, host);
	} else if (presentation.family === 'code' || presentation.family === 'scaffold') {
		// Field 2026-09-10: this body hardcoded a fake RUNTIME value —
		// invented text on a JS scaffolding call. The card shows the call's
		// OWN fields and the honest state, nothing else.
		const scaffoldFields: (readonly [string, string])[] = [];
		const targetPath = firstString(args, ['path', 'project_path', 'projectPath', 'directory', 'dir']);
		if (targetPath) { scaffoldFields.push(['Location', targetPath]); }
		const template = firstString(args, ['template', 'framework', 'stack']);
		if (template) { scaffoldFields.push(['Template', template]); }
		scaffoldFields.push(['Status', stateLabel(tool.state)]);
		body.append(toolFields(scaffoldFields));
		const detail = result ?? boundedText(tool.arguments, 400);
		if (detail) { body.append(element('pre', 'crusorai-tool-pre crusorai-terminal-output', boundedText(detail, 600).slice(0, 700))); }
	} else {
		// Generic families: a STRING result is model prose (think reasoning,
		// salvage notes). Render it through the same markdown pass as
		// assistant copy, inside the hermes expandable (cap + fade + chevron).
		// The old raw JSON dump leaked `**Thinking:**` and \n escapes into
		// the panel (owner verdict: disgusting). Arguments stay reachable,
		// collapsed, honestly labeled.
		const resultText = typeof tool.result === 'string' ? tool.result : '';
		// Models often self-announce ("**Thinking:** ...") — the card title
		// already says what the tool is, so a duplicated label is fake chrome.
		// Presentation-only strip of the leading self-labels.
		// Both self-announce shapes leak in the field: "💭 **Thinking:**" and
		// "**Thinking:**" — the label marker may sit on either side of the
		// bold wrapper (and the 💭 on either side of the label). One pattern
		// per position, tolerant of order.
		const prose = resultText
			.replace(/^\s*(?:\*\*)?\s*💭?\s*(?:\*\*)?\s*thinking\s*:?\s*(?:\*\*)?\s*:?\s*/i, '')
			.replace(/^\s*💭\s+/, '')
			.replace(/^\s*(?:\*\*)?\s*reasoning\s*:?\s*(?:\*\*)?\s*:?\s*/i, '');
		if (prose.trim()) {
			if (tool.name === 'think') {
				// Hermes thought body: small, dim, quiet scaffold — never a
				// full-width prose block competing with the answer.
				body.append(expandableOutput(element('div', 'crusorai-thought-body', markdownCopy(prose))));
			} else {
				body.append(expandableOutput(markdownCopy(prose)));
			}
			if (tool.name !== 'think') {
				// Hermes thought cards carry ONLY the thought — an "Arguments"
				// disclosure under a thinking row is chrome the user never asked
				// to open (field screenshot 2026-09-05).
				const argsDetails = element('details', 'crusorai-tool-args-details') as HTMLDetailsElement;
				argsDetails.append(element('summary', 'crusorai-tool-args-summary', 'Arguments'));
				argsDetails.append(labeledPayload('Arguments', tool.arguments));
				body.append(argsDetails);
			}
		} else {
			body.append(labeledPayload('Details', { arguments: tool.arguments, result: tool.result }));
		}
	}
	const fileTarget = firstString(tool.arguments, ['path', 'file_path', 'resource']);
	if (fileTarget && presentation.family !== 'file-read' && presentation.family !== 'file-write') {
		if (!body.querySelector('.crusorai-tool-actions')) body.append(element('div', 'crusorai-tool-actions', button('Open file', 'crusorai-link-button', () => host.revealFile(fileTarget), 'go-to-file')));
	}
	return body;
}

function toolRow(tool: CrusorAIToolView, host: CrusorAIRenderHost, openTools: Set<string>, pendingClarify?: CrusorAIRenderModel['clarify']): HTMLDetailsElement {
	// Hermes (message-parts ChainToolFallback): a clarify call renders its own
	// widget card — the interactive question while it blocks, the settled Q&A
	// after — never a generic collapsible tool row.
	if (tool.name === 'clarify' && pendingClarify !== undefined) {
		// The card is a widget, not a disclosure row; the toolSection slot
		// only appends HTMLElements, so the cast keeps the signature honest.
		return clarifyCard(tool, host, openTools, pendingClarify) as unknown as HTMLDetailsElement;
	}
	const presentation = crusorAIToolPresentation(tool.name);
	const isPending = tool.state === 'running' || tool.state === 'queued';
	const details = element('details', `crusorai-tool-row is-${tool.state}`);
	details.dataset.component = 'tool-trigger';
	details.dataset.conversationScaffold = '';
	details.dataset.toolId = tool.id;
	details.dataset.toolName = tool.name;
	const shouldDefaultOpen = presentation.defaultOpen === 'always' || (presentation.defaultOpen === 'running' && (tool.state === 'running' || tool.state === 'approval'));
	details.open = openTools.has(tool.id) || shouldDefaultOpen;

	// Hermes wording (ThinkingDisclosure): a live block says "Thinking", a
	// settled one says "Thought" — the tool catalog title stays canonical for
	// other surfaces; the transcript row speaks hermes.
	const rowTitle = tool.name === 'think' ? (isPending ? 'Thinking' : 'Thought') : presentation.title;
	const titleSpan = element('strong', isPending ? 'crusorai-shimmer' : undefined, rowTitle);
	const targetText = displayTarget(tool);
	// Hermes quiet-card rule: the target echo must SAY something. When it
	// just repeats the tool name ("Think think"), it is noise — drop it.
	const targetMeaningful = !!targetText
		&& targetText.toLowerCase() !== tool.name.toLowerCase()
		&& targetText.toLowerCase() !== presentation.title.toLowerCase();
	const summary = element('summary', 'crusorai-tool-summary',
		tool.name === 'think' ? element('span', 'crusorai-glyph-spacer') : statusGlyph(tool.state),
		icon(presentation.icon),
		titleSpan,
		targetMeaningful ? element('span', 'crusorai-tool-target', targetText) : undefined,
		tool.duration ? element('span', 'crusorai-tool-duration', tool.duration) : undefined,
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
function toolSection(tools: readonly CrusorAIToolView[], host: CrusorAIRenderHost, openTools: Set<string>, live: boolean, showHeading = true, pendingClarify?: CrusorAIRenderModel['clarify']): HTMLElement {
	const section = element('section', 'crusorai-tool-list');
	section.dataset.component = 'tool-list';
	if (showHeading) {
		section.append(element('div', 'crusorai-section-heading',
			element('span', undefined, 'Actions'),
			element('span', 'crusorai-section-count', String(tools.length)),
		));
	}

	const groups = splitRunGroups(tools);
	// Hermes: a SINGLE action is one bare row — never a collapsible run group
	// with a "(1)" count bubble wrapping its own duplicate header (owner
	// screenshot 2026-09-04: "Running dir /b (1)" over a "Terminal dir /b"
	// card said the same thing twice). Only 2+ calls earn a run summary.
	if (groups.length === 1 && groups[0].kind === 'run' && groups[0].tools.length === 1) {
		section.append(toolRow(groups[0].tools[0], host, openTools, pendingClarify));
		return section;
	}
	for (const group of groups) {
		if (group.kind === 'card') {
			section.append(toolRow(group.tool, host, openTools, pendingClarify));
			continue;
		}
		const runTools = group.tools;
		const key = runTools[0]?.id ?? `run-${group.start}`;
		const runLive = live && runTools.some(tool => tool.state === 'running' || tool.state === 'queued');
		const details = element('details', `crusorai-tool-run${runLive ? ' is-live' : ''}`) as HTMLDetailsElement;
		details.dataset.component = 'tool-run';
		details.dataset.conversationScaffold = '';
		details.dataset.runKey = key;
		details.open = runLive || openTools.has(key);
		details.addEventListener('toggle', () => {
			if (details.open) { openTools.add(key); } else { openTools.delete(key); }
		});
		const summary = element('summary', 'crusorai-tool-run-summary',
			runLive ? element('span', 'crusorai-mini-spinner') : icon('tools'),
			element('span', 'crusorai-tool-run-text', summarizeToolRun(runTools, runLive, tool => compactTarget(displayTarget(tool)) ?? tool.name)),
			element('span', 'crusorai-tool-run-count', String(runTools.length)),
		);
		details.append(summary);
		const body = element('div', 'crusorai-tool-run-body');
		for (const tool of runTools) { body.append(toolRow(tool, host, openTools, pendingClarify)); }
		details.append(body);
		section.append(details);
	}
	return section;
}


function engineStatus(model: CrusorAIRenderModel): HTMLElement {
	const state = model.engineState;
	const tone = state === 'ready' ? 'ready' : state === 'starting' ? 'running' : state === 'crashed' || state === 'degraded' ? 'failed' : 'idle';
	const chip = element('span', `crusorai-engine-status is-${tone}`, element('span', 'crusorai-status-dot'), state === 'ready' ? 'Crusor ready' : `Engine ${state}`);
	let engineTitle = '';
	if (model.engineBuild && model.engineBuild !== 'unknown') {
		const short = model.engineBuild.split(/\s+/)[0];
		chip.append(element('span', 'crusorai-engine-build', short));
		engineTitle = `Engine build: ${model.engineBuild}`;
	}
	// Freshness stamp next to the engine hash (see CRUSORAI_UI_STAMP): the
	// engine chip alone could not catch the 2026-09-08 field round where the
	// engine rebuilt but the workbench JS did not. An engine build dated
	// AFTER this stamp means the compiled workbench predates the engine.
	const engineDate = /\b\d{4}-\d{2}-\d{2}\b/.exec(model.engineBuild ?? '')?.[0];
	const stale = !!engineDate && engineDate > CRUSORAI_UI_STAMP;
	chip.append(element('span', 'crusorai-engine-build', `ui ${CRUSORAI_UI_STAMP}${stale ? ' STALE' : ''}`));
	const uiTitle = `Workbench UI build: ${CRUSORAI_UI_STAMP}`;
	chip.title = engineTitle ? `${uiTitle} · ${engineTitle}` : uiTitle;
	if (stale) {
		chip.title = `Workbench UI build ${CRUSORAI_UI_STAMP} is OLDER than the engine build (${model.engineBuild}) — the engine rebuilt, the desktop workbench did not. Recompile the desktop app to pick up the current UI.`;
	}
	return chip;
}

/** Hermes' todo tone rules (ui-tui todoTone / desktop composer-status): the
 *  row's own status drives the glyph -- the strip never guesses from the
 *  row index again. */
function planStepGlyph(status: CrusorAIPlanStepView['status']): HTMLElement {
	if (status === 'in_progress') { return element('span', 'crusorai-mini-spinner'); }
	if (status === 'completed') { return icon('pass-filled'); }
	if (status === 'failed') { return icon('circle-slash'); }
	const ring = element('span', 'crusorai-todo-ring');
	ring.setAttribute('aria-hidden', 'true');
	return ring;
}

function planStrip(model: CrusorAIRenderModel, open: boolean | undefined, onToggle: (open: boolean) => void): HTMLElement | undefined {
	if (!model.plan.length) { return undefined; }
	const done = model.plan.filter(s => s.status === 'completed').length;
	const anyActive = model.plan.some(s => s.status === 'in_progress');
	const details = element('details', 'crusorai-plan-strip') as HTMLDetailsElement;
	details.dataset.component = 'plan-strip';
	details.open = open ?? model.running;
	details.addEventListener('toggle', () => onToggle(details.open));
	const summary = element('summary', 'crusorai-plan-strip-summary',
		icon('list-ordered'),
		element('strong', undefined, 'Plan'),
		element('span', undefined, `${done}/${model.plan.length}`),
		model.running && anyActive ? element('span', 'crusorai-plan-strip-state', element('span', 'crusorai-mini-spinner'), 'In progress') : undefined,
		icon('chevron-down'),
	);
	const list = element('ol', 'crusorai-plan-strip-list');
	for (const step of model.plan) {
		list.append(element('li', `is-${step.status}`,
			planStepGlyph(step.status),
			element('span', undefined, step.text),
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
const thoughtKey = (model: CrusorAIRenderModel): string => `thought:${model.sessionId ?? 'session'}`;

function createActivityState(tick: () => void) {
	let lastSignature = '';
	let quietSince: number | undefined;
	let verb = '';
	let revealed = false;
	let quietTimer: ReturnType<typeof setTimeout> | undefined;
	let revealTimer: ReturnType<typeof setTimeout> | undefined;
	let ticker: ReturnType<typeof setInterval> | undefined;

	return {
		sync(model: CrusorAIRenderModel): void {
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
		row(model: CrusorAIRenderModel): HTMLElement | undefined {
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
			const row = element('div', 'crusorai-scaffold-status');
			row.dataset.conversationScaffold = '';
			row.dataset.slot = slot;
			row.setAttribute('aria-label', hint || UNNAMED_WAIT_LABEL);
			row.setAttribute('aria-live', 'polite');
			row.setAttribute('role', 'status');
			const breathe = element('span', 'crusorai-scaffold-crusor');
			breathe.setAttribute('aria-hidden', 'true');
			const meta = element('span', 'crusorai-scaffold-meta', element('span', undefined, formatElapsed(seconds)));
			row.append(breathe, ...(hint ? [element('span', 'crusorai-shimmer crusorai-scaffold-hint', hint)] : []), meta);
			return row;
		},
		/**
		 * How long the CURRENT turn's thinking ran, once it has stopped running. The measurement
		 * is armed while the last thing the turn produced is a thought and closed the moment the
		 * turn moves on, so the number survives every repaint of the row that watched it.
		 */
		thoughtSeconds(model: CrusorAIRenderModel): number | undefined {
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
function thinkingBlock(reasoning: string, openTools: Set<string>, live: boolean, seconds?: number, partKey?: string): HTMLElement {
	reasoning = separateGluedReasoningBlocks(reasoning);
	const key = partKey || 'thought';
	const details = element('details', 'crusorai-thought-row') as HTMLDetailsElement;
	details.dataset.component = 'disclosure';
	details.dataset.conversationScaffold = '';
	details.dataset.disclosureKey = key;
	details.open = true;
	details.addEventListener('toggle', () => {
		if (details.open) { openTools.add(key); } else { openTools.delete(key); }
	});
	// Split accumulated reasoning into separate blocks (one per LLM call)
	const body = element('div', 'crusorai-thought-body');
	const blocks = reasoning.split(/\n\n---\n\n/);
	for (const block of blocks) {
		const trimmed = block.trim();
		if (trimmed) {
			body.append(element('p', undefined, trimmed));
		}
	}
	details.append(
		element('summary', 'crusorai-disclosure-row',
			element('span', 'crusorai-disclosure-stack',
				icon('brain'),
				element('strong', live ? 'crusorai-shimmer' : undefined, live ? 'Thinking' : 'Thought'),
			),
			seconds !== undefined ? element('span', 'crusorai-scaffold-meta', formatElapsed(seconds)) : undefined,
			element('span', 'crusorai-disclosure-caret', '\u25be'),
		),
		body,
	);
	return details;
}

/**
 * One assistant turn: label, thinking disclosure, then the ORDERED timeline —
 * hermes message-parts.tsx walks message.parts at their arrival index, so a
 * work-then-answer turn reads top-to-bottom in the order the model produced
 * it: tool cards where the calls happened, final wording LAST. Tool bodies
 * come from the view map; a tool whose start frame was missed still paints
 * (after the timeline) so a card can never silently vanish.
 */
function assistantTurn(
	spec: {
		reasoningParts: readonly { readonly text: string; readonly completedAt?: number }[];
		assistantText: string;
		parts: readonly CrusorAITurnPart[];
		tools: readonly CrusorAIToolView[];
		live: boolean;
		current?: boolean;
		thoughtSeconds?: number;
		cancelRequested?: boolean;
		clarify?: CrusorAIRenderModel['clarify'];
		turnKey?: string;
	},
	host: CrusorAIRenderHost,
	openTools: Set<string>,
): HTMLElement {
	const live = spec.live;
	const response = element('section', `crusorai-assistant-message${live ? ' crusorai-breathing-edge is-streaming' : ''}`);
	if (spec.current) { response.dataset.component = 'session-turn'; }
	response.append(element('div', 'crusorai-assistant-label', icon('crusor'), element('strong', undefined, 'Crusor'), live ? element('span', 'crusorai-stream-label', spec.cancelRequested ? 'Stopping.' : 'Working') : undefined));
	// Reasoning parts are tracked INLINE in the parts array (kind='reasoning') so their
	// chronological position relative to text and tools is always preserved exactly.
	// This mirrors the Hermes approach (message.content is a single ordered array).
	const reasoningParts = (spec.reasoningParts || []).filter(p => p && p.text);
	// Parts are the ordering source. A turn that predates them (or somehow
	// carries text without a single text part) falls back to the legacy
	// single-block paint so the answer can never be dropped by a missing
	// timeline.
	const parts = spec.parts.length
		? spec.parts
		: (spec.assistantText ? [{ kind: 'text' as const, text: spec.assistantText }] : []);
	const toolsById = new Map(spec.tools.map(t => [t.id, t]));
	let lastTextIndex = -1;
	for (let i = 0; i < parts.length; i++) {
		const part = parts[i];
		if (part.kind === 'text' && part.text) { lastTextIndex = i; }
	}
	// The streaming slot rides the LAST text segment only: the painter's fast
	// path patches exactly that node per token; earlier segments are frozen.
	let run: CrusorAIToolView[] = [];
	const flushRun = () => {
		if (!run.length) { return; }
		response.append(toolSection(run, host, openTools, live, false, spec.clarify));
		run = [];
	};
	parts.forEach((part, index) => {
		if (part.kind === 'reasoning') {
			// Flush any accumulated tool run BEFORE the reasoning block (preserves order)
			flushRun();
			const rp = reasoningParts[part.reasoningIndex];
			if (rp && rp.text) {
				// A reasoning block is "live" (spinner + growing text) only when it is the
				// last part in the timeline and the turn is still running.
				const isLastPart = index === parts.length - 1;
				response.append(thinkingBlock(rp.text, openTools, live && isLastPart, spec.thoughtSeconds, `${spec.turnKey || 'turn'}:${part.reasoningIndex}`));
			}
			return;
		}
		if (part.kind === 'tool') {
			const tool = toolsById.get(part.toolId);
			if (tool) { run.push(tool); }
			return;
		}
		if (!part.text) { return; }
		flushRun();
		response.append(markdownCopy(part.text, spec.current && index === lastTextIndex ? 'session-turn-content' : undefined));
	});
	flushRun();
	// A tool with no part (a replay that lost its start frame) must still show.
	const inTimeline = new Set(parts.filter(p => p.kind === 'tool').map(p => p.toolId));
	const orphans = spec.tools.filter(t => !inTimeline.has(t.id));
	if (orphans.length) { response.append(toolSection(orphans, host, openTools, live, false, spec.clarify)); }
	if (spec.assistantText && lastTextIndex < 0) {
		response.append(markdownCopy(spec.assistantText, spec.current ? 'session-turn-content' : undefined));
	}
	if (spec.assistantText && !live) { response.append(copyButton(spec.assistantText, host)); }
	return response;
}

function transcript(model: CrusorAIRenderModel, host: CrusorAIRenderHost, openTools: Set<string>, liveThoughtSeconds?: number): HTMLElement {
	const scroll = element('div', 'crusorai-transcript-scroll');
	const lane = element('div', 'crusorai-transcript-lane');
	// History: previous turns (user → agent) preserved wireframe style, no breathing
	for (const turn of model.history) {
		if (turn.userMessage) lane.append(element('div', 'crusorai-user-message', turn.userMessage));
		if (turn.assistantText || turn.parts.length || turn.tools.length) {
			lane.append(assistantTurn({
				reasoningParts: turn.reasoningParts,
				assistantText: turn.assistantText,
				parts: turn.parts,
				tools: turn.tools,
				live: false,
				turnKey: `history:${model.sessionId || 's'}`,
			}, host, openTools));
		}
		if (turn.subAgents.length) {
			const subAgents = element('section', 'crusorai-subagent-list');
			subAgents.append(element('div', 'crusorai-section-heading', element('span', undefined, 'Sub-Agents'), element('span', 'crusorai-section-count', String(turn.subAgents.length))));
			for (const subAgent of turn.subAgents) {
				const row = element('div', `crusorai-subagent-row is-${subAgent.state}`, element('span', undefined, ''), element('span', 'crusorai-subagent-goal', subAgent.goal ?? 'Sub-agent task'), element('span', `crusorai-subagent-state is-${subAgent.state}`, subAgent.state));
				if (subAgent.duration) row.append(element('span', 'crusorai-subagent-duration', subAgent.duration));
				subAgents.append(row);
			}
			lane.append(subAgents);
		}
		// Hermes pattern: no green confetti for success -- the answer IS the
		// completion receipt. Only real deviations (cancelled, failed) get a row.
		if (turn.turnOutcome === 'cancelled' || turn.turnOutcome === 'failed') {
			const label = turn.turnOutcome === 'cancelled' ? 'Run cancelled' : 'Run failed';
			const iconName = turn.turnOutcome === 'cancelled' ? 'circle-slash' : 'error';
			lane.append(element('div', `crusorai-turn-receipt is-${turn.turnOutcome}`, icon(iconName), element('span', undefined, label)));
		}
		// same closing rollup for past turns (first-touched order, +/- summed)
		const turnFiles = deriveChangedFiles(turn.tools);
		if (turnFiles.length) {
			const card = element('div', 'crusorai-changed-files');
			card.dataset.component = 'changed-files';
			card.append(element('div', 'crusorai-changed-files-head',
				element('span', undefined, `${turnFiles.length} file${turnFiles.length === 1 ? '' : 's'} changed`)));
			const rows = element('div', 'crusorai-changed-files-rows');
			for (const file of turnFiles) {
				const row = element('div', 'crusorai-changed-file-row is-activatable',
					icon('file'),
					element('span', 'crusorai-changed-file-name', file.name),
					element('span', 'crusorai-diff-count',
						element('span', 'is-added', `+${file.added}`),
						element('span', 'is-removed', `−${file.removed}`)));
				row.title = file.path;
				const target = file.path;
				row.addEventListener('click', () => host.revealFile(target));
				rows.append(row);
			}
			card.append(rows);
			lane.append(card);
		}
	}
	// Current turn (breathing when running)
	if (model.userMessage) {
		lane.append(element('div', 'crusorai-user-message', model.userMessage));
	}
	// No assistant text means there is nothing to narrate. The line used to fall back to a sentence
	// claiming the agent was inspecting the workspace, which the turn had never done -- so a run that
	// died on a provider error still printed confident progress. The spinner and the 'Working' label
	// already say the only true thing: the turn is open.
	if (model.assistantText || model.reasoningParts.length || model.running || model.parts.length || model.tools.length) {
		lane.append(assistantTurn({
			reasoningParts: model.reasoningParts,
			assistantText: model.assistantText,
			parts: model.parts,
			tools: model.tools,
			live: model.running,
			current: true,
			thoughtSeconds: liveThoughtSeconds,
			cancelRequested: model.cancelRequested,
			clarify: model.clarify,
			turnKey: `current:${model.sessionId || 's'}`,
		}, host, openTools));
	}
	if (model.subAgents.length) {
		const subAgents = element('section', 'crusorai-subagent-list');
		subAgents.dataset.component = 'subagent-list';
		subAgents.append(element('div', 'crusorai-section-heading', element('span', undefined, 'Sub-Agents'), element('span', 'crusorai-section-count', String(model.subAgents.length))));
		for (const subAgent of model.subAgents) {
			const state = subAgent.state;
			const desc = (subAgent as any).description ?? subAgent.goal ?? 'Sub-agent task';
			const childId = (subAgent as any).childThreadId ?? subAgent.id;
			const isRunning = state === 'running' || state === 'pending';
			const row = element('div', `crusorai-subagent-row is-${state}${childId ? ' is-clickable' : ''}`);
			if (childId) {
				row.dataset.sessionId = childId;
				row.tabIndex = 0;
				row.setAttribute('role', 'button');
				row.addEventListener('click', () => { if (host.navigateToSession) host.navigateToSession(childId); });
				row.addEventListener('keydown', (e: KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (host.navigateToSession) host.navigateToSession(childId); } });
			}
			const iconEl = isRunning ? element('span', 'crusorai-mini-spinner') : icon(state === 'completed' ? 'pass-filled' : state === 'failed' ? 'error' : state === 'cancelled' ? 'circle-slash' : 'circle-outline');
			const goalEl = element('span', 'crusorai-subagent-goal', desc);
			goalEl.style.setProperty('--task-agent-color', agentColor((subAgent as any).agentName ?? subAgent.mode ?? 'general'));
			row.append(iconEl, goalEl, element('span', `crusorai-subagent-state is-${state}`, state));
			if ((subAgent as any).background) row.append(element('span', 'crusorai-subagent-badge', 'bg'));
			if ((subAgent as any).toolCalls) row.append(element('span', 'crusorai-subagent-calls', `${(subAgent as any).toolCalls} calls`));
			if (subAgent.duration) row.append(element('span', 'crusorai-subagent-duration', subAgent.duration));
			if (childId) row.append(element('span', 'crusorai-subagent-action', icon('arrow-up-right')));
			subAgents.append(row);
		}
		lane.append(subAgents);
	}
	if (model.turnOutcome === 'cancelled' || model.turnOutcome === 'failed') {
		const label = model.turnOutcome === 'cancelled' ? 'Run cancelled' : 'Run failed';
		const iconName = model.turnOutcome === 'cancelled' ? 'circle-slash' : 'error';
		lane.append(element('div', `crusorai-turn-receipt is-${model.turnOutcome}`, icon(iconName), element('span', undefined, label)));
	}
	// hermes changed-files-card: the turn-closing "N files changed" rollup.
	const changed = changedFilesCard(model, host);
	if (changed) { lane.append(changed); }
	if (model.voiceHeard) {
		const heard = model.voiceHeard;
		if (heard.ok) {
			lane.append(element('div', 'crusorai-context-status-row is-info', icon('lightbulb'),
				element('span', undefined, `\u{1F3A4} Heard: ${heard.text.slice(0, 200)}`)));
		} else {
			lane.append(element('div', 'crusorai-context-status-row is-warning', icon('warning'),
				element('span', undefined, `\u{1F3A4} Voice error: ${heard.error ?? 'unknown'}`)));
		}
	}
	if (model.degraded) {
		lane.append(element('div', 'crusorai-context-status-row is-warning', icon('warning'),
			element('span', undefined, model.degraded)));
	}
	// Hermes port (assistant-ui/thread/status.tsx ResponseLoadingIndicator):
	// while the turn runs, the TAIL carries one activity row -- crusor dot +
	// wait hint + LIVE elapsed seconds. Turn ended -> the row is gone;
	// history turns never grow one (tail-only rule). The hint names REAL
	// state, never a guess: a live tool card means the tool is the thing
	// working (owner run: the row claimed "Waiting on the model" for 4min
	// while dir /s /b was the one grinding); only a truly idle gap between
	// tool and model may fall through to the generic text.
	if (model.running && !model.llmReasoningLive) {
		// `llmReasoningLive`: the Thinking card is the live activity — the row
		// would narrate the same wait twice (field 2026-09-17: while the model
		// thinks, the tail showed both a Thinking card and an Asking… row).
		const liveTool = [...model.tools].reverse().find(tool => tool.state === 'running' || tool.state === 'queued');
		let hint: string;
		let stalled = model.stalled === true;
		if (liveTool) {
			const target = compactTarget(displayTarget(liveTool)) ?? liveTool.name;
			hint = liveTool.state === 'queued'
				? `Queued: ${liveTool.name}\u2026`
				: `Running ${target}\u2026`;
		} else if (model.llmStatus) {
			const attempt = model.llmStatus.attempt > 1 ? ` \u2014 attempt ${model.llmStatus.attempt}` : '';
			hint = `Asking ${model.llmStatus.model || 'model'}${attempt}\u2026`;
		} else if (model.stalled) {
			// Hermes wording discipline: silence is not completion and not an
			// error — state the fact and keep the Stop option, without
			// screaming failure or pretending progress.
			hint = 'No activity for 5:00 \u2014 the turn is still running, but nothing has arrived.';
			stalled = true;
		} else {
			hint = 'Waiting on the model\u2026';
		}
		const row = element('div', `crusorai-context-status-row is-info crusorai-activity-row${stalled ? ' is-stalled' : ''}`);
		row.append(element('span', 'crusorai-activity-dot'));
		row.append(element('span', undefined, hint));
		row.append(elapsedSpan(model.turnStartedAt));
		lane.append(row);
		// The anatomy inspector: the LIVE request, role+head per message —
		// "why 8 messages for hi?" becomes one click in the product, not a
		// chat question. Data rides the llm.request frame (factory caps the
		// heads); display slices are presentation guards only.
		const heads = model.llmHeads ?? [];
		if (heads.length) {
			const anatomy = element('details', 'crusorai-llm-anatomy') as HTMLDetailsElement;
			anatomy.append(element('summary', 'crusorai-llm-anatomy-summary',
				element('span', undefined, `What the model sees \u2014 ${heads.length} message${heads.length === 1 ? '' : 's'}`),
			));
			const list = element('div', 'crusorai-llm-anatomy-list');
			for (const head of heads.slice(0, 32)) {
				const roleLabel = head.role === 'human' ? 'user'
					: head.role === 'ai' ? 'assistant' : head.role;
				list.append(element('div', 'crusorai-llm-anatomy-row',
					element('span', `crusorai-llm-anatomy-role is-${roleLabel}`, roleLabel),
					element('code', 'crusorai-llm-anatomy-head', (head.head || '').replace(/\s+/g, ' ').slice(0, 140)),
				));
			}
			anatomy.append(list);
			lane.append(anatomy);
		}
	}
	if (model.contextStatus) {
		const status = model.contextStatus;
		const percent = typeof status.usagePercent === 'number' && status.usagePercent > 0
			? ` (${Math.min(100, Math.round(status.usagePercent))}% of the context window)`
			: '';
		lane.append(element('div', `crusorai-context-status-row is-${status.severity}`,
			icon(status.severity === 'warning' ? 'warning' : 'lightbulb'),
			element('span', undefined, status.message + percent)));
	}
	if (model.engineFault) {
		const fault = model.engineFault;
		const followUp = fault.retrying
			? ` Retrying automatically (attempt ${fault.attempts + 1} of 3).`
			: ' Crusor stopped retrying on its own.';
		lane.append(element('div', 'crusorai-error-row is-engine-fault', icon('error'),
			element('span', undefined, fault.message + followUp),
			button('Retry engine', 'crusorai-link-button', host.retryEngine),
		));
	}
	if (model.error) {
		const setup = model.engineSetupError;
		lane.append(element('div', 'crusorai-error-row', icon(setup ? 'settings-gear' : 'warning'),
			element('span', undefined, setup ? `Crusor engine setup: ${model.error}` : model.error),
			setup
				? button('Open Settings', 'crusorai-link-button', host.openEngineSettings, 'settings-gear')
				: button('Retry', 'crusorai-link-button', host.retryEngine),
		));
	}
	// OpenCode parity: child view lock banner + agent-designed prompt as user message
	if (model.isChild) {
		// Show the agent's delegated task as the first user bubble — not the original user prompt
		const delegatedTask = (model as any).userMessage || (model as any).subAgentGoal || '';
		if (delegatedTask) {
			lane.append(element('div', 'crusorai-user-message', delegatedTask.slice(0, 800)));
		}
		const banner = element('div', 'crusorai-child-banner');
		banner.dataset.component = 'child-banner';
		banner.append(icon('info'), element('span', undefined, 'Sub-agent session — prompt disabled'));
		if (model.parentSessionId && host.navigateToSession) {
			const parentId = model.parentSessionId;
			banner.append(button('Back to Parent', 'crusorai-link-button', () => host.navigateToSession!(parentId), 'arrow-left'));
		}
		lane.append(banner);
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
function emptyState(model: CrusorAIRenderModel, host: CrusorAIRenderHost): HTMLElement | undefined {
	if (model.running || model.history.length || model.userMessage || model.assistantText || model.tools.length) { return undefined; }
	if (model.engineSetupError || model.noWorkspace || model.workspaceSelectionRequired) { return undefined; }
	const wrap = element('section', 'crusorai-empty-state');
	wrap.dataset.component = 'empty-state';
	wrap.append(
		element('div', 'crusorai-section-heading', element('span', undefined, 'Crusor Agent')),
		element('p', 'crusorai-empty-copy', 'Ask for a change, or start from one of these. Every file write is consent-checked: git can undo it, so it just runs; git cannot, so it asks.'),
	);
	const grid = element('div', 'crusorai-starter-grid');
	for (const prompt of STARTER_PROMPTS) {
		grid.append(button(prompt, 'crusorai-starter-prompt', () => host.submitPrompt(prompt), 'arrow-right'));
	}
	wrap.append(grid);
	return wrap;
}

function approvalDock(model: CrusorAIRenderModel, host: CrusorAIRenderHost): HTMLElement | undefined {
	if (!model.approval) { return undefined; }
	const approval = model.approval;
	ensureGlobalCardKeys();
	const dock = element('section', 'crusorai-approval-dock');
	dock.dataset.component = 'approval-dock';
	dock.dataset.toolId = approval.toolId;

	// Hermes ApprovalBar (apps/desktop/.../tool/approval.tsx), ported shape for
	// shape: a compact split pill [Run ⌘⏎ | ▾] under the pending tool row, a
	// separate Reject ghost with its Esc hint, a Command disclosure revealing
	// the full call, and "Always allow" behind a confirm dialog. The ▾ menu —
	// Allow for session / Always allow… / Reject — is the piece the old flat
	// button row was missing.
	const commandText = approvalCommandText(approval.name, approval.diff);
	const diffRecord = (approval.diff && typeof approval.diff === 'object') ? approval.diff as Record<string, unknown> : undefined;
	const diffString = typeof approval.diff === 'string' ? approval.diff : (typeof diffRecord?.diff === 'string' ? diffRecord.diff : undefined);
	const diffStatistics = diffString ? diffStats(diffString) : undefined;
	const isShell = approval.name === 'run_terminal' || approval.name === 'start_terminal' || approval.name === 'terminal' || approval.name === 'execute_code' || diffRecord?.kind === 'shell';

	let inlineDiffCard: HTMLElement | undefined;
	if (diffString) {
		const targetPath = (diffRecord && (diffRecord.relative_path || diffRecord.path))
			? String(diffRecord.relative_path || diffRecord.path)
			: displayTarget({ id: approval.toolId, name: approval.name, state: 'approval', arguments: approval.diff });
		const action = typeof diffRecord?.action === 'string' ? diffRecord.action : 'modify';
		const actionLabel = action === 'create' ? 'Create' : action === 'delete' ? 'Delete' : action === 'copy' ? 'Copy' : 'Edit';

		const header = element('div', 'crusorai-approval-diff-header',
			element('span', 'crusorai-approval-action-badge', actionLabel),
			element('span', 'crusorai-approval-file-path', targetPath),
		);
		if (diffStatistics) {
			const count = element('span', 'crusorai-diff-count');
			if (diffStatistics.added > 0) { count.append(element('span', 'is-added', `+${diffStatistics.added}`)); }
			if (diffStatistics.removed > 0) { count.append(element('span', 'is-removed', `−${diffStatistics.removed}`)); }
			header.append(count);
		}
		inlineDiffCard = element('div', 'crusorai-approval-diff-preview', header, diffPreview(diffString));
	}

	let warningBox: HTMLElement | undefined;
	if (approval.warning) {
		warningBox = element('div', 'crusorai-approval-warning', icon('shield'), element('span', undefined, approval.warning));
	}

	let shellRiskBadge: HTMLElement | undefined;
	if (isShell) {
		const riskText = typeof diffRecord?.risk === 'string' ? diffRecord.risk : undefined;
		if (riskText) {
			shellRiskBadge = element('div', 'crusorai-approval-risk-badge', icon('shield'), element('span', undefined, riskText));
		}
	}

	const runButton = button('Run', 'crusorai-approval-run', () => host.replyToSafety(approval.toolId, true), 'check');
	runButton.dataset.approveOnce = '';
	hinted(runButton, 'Allow this call only.');
	const runHint = element('span', 'crusorai-approval-kbd', isMac() ? '⌘⏎' : 'Ctrl⏎');
	runButton.append(runHint);

	const menu = element('div', 'crusorai-approval-menu');
	menu.append(
		button('Allow for session', 'crusorai-approval-menu-item', () => {
			// The client protocol has carried `always_allow` since the start and the
			// bridge honours it, but no control ever sent it before the hermes bar:
			// every ordinary write re-prompted for the rest of the session.
			menu.classList.remove('is-open');
			host.replyToSafety(approval.toolId, true, true);
		}, 'pass-filled'),
		button('Always allow…', 'crusorai-approval-menu-item', () => {
			menu.classList.remove('is-open');
			overlay.classList.add('is-open');
		}, 'shield'),
		button('Reject', 'crusorai-approval-menu-item is-destructive', () => {
			menu.classList.remove('is-open');
			host.replyToSafety(approval.toolId, false);
		}, 'close'),
	);

	const menuTrigger = element('button', 'crusorai-approval-more') as HTMLButtonElement;
	menuTrigger.type = 'button';
	menuTrigger.setAttribute('aria-label', 'More options');
	menuTrigger.setAttribute('aria-expanded', 'false');
	menuTrigger.append(icon('chevron-down'));
	menuTrigger.addEventListener('click', event => {
		event.stopPropagation();
		const open = menu.classList.toggle('is-open');
		menuTrigger.setAttribute('aria-expanded', String(open));
	});
	document.addEventListener('click', () => menu.classList.remove('is-open'), { once: true });

	const pill = element('div', 'crusorai-approval-pill', runButton);
	if (true) {
		const divider = element('span', 'crusorai-approval-divider');
		divider.setAttribute('aria-hidden', 'true');
		pill.append(divider, menuTrigger);
	}
	pill.append(menu);

	const reject = hinted(button('Reject', 'crusorai-approval-reject', () => host.replyToSafety(approval.toolId, false), 'close'), 'Deny this call. The next write is asked about again.');
	reject.dataset.deny = '';
	const rejectHint = element('span', 'crusorai-approval-kbd', 'Esc');
	reject.append(rejectHint);

	const commandToggle = element('button', 'crusorai-approval-command-toggle') as HTMLButtonElement;
	commandToggle.type = 'button';
	commandToggle.append(element('span', undefined, 'Command'), icon('chevron-down'));
	const commandPre = element('pre', 'crusorai-approval-command', commandText);
	commandToggle.setAttribute('aria-expanded', 'false');
	commandToggle.addEventListener('click', () => {
		const open = commandPre.classList.toggle('is-open');
		commandToggle.setAttribute('aria-expanded', String(open));
	});

	// "Always allow" persists for the session, so it goes through a confirm
	// step rather than firing straight from the menu (hermes' dialog rule).
	const overlay = element('div', 'crusorai-dialog-overlay');
	const dialog = element('div', 'crusorai-dialog');
	dialog.append(
		element('h3', undefined, 'Always allow this?'),
		element('p', 'crusorai-dialog-copy', `Crusor will stop asking before running ${crusorAIToolPresentation(approval.name).title} for the rest of this session. Secret paths and git-ignored files are still asked every time.`),
	);
	// append() takes (string | Node)[] — a ternary undefined arg is a type
	// error, so the optional command preview appends conditionally.
	if (commandText) { dialog.append(element('pre', 'crusorai-dialog-command', commandText)); }
	const dialogButtons = element('div', 'crusorai-dialog-actions');
	dialogButtons.append(
		button('Cancel', 'crusorai-button crusorai-button-secondary', () => overlay.classList.remove('is-open')),
		button('Always allow', 'crusorai-button crusorai-button-primary', () => {
			overlay.classList.remove('is-open');
			host.replyToSafety(approval.toolId, true, true);
		}),
	);
	dialog.append(dialogButtons);
	overlay.append(dialog);
	overlay.addEventListener('click', event => { if (event.target === overlay) overlay.classList.remove('is-open'); });

	dock.append(
		element('div', 'crusorai-approval-copy', icon('shield'), element('div', undefined,
			element('strong', undefined, `${crusorAIToolPresentation(approval.name).title} needs approval`),
			element('span', undefined, displayTarget({ id: approval.toolId, name: approval.name, state: 'approval', arguments: approval.diff })))),
	);
	if (warningBox) { dock.append(warningBox); }
	if (shellRiskBadge) { dock.append(shellRiskBadge); }
	if (inlineDiffCard) { dock.append(inlineDiffCard); }
	dock.append(
		element('div', 'crusorai-approval-bar',
			pill,
			reject,
			approval.diff ? button('Review change', 'crusorai-approval-review', () => host.openDiff(approval.toolId), 'diff') : undefined,
			commandText && !diffString ? commandToggle : undefined,
		)
	);
	if (commandText && !diffString) { dock.append(commandPre); }
	dock.append(overlay);
	return dock;
}

function isMac(): boolean {
	return typeof navigator !== 'undefined' && /Mac|iP(hone|ad|od)/.test(navigator.platform);
}

function approvalCommandText(name: string, diff: unknown): string {
	const row = (diff && typeof diff === 'object') ? diff as Record<string, unknown> : {};
	for (const key of ['command', 'cmd', 'path', 'file_path']) {
		const value = row[key];
		if (typeof value === 'string' && value.trim()) { return value.trim(); }
	}
	if (diff === undefined || diff === null) { return name; }
	try { return `${name} ${JSON.stringify(diff)}`.trim(); } catch { return name; }
}

// ── Hermes clarify card (the ask tool) ───────────────────────────────────────
// Port of apps/desktop/src/components/assistant-ui/clarify-tool.tsx: a widget
// card — the interactive batch form while the turn blocks, the settled Q&A
// after, and a skipped card whose choices draft a follow-up instead of
// vanishing. Draft state lives OUTSIDE the render (keyed by request id), the
// same way `openTools` survives re-renders.

const RECOMMENDED_LABEL = '(Recommended)';

interface ClarifyDraft {
	selected: Map<string, Set<string>>;
	other: Map<string, string>;
	cursor: number;
}

const clarifyDrafts = new Map<string, ClarifyDraft>();

function clarifyDraft(requestId: string): ClarifyDraft {
	let draft = clarifyDrafts.get(requestId);
	if (!draft) {
		draft = { selected: new Map(), other: new Map(), cursor: 0 };
		clarifyDrafts.set(requestId, draft);
	}
	return draft;
}

interface ClarifyResponseRow {
	id?: string;
	question?: string;
	user_response?: string | readonly string[];
	choices_offered?: readonly string[] | null;
}

function parseClarifyResult(raw: unknown): { responses: ClarifyResponseRow[]; timedOut: boolean; error?: string } {
	if (typeof raw !== 'string') { return { responses: [], timedOut: false }; }
	try {
		const parsed = JSON.parse(raw) as Record<string, unknown>;
		if (typeof parsed.error === 'string') { return { responses: [], timedOut: false, error: parsed.error }; }
		const responses: ClarifyResponseRow[] = [];
		const list = Array.isArray(parsed.responses) ? parsed.responses : [parsed];
		for (const entry of list) {
			if (entry && typeof entry === 'object') { responses.push(entry as ClarifyResponseRow); }
		}
		return { responses, timedOut: parsed.timed_out === true };
	} catch {
		return { responses: [], timedOut: false };
	}
}

function letterFor(index: number): string {
	return String.fromCharCode(97 + index);
}

function keyBadge(char: string, selected: boolean): HTMLElement {
	const badge = element('span', `crusorai-key-badge${selected ? ' is-selected' : ''}`, char);
	badge.setAttribute('aria-hidden', 'true');
	return badge;
}

/** Split "Use React (Recommended)" into [bare, recommended?] the way the
 * ChoiceLabel renders it: the suffix is presentation, tertiary-toned. */
function choiceParts(choice: string): { bare: string; recommended: boolean } {
	const trimmed = String(choice ?? '').trim();
	if (trimmed.toLowerCase().endsWith(RECOMMENDED_LABEL.toLowerCase())) {
		return { bare: trimmed.slice(0, -RECOMMENDED_LABEL.length).trim(), recommended: true };
	}
	return { bare: trimmed, recommended: false };
}

function clarifyChoiceRow(
	qid: string, index: number, choice: string, multi: boolean,
	draft: ClarifyDraft, requestId: string, onDirty: () => void,
): HTMLElement {
	const { bare, recommended } = choiceParts(choice);
	const picked = draft.selected.get(qid)?.has(bare) ?? false;
	const row = element('button', `crusorai-clarify-choice${picked ? ' is-selected' : ''}`) as HTMLButtonElement;
	row.type = 'button';
	row.dataset.choiceIndex = String(index);
	row.dataset.qid = qid;
	row.dataset.choice = bare;
	row.setAttribute('aria-pressed', String(picked));
	row.append(keyBadge(letterFor(index), picked));
	const label = element('span', 'crusorai-clarify-choice-label');
	label.append(document.createTextNode(bare));
	if (recommended) { label.append(element('span', 'crusorai-clarify-recommended', ` ${RECOMMENDED_LABEL}`)); }
	row.append(label);
	row.addEventListener('click', () => {
		const set = draft.selected.get(qid) ?? new Set<string>();
		if (multi) {
			if (set.has(bare)) { set.delete(bare); row.classList.remove('is-selected'); row.setAttribute('aria-pressed', 'false'); }
			else { set.add(bare); row.classList.add('is-selected'); row.setAttribute('aria-pressed', 'true'); }
			draft.selected.set(qid, set);
			return;
		}
		// Single select: one picked row per question; picking clears siblings.
		set.clear();
		set.add(bare);
		draft.selected.set(qid, set);
		draft.other.set(qid, '');
		const form = row.closest('.crusorai-clarify-form');
		for (const other of (form?.querySelectorAll<HTMLElement>(`[data-qid="${qid}"].crusorai-clarify-choice`) ?? [])) {
			const isThis = other === row;
			other.classList.toggle('is-selected', isThis);
			other.setAttribute('aria-pressed', String(isThis));
		}
		const textarea = form?.querySelector<HTMLTextAreaElement>(`textarea[data-qid="${qid}"]`);
		if (textarea) { textarea.value = ''; }
		onDirty();
	});
	return row;
}

function clarifyCard(
	tool: CrusorAIToolView, host: CrusorAIRenderHost, _openTools: Set<string>,
	pending: NonNullable<CrusorAIRenderModel['clarify']>,
): HTMLElement {
	ensureGlobalCardKeys();
	// Settled: the tool result carries the batch JSON — Q/A card, hermes
	// ClarifyToolSettled. A skipped card keeps its choices clickable; a pick
	// drafts a quoted follow-up into the composer (Enter sends, a running turn
	// queues it like any other prompt).
	if (tool.result !== undefined) {
		const { responses, timedOut, error } = parseClarifyResult(tool.result);
		const card = element('div', 'crusorai-clarify-card');
		card.dataset.component = 'clarify-settled';
		const skipped = !error && responses.length > 0 && responses.every(r => {
			const value = r.user_response;
			return value === undefined || value === '' || (Array.isArray(value) && value.length === 0);
		});
		for (const response of responses) {
			card.append(element('div', 'crusorai-clarify-q', icon('question'), element('span', undefined, response.question ?? '')));
			const answer = response.user_response;
			const answerText = error
				? error
				: skipped ? 'Skipped'
					: Array.isArray(answer) ? (answer as readonly string[]).join(', ')
						: (typeof answer === 'string' ? answer : '').trim();
			if (answerText) {
				card.append(element('div', `crusorai-clarify-a${error ? ' is-error' : ''}${skipped ? ' is-skipped' : ''}`,
					element('span', 'crusorai-clarify-a-badge', 'A'), element('span', undefined, answerText)));
			}
			if (timedOut || skipped) {
				const choices = response.choices_offered ?? [];
				if (choices.length) {
					const late = element('div', 'crusorai-clarify-late');
					choices.forEach((choice, index) => {
						const { bare } = choiceParts(choice);
						const row = element('button', 'crusorai-clarify-choice') as HTMLButtonElement;
						row.type = 'button';
						row.append(keyBadge(letterFor(index), false), element('span', 'crusorai-clarify-choice-label', bare));
						row.addEventListener('click', () => {
							// Hermes late-answer: a pick can't resolve the dead
							// request — it drafts a quoted follow-up instead.
							host.setDraft(`Re: "${response.question ?? 'your question'}" — ${bare}`);
						});
						late.append(row);
					});
					late.append(element('p', 'crusorai-clarify-late-hint', 'The turn moved on — pick one to draft a follow-up instead.'));
					card.append(late);
				}
			}
		}
		return card;
	}

	// Pending: the interactive batch form (hermes ClarifyToolSinglePending /
	// ClarifyToolBatchPending). Args alone can't drive it — the request frame
	// carries the qids the reply needs.
	const draft = clarifyDraft(pending.requestId);
	const form = element('div', 'crusorai-clarify-card crusorai-clarify-form');
	form.dataset.component = 'clarify-inline';
	form.dataset.live = '1';
	form.dataset.requestId = pending.requestId;

	const collectAnswers = (): Record<string, string | readonly string[]> => {
		const answers: Record<string, string | readonly string[]> = {};
		for (const question of pending.questions) {
			const other = draft.other.get(question.qid) ?? '';
			if (other.trim()) { answers[question.qid] = other.trim(); continue; }
			const picked = Array.from(draft.selected.get(question.qid) ?? []);
			if (picked.length === 1) { answers[question.qid] = picked[0]; }
			else if (picked.length > 1) { answers[question.qid] = picked; }
		}
		return answers;
	};

	const submitButton = element('button', 'crusorai-button crusorai-button-primary crusorai-clarify-submit') as HTMLButtonElement;
	submitButton.type = 'button';
	submitButton.dataset.clarifySubmit = '';
	submitButton.append('Continue', element('span', 'crusorai-approval-kbd', '⏎'));
	submitButton.addEventListener('click', () => {
		form.dataset.live = '0';
		host.replyToClarify(pending.requestId, collectAnswers(), false);
	});

	const skipButton = element('button', 'crusorai-button crusorai-button-secondary crusorai-clarify-skip') as HTMLButtonElement;
	skipButton.type = 'button';
	skipButton.textContent = 'Skip';
	skipButton.addEventListener('click', () => {
		form.dataset.live = '0';
		// Hermes skip: the batch resolves EMPTY — a deliberate skip the model
		// reads as "" answers, distinct from a walk-away timeout.
		host.replyToClarify(pending.requestId, {}, false);
	});

	for (const question of pending.questions) {
		const multi = question.multi_select === true;
		const block = element('div', 'crusorai-clarify-block');
		block.append(element('div', 'crusorai-clarify-q', icon('question'), element('span', undefined, question.question)));
		const choices = question.choices ?? [];
		if (choices.length) {
			const group = element('div', 'crusorai-clarify-choices');
			group.setAttribute('role', 'group');
			choices.forEach((choice, index) => {
				group.append(clarifyChoiceRow(question.qid, index, choice, multi, draft, pending.requestId, () => refreshSubmit()));
			});
			// The auto-appended "Other (type your answer)" row — hermes: the UI
			// always appends it; typing is its own answer and clears picks.
			const otherRow = element('label', 'crusorai-clarify-other');
			otherRow.dataset.choiceIndex = String(choices.length);
			otherRow.dataset.qid = question.qid;
			otherRow.append(keyBadge(letterFor(choices.length), false));
			const textarea = element('textarea', 'crusorai-clarify-other-input') as HTMLTextAreaElement;
			textarea.rows = 1;
			textarea.placeholder = 'Other (type your answer)';
			textarea.dataset.qid = question.qid;
			textarea.value = draft.other.get(question.qid) ?? '';
			textarea.addEventListener('input', () => {
				draft.other.set(question.qid, textarea.value);
				if (textarea.value.trim()) {
					draft.selected.set(question.qid, new Set());
					for (const row of form.querySelectorAll<HTMLElement>(`[data-qid="${question.qid}"].crusorai-clarify-choice`)) {
						row.classList.remove('is-selected');
						row.setAttribute('aria-pressed', 'false');
					}
				}
				refreshSubmit();
			});
			otherRow.append(textarea);
			group.append(otherRow);
			block.append(group);
		} else {
			const textarea = element('textarea', 'crusorai-clarify-other-input crusorai-clarify-open') as HTMLTextAreaElement;
			textarea.rows = 2;
			textarea.placeholder = 'Type your answer…';
			textarea.dataset.qid = question.qid;
			textarea.value = draft.other.get(question.qid) ?? '';
			textarea.addEventListener('input', () => { draft.other.set(question.qid, textarea.value); refreshSubmit(); });
			block.append(textarea);
		}
		form.append(block);
	}

	function refreshSubmit(): void {
		const answers = collectAnswers();
		const hasAnswer = Object.keys(answers).length > 0;
		submitButton.disabled = !hasAnswer;
	}
	refreshSubmit();

	const actions = element('div', 'crusorai-clarify-actions', skipButton, submitButton);
	form.append(actions);
	return form;
}

// ── Hermes todo panel (the task tool) ────────────────────────────────────────
// Port of the composer status stack's todo rows (status-row.tsx): checkbox
// glyphs, not spinner-and-dot — a dashed ring while pending, codicons once the
// item resolves, a live spinner only on the in_progress item; depth-indented
// subtasks; an X/Y count. Rendered ABOVE the composer, like upstream.

function todoStack(model: CrusorAIRenderModel): HTMLElement | undefined {
	const todos = model.todos;
	if (!todos.length) { return undefined; }  // hermes: no active list, no panel
	const counted = todos.filter(t => t.status !== 'cancelled');
	const done = counted.filter(t => t.status === 'completed').length;
	const stack = element('section', 'crusorai-todo-stack');
	stack.dataset.component = 'todo-stack';
	stack.append(element('div', 'crusorai-section-heading',
		icon('list-ordered'),
		element('span', undefined, 'Tasks'),
		element('span', 'crusorai-section-count', `${done}/${counted.length}`),
	));
	const list = element('div', 'crusorai-todo-list');
	for (const todo of todos) {
		const depth = todoDepth(todo, todos);
		const glyph = todoGlyph(todo.status);
		const row = element('div', `crusorai-todo-row is-${todo.status}`);
		if (depth) { row.style.paddingLeft = `${Math.min(depth, 4) * 0.8}rem`; }
		row.append(glyph, element('span', 'crusorai-todo-content', todo.content));
		list.append(row);
	}
	stack.append(list);
	return stack;
}

function todoDepth(todo: CrusorTodoItem, todos: readonly CrusorTodoItem[]): number {
	let depth = 0;
	let current = todo;
	const byId = new Map(todos.map(t => [t.id, t]));
	while (current.parent && byId.has(current.parent) && current.parent !== current.id && depth < 4) {
		current = byId.get(current.parent)!;
		depth += 1;
	}
	return depth;
}

function todoGlyph(status: CrusorTodoItem['status']): HTMLElement {
	if (status === 'in_progress') { return element('span', 'crusorai-mini-spinner'); }
	if (status === 'completed') { return icon('pass-filled'); }
	if (status === 'cancelled') { return icon('circle-slash'); }
	// Pending: a dashed ring — the row speaks checkbox, not spinner-and-dot.
	const ring = element('span', 'crusorai-todo-ring');
	ring.setAttribute('aria-hidden', 'true');
	return ring;
}

// ── Global card keys ─────────────────────────────────────────────────────────
// One capture-phase listener, installed once (hermes' window keydown in
// ClarifyToolSinglePending + ApprovalBar): ⌘/Ctrl+Enter runs the approval,
// Esc rejects it; letters/numbers/arrows/Enter drive the live clarify card.
// The DOM is the state — a re-render between keystrokes cannot desync us.

let globalCardKeysInstalled = false;

function ensureGlobalCardKeys(): void {
	if (globalCardKeysInstalled || typeof document === 'undefined') { return; }
	globalCardKeysInstalled = true;
	document.addEventListener('keydown', (event: KeyboardEvent) => {
		const dock = document.querySelector<HTMLElement>('[data-component="approval-dock"][data-tool-id]');
		if (dock) {
			if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
				event.preventDefault();
				dock.querySelector<HTMLButtonElement>('[data-approve-once]')?.click();
				return;
			}
			if (event.key === 'Escape') {
				event.preventDefault();
				dock.querySelector<HTMLButtonElement>('[data-deny]')?.click();
				return;
			}
		}
		const form = document.querySelector<HTMLElement>('.crusorai-clarify-form[data-live="1"]');
		if (!form || event.metaKey || event.ctrlKey || event.altKey || event.defaultPrevented) { return; }
		const active = document.activeElement as HTMLElement | null;
		if (active && (active.tagName === 'TEXTAREA' || active.tagName === 'INPUT' || active.isContentEditable)) { return; }
		const rows = Array.from(form.querySelectorAll<HTMLElement>('[data-choice-index]'));
		if (!rows.length) { return; }
		if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
			event.preventDefault();
			const delta = event.key === 'ArrowDown' ? 1 : -1;
			const current = rows.findIndex(row => row.classList.contains('is-active'));
			const next = Math.max(0, Math.min(rows.length - 1, (current === -1 ? 0 : current + delta)));
			rows.forEach((row, index) => row.classList.toggle('is-active', index === next));
			return;
		}
		if (/^[1-9]$/.test(event.key)) {
			const row = rows[Number(event.key) - 1];
			if (row) { event.preventDefault(); row.classList.add('is-active'); (row as HTMLButtonElement).click?.(); }
			return;
		}
		const key = event.key.toLowerCase();
		if (key.length === 1 && key >= 'a' && key <= 'z') {
			const row = rows[key.charCodeAt(0) - 97];
			if (row) { event.preventDefault(); row.classList.add('is-active'); if ((row as HTMLButtonElement).click) { (row as HTMLButtonElement).click(); } else { (row.querySelector('textarea') as HTMLTextAreaElement | null)?.focus(); } }
			return;
		}
		if (event.key === 'Enter') {
			const activeRow = rows.find(row => row.classList.contains('is-active'));
			if (activeRow) { event.preventDefault(); if ((activeRow as HTMLButtonElement).click) { (activeRow as HTMLButtonElement).click(); } else { (activeRow.querySelector('textarea') as HTMLTextAreaElement | null)?.focus(); } return; }
			const submit = form.querySelector<HTMLButtonElement>('[data-clarify-submit]');
			if (submit && !submit.disabled) { event.preventDefault(); submit.click(); }
		}
	}, true);
}

/** A `title` hint for buttons built through `button()`, which has no options bag. */
function hinted<T extends HTMLElement>(control: T, hint: string): T {
	control.title = hint;
	return control;
}

export interface CrusorAIDiffStats {
	readonly added: number;
	removed: number;
}

/**
 * Line counts for a unified diff, counted -- not assumed. Returns undefined when the
 * payload carries no +/- body at all, so callers can show '—' instead of a number.
 */
export function diffStats(diff: string | undefined): CrusorAIDiffStats | undefined {
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

// hermes diff-lines.tsx wireframe, ported: file-headers + `@@` hunk noise and
// the +/- gutter are DROPPED -- changes read by tint + a 2px gutter accent,
// rows flush to the card edges, the box scrolls like a code block.
function diffPreview(diff: string): HTMLElement {
	const wrap = element('div', 'crusorai-diff-body');
	const parsed = parseDiff(diff || '');
	const shown = parsed.slice(0, DIFF_PREVIEW_LINE_LIMIT);
	for (const line of shown) {
		const row = element('span', `crusorai-diff-row is-${line.kind}`, line.text.length ? line.text : ' ');
		if (line.newNo !== undefined) { row.dataset.newNo = String(line.newNo); }
		if (line.oldNo !== undefined) { row.dataset.oldNo = String(line.oldNo); }
		wrap.append(row);
	}
	if (parsed.length > DIFF_PREVIEW_LINE_LIMIT) {
		wrap.append(element('div', 'crusorai-diff-row is-truncated', `… ${parsed.length - DIFF_PREVIEW_LINE_LIMIT} more line(s) — 'Open native diff' shows all of it`));
	}
	return wrap;
}

// hermes terminal-output.tsx + lib/ansi.ts: bounded tail (paint, not
// correctness) with SGR-colored segments; plain text when there is no ANSI.
const TERMINAL_PAINT_LINE_LIMIT = 400;

function terminalOutputContent(output: string, running: boolean): HTMLElement {
	const pre = element('pre', 'crusorai-terminal-output');
	const text = output || (running ? 'Waiting for output...' : 'No captured output');
	const windowed = windowedTailLines(text, TERMINAL_PAINT_LINE_LIMIT);
	if (windowed.hidden > 0) {
		pre.append(element('div', 'crusorai-terminal-earlier', `… ${windowed.hidden} earlier line(s) — full history stays in the run log`));
	}
	const body = windowed.lines.join('\n');
	if (!hasAnsiCodes(body)) {
		pre.append(document.createTextNode(body));
		return pre;
	}
	let line: HTMLElement | undefined;
	for (const segment of parseAnsi(body)) {
		if (!line) { line = element('span', 'crusorai-ansi-line'); pre.append(line); }
		const span = element('span', segment.fg ? `crusorai-ansi-${segment.fg}` : undefined, segment.text);
		if (segment.bold) { span.classList.add('is-bold'); }
		// hermes ansi segments carry embedded \n — split into rows
		const parts = segment.text.split('\n');
		for (let i = 0; i < parts.length; i += 1) {
			if (i > 0) { line = element('span', 'crusorai-ansi-line'); pre.append(line); }
			if (parts[i]) { line.append(element('span', segment.fg ? `crusorai-ansi-${segment.fg}` : undefined, parts[i])); }
		}
	}
	return pre;
}

// hermes changed-files-card.tsx: the turn-closing "N files changed" rollup —
// one row per LANDED file edit, +/- summed, click opens the file. Wears the
// shared widget chrome so it reads as the transcript's other inline widgets.
function changedFilesCard(model: CrusorAIRenderModel, host: CrusorAIRenderHost): HTMLElement | undefined {
	const files = deriveChangedFiles(model.tools);
	if (!files.length) { return undefined; }
	const card = element('div', 'crusorai-changed-files');
	card.dataset.component = 'changed-files';
	card.append(element('div', 'crusorai-changed-files-head',
		element('span', undefined, `${files.length} file${files.length === 1 ? '' : 's'} changed`)));
	const rows = element('div', 'crusorai-changed-files-rows');
	for (const file of files) {
		const row = element('div', 'crusorai-changed-file-row');
		row.append(icon('file'),
			element('span', 'crusorai-changed-file-name', file.name),
			element('span', 'crusorai-diff-count',
				element('span', 'is-added', `+${file.added}`),
				element('span', 'is-removed', `−${file.removed}`)));
		row.title = file.path;
		row.classList.add('is-activatable');
		row.addEventListener('click', () => host.revealFile(file.path));
		rows.append(row);
	}
	card.append(rows);
	return card;
}

const executionModes: readonly { readonly id: CrusorExecutionMode; readonly label: string; readonly description: string; readonly icon: string }[] = [
	{ id: 'agent', label: 'Agent', description: 'Build, change, and verify', icon: 'infinity' },
	{ id: 'plan', label: 'Plan', description: 'Design before execution', icon: 'list-ordered' },
	{ id: 'debug', label: 'Debug', description: 'Diagnose, fix, and retest', icon: 'debug-alt' },
	{ id: 'ask', label: 'Ask', description: 'Explain without using tools', icon: 'comment' },
];

function modePicker(model: CrusorAIRenderModel, host: CrusorAIRenderHost): HTMLElement {
	const selected = executionModes.find(mode => mode.id === model.mode) ?? executionModes[0];
	const details = element('details', 'crusorai-mode-picker') as HTMLDetailsElement;
	const summary = element('summary', 'crusorai-mode-summary', icon(selected.icon), element('span', undefined, selected.label), icon('chevron-down'));
	summary.setAttribute('aria-label', `Execution mode: ${selected.label}`);
	if (model.running) {
		summary.setAttribute('aria-disabled', 'true');
		summary.addEventListener('click', event => event.preventDefault());
	}
	const menu = element('div', 'crusorai-mode-menu');
	menu.setAttribute('role', 'menu');
	menu.setAttribute('aria-label', 'Execution mode');
	for (const mode of executionModes) {
		const item = element('button', mode.id === selected.id ? 'crusorai-mode-option is-selected' : 'crusorai-mode-option',
			icon(mode.icon),
			element('span', 'crusorai-mode-option-copy', element('strong', undefined, mode.label), element('small', undefined, mode.description)),
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

// hermes desktop lib/reasoning-effort.ts + composer model-pill: the Think
// scale beside the execution mode. '' (no pick yet) means "inherit the
// engine default" — the summary shows that honestly instead of guessing.
const thinkOptions: readonly { readonly id: CrusorReasoningEffortValue; readonly description: string }[] = [
	{ id: 'low', description: 'Quick replies, light reasoning' },
	{ id: 'medium', description: 'Balanced default' },
	{ id: 'high', description: 'Deep reasoning, slower turns' },
	{ id: 'none', description: 'Disable extended thinking' },
];

function thinkPicker(model: CrusorAIRenderModel, host: CrusorAIRenderHost): HTMLElement {
	const details = element('details', 'crusorai-mode-picker crusorai-think-picker') as HTMLDetailsElement;
	const current = model.reasoningEffort ?? '';
	const summary = element('summary', 'crusorai-mode-summary',
		element('span', undefined, current ? reasoningEffortLabel(current) : 'Think'),
		icon('chevron-down'));
	summary.setAttribute('aria-label', `Thinking effort: ${current ? reasoningEffortLabel(current) : 'engine default'}`);
	if (model.running) {
		summary.setAttribute('aria-disabled', 'true');
		summary.addEventListener('click', event => event.preventDefault());
	}
	const menu = element('div', 'crusorai-mode-menu');
	menu.setAttribute('role', 'menu');
	menu.setAttribute('aria-label', 'Thinking effort');
	for (const option of thinkOptions) {
		const selected = option.id === current;
		const item = element('button', selected ? 'crusorai-mode-option is-selected' : 'crusorai-mode-option',
			icon(option.id === 'none' ? 'circle-slash' : 'lightbulb'),
			element('span', 'crusorai-mode-option-copy', element('strong', undefined, reasoningEffortLabel(option.id)), element('small', undefined, option.description)),
			selected ? icon('check') : undefined,
		) as HTMLButtonElement;
		item.type = 'button';
		item.setAttribute('role', 'menuitemradio');
		item.setAttribute('aria-checked', String(selected));
		item.addEventListener('click', () => {
			details.open = false;
			host.setReasoningEffort(option.id);
		});
		menu.append(item);
	}
	details.append(summary, menu);
	return details;
}

function composer(model: CrusorAIRenderModel, host: CrusorAIRenderHost, manager: boolean): HTMLElement {
	const input = element('textarea', 'crusorai-composer-input') as HTMLTextAreaElement;
	input.rows = manager ? 2 : 3;
	input.placeholder = model.isChild ? 'Sub-agent session — prompt disabled. Use Back to Parent.' : manager ? 'Steer this agent or add context...' : 'Plan, @ for context, / for commands';
	input.value = model.draft;
	input.addEventListener('input', () => host.setDraft(input.value));
	const inputBlocked = model.noWorkspace || model.workspaceSelectionRequired || !!model.isChild;
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
	const send = element('button', running ? 'crusorai-send-button crusorai-send-stop' : 'crusorai-send-button') as HTMLButtonElement;
	send.type = 'button';
	send.setAttribute('aria-label', running ? 'Stop' : 'Send');
	send.append(icon(running ? 'debug-pause' : 'arrow-up'));
	send.addEventListener('click', running ? host.cancel : submit);
	if (running && model.cancelRequested) { send.disabled = true; }
	if (inputBlocked) { send.disabled = true; }

	// hermes composer layout: the Think pill sits beside the execution-mode
	// picker; the Send button stays right-aligned via the toolbar's spare
	// `.crusorai-composer-left` grid track.
	const toolbar = element('div', 'crusorai-composer-toolbar',
		modePicker(model, host),
		thinkPicker(model, host),
		element('span', 'crusorai-composer-left'),
		send);
	const hint = element('div', 'crusorai-composer-hint',
		model.noWorkspace
			? element('span', undefined, model.noWorkspaceHint)
			: model.workspaceSelectionRequired
				? element('span', undefined, 'Select a workspace folder to start a Crusor session.')
				: element('span', undefined, 'Enter to send'),
		element('span', undefined, model.noWorkspace ? '' : 'Shift+Enter for new line'),
	);
	if (model.noWorkspace) {
		hint.append(button('Open Folder', 'crusorai-link-button', host.openFolder, 'folder'));
	}
	return element('footer', 'crusorai-composer', element('div', 'crusorai-composer-box', input, toolbar), hint);
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
interface CrusorAIActivitySurface {
	row(model: CrusorAIRenderModel): HTMLElement | undefined;
	thoughtSeconds(model: CrusorAIRenderModel): number | undefined;
}

function agentColumn(model: CrusorAIRenderModel, host: CrusorAIRenderHost, openTools: Set<string>, activity: CrusorAIActivitySurface, planOpen: boolean | undefined, setPlanOpen: (open: boolean) => void): HTMLElement[] {
	const nodes: HTMLElement[] = [];
	const plan = planStrip(model, planOpen, setPlanOpen);
	if (plan) { nodes.push(plan); }
	// An engine that is not ready is a FACT the panel must paint — the empty
	// state's starter grid under a dead engine reads as a send button that
	// does nothing (field 2026-09-05). Same quiet row the activity ticker
	// uses; the chip lives in the Manager, this names the state HERE.
	if (model.engineState !== 'ready' && !model.engineFault) {
		const row = element('div', 'crusorai-context-status-row is-info');
		row.append(element('span', 'crusorai-activity-dot'));
		row.append(element('span', undefined, model.engineState === 'starting'
			? 'Crusor engine is starting — prompts send the moment it is ready.'
			: `Crusor engine: ${model.engineState}.`));
		nodes.push(row);
	}
	// An empty transcript is a designed surface, not a blank div -- the same rule the ported
	// webview follows (`hermes-ui/components/empty-state.tsx`). Exactly one of the two is
	// mounted, so a first-run view never shows an empty lane under a grid of starters.
	const empty = emptyState(model, host);
	nodes.push(empty ?? transcript(model, host, openTools, activity.thoughtSeconds(model)));
	const working = activity.row(model);
	if (working) { nodes.push(working); }
	const approval = approvalDock(model, host);
	if (approval) { nodes.push(approval); }
	// Hermes: the todo panel lives between the transcript and the composer
	// (the composer status stack) — the list rides ABOVE the input, never
	// buried in transcript history.
	const todos = todoStack(model);
	if (todos) { nodes.push(todos); }
	return nodes;
}

function renderAgent(root: HTMLElement, model: CrusorAIRenderModel, host: CrusorAIRenderHost, openTools: Set<string>, planOpen: boolean | undefined, setPlanOpen: (open: boolean) => void, activity: CrusorAIActivitySurface): void {
	const shell = element('div', 'crusorai-agent-shell');
	const header = element('div', 'crusorai-agent-header',
		element('span', 'crusorai-agent-header-title', 'Crusor Agent'),
		button('Manager', 'crusorai-agent-manager-button', () => host.openManager(), 'organization'),
	);
	// Field run 2026-09-09 (owner: "Ur claim failed"): the STALE chip lived
	// only in the Manager titlebar, so an Agent-pane session ran a pre-
	// fef8cdb2/74d146bd workbench against a current engine — every card-
	// format fix invisible — with NO warning where the user was looking.
	// The chip rides the Agent header too (next to the Manager button).
	header.append(engineStatus(model));
	shell.append(header);
	shell.append(...agentColumn(model, host, openTools, activity, planOpen, setPlanOpen));
	shell.append(composer(model, host, false));
	root.append(shell);
}

function inspector(model: CrusorAIRenderModel): HTMLElement {
	const pane = element('aside', 'crusorai-manager-inspector');
	pane.append(element('header', 'crusorai-manager-pane-head', element('div', undefined, element('span', 'crusorai-eyebrow', 'LIVE EVIDENCE'), element('h2', undefined, 'Run inspector'))));
	const plan = element('section', 'crusorai-inspector-section', element('div', 'crusorai-inspector-title', element('span', undefined, 'Plan'), element('strong', undefined, `${model.plan.length} steps`)));
	const list = element('ol', 'crusorai-plan-list');
	for (const step of model.plan) { list.append(element('li', `is-${step.status}`, planStepGlyph(step.status), element('span', undefined, step.text))); }
	if (!model.plan.length) { list.append(element('li', 'is-muted', icon('circle-outline'), element('span', undefined, 'Plan appears when the run starts'))); }
	plan.append(list);
	const evidence = element('section', 'crusorai-inspector-section', element('div', 'crusorai-inspector-title', element('span', undefined, 'Verification'), element('strong', undefined, model.verification ?? 'Not started')),
		element('div', 'crusorai-evidence-row', icon(model.verification === 'passed' ? 'pass-filled' : 'circle-outline'), element('span', undefined, model.verification ? `Runtime reported ${model.verification}` : 'No evidence receipt yet')));
	const capabilities = element('section', 'crusorai-inspector-section', element('div', 'crusorai-inspector-title', element('span', undefined, 'Workbench capabilities'), element('strong', undefined, `${model.capabilitySummary.available}/${model.capabilitySummary.total}`)),
		element('div', 'crusorai-evidence-row', icon('plug'), element('span', undefined, `${model.capabilitySummary.available} available · ${model.capabilitySummary.blocked} blocked`)));
	const usage = element('section', 'crusorai-inspector-section crusorai-usage', element('div', 'crusorai-inspector-title', element('span', undefined, 'Usage'), element('strong', undefined, model.telemetry.cost === undefined ? '\u2014' : `$${model.telemetry.cost.toFixed(4)}`)),
		element('div', 'crusorai-usage-grid', element('span', undefined, 'Input'), element('strong', undefined, String(model.telemetry.input ?? 0)), element('span', undefined, 'Cache'), element('strong', undefined, String(model.telemetry.cache ?? 0)), element('span', undefined, 'Output'), element('strong', undefined, String(model.telemetry.output ?? 0))));
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
function sessionList(model: CrusorAIRenderModel): HTMLElement {
	const group = element('div', 'crusorai-workspace-group');
	group.append(element('div', 'crusorai-workspace-title', icon('chevron-down'), icon('folder'), element('strong', undefined, model.workspaceLabel)));
	const rows = model.sessions;
	if (!rows || !rows.length) {
		group.append(element('div', 'crusorai-session-row is-empty',
			element('span', 'crusorai-status-dot is-idle'),
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
		const classes = ['crusorai-session-row'];
		if (row.isActive) { classes.push('is-active'); }
		if (row.statusName === 'needsInput') { classes.push('is-needs-input'); }
		if (row.needsAttention) { classes.push('is-attention'); }
		const button = element('button', classes.join(' '),
			element('span', `crusorai-status-dot is-${dot}`),
			element('div', undefined, element('strong', undefined, row.label), element('span', 'crusorai-session-detail', detail)),
			element('span', 'crusorai-session-state', state),
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

function renderManager(root: HTMLElement, model: CrusorAIRenderModel, host: CrusorAIRenderHost, openTools: Set<string>, activity: CrusorAIActivitySurface, planOpen: boolean | undefined, setPlanOpen: (open: boolean) => void): void {
	const shell = element('div', 'crusorai-manager-shell');
	const sidebar = element('aside', 'crusorai-manager-sidebar',
		element('header', 'crusorai-manager-pane-head', element('div', undefined, element('span', 'crusorai-eyebrow', 'CONTROL PLANE'), element('h2', undefined, 'Workspaces')), button('', 'crusorai-icon-button', () => undefined, 'add')),
		element('div', 'crusorai-manager-search', icon('search'), element('span', undefined, 'Find workspace or agent')),
		sessionList(model),
		element('footer', 'crusorai-manager-sidebar-footer', icon('organization'), element('span', undefined, model.sessions?.length ? `${model.sessions.length} session(s) remembered · ${model.running ? '1 running' : 'none running'}` : 'No session yet')),
	);
	const main = element('main', 'crusorai-manager-main');
	main.append(
		element('header', 'crusorai-manager-titlebar', element('div', undefined, element('div', 'crusorai-manager-breadcrumb', model.workspaceLabel, ' / ', model.sessionId?.slice(0, 12) ?? 'new-session'), element('h1', undefined, model.userMessage || 'Crusor Manager')), engineStatus(model)),
		element('nav', 'crusorai-manager-tabs', element('button', 'is-active', icon('comment-discussion'), 'Session'), element('button', undefined, icon('terminal'), `Tools ${model.tools.length}`), element('button', undefined, icon('diff'), 'Changes')),
		...agentColumn(model, host, openTools, activity, planOpen, setPlanOpen),
		composer(model, host, true),
	);
	shell.append(sidebar, main, inspector(model));
	root.append(shell);
}

export function mountCrusorAIRenderer(root: HTMLElement, surface: CrusorAISurface, host: CrusorAIRenderHost): CrusorAIRenderMount {
	const openTools = new Set<string>();
	let planOpen: boolean | undefined;
	let planSession: string | undefined;
	let disposed = false;
	let lastModel: CrusorAIRenderModel | undefined;
	// Hermes streaming isolation (apps/desktop mechanism 6): while tokens
	// arrive, ONLY the message part re-renders — never the whole transcript.
	// The full rebuild tore down every tool card + re-parsed all markdown on
	// every animation frame, O(turn length) per frame (the owner's "UI not
	// nice" jank that compounds the longer a turn runs). `paintSignature`
	// covers everything EXCEPT text content: it pins the part SHAPE (kinds +
	// tool ids), so token growth keeps the signature identical and patches the
	// [data-slot=session-turn-content] node (the LAST text segment — hermes
	// parts order means that is the live one) with the near-bottom scroll rule
	// preserved. A new part or tool changes the shape and takes the full paint
	// exactly as before.
	let lastPaint: { signature: string; text: string } | undefined;
	const lastTextPart = (model: CrusorAIRenderModel): Extract<CrusorAITurnPart, { kind: 'text' }> | undefined => {
		for (let i = model.parts.length - 1; i >= 0; i--) {
			const part = model.parts[i];
			if (part.kind === 'text' && part.text) { return part; }
		}
		return undefined;
	};
	const paintSignature = (model: CrusorAIRenderModel): string => {
		const shape = model.parts.map(p => (p.kind === 'tool' ? `tool:${p.toolId}` : 'text') + (p.kind === 'reasoning' ? `:r${p.reasoningIndex}` : '')).join('>');
		return `${JSON.stringify({ ...model, assistantText: undefined, parts: undefined, reasoningParts: undefined })}|${shape}`;
	};
	// The activity row's timers outlive individual renders; a tick repaints from the last model,
	// which is what makes the seconds move while the engine is quiet.
	const activity = createActivityState(() => { if (!disposed) { tick(); } });
	const tick = (): void => { if (!disposed && lastModel) { paint(lastModel); } };
	const paint = (model: CrusorAIRenderModel): void => {
		if (model.sessionId !== planSession) {
			planSession = model.sessionId;
			planOpen = undefined;
			lastPaint = undefined;
		}
		const signature = paintSignature(model);
		const streaming = lastTextPart(model);
		if (
			lastPaint
			&& lastPaint.signature === signature
			&& streaming
			&& streaming.text !== lastPaint.text
			&& streaming.text.startsWith(lastPaint.text)
		) {
			const slot = root.querySelector<HTMLElement>('[data-slot="session-turn-content"]');
			if (slot) {
				slot.replaceChildren(markdownCopy(streaming.text, 'session-turn-content'));
				const scroller = root.querySelector<HTMLElement>('.crusorai-transcript-scroll');
				if (scroller && scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 32) {
					scroller.scrollTop = scroller.scrollHeight;
				}
				lastPaint = { signature, text: streaming.text };
				return;
			}
			// No live slot even though the shape says one should exist — the
			// DOM does not match the model; take the full paint to resync.
		}
		const previousScroll = root.querySelector<HTMLElement>('.crusorai-transcript-scroll');
		const scrollTop = previousScroll?.scrollTop ?? 0;
		const wasNearBottom = !previousScroll || previousScroll.scrollHeight - previousScroll.scrollTop - previousScroll.clientHeight < 32;
		const activeElement = document.activeElement;
		const activeComposer = root.contains(activeElement) && activeElement instanceof HTMLTextAreaElement ? activeElement : undefined;
		// Don't steal focus from ask tool (clarify card) — vibrations/streaming re-renders were
		// yanking focus back to the main composer while user typed in the card
		const isClarifyInput = activeComposer?.closest('.crusorai-clarify-card') !== null;
		const selectionStart = activeComposer?.selectionStart;
		const selectionEnd = activeComposer?.selectionEnd;
		root.replaceChildren();
		root.dataset.surface = surface;
		if (surface === 'agent') { renderAgent(root, model, host, openTools, planOpen, open => { planOpen = open; }, activity); }
		else { renderManager(root, model, host, openTools, activity, planOpen, open => { planOpen = open; }); }
		const nextScroll = root.querySelector<HTMLElement>('.crusorai-transcript-scroll');
		if (nextScroll) { nextScroll.scrollTop = wasNearBottom ? nextScroll.scrollHeight : scrollTop; }
		if (activeComposer && !isClarifyInput && activeComposer.classList.contains('crusorai-composer-input')) {
			const input = root.querySelector<HTMLTextAreaElement>('.crusorai-composer-input');
			input?.focus({ preventScroll: true });
			if (input && selectionStart !== undefined && selectionEnd !== undefined) { input.setSelectionRange(selectionStart, selectionEnd); }
		} else if (isClarifyInput && activeComposer) {
			// Restore focus to the clarify card's textarea (it was recreated by replaceChildren)
			const nextClarify = root.querySelector<HTMLTextAreaElement>('.crusorai-clarify-card textarea');
			if (nextClarify) {
				nextClarify.focus({ preventScroll: true });
				if (selectionStart !== undefined && selectionEnd !== undefined) { nextClarify.setSelectionRange(selectionStart, selectionEnd); }
			}
		}
		lastPaint = { signature, text: lastTextPart(model)?.text ?? '' };

	};
	return {
		update(model: CrusorAIRenderModel): void {
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
