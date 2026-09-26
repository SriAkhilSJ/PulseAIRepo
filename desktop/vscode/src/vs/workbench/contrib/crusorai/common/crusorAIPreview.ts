/*---------------------------------------------------------------------------------------------
 * Crusor Preview — the contract shared by the workbench host, the preview window, and the overlay.
 *
 * Three surfaces exchange these messages, and only two of them are ours at runtime:
 *
 *   workbench (this contribution)  --postMessage-->  preview window frame
 *   preview window (media/crusor-preview/preview.js) --> overlay (injected into the agent's page)
 *   overlay --> preview window --> workbench
 *
 * The overlay is INJECTED INTO THE PAGE THE AGENT BUILT, which the user may have written with any
 * framework, on any origin. It cannot import from us, and we cannot reach into it: every message
 * below is a plain object crossing a window boundary. That is exactly why the names live here, in
 * a module with no imports of its own — the messages are strings, and a typo in one of them is a
 * silently dead feature. `src/tests/test_preview_contract.py` pins these literals against the two
 * JavaScript files that must agree with them, and exercises the pure helpers below through node.
 *
 * Nothing in this file touches `vscode` or the DOM: it is imported by the browser layer AND by
 * that node-driven test.
 *--------------------------------------------------------------------------------------------*/

export const CRUSOR_PREVIEW_VERSION = 1;

/** `data-*` marker the injected overlay leaves on its own tag, used to find the frame it lives in. */
export const CRUSOR_PREVIEW_OVERLAY_ID = 'crusor-preview-overlay';

/** `postMessage` identities. A receiver ignores anything whose `source` is not its peer's. */
export const CrusorPreviewSource = {
	/** set by the injected overlay on everything it sends */
	Overlay: 'crusor-preview-overlay',
	/** set by the preview window when it commands the overlay (it IS the overlay's host) */
	OverlayHost: 'crusor-preview-host',
	/** set by the workbench when it commands the preview window */
	Workbench: 'crusor-preview-workbench',
	/** set by the preview window on everything it sends up to the workbench */
	Window: 'crusor-preview-window',
} as const;

/** Commands the preview window sends INTO the injected overlay. */
export const CrusorPreviewOverlayCommand = {
	Configure: 'configure',
	Inspect: 'inspect',
	Pins: 'pins',
	ClearPins: 'clear-pins',
	Flash: 'flash',
	ClosePanel: 'close-panel',
} as const;

/** Events the injected overlay emits to the preview window. */
export const CrusorPreviewOverlayEvent = {
	Ready: 'ready',
	Inspect: 'inspect',
	Selected: 'selected',
	Fix: 'fix',
	PinClick: 'pin-click',
} as const;

/** Commands the workbench sends to the preview window. */
export const CrusorPreviewWindowCommand = {
	Configure: 'configure',
	Theme: 'theme',
	SetTarget: 'set-target',
	Inspect: 'inspect',
	AgentApplied: 'agent-applied',
	Toast: 'toast',
} as const;

/** Events the preview window emits to the workbench. */
export const CrusorPreviewWindowEvent = {
	Ready: 'ready',
	Navigate: 'navigate',
	ThemeApplied: 'theme-applied',
	Inspect: 'inspect',
	ElementSelected: 'element-selected',
	FixAdded: 'fix-added',
	ReviewOpen: 'review-open',
	ReviewClose: 'review-close',
	/** the injected overlay answered after a (re)load — inspect is only possible once it does */
	OverlayReady: 'overlay-ready',
	/** the reviewed batch — this is the handoff that becomes an agent turn */
	ReviewSubmit: 'review-submit',
	OpenSource: 'open-source',
	CloseRequest: 'close-request',
	Viewport: 'viewport',
} as const;

export type CrusorPreviewKind = 'url' | 'file';
export type CrusorPreviewViewport = 'responsive' | 'desktop' | 'tablet' | 'phone';

export interface CrusorPreviewRect {
	readonly x: number;
	readonly y: number;
	readonly width: number;
	readonly height: number;
}

export interface CrusorPreviewSourceHint {
	readonly file?: string;
	readonly line?: number;
	readonly component?: string;
}

export interface CrusorPreviewFingerprint {
	readonly tag?: string;
	readonly classes?: readonly string[];
	readonly text?: string;
	readonly attrs?: readonly { readonly name: string; readonly value: string }[];
	/** present only when the project stamps source positions into the DOM */
	readonly source?: CrusorPreviewSourceHint;
}

/** One element the user clicked in the preview, described well enough to be found in source. */
export interface CrusorPreviewElement {
	readonly selector: string;
	readonly xpath?: string;
	readonly tag: string;
	readonly id?: string;
	readonly classes: readonly string[];
	readonly text?: string;
	readonly outerHtml?: string;
	readonly styles?: Readonly<Record<string, string>>;
	readonly fingerprint?: CrusorPreviewFingerprint;
	readonly rect?: CrusorPreviewRect;
	readonly pageUrl?: string;
	readonly viewport?: { readonly width: number; readonly height: number; readonly dpr?: number };
	readonly scroll?: { readonly x: number; readonly y: number };
}

/** One fix: what the user typed, about one element. */
export interface CrusorPreviewFix {
	readonly id: string;
	readonly order?: number;
	readonly instruction: string;
	readonly label?: string;
	readonly element: CrusorPreviewElement;
}

/** The reviewed batch handed to the agent. */
export interface CrusorPreviewBatch {
	readonly sessionId?: string;
	readonly target: string;
	readonly targetLabel?: string;
	readonly kind?: CrusorPreviewKind;
	readonly viewport?: CrusorPreviewViewport;
	readonly createdAt?: string;
	readonly fixes: readonly CrusorPreviewFix[];
}

/** The handshake file the preview proxy publishes (see src/preview/endpoint.py). */
export interface CrusorPreviewEndpoint {
	readonly session_id: string;
	readonly origin: string;
	readonly token?: string;
	/** registration capability, handed to the preview window (see src/preview/endpoint.py) */
	readonly secret?: string;
	readonly workspace?: string;
	readonly ui_path?: string;
	readonly health_path?: string;
	readonly target_path?: string;
	readonly started_at?: number;
	readonly pid?: number;
}

export const DEFAULT_UI_PATH = '/crusor-preview/ui/';

/** `http://127.0.0.1:8931/crusor-preview/ui/?target=…&label=…` */
export function previewWindowUrl(
	endpoint: Pick<CrusorPreviewEndpoint, 'origin' | 'ui_path'>,
	options: { readonly target?: string; readonly label?: string; readonly kind?: CrusorPreviewKind; readonly sessionId?: string },
): string {
	const origin = String(endpoint.origin || '').replace(/\/+$/, '');
	const base = origin + (endpoint.ui_path || DEFAULT_UI_PATH);
	const query: string[] = [];
	if (options.target) { query.push('target=' + encodeURIComponent(options.target)); }
	if (options.label) { query.push('label=' + encodeURIComponent(options.label)); }
	if (options.kind) { query.push('kind=' + encodeURIComponent(options.kind)); }
	if (options.sessionId) { query.push('session=' + encodeURIComponent(options.sessionId)); }
	return query.length ? base + '?' + query.join('&') : base;
}

/**
 * Query string the preview window needs in order to reach its proxy: the endpoint origin (because the
 * window registers the target itself) and the run secret (because registration is gated — the window's
 * origin is opaque, so the proxy cannot tell our window from a hostile one by origin alone).
 */
export function previewWindowQuery(endpoint: Pick<CrusorPreviewEndpoint, 'origin' | 'secret'>, extra: Record<string, string> = {}): string {
	// A list of pairs, not a list of strings: `query.map(([key, value]) => ...)` destructures pairs, and a
	// flat string destructures into its first two characters instead — which is how a URL silently turns
	// into `e=n&n=d&d=p…` while every test still passes.
	const query: [string, string][] = [['endpoint', String(endpoint.origin || '').replace(/\/+$/, '')]];
	if (endpoint.secret) { query.push(['secret', endpoint.secret]); }
	for (const key of Object.keys(extra)) {
		if (extra[key]) { query.push([key, extra[key]]); }
	}
	return query.map(([key, value]) => `${key}=${encodeURIComponent(value)}`).join('&');
}

/** The proxied URL for a registered target — what the preview window frames. */
export function proxiedTargetUrl(endpoint: Pick<CrusorPreviewEndpoint, 'origin'>, token: string, path = ''): string {
	const origin = String(endpoint.origin || '').replace(/\/+$/, '');
	const suffix = String(path || '').replace(/^\/+/, '');
	return `${origin}/p/${encodeURIComponent(token)}/${suffix}`;
}

export function isBatchEmpty(batch: CrusorPreviewBatch | undefined | null): boolean {
	return !batch || !Array.isArray(batch.fixes) || batch.fixes.filter(fix => (fix?.instruction || '').trim().length > 0).length === 0;
}

/** `<button> "Get started"` — the element line every surface shows. */
export function describeFixElement(fix: CrusorPreviewFix | undefined | null): string {
	const element = fix?.element;
	if (!element) { return 'element'; }
	const text = String(element.text || '').trim();
	const classes = element.classes || [];
	if (text) { return `<${element.tag}> "${text.length > 40 ? text.slice(0, 39) + '…' : text}"`; }
	if (classes.length) { return `<${element.tag}> .${classes[0]}`; }
	return `<${element.tag}>`;
}

/** `3 preview fixes · aurora-landing · dev server` */
export function summarizeBatch(batch: CrusorPreviewBatch | undefined | null): string {
	const count = batch?.fixes?.length || 0;
	const label = String(batch?.targetLabel || batch?.target || '').trim();
	const fixes = `${count} preview fix${count === 1 ? '' : 'es'}`;
	return label ? `${fixes} · ${label}` : fixes;
}

function quote(value: unknown, limit = 0): string {
	const text = String(value ?? '').replace(/\s+/g, ' ').trim();
	if (!limit || text.length <= limit) { return text; }
	return text.slice(0, limit - 1).trimEnd() + '…';
}

function fingerprintLine(element: CrusorPreviewElement): string {
	const parts: string[] = [];
	const classes = element.classes || [];
	if (classes.length) { parts.push('classes=' + classes.slice(0, 8).join(' ')); }
	const text = quote(element.fingerprint?.text || element.text, 90);
	if (text) { parts.push(`text="${text}"`); }
	const attrs = element.fingerprint?.attrs || [];
	if (attrs.length) {
		parts.push('attrs=' + attrs.slice(0, 6).map(a => `${a.name}="${quote(a.value, 60)}"`).join(', '));
	}
	if (element.id) { parts.push(`id="${quote(element.id, 60)}"`); }
	return parts.filter(Boolean).join(' · ');
}

function sourceLine(element: CrusorPreviewElement): string {
	const source = element.fingerprint?.source;
	if (!source?.file) { return ''; }
	const bits = [quote(source.file, 200)];
	if (typeof source.line === 'number' && source.line > 0) { bits.push(`line ${source.line}`); }
	if (source.component) { bits.push(`component ${quote(source.component, 80)}`); }
	return bits.join(' → ');
}

const SCOPE_RULES = [
	'Apply every fix below. Each one was created by clicking an element in the live preview of the UI you built, so:',
	'- change ONLY the named elements; leave the rest of the page alone;',
	'- locate each element in the source with the fingerprints given (grep the classes, the text, the data attributes) before editing — do not guess a file;',
	"- keep the fix minimal and in the project's own style system (its tokens/variables/utility classes), not inline overrides, unless the project already does that;",
	'- if a fix is ambiguous or the element cannot be found, say so for that fix and continue with the others;',
	'- when done, list the files you changed.',
].join('\n');

/**
 * The scoped turn text. Canonical builder for engine-side hosts is
 * `src/preview/prompt.py` (`build_preview_prompt`); this mirror exists because the composer must
 * show the EXACT text before the turn is dispatched, and a renderer cannot call Python. The
 * cross-language test pins that both carry the same required fields and scope rules.
 */
export function buildPreviewPrompt(batch: CrusorPreviewBatch, options?: { readonly maxChars?: number }): string {
	const fixes = (batch?.fixes || []).filter(fix => (fix?.instruction || '').trim().length > 0);
	if (!fixes.length) { return ''; }
	const maxChars = options?.maxChars ?? 12_000;
	const target = quote(batch.targetLabel || batch.target, 200) || 'the previewed page';

	const header = [
		`<!-- crusor-preview:fix-batch count=${fixes.length} -->`,
		`Crusor Preview — ${fixes.length} UI fix${fixes.length === 1 ? '' : 'es'} from the live preview of ${target}.`,
		'',
		SCOPE_RULES,
	];
	if (batch.viewport && batch.viewport !== 'responsive') {
		header.push(`(Previewed at the ${batch.viewport} viewport preset.)`);
	}

	const blocks: string[] = [];
	let dropped = 0;
	for (let index = 0; index < fixes.length; index++) {
		const fix = fixes[index];
		const element = fix.element || ({} as CrusorPreviewElement);
		const lines = [
			`Fix ${index + 1} — ${quote(fix.label, 120) || describeFixElement(fix)}`,
			`  instruction: ${quote(fix.instruction, 400)}`,
		];
		if (element.selector) { lines.push(`  selector: ${quote(element.selector, 220)}`); }
		const fingerprint = fingerprintLine(element);
		if (fingerprint) { lines.push(`  fingerprint: ${fingerprint}`); }
		const source = sourceLine(element);
		if (source) { lines.push(`  source: ${source}`); }
		if (element.rect) {
			let box = `  box: ${element.rect.width}×${element.rect.height} at (${element.rect.x},${element.rect.y})`;
			if (element.viewport) { box += ` · viewport ${element.viewport.width}×${element.viewport.height}`; }
			lines.push(box);
		}
		if (element.styles) {
			const rendered = Object.keys(element.styles).slice(0, 10).map(key => `${key}: ${element.styles![key]}`);
			if (rendered.length) { lines.push(`  styles: ${rendered.join('; ')}`); }
		}
		const html = quote(element.outerHtml, 420);
		if (html) { lines.push(`  html: ${html}`); }

		const candidate = blocks.concat([lines.join('\n')]).join('\n\n');
		if (header.join('\n').length + candidate.length > maxChars) {
			dropped = fixes.length - index;
			break;
		}
		blocks.push(lines.join('\n'));
	}

	const parts = [header.join('\n'), '', blocks.join('\n\n')];
	if (dropped) {
		parts.push(`\n(${dropped} further fix${dropped === 1 ? '' : 'es'} were left out to stay inside the prompt budget — ask me to re-send them.)`);
	}
	parts.push('\nAfter editing, re-read the lines you changed to confirm them. Do not start a dev '
		+ 'server, watcher, or any other long-running process to check your work — the preview window '
		+ 're-renders the page itself, and the user sees the result in place.');
	return parts.join('\n').trim() + '\n';
}

/* -------------------------------------------------------------------------------------------- *
 * Step 1: is a preview available? — decided from what the session actually did.
 *
 * Pure on purpose. The renderer feeds it evidence from streamed tool calls and written files, and
 * the answer ("there is UI to look at, here is where") is what lights the Preview affordance. A
 * heuristic that lives in a service is a heuristic nobody can test; this one takes an array.
 * -------------------------------------------------------------------------------------------- */

export interface CrusorPreviewEvidence {
	/** 'command' = a shell/run tool invocation, 'file' = a file the agent wrote */
	readonly kind: 'command' | 'file';
	readonly text?: string;
	readonly path?: string;
}

export interface CrusorPreviewAvailability {
	readonly available: boolean;
	readonly reason: 'dev-server' | 'html-file' | '';
	readonly url?: string;
	readonly file?: string;
	readonly label?: string;
	/** the command that produced the url — shown in the UI so the claim is checkable */
	readonly evidence?: string;
}

const DEV_SERVER_PATTERNS: readonly RegExp[] = [
	/\b(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:dev|start|serve|preview)\b/i,
	/\b(?:vite|next|nuxt|astro|remix|parcel|webpack-dev-server|ng serve|expo start)\b/i,
	/\b(?:python3?|py)\s+-m\s+http\.server\b/i,
	/\b(?:flask|uvicorn|gunicorn|fastapi)\s+run\b/i,
	/\bphp\s+-S\b/i,
	/\bcargo\s+(?:run|watch)\b/i,
	/\bdotnet\s+run\b/i,
	/\bgo\s+run\b/i,
];

const LOCAL_URL = /\bhttps?:\/\/(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(?::(\d{1,5}))?[^\s"'`,;)]*/i;

const HTML_FILE = /\.(?:html?|xhtml)(?:$|[?#])/i;
const UI_FILE = /\.(?:tsx|jsx|vue|svelte|astro|css|scss|sass|less)(?:$|[?#])/i;

/**
 * Decide whether the session produced something previewable.
 *
 * Later evidence wins (the agent restarts a dev server on a new port, or writes a second page), so
 * the array is read back-to-front. A dev-server command is preferred over a written file because it
 * is a *live* target; a written HTML file is still previewable with no server at all, which is the
 * whole point of supporting `kind: 'file'`.
 */
export function detectPreviewAvailability(evidence: readonly CrusorPreviewEvidence[]): CrusorPreviewAvailability {
	let best: CrusorPreviewAvailability = { available: false, reason: '' };
	for (let index = evidence.length - 1; index >= 0; index--) {
		const entry = evidence[index];
		if (!entry) { continue; }
		if (entry.kind === 'command') {
			const text = String(entry.text || '');
			if (!DEV_SERVER_PATTERNS.some(pattern => pattern.test(text))) { continue; }
			const url = text.match(LOCAL_URL);
			if (url) {
				const raw = url[0].replace(/[.,;)]+$/, '');
				const normalized = raw.replace('0.0.0.0', '127.0.0.1').replace(/\/+$/, '/');
				return {
					available: true, reason: 'dev-server', url: normalized,
					label: `dev server · ${new URL(normalized.replace('localhost', '127.0.0.1')).port || '80'}`,
					evidence: text.trim().slice(0, 200),
				};
			}
			// A dev-server command with no URL in its own text: the port is often printed later, so
			// this stays "not available" rather than guessing a port that may host something else.
			continue;
		}
		const path = String(entry.path || '');
		if (!path) { continue; }
		if (HTML_FILE.test(path)) {
			best = { available: true, reason: 'html-file', file: path, label: `workspace file · ${path}`, evidence: path };
			break;
		}
		if (!best.available && UI_FILE.test(path)) {
			// UI source with no server and no HTML yet: worth offering, nothing to frame.
			best = { available: true, reason: 'html-file', label: `UI source · ${path}`, evidence: path };
		}
	}
	return best;
}

/** Fold one streamed tool call into preview evidence, defensively (arguments are engine-shaped). */
export function evidenceFromToolCall(name: string, args: unknown): CrusorPreviewEvidence | undefined {
	const tool = String(name || '').toLowerCase();
	const serialized = typeof args === 'string' ? args : safeStringify(args);
	if (/run|shell|bash|exec|terminal|command/.test(tool)) {
		return { kind: 'command', text: serialized.slice(0, 4000) };
	}
	if (/write|create|edit|apply|patch|multi_edit/.test(tool)) {
		const path = extractPath(args) || serialized.match(/[\w./@-]+\.(?:html?|tsx|jsx|vue|svelte|astro|css)/i)?.[0];
		if (path) { return { kind: 'file', path, text: serialized.slice(0, 500) }; }
	}
	return undefined;
}

function extractPath(args: unknown): string | undefined {
	if (!args || typeof args !== 'object') { return undefined; }
	const record = args as Record<string, unknown>;
	for (const key of ['file_path', 'path', 'filePath', 'file', 'target_file', 'targetFile']) {
		const value = record[key];
		if (typeof value === 'string' && value.trim()) { return value.trim(); }
	}
	return undefined;
}

function safeStringify(value: unknown): string {
	try { return JSON.stringify(value) ?? ''; } catch { return ''; }
}
