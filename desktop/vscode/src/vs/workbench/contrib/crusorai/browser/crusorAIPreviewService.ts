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
import { Emitter, Event } from '../../../../base/common/event.js';
import { URI } from '../../../../base/common/uri.js';
import { FileAccess } from '../../../../base/common/network.js';
import { IFileService } from '../../../../platform/files/common/files.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IAuxiliaryWindowService } from '../../../services/auxiliaryWindow/browser/auxiliaryWindowService.js';
import { IPathService } from '../../../services/path/common/pathService.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ICrusorAISessionStore } from '../common/crusorAISessionStore.js';
import { CrusorAICommandId } from '../common/crusorAI.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import { ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
import {
	CrusorPreviewAvailability,
	CrusorPreviewBatch,
	CrusorPreviewElement,
	CrusorPreviewEndpoint,
	CrusorPreviewEvidence,
	CrusorPreviewKind,
	CrusorPreviewSource,
	CrusorPreviewWindowCommand,
	CrusorPreviewWindowEvent,
	buildPreviewPrompt,
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

	/** Steps 2-9: open (or focus) the preview window for the current target. */
	openPreview(target?: { url?: string; file?: string; label?: string }): Promise<void>;
	closePreview(): void;
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

	/** Evidence accumulates for the whole session: a dev server started ten turns ago still counts. */
	private readonly evidence: CrusorPreviewEvidence[] = [];
	private _availability: CrusorPreviewAvailability = { available: false, reason: '' };
	private readonly host = this._register(new MutableDisposable<DisposableStore>());

	constructor(
		@ICrusorAIEngineService private readonly engine: ICrusorAIEngineService,
		@IAuxiliaryWindowService private readonly auxiliaryWindows: IAuxiliaryWindowService,
		@IPathService private readonly pathService: IPathService,
		@IFileService private readonly fileService: IFileService,
		@IThemeService private readonly themeService: IThemeService,
		@IWorkspaceContextService private readonly workspaceService: IWorkspaceContextService,
		@IEditorService private readonly editorService: IEditorService,
		@ICrusorAISessionStore private readonly sessionStore: ICrusorAISessionStore,
		@ICommandService private readonly commandService: ICommandService,
		@ILogService private readonly logService: ILogService,
	) {
		super();
		this._register(this.engine.onDidReceiveFrame(frame => this.absorb(frame)));
	}

	get availability(): CrusorPreviewAvailability {
		return this._availability;
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
				if (endpoint.workspace && !open.includes(endpoint.workspace)) {
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
		if (Date.now() - (newest.started_at ?? 0) * 1000 > 12 * 60 * 60 * 1000) {
			this.logService.warn('[crusor-preview] newest endpoint is stale', newest.origin);
			return undefined;
		}
		return newest;
	}

	// ── step 2: the window ────────────────────────────────────────────────────────────────────

	async openPreview(target?: { url?: string; file?: string; label?: string }): Promise<void> {
		if (this.host.value) {
			// Already open: the auxiliary window keeps its state, and re-opening would lose the batch.
			this._onDidChangeWindow.fire(true);
			return;
		}
		const endpoint = await this.resolveEndpoint();
		if (!endpoint) {
			this.logService.warn('[crusor-preview] no preview proxy published for this workspace');
			return;
		}
		const resolved = target ?? this.targetFromAvailability();
		if (!resolved.url && !resolved.file) {
			this.logService.warn('[crusor-preview] no target to preview');
			return;
		}

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

		const frame = auxiliary.window.document.createElement('iframe');
		frame.className = 'crusor-preview-window-frame';
		frame.setAttribute('title', 'Crusor Preview');
		// Absolute, over the auxiliary window's content area. The window's own `container` div is left
		// alone on purpose: it is positioned and laid out by the workbench, and overwriting its styles
		// from here is how an auxiliary window ends up unable to render its own parts.
		frame.style.cssText = 'position:absolute;inset:0;z-index:100;display:block;width:100%;height:100%;border:0;background:#1f1f1f;';
		frame.setAttribute('src', url);
		const host = auxiliary.window.document.body;
		host.appendChild(frame);
		// The same derived-token machine the Agent pane runs, on this window's container: the preview
		// chrome and the injected overlay wear the live theme, not a palette of their own.
		store.add(installCrusorTheme(auxiliary.container, this.themeService));
		store.add(this.themeService.onDidColorThemeChange(() => this.pushTheme(frame, auxiliary.container)));
		store.add(this.listen(frame));
		store.add(toDisposable(() => {
			this._onDidChangeWindow.fire(false);
			frame.remove();
		}));

		this.host.value = store;
		this._onDidChangeWindow.fire(true);
		this.logService.info('[crusor-preview] window opened', url);
	}

	closePreview(): void {
		this.host.clear();
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
		this.engine.send(frame as never);
		this.logService.info('[crusor-preview] sent', summarizeBatch(batch));

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
