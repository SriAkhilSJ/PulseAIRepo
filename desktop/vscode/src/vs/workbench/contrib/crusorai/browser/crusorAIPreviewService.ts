/*---------------------------------------------------------------------------------------------
 * Crusor Preview — the workbench side of the flow.
 *
 * What this service owns, and what it deliberately does not:
 *
 *   owns   step 1  deciding that a preview is available, from what the session actually did;
 *          step 2  opening the SEPARATE desktop window (a workbench auxiliary window: a real
 *                  native window, not a tab, not a side panel);
 *          step 9  taking the reviewed batch and dispatching it as an ordinary bridge `prompt`
 *                  frame, scoped to the elements the user clicked.
 *
 *   does not own
 *          steps 3-8, which live in the preview window itself
 *                  (browser/media/crusor-preview/{index.html,preview.css,preview.js} and the
 *                  injected overlay). This service starts that window and listens to it.
 *
 * Two architectural decisions worth stating, because both were forced rather than chosen:
 *
 * 1. The preview window's content is OUR page loaded from the workbench's own origin
 *    (`FileAccess.asBrowserUri`), the same trick `crusorAIViewPane.ts` documents for the
 *    CopilotKit SPA: the workbench document's CSP frames only 'self' and vscode-webview:, so an
 *    iframe pointing straight at `http://localhost:5173` is refused before the dev server is ever
 *    asked. Our page sets its own, narrower policy (allowing the loopback proxy) and frames the
 *    proxied, overlay-injected document inside it.
 *
 * 2. The target is registered with the preview proxy BY THE PREVIEW WINDOW, not here. Registering
 *    returns a capability token, and the call has to reach `http://127.0.0.1:<port>`; the
 *    workbench document's own `connect-src` does not allow that, while the preview page's does. So
 *    the workbench passes the target and the proxy origin along in the URL, and the window that is
 *    allowed to talk to the proxy does the talking.
 *--------------------------------------------------------------------------------------------*/

import { Disposable, DisposableStore, IDisposable, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { isWindows } from '../../../../base/common/platform.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { URI } from '../../../../base/common/uri.js';
import { FileAccess } from '../../../../base/common/network.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { IRequestService } from '../../../../platform/request/common/request.js';
import { INotificationService } from '../../../../platform/notification/common/notification.js';
import { CancellationToken } from '../../../../base/common/cancellation.js';
import { localize } from '../../../../nls.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IAuxiliaryWindowService } from '../../../services/auxiliaryWindow/browser/auxiliaryWindowService.js';
import { IPathService } from '../../../services/path/common/pathService.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ICrusorAISessionStore } from '../common/crusorAISessionStore.js';
import { CrusorAICommandId } from '../common/crusorAI.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
import {
	CrusorPreviewAvailability,
	CrusorPreviewBatch,
	CrusorPreviewElement,
	CrusorPreviewEndpoint,
	CrusorPreviewEvidence,
	CrusorPreviewHealth,
	CrusorPreviewKind,
	CrusorPreviewSource,
	CrusorPreviewWindowCommand,
	CrusorPreviewWindowEvent,
	buildPreviewPrompt,
	buildPreviewRelaunchPrompt,
	detectPreviewAvailability,
	evidenceFromToolCall,
	isBatchEmpty,
	previewWindowQuery,
	summarizeBatch,
} from '../common/crusorAIPreview.js';
import { installCrusorTheme } from './crusorTheme.js';

export const ICrusorAIPreviewService = createDecorator<ICrusorAIPreviewService>('crusorAIPreviewService');

export interface ICrusorAIPreviewService {
	readonly _serviceBrand: undefined;

	/** Step 1: is there UI to look at, and where? */
	readonly availability: CrusorPreviewAvailability;
	readonly onDidChangeAvailability: Event<CrusorPreviewAvailability>;
	/** A window the user can bring forward again without re-deriving the target. */
	readonly onDidChangeWindow: Event<boolean>;

	/** True while a preview window exists (the Preview chip shows its OPEN state off this). */
	readonly isWindowOpen: boolean;

	/**
	 * The observed target state: `closed` → `starting` → `live` | `down`. Only
	 * `live` may paint the Preview tab green; `down` turns it red and makes the
	 * click ASK THE AGENT to relaunch instead of opening a dead window.
	 */
	readonly health: CrusorPreviewHealth;
	readonly onDidChangeHealth: Event<CrusorPreviewHealth>;

	/** Steps 2-9: open (or focus) the preview window for the current target. Pre-flights URL targets. */
	openPreview(target?: { url?: string; file?: string; label?: string }): Promise<{ ok: boolean; reason?: string }>;
	closePreview(): void;

	/**
	 * The user clicked the red (down) Preview tab: send the agent one scoped turn
	 * that restarts the dev server and re-opens the preview. No hand-holding.
	 */
	requestRelaunch(): Promise<void>;
}

/** The preview window chrome, as shipped inside the app. */
const PREVIEW_WINDOW_RESOURCE = 'vs/workbench/contrib/crusorai/browser/media/crusor-preview/index.html';
const ENDPOINT_DIR = ['preview'];

export class CrusorAIPreviewService extends Disposable implements ICrusorAIPreviewService {
	declare readonly _serviceBrand: undefined;

	private readonly _onDidChangeAvailability = this._register(new Emitter<CrusorPreviewAvailability>());
	readonly onDidChangeAvailability = this._onDidChangeAvailability.event;
	private readonly _onDidChangeWindow = this._register(new Emitter<boolean>());
	readonly onDidChangeWindow = this._onDidChangeWindow.event;
	private readonly _onDidChangeHealth = this._register(new Emitter<CrusorPreviewHealth>());
	readonly onDidChangeHealth = this._onDidChangeHealth.event;

	/** The preview target's observed state (drives the Preview tab's color and click behavior). */
	private _health: CrusorPreviewHealth = 'closed';
	/** The live window's frame, kept so turn-end can command the reload itself. */
	private currentFrame: HTMLIFrameElement | undefined;
	/** The target the current window frames (for the relaunch turn when it dies). */
	private currentTarget: { url?: string; file?: string; label?: string } | undefined;
	/** Set when a preview-sourced turn is dispatched; consumed at that turn's end to reload the frame. */
	private pendingPreviewTurn = false;
	/** Per-session turnEndedAt high-water marks: detects a COMPLETED turn without guessing from event shapes. */
	private readonly lastSeenTurnEnd = new Map<string, number>();

	/** Evidence accumulates for the whole session: a dev server started ten turns ago still counts. */
	private readonly evidence: CrusorPreviewEvidence[] = [];
	private _availability: CrusorPreviewAvailability = { available: false, reason: '' };
	private readonly host = this._register(new MutableDisposable<DisposableStore>());
	/** Dedupe for target-error notifications: one toast per outage, not one per Reload click. */
	private lastTargetError: { url: string; at: number } = { url: '', at: 0 };

	constructor(
		@ICrusorAIEngineService private readonly engine: ICrusorAIEngineService,
		@IAuxiliaryWindowService private readonly auxiliaryWindows: IAuxiliaryWindowService,
		@IPathService private readonly pathService: IPathService,
		@IFileService private readonly fileService: IFileService,
		@IThemeService private readonly themeService: IThemeService,
		@IWorkspaceContextService private readonly workspaceService: IWorkspaceContextService,
		@IEditorService private readonly editorService: IEditorService,
		@ICrusorAISessionStore private readonly sessionStore: ICrusorAISessionStore,
		@ICrusorAIRendererService private readonly renderer: ICrusorAIRendererService,
		@ICommandService private readonly commandService: ICommandService,
		@ILogService private readonly logService: ILogService,
		@IRequestService private readonly requestService: IRequestService,
		@INotificationService private readonly notificationService: INotificationService,
	) {
		super();
		this._register(this.engine.onDidReceiveFrame(frame => this.absorb(frame)));
		// Turn-end watcher: when a preview-sourced turn completes, command the
		// window to reload so the fix (or the relaunch) is VISIBLE without the
		// user pressing anything. Session records carry turnEndedAt.
		this._register(this.sessionStore.onDidChange(() => this.onSessionsChanged()));
	}

	get isWindowOpen(): boolean { return this.host.value !== undefined; }

	get availability(): CrusorPreviewAvailability {
		return this._availability;
	}

	get health(): CrusorPreviewHealth {
		return this._health;
	}

	private set health(next: CrusorPreviewHealth) {
		if (this._health === next) { return; }
		this._health = next;
		this._onDidChangeHealth.fire(next);
	}

	/** Turn-end watcher: reload the live window the moment a preview turn completes. */
	private onSessionsChanged(): void {
		if (!this.pendingPreviewTurn) { return; }
		for (const record of this.sessionStore.records()) {
			const ended = record.turnEndedAt ?? 0;
			const seen = this.lastSeenTurnEnd.get(record.sessionId) ?? 0;
			if (ended > seen) {
				this.lastSeenTurnEnd.set(record.sessionId, ended);
				if (this.pendingPreviewTurn && this.currentFrame) {
					// A turn we handed off just ended: make the result visible. The
					// window reloads its frame (cache-busted) and reports target-ok
					// or target-error, which drives the health state from here.
					this.pendingPreviewTurn = false;
					this.health = 'starting';
					this.logService.info('[crusor-preview] preview turn ended — reloading the framed app');
					void this.retargetWindow(this.currentFrame);
				}
			}
		}
	}

	/**
	 * Retarget the live window at the RAW target with a FRESH endpoint handshake.
	 * The window re-registers through the proxy and frames the inspectable copy —
	 * sending the raw URL alone used to make it frame the dev server directly:
	 * a green chip on a window no click could ever inspect. The secret rotates
	 * on every proxy restart, so it is re-read here, not cached.
	 */
	private async retargetWindow(frame: HTMLIFrameElement): Promise<void> {
		const endpoint = await this.resolveEndpoint();
		if (!endpoint) {
			this.logService.warn('[crusor-preview] retarget: proxy gone — leaving the window on its last frame');
			return;
		}
		this.postToWindow(frame, CrusorPreviewWindowCommand.SetTarget, {
			target: this.currentTarget?.url ?? '',
			file: this.currentTarget?.file ?? '',
			label: this.currentTarget?.label ?? '',
			kind: this.currentTarget?.file ? 'file' : 'url',
			endpoint: endpoint.origin,
			secret: endpoint.secret ?? '',
		});
	}

	/** Fold a streamed frame into the evidence that decides availability (step 1). */
	private absorb(frame: unknown): void {
		const record = frame as { type?: string; name?: string; arguments?: unknown } | undefined;
		if (record?.type !== 'tool_call_start' || !record.name) {
			return;
		}
		const evidence = evidenceFromToolCall(record.name, record.arguments);
		if (!evidence) {
			return;
		}
		this.evidence.push(evidence);
		if (this.evidence.length > 400) {
			this.evidence.splice(0, this.evidence.length - 400);
		}
		const next = detectPreviewAvailability(this.evidence);
		// Sticky within a session: once the agent has built UI, the affordance stays even though a later
		// unrelated command (a test run, a lint) is the newest evidence. Retracting it would make the
		// Preview button flicker away the moment the agent did anything else.
		if (!next.available) {
			return;
		}
		if (next.url === this._availability.url && next.file === this._availability.file && next.reason === this._availability.reason) {
			return;
		}
		this._availability = next;
		this._onDidChangeAvailability.fire(next);
	}

	// ── the endpoint (src/preview/endpoint.py publishes it; the IDE only reads) ───────────────

	/**
	 * True liveness probe: `started_at` in the registration file is the proxy's boot time, not a
	 * health signal, so an old file says nothing about the proxy behind it. Any HTTP answer (even
	 * an error status) proves the process is listening; only a connection failure means it is gone.
	 * The request runs through the main process, so the renderer CSP's connect-src list does not
	 * apply to this loopback GET.
	 */
	private async proxyAlive(endpoint: CrusorPreviewEndpoint): Promise<boolean> {
		if (!endpoint.origin) {
			return false;
		}
		const health = `${endpoint.origin.replace(/\/$/, '')}${endpoint.health_path ?? '/crusor-preview/health'}`;
		try {
			await this.requestService.request({ type: 'GET', url: health, timeout: 3000, callSite: 'crusorAIPreviewService.proxyAlive' }, CancellationToken.None);
			return true;
		} catch {
			return false;
		}
	}


	private endpointDirectory(): URI {
		return URI.joinPath(this.pathService.userHome({ preferLocal: true }), '.crusorai', ...ENDPOINT_DIR);
	}

	/**
	 * The folder this session is bound to, by the contribution's P0 rule (the same one
	 * `crusorAIRendererService.sessionFolder` applies to the composer): zero folders means no
	 * workspace, one folder is unambiguous, and a multi-root workspace is NEVER silently resolved to
	 * `folders[0]` — this service owns no folder picker, so it declines rather than guesses.
	 *
	 * The engine enforces this path in two directions: `prompt` frames may not omit it (the bridge
	 * answers `workspace required: open a project folder before starting a Crusor session`), and a
	 * frame whose workspace differs from the session's bound one is refused as a workspace switch.
	 */
	private get workspacePath(): string | undefined {
		const folders = this.workspaceService.getWorkspace().folders;
		return folders.length === 1 ? folders[0].uri.fsPath : undefined;
	}

	/**
	 * The freshest published endpoint for this workspace. The proxy writes one file per session, and
	 * the workbench is not told which session id owns the local proxy, so the workspace path decides:
	 * a preview server started for THIS folder is the one worth framing.
	 */
	private async resolveEndpoint(): Promise<CrusorPreviewEndpoint | undefined> {
		const open = this.workspaceService.getWorkspace().folders.map(folder => folder.uri.fsPath);
		if (!open.length) {
			return undefined;
		}
		const directory = this.endpointDirectory();
		let children;
		try {
			children = await this.fileService.resolve(directory);
		} catch (error) {
			this.logService.trace('[crusor-preview] no endpoint directory yet', error);
			return undefined;
		}
		const candidates: { endpoint: CrusorPreviewEndpoint; path: URI }[] = [];
		for (const child of children.children ?? []) {
			if (!child.name.endsWith('.json')) {
				continue;
			}
			try {
				const content = await this.fileService.readFile(child.resource);
				const endpoint = JSON.parse(content.value.toString()) as CrusorPreviewEndpoint;
				if (!endpoint?.origin) {
					continue;
				}
				// An endpoint names the workspace its proxy serves. Accept only one of the folders that
				// are actually open: with an empty `open` this used to accept ANY endpoint, so a
				// multi-root workspace (or no folder at all) could frame a different project's proxy.
				// Windows paths are case-insensitive: the proxy publishes the resolved
				// (canonical-case) path while the workbench reports the folder as opened
				// (`d:\TestPulseAI` vs `D:\TestPulseAI`), so compare accordingly there.
				const matchesOpen = (candidate: string) => isWindows
					? open.some(folder => folder.toLowerCase() === candidate.toLowerCase())
					: open.includes(candidate);
				if (endpoint.workspace && !matchesOpen(endpoint.workspace)) {
					continue;
				}
				candidates.push({ endpoint, path: child.resource });
			} catch (error) {
				this.logService.trace('[crusor-preview] unreadable endpoint', child.resource.toString(), error);
			}
		}
		if (!candidates.length) {
			return undefined;
		}
		candidates.sort((a, b) => (b.endpoint.started_at ?? 0) - (a.endpoint.started_at ?? 0));
		const newest = candidates[0].endpoint;
		const age = Date.now() - (newest.started_at ?? 0) * 1000;
		if (age > 12 * 60 * 60 * 1000) {
			// An old registration is stale only if the proxy behind it is gone: probe the health
			// endpoint before rejecting. A dev proxy that has been serving for a day is healthy —
			// age alone must never block Preview (a healthy long-lived proxy used to be rejected
			// here, which is exactly the "Preview does nothing" report this replaced).
			if (!(await this.proxyAlive(newest))) {
				this.logService.warn('[crusor-preview] newest endpoint is stale and its proxy does not answer', newest.origin);
				return undefined;
			}
			this.logService.info('[crusor-preview] long-lived but healthy preview proxy accepted', newest.origin);
		}
		return newest;
	}

	// ── step 2: the window ────────────────────────────────────────────────────────────────────

	async openPreview(target?: { url?: string; file?: string; label?: string }): Promise<{ ok: boolean; reason?: string }> {
		if (this.host.value) {
			// Already open: the auxiliary window keeps its state, and re-opening would lose the batch.
			this._onDidChangeWindow.fire(true);
			return { ok: true };
		}
		const endpoint = await this.resolveEndpoint();
		if (!endpoint) {
			this.logService.warn('[crusor-preview] no preview proxy published for this workspace');
			this.notificationService.warn(localize('crusorai.preview.noEndpoint', 'Crusor Preview: no preview proxy is registered for this workspace. Run a preview batch (or start your dev server through the agent), then press Preview again.'));
			return { ok: false, reason: 'no preview proxy is registered for this workspace' };
		}
		const resolved = target ?? this.targetFromAvailability();
		if (!resolved.url && !resolved.file) {
			this.logService.warn('[crusor-preview] no target to preview');
			this.notificationService.warn(localize('crusorai.preview.noTarget', 'Crusor Preview: nothing to preview yet — ask the agent to build or run your app, then press Preview.'));
			return { ok: false, reason: 'no target to preview yet' };
		}
		// Pre-flight conditions (the cheap ones first): a dead proxy or a dead
		// dev server used to open a white window and cost a whole LLM turn to
		// discover. The engine probe in the preview.open receipt stays the agent
		// path; this one protects the human click path. URL targets only — a
		// workspace file cannot be probed with a socket.
		if (!(await this.proxyAlive(endpoint))) {
			this.logService.warn('[crusor-preview] proxy dead — refusing to spawn a dead window');
			this.notificationService.warn(localize('crusorai.preview.proxyDown', 'Crusor Preview: the preview proxy is not running. Ask Crusor to start it, then press Preview again.'));
			return { ok: false, reason: 'the preview proxy is not running' };
		}
		if (resolved.url) {
			const targetAlive = await this.targetReachable(resolved.url);
			if (!targetAlive.ok) {
				this.logService.warn('[crusor-preview] target refused pre-flight —', targetAlive.detail);
				this.health = 'down';
				this.currentTarget = resolved;
				this.notificationService.warn(localize('crusorai.preview.targetDown', 'Crusor Preview: {0} is not answering. Click the red Preview tab to ask Crusor to restart it.', resolved.url));
				return { ok: false, reason: targetAlive.detail };
			}
		}
		this.health = 'starting';
		this.currentTarget = resolved;

		const kind: CrusorPreviewKind = resolved.file ? 'file' : 'url';
		const uri = FileAccess.asBrowserUri(PREVIEW_WINDOW_RESOURCE as never).toString(true);
		const query = previewWindowQuery(endpoint, {
			kind,
			target: resolved.url ?? '',
			file: resolved.file ?? '',
			label: resolved.label ?? '',
			session: endpoint.session_id ?? '',
		});
		const url = `${uri}?${query}`;

		// The frame MUST be created in the main window's document, before the
		// auxiliary window opens: the aux document forbids createElement (its
		// instanceof guard throws), while a main-created node adopted via
		// appendChild keeps working `instanceof HTMLElement` checks. Creating
		// first also means a failure here leaks no open auxiliary window.
		const frame = document.createElement('iframe');
		frame.className = 'crusor-preview-window-frame';
		frame.setAttribute('title', 'Crusor Preview');
		// Absolute, over the auxiliary window's content area. The window's own `container` div is left
		// alone on purpose: it is positioned and laid out by the workbench, and overwriting its styles
		// from here is how an auxiliary window ends up unable to render its own parts.
		frame.style.cssText = 'position:absolute;inset:0;z-index:100;display:block;width:100%;height:100%;border:0;background:#1f1f1f;';
		frame.setAttribute('src', url);

		const auxiliary = await this.auxiliaryWindows.open({
			// A preview wants room: it is a page rendered at a real size, not a panel. The OS titlebar
			// stays: it is how the window is moved and closed, since the preview iframe covers the
			// window's content area and our own chrome cannot drag a frameless window from inside a frame.
			bounds: { width: 1180, height: 840 },
			nativeTitlebar: true,
			backgroundColor: '#1f1f1f',
		});
		const store = new DisposableStore();
		store.add(auxiliary);

		const host = auxiliary.window.document.body;
		host.appendChild(frame);
		// The same derived-token machine the Agent pane runs, on this window's container: the preview
		// chrome and the injected overlay wear the live theme, not a palette of their own.
		store.add(installCrusorTheme(auxiliary.container, this.themeService));
		store.add(this.themeService.onDidColorThemeChange(() => this.pushTheme(frame, auxiliary.container)));
		store.add(this.listen(frame));
		store.add(toDisposable(() => {
			this._onDidChangeWindow.fire(false);
			this.currentFrame = undefined;
			this.health = 'closed';
			frame.remove();
		}));

		this.host.value = store;
		this.currentFrame = frame;
		this._onDidChangeWindow.fire(true);
		this.logService.info('[crusor-preview] window opened', url);
		return { ok: true };
	}

	/**
	 * HTTP reachability for a URL target, from the renderer via the main
	 * process (loopback CSP-safe, same as proxyAlive). ANY answer counts as
	 * alive — a 500 compile-error page still means the server is up; a
	 * connection refusal means the click would spawn a white window.
	 */
	private async targetReachable(url: string): Promise<{ ok: boolean; detail: string }> {
		let parsed: URL;
		try {
			parsed = new URL(url);
		} catch {
			return { ok: false, detail: `not a usable URL: ${url}` };
		}
		if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
			return { ok: false, detail: `not an http(s) URL: ${url}` };
		}
		// no-cors on purpose: ANY answer — a 404, a 500, a redirect — proves the
		// server is up (the window's own load handler judges the page itself),
		// and an opaque response sidesteps CORS entirely. Field 2026-09-27:
		// `npx serve` landed on a random port and answered fine, but a plain
		// fetch read the CORS block as "nothing answered" and refused a LIVE
		// target three times — exactly the wasted agent calls this gate exists
		// to prevent. Reject here means network-level refusal, nothing else.
		const controller = new AbortController();
		const timer = setTimeout(() => controller.abort(), 3000);
		try {
			await fetch(url, { mode: 'no-cors', cache: 'no-store', signal: controller.signal });
			return { ok: true, detail: 'answered' };
		} catch (error) {
			const aborted = error instanceof Error && error.name === 'AbortError';
			// Second opinion before refusing: the renderer fetch can also fail
			// on a CSP connect-src block in a packaged build — not the server's
			// fault. The request service path runs through the main process
			// (same channel proxyAlive uses), immune to both CORS and CSP.
			try {
				await this.requestService.request({ type: 'GET', url, timeout: 3000, callSite: 'crusorAIPreviewService.targetReachable' }, CancellationToken.None);
				return { ok: true, detail: 'answered (via request service)' };
			} catch {
				return { ok: false, detail: aborted
					? `${parsed.host} did not answer within 3s`
					: `nothing is listening on ${parsed.host}` };
			}
		} finally {
			clearTimeout(timer);
		}
	}

	/**
	 * The user clicked the red (down) Preview tab: hand the restart to the agent
	 * as one scoped turn (start dev server → verify HTTP 200 → preview.open with
	 * target_reachable check), not another dead window.
	 */
	async requestRelaunch(): Promise<void> {
		const workspace = this.workspacePath;
		if (!workspace) {
			this.notificationService.warn(localize('crusorai.preview.relaunchNoWorkspace', 'Crusor Preview: open one project folder first — the relaunch turn must name its workspace.'));
			return;
		}
		const text = buildPreviewRelaunchPrompt(this.currentTarget ?? this.targetFromAvailability());
		const frame = {
			type: 'prompt',
			session_id: this.latestSessionId() ?? '',
			workspace,
			text,
			mode: 'agent',
			preview_batch: {
				source: 'crusor-preview',
				target: this.currentTarget?.url ?? '',
				target_label: this.currentTarget?.label ?? '',
				kind: this.currentTarget?.file ? 'file' : 'url',
				viewport: 'responsive',
				count: 0,
				summary: 'preview relaunch request (target down)',
			},
		};
		// Same composer-parity gate as sendBatchToAgent: the user bubble plus a
		// live session, else the session_info handler opens a fresh one.
		if (this.renderer.beginExternalTurn(text)) {
			this.engine.send(frame as never);
			// The relaunch turn ends with the server either back or explained:
			// the watcher reloads the frame, and target-ok/target-error re-paint
			// the tab. If the agent re-opens the window instead, preview.open's
			// pre-flight gates a fresh spawn on a live target first.
			this.pendingPreviewTurn = true;
			this.logService.info('[crusor-preview] relaunch requested — the agent will restart the dev server and re-open the preview');
			this.notificationService.info(localize('crusorai.preview.relaunchSent', 'Crusor Preview: asked Crusor to bring the preview back — watch the Agent tab.'));
		} else {
			this.logService.info('[crusor-preview] relaunch: no live Agent session; the request opens a fresh session');
		}
		try {
			await this.commandService.executeCommand(CrusorAICommandId.Focus);
		} catch (error) {
			this.logService.warn('[crusor-preview] could not focus the Agent surface', error);
		}
	}

	closePreview(): void {
		this.host.clear();
		this.currentFrame = undefined;
		this.health = 'closed';
	}

	private targetFromAvailability(): { url?: string; file?: string; label?: string } {
		const availability = this._availability;
		if (availability.reason === 'dev-server' && availability.url) {
			return { url: availability.url, label: availability.label };
		}
		if (availability.file) {
			return { file: availability.file, label: availability.label };
		}
		return { label: availability.label };
	}

	/** The preview window's palette is the pane's palette: the same derived-token machine. */
	private pushTheme(frame: HTMLIFrameElement, container: HTMLElement): void {
		const computed = container.ownerDocument.defaultView?.getComputedStyle(container);
		if (!computed) {
			return;
		}
		const read = (name: string): string | undefined => computed.getPropertyValue(name).trim() || undefined;
		const theme = {
			accent: read('--crusorai-accent'),
			agent: read('--crusorai-agent'),
			verified: read('--crusorai-verified'),
			approval: read('--crusorai-approval'),
			failed: read('--crusorai-failed'),
			bg: read('--vscode-editor-background'),
			surface: read('--vscode-sideBar-background'),
			surfaceRaised: read('--vscode-editorWidget-background'),
			surfaceStrong: read('--vscode-button-secondaryBackground'),
			text: read('--vscode-foreground'),
			textWeak: read('--vscode-descriptionForeground'),
			border: read('--vscode-widget-border'),
			fontUi: read('--vscode-font-family'),
			fontMono: read('--vscode-editor-font-family'),
			onAccent: read('--vscode-button-secondaryForeground'),
		};
		this.postToWindow(frame, CrusorPreviewWindowCommand.Configure, { theme });
	}

	private postToWindow(frame: HTMLIFrameElement, command: string, payload: Record<string, unknown> = {}): void {
		const target = frame.contentWindow;
		if (!target) {
			return;
		}
		target.postMessage({ source: CrusorPreviewSource.Workbench, command, ...payload }, '*');
	}

	/** Messages from the preview window: the batch, a source request, and the window's own chrome. */
	private listen(frame: HTMLIFrameElement): IDisposable {
		const listener = (event: MessageEvent) => {
			const data = event?.data as { source?: string; type?: string } & Record<string, unknown> | undefined;
			if (!data || data.source !== CrusorPreviewSource.Window) {
				return;
			}
			switch (data.type) {
				case CrusorPreviewWindowEvent.Ready:
					this.pushTheme(frame, frame.parentElement ?? frame);
					break;
				case CrusorPreviewWindowEvent.TargetOk:
					// The window's own load handler says the framed app rendered:
					// the only state allowed to paint the Preview tab green.
					this.health = 'live';
					this.logService.info('[crusor-preview] target is live', data['url']);
					break;
				case CrusorPreviewWindowEvent.ReviewSubmit:
					void this.sendBatchToAgent(data.batch as CrusorPreviewBatch);
					break;
				case CrusorPreviewWindowEvent.OpenSource:
					void this.revealSource(data.element as CrusorPreviewElement);
					break;
				case CrusorPreviewWindowEvent.CloseRequest:
					this.closePreview();
					break;
				case CrusorPreviewWindowEvent.Viewport:
					this.logService.trace('[crusor-preview]', data.type, data);
					break;
				case CrusorPreviewWindowEvent.TargetError: {
					// The window already explains itself in-place; this makes the
					// outage impossible to miss AND turns the Preview tab red so
					// the next click becomes a relaunch request, not a dead window.
					const url = typeof data['url'] === 'string' ? data['url'] : '';
					const now = Date.now();
					this.logService.warn('[crusor-preview] target error', data);
					if (url !== this.lastTargetError.url || now - this.lastTargetError.at > 15000) {
						this.lastTargetError = { url, at: now };						this.notificationService.warn(
							'Crusor Preview: the framed app failed to render'
							+ (url ? ` (${url})` : '')
							+ ' — click the red Preview tab and Crusor will bring it back.'
						);
						}
						this.health = 'down';
						break;
					}
				case CrusorPreviewWindowEvent.Inspect:
				case CrusorPreviewWindowEvent.ElementSelected:
				case CrusorPreviewWindowEvent.FixAdded:
					this.logService.trace('[crusor-preview]', data.type, data);
					break;
				default:
					break;
			}
		};
		frame.ownerDocument.defaultView?.addEventListener('message', listener);
		return toDisposable(() => frame.ownerDocument.defaultView?.removeEventListener('message', listener));
	}

	// ── step 9: the handoff ───────────────────────────────────────────────────────────────────

	/**
	 * Dispatch the reviewed batch. The text is built here (via the shared contract module) because
	 * the composer must be able to show exactly what is sent; the Python builder in
	 * `src/preview/prompt.py` is the canonical one for engine-side hosts, and the two are pinned
	 * against each other (src/tests/test_preview_contract.py).
	 */
	async sendBatchToAgent(batch: CrusorPreviewBatch): Promise<void> {
		if (isBatchEmpty(batch)) {
			return;
		}
		// The bridge rejects a `prompt` frame without a workspace (`_WORKSPACE_REQUIRED_METHODS`), so
		// this is refused here with an honest log line instead of being sent to die as an error card.
		const workspace = this.workspacePath;
		if (!workspace) {
			this.logService.warn(
				'[crusor-preview] batch not sent: no single project folder is open '
				+ '(open one folder, or pick one in a multi-root workspace) — a preview turn must name its workspace'
			);
			return;
		}
		const text = buildPreviewPrompt(batch);
		const frame = {
			type: 'prompt',
			session_id: batch.sessionId || this.latestSessionId() || '',
			workspace,
			text,
			mode: 'agent',
			preview_batch: {
				source: 'crusor-preview',
				target: batch.target,
				target_label: batch.targetLabel ?? '',
				kind: batch.kind ?? 'url',
				viewport: batch.viewport ?? 'responsive',
				count: batch.fixes.length,
				summary: summarizeBatch(batch),
			},
		};
		// The transcript owns the USER half of the turn: beginExternalTurn sets
		// the user bubble and flips the running state exactly as the composer's
		// send does — without it the batch ran invisibly (Thought/Navigate cards
		// with nothing above them). It also answers whether a session is live:
		// without one the frame below would be refused (prompt requires a
		// session), so the text is left parked behind a session_create and the
		// session_info handler starts the fresh turn with it instead.
		if (this.renderer.beginExternalTurn(text)) {
			this.engine.send(frame as never);
			// This turn ends with the fixes either applied or explained: the
			// turn-end watcher reloads the frame so the result is visible with
			// zero clicks, and the load outcome re-drives the health state.
			this.pendingPreviewTurn = true;
			this.logService.info('[crusor-preview] sent', summarizeBatch(batch));
		} else {
			// Parked behind a session_create: the session_info handler starts the
			// fresh turn with this text. Its end is still ours to watch — the
			// turn-end watcher reloads the frame exactly as for a live session.
			this.pendingPreviewTurn = true;
			this.logService.info('[crusor-preview] no live Agent session; the batch opens a fresh session');
		}

		// Step 9's other half: the Agent surface comes forward in the MAIN window, because that is where
		// the work now is ("Review -> redirects/focuses back to the main Agent"). Every Crusor entry
		// point in this contribution funnels through the same focus command; the turn is already sent,
		// and `preserveFocus`-style stealing is avoided by letting the command own the focus rules.
		try {
			await this.commandService.executeCommand(CrusorAICommandId.Focus);
		} catch (error) {
			this.logService.warn('[crusor-preview] could not focus the Agent surface', error);
		}
	}

	/** The session the composer is talking to: the most recently active one the store knows about. */
	private latestSessionId(): string | undefined {
		const records = this.sessionStore.records();
		if (!records.length) {
			return undefined;
		}
		let best = records[0];
		let bestAt = 0;
		for (const record of records) {
			const at = record.turnEndedAt ?? record.turnStartedAt ?? record.firstSeenAt ?? 0;
			if (at >= bestAt) {
				best = record;
				bestAt = at;
			}
		}
		return best.sessionId;
	}

	/** The element carries enough to find its source; the editor is where the user can act on it. */
	private async revealSource(element: CrusorPreviewElement | undefined): Promise<void> {
		const file = element?.fingerprint?.source?.file;
		if (!file) {
			this.logService.trace('[crusor-preview] no stamped source for this element', element?.selector);
			return;
		}
		const folder = this.workspaceService.getWorkspace().folders[0];
		if (!folder) {
			return;
		}
		const resource = URI.joinPath(folder.uri, ...file.split('/'));
		try {
			await this.editorService.openEditor({ resource, options: { pinned: false } });
		} catch (error) {
			this.logService.warn('[crusor-preview] could not open', file, error);
		}
	}
}
