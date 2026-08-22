/*---------------------------------------------------------------------------------------------
 * One shared event model and host adapter for the compact Agent view and Pulse Manager.
 *--------------------------------------------------------------------------------------------*/

import { Disposable, IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { URI } from '../../../../base/common/uri.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IWorkspaceContextService, IWorkspaceFolder } from '../../../../platform/workspace/common/workspace.js';
import { PulseAICommandId } from '../common/pulseAI.js';
import { IPulseAIEngineService, PulseAIEngineSetupError, PulseAIEngineState } from '../common/pulseAIEngineService.js';
import type { PulseClientMethod, PulseServerEvent } from '../common/pulseAIProtocol.js';
import { IPulseAIRendererService, PulseAISurface } from '../common/pulseAIRendererService.js';
import { IPulseAIWorkbenchService } from '../common/pulseAIWorkbenchService.js';
import {
	mountPulseAIRenderer,
	PulseAIRenderHost,
	PulseAIRenderModel,
	PulseAIRenderMount,
	PulseAIToolState,
	PulseAIToolView,
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
	private pendingPrompt: string | undefined;
	private draft = '';
	private sessionId: string | undefined;
	private running = false;
	private cancelRequested = false;
	private turnOutcome: PulseAIRenderModel['turnOutcome'] = 'idle';
	private userMessage: string | undefined;
	private assistantText = '';
	private reasoning: string | undefined;
	private approval: PulseAIRenderModel['approval'];
	private plan: readonly string[] = [];
	private verification: string | undefined;
	private telemetry: PulseAIRenderModel['telemetry'] = {};
	private error: string | undefined;
	private engineSetupError = false;

	/**
	 * Explicit multi-root selection (P0): never silently pick folders[0].
	 * Set through selectWorkspace() and retained for the session, surviving
	 * re-renders, until the folder leaves the workspace or is replaced.
	 */
	private selectedWorkspaceUri: URI | undefined;

	private readonly host: PulseAIRenderHost = {
		setDraft: value => { this.draft = value; },
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
			void this.ensureEngine();
		},
		selectWorkspace: uri => this.selectWorkspace(uri),
		openFolder: () => { void this.commandService.executeCommand('workbench.action.files.openFolder'); },
		openEngineSettings: () => { void this.commandService.executeCommand(PulseAICommandId.OpenSettings); },
	};

	constructor(
		@IPulseAIEngineService private readonly engineService: IPulseAIEngineService,
		@IPulseAIWorkbenchService private readonly workbenchService: IPulseAIWorkbenchService,
		@IWorkspaceContextService private readonly workspaceContextService: IWorkspaceContextService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@ICommandService private readonly commandService: ICommandService,
	) {
		super();
		this._register(this.engineService.onDidChangeState(state => {
			if (state === PulseAIEngineState.Ready) {
				this.restartAttempts = 0;
			} else if (state === PulseAIEngineState.Crashed) {
				this.scheduleRestart();
			}
			this.render();
		}));
		this._register(this.engineService.onDidReceiveFrame(frame => this.acceptFrame(frame)));
		this._register(this.workbenchService.onDidChangeCapabilities(() => this.render()));
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
			this.userMessage = undefined;
			this.assistantText = '';
			this.pendingPrompt = undefined;
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
			workspaceLabel: this.workspaceLabel,
			noWorkspace: this.workspaceFolderCount === 0,
			// P0: exact hint the renderer shows when no project folder is open.
			noWorkspaceHint: 'Open a folder to start a Pulse session.',
			workspaceSelectionRequired: this.workspaceFolderCount > 1 && !this.sessionFolder,
			workspaceChoices: this.workspaceChoices,
			engineSetupError: this.engineSetupError,
			sessionId: this.sessionId,
			running: this.running,
			cancelRequested: this.cancelRequested,
			turnOutcome: this.turnOutcome,
			userMessage: this.userMessage,
			assistantText: this.assistantText,
			reasoning: this.reasoning,
			tools: [...this.tools.values()],
			approval: this.approval,
			plan: this.plan,
			verification: this.verification,
			telemetry: this.telemetry,
			capabilitySummary: this.capabilitySummary,
			error: this.error,
			draft: this.draft,
		};
	}

	private render(): void {
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
		this.userMessage = text;
		this.assistantText = '';
		this.reasoning = undefined;
		this.tools.clear();
		this.approval = undefined;
		this.plan = [];
		this.verification = undefined;
		this.running = true;
		this.cancelRequested = false;
		this.turnOutcome = 'running';
		this.send({ type: 'prompt', session_id: this.sessionId, workspace: this.workspacePath, text });
		this.render();
	}

	private send(frame: PulseClientMethod): void {
		try {
			this.engineService.send(frame);
		} catch (error) {
			this.error = error instanceof Error ? error.message : String(error);
			this.render();
		}
	}

	private acceptFrame(frame: PulseServerEvent): void {
		if ('event_id' in frame && frame.event_id && !this.rememberEvent(frame.event_id)) { return; }
		if (frame.type === 'events_replay') {
			for (const event of frame.events) {
				const candidate = valueRecord(event);
				if (typeof candidate?.type === 'string') { this.acceptFrame(event as PulseServerEvent); }
			}
			return;
		}
		if (frame.type === 'session_info') {
			this.sessionId = frame.session_id;
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
		} else if (frame.type === 'token') {
			this.assistantText += frame.text;
		} else if (frame.type === 'reasoning') {
			this.reasoning = frame.text;
		} else if (frame.type === 'plan_updated') {
			this.plan = frame.steps.map(planText);
		} else if (frame.type === 'tool_call_start') {
			this.tools.set(frame.tool_id, { id: frame.tool_id, name: frame.name, arguments: frame.arguments, state: 'running' });
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
			this.approval = { toolId: frame.tool_id, name: frame.name, diff: frame.diff };
		} else if (frame.type === 'verification_updated') {
			this.verification = frame.status;
		} else if (frame.type === 'telemetry') {
			this.telemetry = { ...this.telemetry, input: frame.input, output: frame.output, cache: frame.cache, cost: frame.cost };
		} else if (frame.type === 'turn_done') {
			this.running = false;
			this.cancelRequested = false;
			this.turnOutcome = frame.completed ? 'completed' : 'cancelled';
			if (frame.message && !this.assistantText) { this.assistantText = frame.message; }
		} else if (frame.type === 'turn_failed') {
			this.running = false;
			this.cancelRequested = false;
			this.turnOutcome = 'failed';
			this.error = frame.error;
		} else if (frame.type === 'runtime_degraded') {
			this.error = frame.reason;
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
		if (/^[a-z][a-z0-9+.-]*:/i.test(resource)) { return URI.parse(resource); }
		if (/^(?:[a-z]:[\\/]|[\\/])/i.test(resource)) { return URI.file(resource); }
		return folder ? URI.joinPath(folder.uri, resource) : URI.file(resource);
	}
}
