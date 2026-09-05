/*---------------------------------------------------------------------------------------------
 * One shared event model and host adapter for the compact Agent view and Pulse Manager.
 *--------------------------------------------------------------------------------------------*/

import { Disposable, IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IWorkspaceContextService, IWorkspaceFolder } from '../../../../platform/workspace/common/workspace.js';
import { IAuxiliaryWindowService } from '../../../services/auxiliaryWindow/browser/auxiliaryWindowService.js';
import { PulseAICommandId } from '../common/pulseAI.js';
import { IPulseAIEngineService, PulseAIEngineSetupError, PulseAIEngineState } from '../common/pulseAIEngineService.js';
import type { PulseClientMethod, PulseExecutionMode, PulseServerEvent } from '../common/pulseAIProtocol.js';
import { PULSE_AI_WORKBENCH_CAPABILITIES } from '../common/pulseAIWorkbenchCapabilities.js';
import { IPulseAIRendererService, PulseAISurface } from '../common/pulseAIRendererService.js';
import { IPulseAISessionStore } from '../common/pulseAISessionStore.js';
import { pulseSessionLabel, pulseSessionRows, pulseSessionStatusName, type PulseAISessionFacts, type PulseAISessionRow } from '../common/pulseAISessionProjection.js';
import { IPulseAIWorkbenchService } from '../common/pulseAIWorkbenchService.js';
import {
	mountPulseAIRenderer,
	PulseAIRenderHost,
	PulseAIRenderModel,
	PulseAIRenderMount,
	PulseAIToolState,
	PulseAIToolView,
	PulseAITurnPart,
	PulseAISubAgentView,
} from './pulseAIRenderer.js';

function valueRecord(value: unknown): Readonly<Record<string, unknown>> | undefined {
	return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Readonly<Record<string, unknown>> : undefined;
}

function toolState(status: string): PulseAIToolState {
	const value = status.toLowerCase();
	if (value.includes('fail') || value.includes('error') || value.includes('denied') || value.includes('cancel')) { return 'failed'; }
	if (value.includes('pass') || value.includes('success') || value.includes('complete') || value === 'ok') { return 'passed'; }
	if (value.includes('approval') || value.includes('permission')) { return 'approval'; }
	if (value.includes('run') || value.includes('start') || value.includes('progress')) { return 'running'; }
	return 'queued';
}

function planText(step: unknown): string {
	if (typeof step === 'string') { return step; }
	const record = valueRecord(step);
	for (const key of ['title', 'text', 'description', 'goal']) {
		if (typeof record?.[key] === 'string') { return record[key] as string; }
	}
	return 'Plan step';
}

function stringField(source: unknown, keys: readonly string[]): string | undefined {
	const value = valueRecord(source);
	for (const key of keys) {
		if (typeof value?.[key] === 'string' && value[key]) { return value[key] as string; }
	}
	return undefined;
}

export class PulseAIRendererService extends Disposable implements IPulseAIRendererService {
	declare readonly _serviceBrand: undefined;
	private readonly mounts = new Set<PulseAIRenderMount>();
	private readonly tools = new Map<string, PulseAIToolView>();
	private readonly seenEventIds = new Set<string>();
	private readonly eventIdOrder: string[] = [];
	private startPromise: Promise<void> | undefined;
	private renderFrame: number | undefined;
	private restartTimer: ReturnType<typeof setTimeout> | undefined;
	private restartAttempts = 0;
	private engineFault: string | undefined;
	private pendingPrompt: string | undefined;
	private draft = '';
	private mode: PulseExecutionMode = 'agent';
	private sessionId: string | undefined;
	private running = false;
	private cancelRequested = false;
	private turnOutcome: PulseAIRenderModel['turnOutcome'] = 'idle';
	private userMessage: string | undefined;
	private assistantText = '';
	/**
	 * Ordered timeline (hermes message.parts): one entry per text segment and
	 * tool call, in arrival order. `assistantText` stays the concatenated
	 * string for copy/inspector; the TRANSCRIPT paints from `parts` so tools
	 * sit where they happened and the final answer lands last. Cleared at
	 * turn boundaries with the rest of the turn state.
	 */
	private parts: PulseAITurnPart[] = [];
	private reasoning: string | undefined;
	/**
	 * Epoch ms the current turn began, or undefined between turns. The tail activity row counts
	 * from here until the transcript shows something, which is why it is a timestamp on the
	 * model rather than a counter in the renderer: a re-render must not restart the number.
	 */
	private turnStartedAt: number | undefined;
	/** When the last turn stopped, for the row's elapsed clock. Turn end is a frame, not a timer. */
	private turnEndedAt: number | undefined;
	private approval: PulseAIRenderModel['approval'];
	private subAgents = new Map<string, PulseAISubAgentView>();
	private plan: readonly string[] = [];
	private verification: string | undefined;
	private telemetry: PulseAIRenderModel['telemetry'] = {};
	private error: string | undefined;
	private engineSetupError = false;
	/**
	 * Live context-engine status (compaction in progress, overflow warning). Produced by the
	 * engine's `context_status` events: `compress`/`pre_api` set `compacting`, `compacted`
	 * clears it, `overflow_blocked` carries a warning that is NOT an `error` (the turn is
	 * still alive — it warns about the NEXT model call). Cleared at turn boundaries, like
	 * the other transient turn state.
	 */
	private contextStatus: PulseAIRenderModel['contextStatus'];
	/** True while the engine reports an open compaction (`compress`/`pre_api` phase). */
	private compacting: boolean | undefined;
	private voiceHeard: PulseAIRenderModel['voiceHeard'];
	/**
	 * Live provider-call status from llm.request/llm.response frames: which
	 * model is being asked and which attempt is in flight. This is what turns
	 * the pre-first-token wait from a frozen sentence into a live status — the
	 * hermes discipline that a stalled call must be visible and named.
	 */
	private llmStatus?: { readonly model: string; readonly attempt: number };
	/**
	 * Bounded anatomy of the LIVE request (llm.request carries role+head per
	 * message — factory `_request_heads`). Answers "what is the model actually
	 * seeing?" with one click instead of a chat question. Cleared with the
	 * other transient turn state.
	 */
	private llmHeads?: readonly { readonly role: string; readonly head: string }[];

	/**
	 * Hermes port (apps/desktop/src/store/session-states.ts): busy but SILENT
	 * for the whole watchdog window. Tuned there against real behavior — under
	 * ~4min paints healthy tool runs as suspect, 8min lands after the user has
	 * already given up; 5min is the compromise. Silence is NOT completion: long
	 * tool calls are legitimately quiet, so this is a presentation hint that
	 * never mutates the engine's real turn state, and ANY frame clears it.
	 */
	private stalled: boolean | undefined;
	private stallWatchdog: number | undefined;
	private hardWatchdog: number | undefined;
	/** Engine build reported on session_info — painted on the status chip so
	 * a stale engine is visible in the panel, not only in stderr. */
	private engineBuild: string | undefined;

	/**
	 * Degradation notices (runtime_degraded frames): honest "this ran bounded"
	 * receipts. Deliberately NOT `error` — a bounded scan is the engine working
	 * as designed, and rendering it as the fatal card (with its Retry button)
	 * told the user the turn died when it was alive. The hermes discipline: a
	 * degradation is spoken, never screamed.
	 */
	private degraded?: string;
	/** Reasoning frames seen this turn. A real reasoning stream sends many; a
	 * transport liveness dress-up (a status line posing as thought) sends one.
	 * The counter is how the renderer can hand a single-frame "reasoning" off
	 * to the llmStatus row without string-matching copy. */
	private reasoningFrameCount = 0;
	private history: PulseAIRenderModel['history'] = [];

	/**
	 * Explicit multi-root selection (P0): never silently pick folders[0].
	 * Set through selectWorkspace() and retained for the session, surviving
	 * re-renders, until the folder leaves the workspace or is replaced.
	 */
	private selectedWorkspaceUri: URI | undefined;

	private readonly host: PulseAIRenderHost = {
		setDraft: value => { this.draft = value; },
		setMode: mode => {
			if (this.running || this.mode === mode) { return; }
			this.mode = mode;
			this.render();
		},
		submitPrompt: text => { void this.submitPrompt(text); },
		cancel: () => {
			if (!this.running || this.cancelRequested) { return; }
			this.cancelRequested = true;
			this.send({ type: 'cancel', session_id: this.sessionId });
			this.render();
		},
		steer: text => { this.send({ type: 'steer', session_id: this.sessionId, text }); this.draft = ''; this.render(); },
		replyToSafety: (toolId, approved, alwaysAllow) => {
			this.send({ type: 'safety_reply', session_id: this.sessionId, tool_id: toolId, approved, always_allow: alwaysAllow });
			const tool = this.tools.get(toolId);
			if (tool) { this.tools.set(toolId, { ...tool, state: approved ? 'running' : 'failed' }); }
			this.approval = undefined;
			this.render();
		},
		openDiff: toolId => { void this.openDiff(toolId); },
		revealFile: resource => { void this.revealFile(resource); },
		restoreCheckpoint: checkpointHash => {
			const workspace = this.workspacePath;
			if (workspace) { this.send({ type: 'checkpoint_restore', session_id: this.sessionId, workspace, checkpoint_hash: checkpointHash }); }
		},
		retryEngine: () => {
			if (this.restartTimer !== undefined) { clearTimeout(this.restartTimer); this.restartTimer = undefined; }
			this.restartAttempts = 0;
			// Clear the fault the moment a manual retry starts: leaving it up claims the engine is still
			// broken while it is being restarted, and the row's own action would look like a no-op.
			this.engineFault = undefined;
			void this.ensureEngine();
		},
		selectWorkspace: uri => this.selectWorkspace(uri),
		openFolder: () => { void this.commandService.executeCommand('workbench.action.files.openFolder'); },
		openEngineSettings: () => { void this.commandService.executeCommand(PulseAICommandId.OpenSettings); },
		openManager: () => { this.openManagerWindow(); },
		copyToClipboard: text => {
			// Real clipboard (field: navigator.clipboard.writeText is
			// permission-blocked inside the webview). The workbench service
			// owns the privileged path; never let clipboard trouble throw.
			try { this.clipboardService.writeText(text); } catch { /* best effort */ }
		},
	};

	constructor(
		@IPulseAIEngineService private readonly engineService: IPulseAIEngineService,
		@IPulseAIWorkbenchService private readonly workbenchService: IPulseAIWorkbenchService,
		@IWorkspaceContextService private readonly workspaceContextService: IWorkspaceContextService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@ICommandService private readonly commandService: ICommandService,
		@IClipboardService private readonly clipboardService: IClipboardService,
		@IAuxiliaryWindowService private readonly auxiliaryWindowService: IAuxiliaryWindowService,
		@IPulseAISessionStore private readonly sessionStore: IPulseAISessionStore,
	) {
		super();
		this._register(this.engineService.onDidChangeState(state => {
			if (state === PulseAIEngineState.Ready) {
				this.restartAttempts = 0;
				this.engineFault = undefined;
			} else if (state === PulseAIEngineState.Crashed || state === PulseAIEngineState.Degraded) {
				// The only trace of a dying sidecar used to be a log line: the process exit is reported by
				// the engine service, `scheduleRestart` swallows exhaustion, and a turn in flight never
				// receives turn_done -- so the panel kept painting a live run that had no engine behind it.
				// A setup failure already has its own actionable row, so it is not overwritten here.
				if (!this.engineSetupError) {
					this.engineFault = state === PulseAIEngineState.Crashed
						? 'The Pulse engine process stopped while this session was open.'
						: 'The Pulse engine could not accept the request, so it never reached the model.';
					if (this.running) {
						this.running = false;
						this.turnOutcome = 'failed';
					}
				}
				this.scheduleRestart();
			}
			this.render();
		}));
		this._register(this.engineService.onDidReceiveFrame(frame => this.acceptFrame(frame)));
		this._register(this.workbenchService.onDidChangeCapabilities(() => {
			this.publishHostCapabilities();
			this.render();
		}));
		this._register(toDisposable(() => {
			if (this.renderFrame !== undefined) { cancelAnimationFrame(this.renderFrame); }
			if (this.restartTimer !== undefined) { clearTimeout(this.restartTimer); }
		}));
	}

	mount(root: unknown /* HTMLElement */, surface: PulseAISurface): IDisposable {
		const mount = mountPulseAIRenderer(root as HTMLElement, surface, this.host);
		this.mounts.add(mount);
		mount.update(this.model);
		if (this.configurationService.getValue<boolean>('pulseai.autoStart') !== false) {
			void this.ensureEngine();
		}
		return toDisposable(() => {
			this.mounts.delete(mount);
			mount.dispose();
		});
	}

	/**
	 * P0 workspace acquisition: the session folder comes ONLY from
	 * IWorkspaceContextService.getWorkspace().folders. Zero folders -> undefined
	 * (submission blocked). One folder -> its exact uri.fsPath. Multiple folders
	 * -> the explicitly retained selection (never folders[0] implicitly).
	 */
	private get sessionFolder(): IWorkspaceFolder | undefined {
		const folders = this.workspaceContextService.getWorkspace().folders;
		if (folders.length === 0) { return undefined; }
		if (folders.length === 1) { return folders[0]; }
		if (this.selectedWorkspaceUri) {
			const selected = folders.find(folder => folder.uri.toString() === this.selectedWorkspaceUri?.toString());
			if (selected) { return selected; }
			this.selectedWorkspaceUri = undefined;
		}
		return undefined;
	}

	private get workspacePath(): string | undefined {
		return this.sessionFolder?.uri.fsPath;
	}

	private get workspaceLabel(): string {
		return this.sessionFolder?.name ?? 'Local workspace';
	}

	private get workspaceFolderCount(): number {
		return this.workspaceContextService.getWorkspace().folders.length;
	}

	private get workspaceChoices(): readonly { label: string; uri: string }[] {
		return this.workspaceContextService.getWorkspace().folders.map(folder => ({
			label: folder.name,
			uri: folder.uri.toString(),
		}));
	}

	private selectWorkspace(uri: string): void {
		const folders = this.workspaceContextService.getWorkspace().folders;
		const matched = folders.find(folder => folder.uri.toString() === uri);
		if (!matched) { return; }
		const changed = this.selectedWorkspaceUri?.toString() !== uri;
		this.selectedWorkspaceUri = matched.uri;
		if (changed) {
			// Retain the selection for the SESSION; a folder switch resets the
			// session binding so frames always carry the same workspace.
			this.sessionId = undefined;
			this.running = false;
			this.cancelRequested = false;
			this.turnOutcome = 'idle';
			this.turnStartedAt = undefined;
			this.turnEndedAt = undefined;
			this.userMessage = undefined;
			this.assistantText = '';
			this.pendingPrompt = undefined;
			this.tools.clear();
			this.subAgents.clear();
			this.history = [];
			this.plan = [];
			this.verification = undefined;
		}
		this.render();
	}

	private get capabilitySummary(): PulseAIRenderModel['capabilitySummary'] {
		const values = this.workbenchService.getCapabilities();
		return {
			available: values.filter(value => value.availability === 'available').length,
			blocked: values.filter(value => value.availability === 'blocked').length,
			total: values.length,
		};
	}

	private get model(): PulseAIRenderModel {
		return {
			engineState: this.engineService.state,
			engineBuild: this.engineBuild,
			workspaceLabel: this.workspaceLabel,
			noWorkspace: this.workspaceFolderCount === 0,
			// P0: exact hint the renderer shows when no project folder is open.
			noWorkspaceHint: 'Open a folder to start a Pulse session.',
			workspaceSelectionRequired: this.workspaceFolderCount > 1 && !this.sessionFolder,
			workspaceChoices: this.workspaceChoices,
			engineSetupError: this.engineSetupError,
			sessionId: this.sessionId,
			mode: this.mode,
			running: this.running,
			cancelRequested: this.cancelRequested,
			turnStartedAt: this.turnStartedAt,
			// Wired: the engine now emits `context_status` frames (compaction start/done and
			// the overflow warning), projected by the bridge from the session-scoped
			// `context.status` event. Absent stays honest: no signal, no row.
			compacting: this.compacting,
			contextStatus: this.contextStatus,
			voiceHeard: this.voiceHeard,
			llmStatus: this.llmStatus,
			llmHeads: this.llmHeads,
			stalled: this.stalled,
			degraded: this.degraded,
			turnOutcome: this.turnOutcome,
			userMessage: this.userMessage,
			assistantText: this.assistantText,
			parts: [...this.parts],
			reasoning: this.reasoning,
			tools: [...this.tools.values()],
			subAgents: [...this.subAgents.values()],
			approval: this.approval,
			plan: this.plan,
			verification: this.verification,
			telemetry: this.telemetry,
			capabilitySummary: this.capabilitySummary,
			error: this.error,
			engineFault: this.engineFault === undefined ? undefined : {
				message: this.engineFault,
				// Same two conditions scheduleRestart checks -- reporting 'retrying' when the backoff had
				// already given up, or when autoStart is off, would be a promise the code cannot keep.
				retrying: this.restartAttempts < 3 && this.configurationService.getValue<boolean>('pulseai.autoStart') !== false,
				attempts: this.restartAttempts,
			},
			draft: this.draft,
			history: this.history,
			sessions: this.sessionRows(),
		};
	}

	/**
	 * The session list is a projection of the run, never a copy of it: this reads the store, and
	 * `noteSession()` is the only writer. Both the manager's own rows and the workbench's Agent
	 * Sessions list come through here, so the two surfaces cannot disagree about what exists.
	 */
	private sessionRows(): readonly PulseAISessionRow[] {
		const readState = new Map<string, boolean>();
		for (const facts of this.sessionStore.records()) {
			const isRead = this.sessionStore.isRead(facts.sessionId);
			if (isRead !== undefined) { readState.set(facts.sessionId, isRead); }
		}
		return pulseSessionRows(this.sessionStore.records(), this.sessionId, Date.now(), readState);
	}

	/**
	 * Called before the mount check: a session nobody has painted is still a session the user
	 * ran. `changes` is left out on purpose until one diff counter is shared with the tool row --
	 * a count of files nobody measured is worse in a list than an absent field.
	 */
	private noteSession(): void {
		if (!this.sessionId) { return; }
		const facts: PulseAISessionFacts = {
			sessionId: this.sessionId,
			label: pulseSessionLabel(this.userMessage, this.sessionId),
			workspaceLabel: this.workspaceLabel,
			statusName: pulseSessionStatusName({ running: this.running, turnOutcome: this.turnOutcome, hasApproval: this.approval !== undefined }),
			firstSeenAt: Date.now(),
			turnStartedAt: this.turnStartedAt,
			turnEndedAt: this.turnEndedAt,
		};
		this.sessionStore.note(facts);
	}

	private render(): void {
		this.noteSession();
		if (this.mounts.size === 0 || this.renderFrame !== undefined) { return; }
		this.renderFrame = requestAnimationFrame(() => {
			this.renderFrame = undefined;
			const model = this.model;
			for (const mount of this.mounts) { mount.update(model); }
		});
	}

	private scheduleRestart(): void {
		if (this.restartTimer !== undefined || this.mounts.size === 0 || this.restartAttempts >= 3) { return; }
		if (this.configurationService.getValue<boolean>('pulseai.autoStart') === false) { return; }
		const delay = 1_000 * (2 ** this.restartAttempts);
		this.restartTimer = setTimeout(() => {
			this.restartTimer = undefined;
			this.restartAttempts += 1;
			void this.ensureEngine();
		}, delay);
	}

	private async ensureEngine(): Promise<void> {
		if (this.engineService.state === PulseAIEngineState.Ready) { return; }
		if (this.startPromise) { return this.startPromise; }
		// P0: no project folder -> no session, no engine start, no frames. The
		// composer is disabled, so this is never an error state; an engine-root
		// problem is still reported as an actionable engine-setup error below.
		const workspace = this.workspacePath;
		if (!workspace) {
			this.engineSetupError = false;
			return;
		}
		this.error = undefined;
		const resumeSession = this.sessionId;
		this.startPromise = this.engineService.start(workspace).then(() => {
			this.engineSetupError = false;
			if (resumeSession && this.engineService.state === PulseAIEngineState.Ready) {
				this.publishHostCapabilities(resumeSession);
				this.send({ type: 'session_resume', session_id: resumeSession, workspace });
				this.send({ type: 'events_replay', session_id: resumeSession });
			}
		}).catch(error => {
			this.engineSetupError = error instanceof PulseAIEngineSetupError;
			this.error = error instanceof Error ? error.message : String(error);
		}).finally(() => {
			this.startPromise = undefined;
			this.render();
		});
		return this.startPromise;
	}

	private async openManagerWindow(): Promise<void> {
		// Opening the manager IS what "read" means, and it is the only honest clear for the
		// attention dot: the workbench's own list keeps its persisted tracking instead.
		if (this.sessionId) { this.sessionStore.markRead(this.sessionId, true); }
		const auxiliaryWindow = await this.auxiliaryWindowService.open({
			bounds: { x: 200, y: 100, width: 1100, height: 750 },
		});
		const container = auxiliaryWindow.container;
		auxiliaryWindow.window.document.title = 'Pulse Manager';

		const root = document.createElement('div');
		root.className = 'pulseai-render-root pulseai-manager-editor';
		root.dataset.surface = 'manager';
		root.style.width = '100%';
		root.style.height = '100%';
		container.appendChild(root);

		const mount = mountPulseAIRenderer(root, 'manager', this.host);
		mount.update(this.model);
		this._register(toDisposable(() => mount.dispose()));
	}

	private publishHostCapabilities(sessionId = this.sessionId): void {
		const workspace = this.workspacePath;
		if (!sessionId || !workspace || this.engineService.state !== PulseAIEngineState.Ready) { return; }
		const statuses = new Map(this.workbenchService.getCapabilities().map(item => [item.id, item]));
		const readIds = new Set([
			'workspace.trust', 'editor.activeSelection', 'editor.dirtyText',
			'diagnostics.markers', 'language.symbols', 'language.definitions',
			'language.references', 'search.workspace', 'scm.state',
		]);
		const capabilities = PULSE_AI_WORKBENCH_CAPABILITIES
			.filter(item => item.risk === 'read' && readIds.has(item.id))
			.map(item => ({ ...item, ...statuses.get(item.id) }));
		this.send({ type: 'host_capabilities_update', session_id: sessionId, workspace, capabilities });
	}

	private async invokeHostCapability(frame: Extract<PulseServerEvent, { type: 'host_tool_request' }>): Promise<void> {
		const started = Date.now();
		const workspace = this.workspacePath;
		if (!this.sessionId || frame.session_id !== this.sessionId || !workspace || frame.workspace !== workspace) {
			this.send({
				type: 'host_tool_result', session_id: frame.session_id, workspace: frame.workspace,
				request_id: frame.request_id, status: 'error',
				error: 'host tool request does not match the active Pulse workspace/session',
				duration_ms: Date.now() - started,
			});
			return;
		}
		const args = valueRecord(frame.arguments) ?? {};
		try {
			const status = this.workbenchService.getCapabilities().find(item => item.id === frame.capability_id);
			if (status?.availability !== 'available') {
				throw new Error(`host capability is ${status?.availability ?? 'unavailable'}: ${frame.capability_id}`);
			}
			let result: unknown;
			switch (frame.capability_id) {
				case 'workspace.trust':
					result = { trusted: this.workbenchService.isWorkspaceTrusted() };
					break;
				case 'editor.activeSelection':
					result = await this.workbenchService.getActiveEditorContext(args['includeVisibleText'] === true);
					break;
				case 'editor.dirtyText':
					result = await this.workbenchService.getActiveEditorContext(true);
					break;
				case 'diagnostics.markers': {
					const resources = Array.isArray(args['resources'])
						? args['resources'].filter((item): item is string => typeof item === 'string').slice(0, 50)
						: undefined;
					result = this.workbenchService.getDiagnostics(resources);
					break;
				}
				case 'language.symbols':
					if (typeof args['resource'] !== 'string') { throw new Error('language.symbols requires resource'); }
					result = await this.workbenchService.getDocumentSymbols(args['resource']);
					break;
				case 'language.definitions':
				case 'language.references': {
					if (typeof args['resource'] !== 'string') { throw new Error(`${frame.capability_id} requires resource`); }
					const line = Number(args['line']);
					const column = Number(args['column']);
					if (!Number.isInteger(line) || line < 1 || !Number.isInteger(column) || column < 1) {
						throw new Error(`${frame.capability_id} requires positive integer line and column`);
					}
					result = frame.capability_id === 'language.definitions'
						? await this.workbenchService.getDefinitions(args['resource'], line, column)
						: await this.workbenchService.getReferences(args['resource'], line, column);
					break;
				}
				case 'search.workspace': {
					if (typeof args['query'] !== 'string' || !args['query'].trim()) { throw new Error('search.workspace requires query'); }
					const requested = Number(args['maxResults'] ?? 100);
					const maxResults = Number.isFinite(requested) ? Math.max(1, Math.min(Math.trunc(requested), 500)) : 100;
					result = await this.workbenchService.searchWorkspace(args['query'], maxResults);
					break;
				}
				case 'scm.state':
					result = this.workbenchService.getSCMState();
					break;
				default:
					throw new Error(`host capability is not allowed: ${frame.capability_id}`);
			}
			this.send({
				type: 'host_tool_result', session_id: frame.session_id, workspace,
				request_id: frame.request_id, status: 'ok', result,
				duration_ms: Date.now() - started,
			});
		} catch (error) {
			this.send({
				type: 'host_tool_result', session_id: frame.session_id, workspace,
				request_id: frame.request_id, status: 'error',
				error: error instanceof Error ? error.message : String(error),
				duration_ms: Date.now() - started,
			});
		}
	}

	private async submitPrompt(text: string): Promise<void> {
		await this.ensureEngine();
		if (this.engineService.state !== PulseAIEngineState.Ready) { return; }
		this.draft = '';
		this.error = undefined;
		if (!this.sessionId) {
			this.pendingPrompt = text;
			this.send({ type: 'session_create', workspace: this.workspacePath });
			this.render();
			return;
		}
		this.startTurn(text);
	}

	private startTurn(text: string): void {
		// Preserve previous turn in history before clearing (user → agent → user → agent)
		if (this.userMessage || this.assistantText || this.tools.size > 0) {
			this.history = [...this.history, {
				userMessage: this.userMessage,
				assistantText: this.assistantText,
				parts: [...this.parts],
				reasoning: this.reasoning,
				tools: [...this.tools.values()],
				subAgents: [...this.subAgents.values()],
				turnOutcome: this.turnOutcome,
				plan: this.plan,
			}].slice(-20); // keep last 20 turns
		}
		this.userMessage = text;
		this.assistantText = '';
		this.parts = [];
		this.reasoning = undefined;
		this.tools.clear();
		this.subAgents.clear();
		this.approval = undefined;
		this.plan = [];
		this.verification = undefined;
		this.running = true;
		this.cancelRequested = false;
		this.turnOutcome = 'running';
		this.turnStartedAt = Date.now();
		this.send({ type: 'prompt', session_id: this.sessionId, workspace: this.workspacePath, text, mode: this.mode });
		this.render();
	}

	/**
	 * Timeline writers (hermes parts ingestion): text extends the LAST text
	 * segment — a token that follows tool calls opens a NEW segment instead of
	 * teleporting into the pre-tool text, which is what keeps interleave order
	 * truthful. Tools pin their position once; updates go through the tools
	 * map, never the timeline.
	 */
	private appendTextPart(chunk: string): void {
		if (!chunk) { return; }
		const last = this.parts[this.parts.length - 1];
		if (last?.kind === 'text') {
			this.parts[this.parts.length - 1] = { kind: 'text', text: last.text + chunk };
		} else {
			this.parts.push({ kind: 'text', text: chunk });
		}
	}

	private pushToolPart(toolId: string): void {
		if (!toolId || this.parts.some(p => p.kind === 'tool' && p.toolId === toolId)) { return; }
		this.parts.push({ kind: 'tool', toolId });
	}

	private send(frame: PulseClientMethod): void {
		try {
			this.engineService.send(frame);
		} catch (error) {
			this.error = error instanceof Error ? error.message : String(error);
			this.render();
		}
	}

	/**
	 * Hermes session-states.ts watchdog, 5-minute window (their tuning note:
	 * under ~4min paints healthy typechecks/test runs as suspect; 8min arrives
	 * after the user gave up). One timer per turn; every frame re-arms it via
	 * acceptFrame. Firing only flips the presentation hint.
	 */
	private armStallWatchdog(): void {
		this.clearStallWatchdog();
		this.stallWatchdog = window.setTimeout(() => {
			this.stallWatchdog = undefined;
			if (this.running) {
				this.stalled = true;
				this.render();
			}
		}, 5 * 60 * 1000);
		// HARD rendering kill (owner, 2026-09-04: "after the task is finished,
		// rendering should stop" — the panel rendered Working for many minutes
		// after the engine had gone quiet). Seven minutes with ZERO frames
		// cannot be a live turn: every provider call is bracketed by
		// llm.request/llm.response frames, so real silence means the engine
		// is gone. End the turn LOCALLY with an honest receipt. If the
		// engine wakes after all, its next terminal frame re-runs this
		// handler and the truth replaces our note.
		this.clearHardWatchdog();
		this.hardWatchdog = window.setTimeout(() => {
			this.hardWatchdog = undefined;
			if (!this.running) { return; }
			this.running = false;
			this.cancelRequested = false;
			this.turnStartedAt = undefined;
			this.turnEndedAt = Date.now();
			this.turnOutcome = 'failed';
			this.stalled = undefined;
			this.llmStatus = undefined;
			this.error = 'The engine stopped responding — the turn was ended locally. The reply above is everything it produced; send another message to continue.';
			this.clearStallWatchdog();
			this.render();
		}, 7 * 60 * 1000);
	}

	private clearHardWatchdog(): void {
		if (this.hardWatchdog !== undefined) { clearTimeout(this.hardWatchdog); this.hardWatchdog = undefined; }
	}

	private clearStallWatchdog(): void {
		if (this.stallWatchdog !== undefined) {
			window.clearTimeout(this.stallWatchdog);
			this.stallWatchdog = undefined;
		}
		this.clearHardWatchdog();
		this.stalled = undefined;
	}

	private acceptFrame(frame: PulseServerEvent): void {
		if ('event_id' in frame && frame.event_id && !this.rememberEvent(frame.event_id)) { return; }
		// Hermes watchdog (apps/desktop/src/store/session-states.ts): ANY state
		// publish re-arms the window; a busy turn that publishes nothing for the
		// whole window paints `stalled`. Presentation hint only — it never
		// mutates the engine's real turn state, and the next frame clears it.
		if (this.running) {
			this.stalled = undefined;
			this.armStallWatchdog();
		}
		if (frame.type === 'events_replay') {
			for (const event of frame.events) {
				const candidate = valueRecord(event);
				if (typeof candidate?.type === 'string') { this.acceptFrame(event as PulseServerEvent); }
			}
			return;
		}
		if (frame.type === 'host_tool_request') {
			void this.invokeHostCapability(frame);
			return;
		}
		if (frame.type === 'session_info') {
			const previousSessionId = this.sessionId;
			this.sessionId = frame.session_id;
			if (typeof frame.build === 'string' && frame.build) { this.engineBuild = frame.build; }
			if (previousSessionId !== frame.session_id) { this.publishHostCapabilities(frame.session_id); }
			if (typeof frame.cancel_requested === 'boolean') { this.cancelRequested = frame.cancel_requested; }
			for (const event of frame.events ?? []) {
				const candidate = valueRecord(event);
				if (typeof candidate?.type === 'string') { this.acceptFrame(event as PulseServerEvent); }
			}
			if (this.pendingPrompt) {
				const prompt = this.pendingPrompt;
				this.pendingPrompt = undefined;
				this.startTurn(prompt);
				return;
			}
		} else if (frame.type === 'turn_started') {
			this.sessionId = frame.session_id;
			this.running = true;
			this.cancelRequested = false;
			this.turnOutcome = 'running';
			this.error = undefined;
			this.compacting = undefined;
			this.contextStatus = undefined;
			this.llmStatus = undefined;
			this.llmHeads = undefined;
			this.degraded = undefined;
			this.voiceHeard = undefined;
			this.reasoningFrameCount = 0;
			this.clearStallWatchdog();
			this.armStallWatchdog();
		} else if (frame.type === 'token') {
			this.assistantText += frame.text;
			this.appendTextPart(frame.text);
			// The answer started; whatever was in the Thinking block is done.
			this.reasoning = undefined;
		} else if (frame.type === 'reasoning') {
			this.reasoning = frame.text;
			this.reasoningFrameCount += 1;
		} else if (frame.type === 'plan_updated') {
			this.plan = frame.steps.map(planText);
		} else if (frame.type === 'tool_call_start') {
			this.tools.set(frame.tool_id, { id: frame.tool_id, name: frame.name, arguments: frame.arguments, state: 'running' });
			this.pushToolPart(frame.tool_id);
		} else if (frame.type === 'tool_call_end') {
			const existing = this.tools.get(frame.tool_id);
			const result = valueRecord(frame.result);
			this.tools.set(frame.tool_id, {
				id: frame.tool_id,
				name: existing?.name ?? 'unknown',
				arguments: existing?.arguments,
				result: frame.result,
				state: toolState(frame.status),
				duration: typeof result?.duration === 'string' ? result.duration : typeof result?.duration_ms === 'number' ? `${result.duration_ms}ms` : undefined,
			});
			if (this.approval?.toolId === frame.tool_id) { this.approval = undefined; }
		} else if (frame.type === 'safety_request') {
			const existing = this.tools.get(frame.tool_id);
			this.tools.set(frame.tool_id, { id: frame.tool_id, name: frame.name, arguments: existing?.arguments ?? frame.arguments ?? frame.diff, result: existing?.result, state: 'approval' });
			// An approval can arrive without a prior start frame; the card must
			// still have a place in the timeline.
			this.pushToolPart(frame.tool_id);
			this.approval = { toolId: frame.tool_id, name: frame.name, diff: frame.diff };
		} else if (frame.type === 'subagent_updated') {
			const subagent_id = frame.subagent_id;
			const existing = this.subAgents.get(subagent_id) ?? { id: subagent_id, state: 'pending' as const };
			const state = (frame as any).state ?? existing.state;
			const duration = (frame as any).duration;
			const result = (frame as any).result;
			this.subAgents.set(subagent_id, {
				...existing,
				id: subagent_id,
				state: state as PulseAISubAgentView['state'],
				goal: (frame as any).goal ?? existing.goal,
				mode: (frame as any).mode ?? existing.mode,
				progress: (frame as any).progress ?? existing.progress,
				result: result ?? existing.result,
				duration: duration ?? existing.duration,
				parentSessionId: (frame as any).parent_session_id ?? existing.parentSessionId,
			});
		} else if (frame.type === 'verification_updated') {
			this.verification = frame.status;
		} else if (frame.type === 'telemetry') {
			this.telemetry = { ...this.telemetry, input: frame.input, output: frame.output, cache: frame.cache, cost: frame.cost };
		} else if (frame.type === 'turn_done') {
			this.running = false;
			this.cancelRequested = false;
			this.turnStartedAt = undefined;
			this.turnEndedAt = Date.now();
			// Transport verdict vs task verdict: `completed:false` with
			// `cancelled:false` is an ENDED-INCOMPLETE turn (finalize said the
			// task failed) — the run itself finished and its trailing receipt
			// already says so in-band. Only a real cancel paints "Run
			// cancelled"; calling every incomplete run cancelled is progress
			// theatre in reverse (a lie about the Stop button).
			this.turnOutcome = frame.cancelled ? 'cancelled' : 'completed';
			if (frame.message && !this.assistantText) {
				this.assistantText = frame.message;
				this.appendTextPart(frame.message);
			}
			this.compacting = undefined;
			this.contextStatus = undefined;
			this.llmStatus = undefined;
			this.llmHeads = undefined;
			this.degraded = undefined;
			this.clearStallWatchdog();
		} else if (frame.type === 'turn_failed') {
			this.running = false;
			this.cancelRequested = false;
			this.turnStartedAt = undefined;
			this.turnEndedAt = Date.now();
			this.turnOutcome = 'failed';
			this.error = frame.error;
			this.compacting = undefined;
			this.contextStatus = undefined;
			this.llmStatus = undefined;
			this.llmHeads = undefined;
			this.degraded = undefined;
			this.clearStallWatchdog();
		} else if (frame.type === 'voice_text') {
			this.voiceHeard = { ok: frame.ok, text: frame.text ?? '', error: frame.error };
		} else if (frame.type === 'llm.request') {
			this.llmStatus = { model: frame.model ?? '', attempt: frame.attempt ?? 1 };
			this.llmHeads = frame.messages;
			// The 📡 row now carries the wait (which model, which attempt). The
			// Thinking block must not parrot it: a status line dressed as
			// reasoning is exactly the fake-progress the user called out. The
			// bridge's single liveness frame is transport copy, not thought --
			// clear it once a real provider attempt is named.
			if (this.reasoningFrameCount <= 1) { this.reasoning = undefined; }
		} else if (frame.type === 'llm.response') {
			this.llmStatus = undefined;
			this.llmHeads = undefined;
			if (this.reasoning && this.reasoning.indexOf('Asking ') === 0) { this.reasoning = undefined; }
		} else if (frame.type === 'context_status') {
			const severity = frame.severity === 'warning' ? 'warning' : 'info';
			if (frame.phase === 'compacted') {
				this.compacting = undefined;
			} else if (frame.phase === 'compress' || frame.phase === 'pre_api') {
				this.compacting = true;
			}
			this.contextStatus = {
				message: frame.message,
				severity,
				phase: frame.phase,
				usagePercent: typeof frame.usage_percent === 'number' ? frame.usage_percent : undefined,
			};
		} else if (frame.type === 'runtime_degraded') {
			this.degraded = frame.reason;
		} else if (frame.type === 'error') {
			this.error = frame.message;
		}
		this.render();
	}

	private rememberEvent(eventId: string): boolean {
		if (this.seenEventIds.has(eventId)) { return false; }
		this.seenEventIds.add(eventId);
		this.eventIdOrder.push(eventId);
		if (this.eventIdOrder.length > 20_000) {
			const removed = this.eventIdOrder.splice(0, 2_000);
			for (const id of removed) { this.seenEventIds.delete(id); }
		}
		return true;
	}

	private async openDiff(toolId: string): Promise<void> {
		try {
			const tool = this.tools.get(toolId);
			const approval = this.approval?.toolId === toolId ? this.approval.diff : undefined;
			const sources = [approval, tool?.result, tool?.arguments];
			let original: string | undefined;
			let modified: string | undefined;
			let originalText: string | undefined;
			let modifiedText: string | undefined;
			let resource: string | undefined;
			for (const source of sources) {
				const value = valueRecord(source);
				original ??= stringField(source, ['original_uri', 'original', 'before_uri', 'base_uri']);
				modified ??= stringField(source, ['modified_uri', 'modified', 'after_uri']);
				resource ??= stringField(source, ['resource', 'file_path', 'path']);
				if (originalText === undefined && value && 'old_text' in value && (typeof value.old_text === 'string' || value.old_text === null)) {
					originalText = typeof value.old_text === 'string' ? value.old_text : '';
				}
				if (modifiedText === undefined && typeof value?.new_text === 'string') { modifiedText = value.new_text; }
			}
			const label = `Pulse: ${tool?.name ?? 'proposed change'}`;
			if (originalText !== undefined && modifiedText !== undefined) {
				await this.workbenchService.openInlineDiff({
					toolId, label, original: originalText, modified: modifiedText,
					...(resource ? { resource } : {}),
				});
				return;
			}
			modified ??= resource;
			if (!original || !modified) {
				throw new Error('This tool receipt does not include inline text or native original/modified diff resources.');
			}
			await this.workbenchService.openNativeDiff(
				this.resourceUri(original).toString(),
				this.resourceUri(modified).toString(),
				label,
			);
		} catch (error) {
			this.error = error instanceof Error ? error.message : String(error);
			this.render();
		}
	}

	private async revealFile(resource: string): Promise<void> {
		try {
			await this.workbenchService.openResource(this.resourceUri(resource).toString());
		} catch (error) {
			this.error = error instanceof Error ? error.message : String(error);
			this.render();
		}
	}

	private resourceUri(resource: string): URI {
		const folder = this.workspaceContextService.getWorkspace().folders[0];
		// Windows drive letters ("D:\repo", "D:/repo") and UNC paths are
		// filesystem paths, NOT URI schemes — so they are tested FIRST. A
		// bare `D:\repo` matches the scheme sniff below (`D:` looks like a
		// scheme to it), and URI.parse mangles the backslashes into
		// `D:%5Crepo` — which the text-model resolver then refuses. That was
		// the owner's "died after a tool call" (2026-09-04 log, Reveal
		// location). Hermes display-path.ts: copy/reveal/IPC always carry
		// the real absolute path; display formatting is paint only.
		if (/^(?:[a-z]:[\\/]|[\\/])/i.test(resource)) { return URI.file(resource); }
		if (/^[a-z][a-z0-9+.-]*:/i.test(resource)) { return URI.parse(resource); }
		return folder ? URI.joinPath(folder.uri, resource) : URI.file(resource);
	}
}
