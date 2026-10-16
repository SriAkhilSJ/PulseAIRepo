/*---------------------------------------------------------------------------------------------
 * One shared event model and host adapter for the compact Agent view and Crusor Manager.
 *--------------------------------------------------------------------------------------------*/

import { Disposable, IDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { FileAccess } from '../../../../base/common/network.js';
import { URI } from '../../../../base/common/uri.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { getIconClasses } from '../../../../editor/common/services/getIconClasses.js';
import { IModelService } from '../../../../editor/common/services/model.js';
import { ILanguageService } from '../../../../editor/common/languages/language.js';
import { FileKind } from '../../../../platform/files/common/files.js';
import { IThemeService } from '../../../../platform/theme/common/themeService.js';
import { IOpenerService } from '../../../../platform/opener/common/opener.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IWorkspaceContextService, IWorkspaceFolder } from '../../../../platform/workspace/common/workspace.js';
import { IAuxiliaryWindowService } from '../../../services/auxiliaryWindow/browser/auxiliaryWindowService.js';
import { CrusorAICommandId } from '../common/crusorAI.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { ICrusorAIEngineService, CrusorAIEngineSetupError, CrusorAIEngineState } from '../common/crusorAIEngineService.js';
import type { CrusorClarifyQuestion, CrusorClientMethod, CrusorExecutionMode, CrusorServerEvent, CrusorSessionMessage, CrusorTodoItem } from '../common/crusorAIProtocol.js';
import { CRUSOR_AI_WORKBENCH_CAPABILITIES } from '../common/crusorAIWorkbenchCapabilities.js';
import type { CrusorReasoningEffortValue } from '../common/crusorAIReasoningEffort.js';
import { separateGluedReasoningBlocks } from './crusorAIReasoningBlocks.js';
import { ICrusorAIRendererService, CrusorAISurface } from '../common/crusorAIRendererService.js';
import { ICrusorAISessionStore } from '../common/crusorAISessionStore.js';
import { crusorFactsFromEngineRow, crusorSessionLabel, crusorSessionLabelIsFallback, crusorSessionRows, crusorSessionStatusName, type CrusorAIEngineSessionRow, type CrusorAISessionFacts, type CrusorAISessionRow, type CrusorAISessionStatusName } from '../common/crusorAISessionProjection.js';
import { ICrusorAIWorkbenchService } from '../common/crusorAIWorkbenchService.js';
import {
	mountCrusorAIRenderer,
	CrusorAIRenderHost,
	CrusorAIRenderModel,
	CrusorAIRenderMount,
	CrusorAIPlanStepView,
	CrusorAIToolState,
	CrusorAIToolView,
	CrusorAITurnPart,
	CrusorAISubAgentView,
	CrusorAISyntaxColors,
} from './crusorAIRenderer.js';

function valueRecord(value: unknown): Readonly<Record<string, unknown>> | undefined {
	return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Readonly<Record<string, unknown>> : undefined;
}

function toolState(status: string): CrusorAIToolState {
	const value = status.toLowerCase();
	if (value.includes('fail') || value.includes('error') || value.includes('denied') || value.includes('cancel')) { return 'failed'; }
	if (value.includes('pass') || value.includes('success') || value.includes('complete') || value === 'ok') { return 'passed'; }
	if (value.includes('approval') || value.includes('permission')) { return 'approval'; }
	if (value.includes('run') || value.includes('start') || value.includes('progress')) { return 'running'; }
	return 'queued';
}

/**
 * Engine sub-agent states, normalized to the desktop vocabulary at
 * intake: the lifecycle says `succeeded`, the views speak `completed`
 * — unnormalized, a settled child matched NEITHER running nor settled
 * anywhere, so its card could not say it had ended (field 2026-10-16:
 * "we can't find out it ended or started").
 */
function subAgentState(raw: unknown, fallback: CrusorAISubAgentView['state'] = 'pending'): CrusorAISubAgentView['state'] {
	const value = typeof raw === 'string' ? raw.toLowerCase() : '';
	switch (value) {
		case 'pending': case 'queued': return 'pending';
		case 'running': case 'in_progress': case 'cancel_requested': return 'running';
		case 'completed': case 'succeeded': case 'success': case 'complete': case 'done': return 'completed';
		case 'failed': case 'error': case 'errored': return 'failed';
		case 'cancelled': case 'canceled': return 'cancelled';
		default: return fallback;
	}
}

function planText(step: unknown): string {
	if (typeof step === 'string') { return step; }
	const record = valueRecord(step);
	for (const key of ['title', 'text', 'description', 'goal']) {
		if (typeof record?.[key] === 'string') { return record[key] as string; }
	}
	return 'Plan step';
}


const PLAN_STATUSES: readonly string[] = ['pending', 'in_progress', 'completed', 'failed'];

/**
 * Content equality for hydrated history. Both lists come from the same
 * builder, so key order is stable and a JSON compare is exact; any doubt
 * fails open to "changed" (a repaint, never a stale transcript).
 */
function sameHistoryTurns(a: readonly unknown[], b: readonly unknown[]): boolean {
	if (a === b) { return true; }
	if (a.length !== b.length) { return false; }
	try {
		return JSON.stringify(a) === JSON.stringify(b);
	} catch {
		return false;
	}
}

function planStepView(step: unknown): CrusorAIPlanStepView {
	const raw = (typeof step === 'object' && step !== null)
		? (step as Record<string, unknown>).status
		: undefined;
	const status = typeof raw === 'string' ? raw : '';
	return {
		text: planText(step),
		status: (PLAN_STATUSES.includes(status)
			? status
			: 'pending') as CrusorAIPlanStepView['status'],
	};
}

function stringField(source: unknown, keys: readonly string[]): string | undefined {
	const value = valueRecord(source);
	for (const key of keys) {
		if (typeof value?.[key] === 'string' && value[key]) { return value[key] as string; }
	}
	return undefined;
}


/** The full live surface of one session, stashed while the user watches a child mid-run. */
interface CrusorSurfaceSnapshot {
	readonly sessionId: string;
	readonly running: boolean;
	readonly cancelRequested: boolean;
	readonly interrupt: { readonly landed: number; readonly dropped: number } | undefined;
	readonly turnOutcome: CrusorAIRenderModel['turnOutcome'];
	readonly turnStartedAt: number | undefined;
	readonly turnEndedAt: number | undefined;
	readonly userMessage: string | undefined;
	readonly assistantText: string;
	readonly parts: CrusorAITurnPart[];
	readonly reasoningParts: { text: string; completedAt?: number }[];
	readonly reasoningPending: boolean;
	readonly tools: Map<string, CrusorAIToolView>;
	readonly subAgents: Map<string, CrusorAISubAgentView>;
	readonly parentMap: Map<string, string>;
	readonly childParentId: string | undefined;
	readonly history: CrusorAIRenderModel['history'];
	readonly plan: readonly CrusorAIPlanStepView[];
	readonly verification: string | undefined;
	readonly telemetry: CrusorAIRenderModel['telemetry'];
	readonly approval: CrusorAIRenderModel['approval'];
	readonly clarify: {
		readonly requestId: string;
		readonly title: string;
		readonly toolId?: string;
		readonly questions: readonly CrusorClarifyQuestion[];
		/** The session that ASKED (OpenCode: requests live on the asking
		 *  session; the tree rule decides which view surfaces them). */
		readonly sessionId: string;
	} | undefined;
	readonly todos: readonly CrusorTodoItem[];
	readonly todoRevision: number;
	readonly compacting: boolean | undefined;
	readonly contextStatus: CrusorAIRenderModel['contextStatus'];
	readonly voiceHeard: CrusorAIRenderModel['voiceHeard'];
	readonly llmStatus: { readonly model: string; readonly attempt: number } | undefined;
	readonly llmHeads: readonly { readonly role: string; readonly head: string }[] | undefined;
	readonly degraded: string | undefined;
	readonly error: string | undefined;
	readonly hadProviderAttempt: boolean;
	readonly pendingPrompt: string | undefined;
}

export class CrusorAIRendererService extends Disposable implements ICrusorAIRendererService {
	declare readonly _serviceBrand: undefined;
	private readonly mounts = new Set<CrusorAIRenderMount>();
	private readonly tools = new Map<string, CrusorAIToolView>();
	private readonly seenEventIds = new Set<string>();
	private readonly eventIdOrder: string[] = [];
	private startPromise: Promise<void> | undefined;
	private renderFrame: number | undefined;
	private restartTimer: ReturnType<typeof setTimeout> | undefined;
	private restartAttempts = 0;
	private engineFault: string | undefined;
	private pendingPrompt: string | undefined;
	private lastSubmittedPrompt: string | undefined;
	/** Session id whose transcript hydration (session_messages) is still in flight. A page for a session the user already left is dropped against this. */
	private pendingHydration: string | undefined;
	/**
	 * Parent surface stashed while the user watches a child session mid-run
	 * (OpenCode: the child is just a session route; the parent keeps
	 * running). Restored verbatim on return so the parent's stream resumes
	 * mid-sentence; invalidated when the parent's turn settles, because its
	 * checkpoint then holds the truth and hydration replaces the snapshot.
	 */
	private liveStash: { readonly sessionId: string; readonly snapshot: CrusorSurfaceSnapshot } | undefined;
	/** After a stash restore, heal the away-window gap once from the settled checkpoint. */
	private healAfterRestore = false;
	private healRequested = false;
	/** Checkpoint-refresh timer while a live child session is open. */
	private childSnapshotTimer: ReturnType<typeof setInterval> | undefined;
	/** True once the viewed child's tail history turn has been adopted into
	 * the live lane: the rest of the turn then streams frame-by-frame like
	 * the parent's (the bridge forwards proven in-tree content), checkpoint
	 * snapshots stand down, and the poll stops. Reset on navigation/settle. */
	private childLiveAdopted = false;
	/** A refresh (unlike the opening hydration) must never blank the paint with an empty in-flight read. */
	private childRefreshInFlight = false;
	private draft = '';
	private mode: CrusorExecutionMode = 'agent';
	/** Think level ('none' = thinking disabled by default). */
	private reasoningEffort: CrusorReasoningEffortValue | '' = 'none';
	private sessionId: string | undefined;
	private running = false;
	private cancelRequested = false;
	/** What the Stop actually did, counted when an interrupted turn ends:
	 *  `landed` = tool calls whose result already exists, `dropped` = calls
	 *  the brake caught before dispatch. Written onto the receipt row. */
	private interrupt?: { readonly landed: number; readonly dropped: number };
	/** Every pending hermes clarify batch (the ask tool), any session's,
	 *  keyed by request id until its tool settles. buildModel surfaces one
	 *  per render via pickTreeClarify — the OpenCode session-tree rule. */
	private readonly clarifies = new Map<string, NonNullable<CrusorSurfaceSnapshot['clarify']>>();

	/** OpenCode's session-tree rule (session-request-tree.ts): the viewed
	 *  session's own pending question first, then the first pending
	 *  question among its descendants (BFS order ≈ arrival order here). A
	 *  question asked OUTSIDE the viewed tree stays parked until its own
	 *  view (or an ancestor's) opens. */
	private pickTreeClarify(): NonNullable<CrusorSurfaceSnapshot['clarify']> | undefined {
		if (!this.sessionId || !this.clarifies.size) { return undefined; }
		const entries = [...this.clarifies.values()];
		const own = entries.find(entry => entry.sessionId === this.sessionId);
		if (own) { return own; }
		const descendants = this.sessionDescendants(this.sessionId);
		return entries.find(entry => descendants.has(entry.sessionId));
	}

	private sessionDescendants(root: string): Set<string> {
		const children = new Map<string, string[]>();
		const link = (child?: string, parent?: string): void => {
			if (!child || !parent || child === parent) { return; }
			const list = children.get(parent) ?? [];
			list.push(child);
			children.set(parent, list);
		};
		for (const [child, parent] of this.parentMap) { link(child, parent); }
		for (const sub of this.subAgents.values()) {
			// Link by the id the child RUNS under as well as the record id:
			// emitters have disagreed about which one subagent_id carries,
			// and a tree that misses the link parks the child's question
			// where no ancestor can see it.
			link(sub.id, sub.parentSessionId);
			link(sub.childThreadId, sub.parentSessionId);
		}
		const seen = new Set<string>();
		const queue = [root];
		while (queue.length) {
			const current = queue.shift()!;
			for (const child of children.get(current) ?? []) {
				if (!seen.has(child)) { seen.add(child); queue.push(child); }
			}
		}
		return seen;
	}

	private clearClarifiesFor(sessionId: string | undefined): void {
		if (!sessionId) { return; }
		for (const [requestId, entry] of this.clarifies) {
			if (entry.sessionId === sessionId) { this.clarifies.delete(requestId); }
		}
	}
	/** Live hermes todo_list state, reconciled atomically on {todos, revision}. */
	private todos: readonly CrusorTodoItem[] = [];
	private todoRevision = 0;
	private turnOutcome: CrusorAIRenderModel['turnOutcome'] = 'idle';
	private userMessage: string | undefined;
	private assistantText = '';
	/**
	 * Ordered timeline (hermes message.parts): one entry per text segment and
	 * tool call, in arrival order. `assistantText` stays the concatenated
	 * string for copy/inspector; the TRANSCRIPT paints from `parts` so tools
	 * sit where they happened and the final answer lands last. Cleared at
	 * turn boundaries with the rest of the turn state.
	 */
	private parts: CrusorAITurnPart[] = [];
	/** Reasoning parts seen this turn — each LLM call that produces reasoning adds a new part. */
	private reasoningParts: { text: string; completedAt?: number }[] = [];
	private reasoningPending = false;
	/**
	 * Epoch ms the current turn began, or undefined between turns. The tail activity row counts
	 * from here until the transcript shows something, which is why it is a timestamp on the
	 * model rather than a counter in the renderer: a re-render must not restart the number.
	 */
	private turnStartedAt: number | undefined;
	/** When the last turn stopped, for the row's elapsed clock. Turn end is a frame, not a timer. */
	private turnEndedAt: number | undefined;
	/** Every pending safety approval, any session's, keyed by tool id.
	 *  Approvals are session-TREE requests exactly like questions
	 *  (OpenCode surfaces both through the same tree rule): buildModel
	 *  shows the viewed tree's first pending one in the approval dock,
	 *  and the reply routes to the asking session. */
	private readonly approvals = new Map<string, NonNullable<CrusorAIRenderModel['approval']> & { readonly sessionId: string }>();

	private pickTreeApproval(): (NonNullable<CrusorAIRenderModel['approval']> & { readonly sessionId: string }) | undefined {
		if (!this.sessionId || !this.approvals.size) { return undefined; }
		const entries = [...this.approvals.values()];
		const own = entries.find(entry => entry.sessionId === this.sessionId);
		if (own) { return own; }
		const descendants = this.sessionDescendants(this.sessionId);
		return entries.find(entry => descendants.has(entry.sessionId));
	}

	private clearApprovalsFor(sessionId: string | undefined): void {
		if (!sessionId) { return; }
		for (const [toolId, entry] of this.approvals) {
			if (entry.sessionId === sessionId) { this.approvals.delete(toolId); }
		}
	}
	private subAgents = new Map<string, CrusorAISubAgentView>();
	/** OpenCode parity: parentMap child_thread_id -> parent_session_id for navigation */
	private parentMap = new Map<string, string>();
	/** Child session tracking: this session is child if in parentMap or startsWith sub- */
	private childParentId: string | undefined;
	private plan: readonly CrusorAIPlanStepView[] = [];
	private verification: string | undefined;
	private telemetry: CrusorAIRenderModel['telemetry'] = {};
	private error: string | undefined;
	private engineSetupError = false;
	/**
	 * Live context-engine status (compaction in progress, overflow warning). Produced by the
	 * engine's `context_status` events: `compress`/`pre_api` set `compacting`, `compacted`
	 * clears it, `overflow_blocked` carries a warning that is NOT an `error` (the turn is
	 * still alive — it warns about the NEXT model call). Cleared at turn boundaries, like
	 * the other transient turn state.
	 */
	private contextStatus: CrusorAIRenderModel['contextStatus'];
	/** True while the engine reports an open compaction (`compress`/`pre_api` phase). */
	private compacting: boolean | undefined;
	private voiceHeard: CrusorAIRenderModel['voiceHeard'];
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

	/** A provider attempt has been named this turn (llm.request seen).
	 * Reasoning arriving AFTER this is real model thought — a buffered
	 * endpoint delivers it as a single whole-text frame — while reasoning
	 * before any provider attempt is the legacy liveness dress-up. */
	private hadProviderAttempt = false;
	private history: CrusorAIRenderModel['history'] = [];

	/**
	 * Explicit multi-root selection (P0): never silently pick folders[0].
	 * Set through selectWorkspace() and retained for the session, surviving
	 * re-renders, until the folder leaves the workspace or is replaced.
	 */
	private selectedWorkspaceUri: URI | undefined;

	private readonly host: CrusorAIRenderHost = {
		setDraft: value => { this.draft = value; },
		setMode: mode => {
			if (this.running || this.mode === mode) { return; }
			this.mode = mode;
			this.render();
		},
		// hermes reasoning-effort: a manual pick sticks for the session; it
		// rides the NEXT prompt frame, so a mid-turn change needs no cancel.
		setReasoningEffort: value => {
			if (this.reasoningEffort === value) { return; }
			this.reasoningEffort = value;
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
			// The verdict routes to the ASKING session (the bridge queue
			// rejects replies addressed to any other session — same rule as
			// clarify), then the pending entry retires.
			const entry = this.approvals.get(toolId);
			this.send({ type: 'safety_reply', session_id: entry?.sessionId ?? this.sessionId, tool_id: toolId, approved, always_allow: alwaysAllow });
			const tool = this.tools.get(toolId);
			if (tool) { this.tools.set(toolId, { ...tool, state: approved ? 'running' : 'failed' }); }
			if (entry) { this.approvals.delete(toolId); }
			this.render();
		},
		replyToClarify: (requestId, answers, timedOut) => {
			// The clarify card rides ONE batch reply (hermes #18450): answers per
			// qid; an explicit Skip resolves the batch empty (deliberate, not a
			// timeout). The reply routes to the ASKING session (a child's
			// question answered from the parent view must resolve the child's
			// wait — the bridge's queue rejects replies addressed to any other
			// session), then the card clears; the ask tool's own tool_call_end
			// paints the settled Q&A in the asking session's transcript.
			const entry = this.clarifies.get(requestId);
			this.send({ type: 'clarify_reply', session_id: entry?.sessionId ?? this.sessionId, request_id: requestId, answers, timed_out: timedOut });
			if (entry) { this.clarifies.delete(requestId); }
			this.render();
		},
		openDiff: toolId => { void this.openDiff(toolId); },
		revealFile: resource => { void this.revealFile(resource); },
		openExternal: url => {
			try { void this.openerService.open(url, { openExternal: true }); } catch (error) { /* link clicks never break the pane */ }
		},
		resourceSrc: resource => this.resourceBrowserSrc(resource),
		syntaxColors: language => this.syntaxColors(language),
		fileIconClasses: resource => {
			// VS Code's own file-icon resolution (Seti theme classes) — the
			// same classes the Explorer paints for this file.
			try {
				return getIconClasses(this.modelService, this.languageService, this.resourceUri(resource), FileKind.FILE).join(' ');
			} catch (error) {
				return undefined;
			}
		},
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
			this.error = undefined;
			const promptToRetry = this.pendingPrompt || this.lastSubmittedPrompt;
			void this.ensureEngine().then(() => {
				if (promptToRetry && this.engineService.state === CrusorAIEngineState.Ready) {
					this.pendingPrompt = undefined;
					void this.submitPrompt(promptToRetry);
				}
			});
		},
		selectWorkspace: uri => this.selectWorkspace(uri),
		openFolder: () => { void this.commandService.executeCommand('workbench.action.files.openFolder'); },
		openEngineSettings: () => { void this.commandService.executeCommand(CrusorAICommandId.OpenSettings); },
		openManager: () => { this.openManagerWindow(); },
		// Composer + -> the Add… dialog (native QuickPick; each row routes to
		// its registered command — one code path with the palette).
		skillsHubOp: (op, extra) => this.skillsHubOp(op, extra),
		copyToClipboard: text => {
			// Real clipboard (field: navigator.clipboard.writeText is
			// permission-blocked inside the webview). The workbench service
			// owns the privileged path; never let clipboard trouble throw.
			try { this.clipboardService.writeText(text); } catch { /* best effort */ }
		},
		// Composer + dialog, One-Shot tab (field 2026-10-02 rev 4): one quick
		// job over the oneshot envelope — same request/response pairing as
		// the hub op hook.
		oneshotRun: (template, instructions, variables) => {
			return new Promise((resolve, reject) => {
				let listener: { dispose(): void } | undefined;
				// 60s: one-shots are REAL model calls — a slow provider is
				// normal-ish; the engine bounds the call itself at 50s, so a
				// timeout here means the frame never got answered at all.
				const timer = setTimeout(() => {
					listener?.dispose();
					reject(new Error('One-shot: the engine did not answer in 60s. Try once more — if it repeats, fully restart CrusorAI so the bridge runs this build (the engine log prints a "[bridge] oneshot" line for every attempt).'));
				}, 60000);
				listener = this.onOneshotResult(frame => {
					clearTimeout(timer);
					listener?.dispose();
					if (frame.error) { reject(new Error(frame.error)); return; }
					resolve({ text: frame.text });
				});
				this.sendOneshot(template, { instructions, variables });
			});
		},
		navigateToSession: (sessionId: string) => { this.navigateToSession(sessionId); },
		newSession: () => { this.newSession(); },
		isChildSession: () => this.isDelegateChildView(),
	};

	constructor(
		@ICrusorAIEngineService private readonly engineService: ICrusorAIEngineService,
		@ICrusorAIWorkbenchService private readonly workbenchService: ICrusorAIWorkbenchService,
		@IWorkspaceContextService private readonly workspaceContextService: IWorkspaceContextService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@ICommandService private readonly commandService: ICommandService,
		@IClipboardService private readonly clipboardService: IClipboardService,
		@IAuxiliaryWindowService private readonly auxiliaryWindowService: IAuxiliaryWindowService,
		@ICrusorAISessionStore private readonly sessionStore: ICrusorAISessionStore,
		@INotificationService private readonly notificationService: INotificationService,
		@IModelService private readonly modelService: IModelService,
		@ILanguageService private readonly languageService: ILanguageService,
		@IThemeService private readonly themeService: IThemeService,
		@IOpenerService private readonly openerService: IOpenerService,
	) {
		super();
		this._register(this.engineService.onDidChangeState(state => {
			if (state === CrusorAIEngineState.Ready) {
				this.restartAttempts = 0;
				this.engineFault = undefined;
			} else if (state === CrusorAIEngineState.Crashed || state === CrusorAIEngineState.Degraded) {
				// The only trace of a dying sidecar used to be a log line: the process exit is reported by
				// the engine service, `scheduleRestart` swallows exhaustion, and a turn in flight never
				// receives turn_done -- so the panel kept painting a live run that had no engine behind it.
				// A setup failure already has its own actionable row, so it is not overwritten here.
				if (!this.engineSetupError) {
					this.engineFault = state === CrusorAIEngineState.Crashed
						? 'The Crusor engine process stopped while this session was open.'
						: 'The Crusor engine could not accept the request, so it never reached the model.';
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
		this._register(this.workbenchService.onDidResolveDiff(event => {
			this.host.replyToSafety(event.toolId, event.approved);
		}));
		this._register(this.workbenchService.onDidChangeCapabilities(() => {
			this.publishHostCapabilities();
			this.render();
		}));
		this._register(this.themeService.onDidColorThemeChange(() => this.syntaxColorCache.clear()));
		this._register(toDisposable(() => {
			if (this.renderFrame !== undefined) { cancelAnimationFrame(this.renderFrame); }
			if (this.restartTimer !== undefined) { clearTimeout(this.restartTimer); }
		}));
	}

	mount(root: unknown /* HTMLElement */, surface: CrusorAISurface): IDisposable {
		const mount = mountCrusorAIRenderer(root as HTMLElement, surface, this.host);
		this.mounts.add(mount);
		mount.update(this.model);
		if (this.configurationService.getValue<boolean>('crusorai.autoStart') !== false) {
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

	/**
	 * Blank-surface reset: every field that belongs to one session's visible turn state. One
	 * method because folder switches, session switches and New Session must clear exactly the
	 * same surface -- two copies drifted once already (history survived navigation).
	 */
	/** One sub-agent frame -> one record, on whichever surface owns it (live or stashed). */
	private mergeSubagentRecord(map: Map<string, CrusorAISubAgentView>, frame: CrusorServerEvent, fallbackParentId: string | undefined): { subagentId: string; childId: string; parentId: string | undefined } {
		const subagentId = (frame as any).subagent_id as string;
		const existing = map.get(subagentId) ?? { id: subagentId, state: 'pending' as const };
		const childId = ((frame as any).child_thread_id ?? subagentId) as string;
		const parentId = ((frame as any).parent_session_id ?? (frame as any).parentSessionId ?? fallbackParentId) as string | undefined;
		map.set(subagentId, {
			...existing,
			id: subagentId,
			state: subAgentState((frame as any).state, existing.state),
			goal: (frame as any).goal ?? existing.goal,
			description: (frame as any).description ?? (existing as any).description,
			mode: (frame as any).mode ?? existing.mode,
			progress: (frame as any).progress ?? existing.progress,
			result: (frame as any).result ?? existing.result,
			duration: (frame as any).duration ?? existing.duration,
			parentSessionId: parentId ?? existing.parentSessionId,
			childThreadId: childId ?? (existing as any).childThreadId,
			background: (frame as any).background ?? (existing as any).background,
			toolCalls: (frame as any).tool_calls ?? (frame as any).toolCalls ?? (existing as any).toolCalls,
			agentName: (frame as any).agent_name ?? (frame as any).agentName ?? existing.mode,
		});
		return { subagentId, childId, parentId };
	}

	/**
	 * While the user watches a child, the stashed parent keeps settling:
	 * apply its tool/sub-agent verdicts to the snapshot so returning
	 * never shows finished work still spinning (field 2026-10-15: the
	 * research child was done; the parent's row stayed RUNNING).
	 */
	private syncStashFrame(foreignId: string, frame: CrusorServerEvent): void {
		if (!this.liveStash || foreignId !== this.liveStash.sessionId) { return; }
		if (frame.type === 'subagent_updated') {
			this.mergeSubagentRecord(this.liveStash.snapshot.subAgents, frame, foreignId);
		} else if (frame.type === 'tool_call_end') {
			const stashTool = this.liveStash.snapshot.tools.get(frame.tool_id);
			if (stashTool) {
				const result = valueRecord(frame.result);
				this.liveStash.snapshot.tools.set(frame.tool_id, {
					...stashTool,
					result: frame.result,
					state: toolState(frame.status),
					duration: typeof result?.duration === 'string' ? result.duration : typeof result?.duration_ms === 'number' ? `${result.duration_ms}ms` : stashTool.duration,
				});
			}
		}
	}

	private captureSurface(sessionId: string): CrusorSurfaceSnapshot {
		return {
			sessionId,
			running: this.running,
			cancelRequested: this.cancelRequested,
			interrupt: this.interrupt,
			turnOutcome: this.turnOutcome,
			turnStartedAt: this.turnStartedAt,
			turnEndedAt: this.turnEndedAt,
			userMessage: this.userMessage,
			assistantText: this.assistantText,
			parts: [...this.parts],
			reasoningParts: [...this.reasoningParts],
			reasoningPending: this.reasoningPending,
			tools: new Map(this.tools),
			subAgents: new Map(this.subAgents),
			parentMap: new Map(this.parentMap),
			childParentId: this.childParentId,
			history: [...this.history],
			plan: this.plan,
			verification: this.verification,
			telemetry: this.telemetry,
			approval: this.pickTreeApproval(),
			clarify: this.pickTreeClarify(),
			todos: this.todos,
			todoRevision: this.todoRevision,
			compacting: this.compacting,
			contextStatus: this.contextStatus,
			voiceHeard: this.voiceHeard,
			llmStatus: this.llmStatus,
			llmHeads: this.llmHeads,
			degraded: this.degraded,
			error: this.error,
			hadProviderAttempt: this.hadProviderAttempt,
			pendingPrompt: this.pendingPrompt,
		};
	}

	private restoreSurface(snapshot: CrusorSurfaceSnapshot): void {
		this.sessionId = snapshot.sessionId;
		this.running = snapshot.running;
		this.cancelRequested = snapshot.cancelRequested;
		this.interrupt = snapshot.interrupt;
		this.turnOutcome = snapshot.turnOutcome;
		this.turnStartedAt = snapshot.turnStartedAt;
		this.turnEndedAt = snapshot.turnEndedAt;
		this.userMessage = snapshot.userMessage;
		this.assistantText = snapshot.assistantText;
		this.parts = [...snapshot.parts];
		this.reasoningParts = [...snapshot.reasoningParts];
		this.reasoningPending = snapshot.reasoningPending;
		this.tools.clear();
		for (const [id, tool] of snapshot.tools) { this.tools.set(id, tool); }
		this.subAgents.clear();
		for (const [id, record] of snapshot.subAgents) { this.subAgents.set(id, record); }
		this.parentMap.clear();
		for (const [child, parent] of snapshot.parentMap) { this.parentMap.set(child, parent); }
		this.childParentId = snapshot.childParentId;
		this.history = [...snapshot.history];
		this.plan = snapshot.plan;
		this.verification = snapshot.verification;
		this.telemetry = snapshot.telemetry;
		// Pending approvals are service-level tree state, not surface state:
		// the `approvals` map survives the stash and pickTreeApproval
		// re-derives what this view shows.
		// Pending clarifies are service-level tree state, not surface state:
		// the `clarifies` map survives the stash and pickTreeClarify re-derives
		// what this view shows, so a question asked while away still surfaces.
		this.todos = snapshot.todos;
		this.todoRevision = snapshot.todoRevision;
		this.compacting = snapshot.compacting;
		this.contextStatus = snapshot.contextStatus;
		this.voiceHeard = snapshot.voiceHeard;
		this.llmStatus = snapshot.llmStatus;
		this.llmHeads = snapshot.llmHeads;
		this.degraded = snapshot.degraded;
		this.error = snapshot.error;
		this.hadProviderAttempt = snapshot.hadProviderAttempt;
		this.pendingPrompt = snapshot.pendingPrompt;
		this.pendingHydration = undefined;
	}

	/**
	 * Adopt the viewed child's tail history turn into the live lane. The
	 * opening snapshot paints the child's turn-so-far as history; the first
	 * live frame for the viewed child means the real stream has arrived —
	 * continuing to append to a fresh live lane would duplicate that turn
	 * (history + live both painting it). Moving the tail up makes the
	 * stream CONTINUE the painted turn exactly like the parent's, and the
	 * checkpoint poll stands down (snapshots would freeze-frame over it).
	 */
	private adoptHistoryTailIfLive(): void {
		if (this.childLiveAdopted) { return; }
		const viewingChild = !!this.sessionId && !!(this.childParentId || this.parentMap.has(this.sessionId));
		if (!viewingChild || !this.history.length) { return; }
		if (this.userMessage || this.assistantText || this.tools.size > 0) { return; }
		const tail = this.history[this.history.length - 1];
		this.history = this.history.slice(0, -1);
		this.userMessage = tail.userMessage;
		this.assistantText = tail.assistantText;
		this.parts = [...tail.parts];
		this.reasoningParts = (tail.reasoningParts ?? []).map(part => ({ ...part }));
		this.tools = new Map(tail.tools.map(entry => [entry.id, entry]));
		this.running = true;
		this.turnOutcome = 'running';
		this.childLiveAdopted = true;
		this.stopChildLivePoll();
	}

	/**
	 * The viewed child's adopted turn just settled: move it into history
	 * and clear the live lane. Order-independent — if a settle snapshot
	 * already hydrated the same turn into the history tail, the lane is
	 * simply cleared so the turn never paints twice (history + live).
	 */
	private settleAdoptedTurn(): void {
		if (!this.childLiveAdopted) { return; }
		this.childLiveAdopted = false;
		const tail = this.history[this.history.length - 1];
		const alreadyHydrated = !!tail && tail.userMessage === this.userMessage
			&& tail.assistantText === this.assistantText;
		if (!alreadyHydrated) { this.archiveLiveTurn(); }
		this.userMessage = undefined;
		this.assistantText = '';
		this.parts = [];
		this.reasoningParts = [];
		this.reasoningPending = false;
		this.tools.clear();
	}

	/** Refresh the open child's transcript from its checkpoint (its steps land there as it works). */
	private requestChildSnapshot(): void {
		if (this.childLiveAdopted) { return; }
		const workspace = this.workspacePath;
		if (!workspace || !this.sessionId) { return; }
		this.childRefreshInFlight = true;
		this.send({ type: 'session_messages', session_id: this.sessionId, workspace, limit: 120, order: 'latest' });
	}

	private stopChildLivePoll(): void {
		if (this.childSnapshotTimer) {
			clearInterval(this.childSnapshotTimer);
			this.childSnapshotTimer = undefined;
		}
	}

	/**
	 * While a child session is open and its record has not settled, keep its
	 * transcript checkpoint-fresh on a timer until its live frames adopt the
	 * tail turn — from then on the child's own stream (forwarded by the
	 * bridge on proven lineage) is the truth and snapshots stand down. The
	 * poll also stops the moment the record settles or the user leaves.
	 */
	private syncChildLivePoll(): void {
		if (this.childLiveAdopted) { this.stopChildLivePoll(); return; }
		const viewingChild = !!this.sessionId && !!(this.childParentId || this.parentMap.has(this.sessionId));
		const record = viewingChild
			? [...this.subAgents.values()].find(entry => (entry.childThreadId ?? entry.id) === this.sessionId)
			: undefined;
		const childLive = viewingChild && (!record || record.state === 'running' || record.state === 'pending');
		if (childLive && !this.childSnapshotTimer) {
			this.childSnapshotTimer = setInterval(() => this.requestChildSnapshot(), 3000);
			this.requestChildSnapshot();
		} else if (!childLive) {
			this.stopChildLivePoll();
		}
	}

	private resetSessionState(): void {
		this.sessionId = undefined;
		this.running = false;
		this.childLiveAdopted = false;
		this.cancelRequested = false;
		this.turnOutcome = 'idle';
		this.turnStartedAt = undefined;
		this.turnEndedAt = undefined;
		this.userMessage = undefined;
		this.assistantText = '';
		this.pendingPrompt = undefined;
		this.pendingHydration = undefined;
		this.tools.clear();
		this.parts = [];
		this.reasoningParts = [];
		this.reasoningPending = false;
		this.subAgents.clear();
		this.parentMap.clear();
		this.childParentId = undefined;
		this.history = [];
		this.plan = [];
		this.verification = undefined;
		this.telemetry = {};
		this.todos = [];
		this.todoRevision = 0;
		this.compacting = undefined;
		this.contextStatus = undefined;
		this.voiceHeard = undefined;
		this.llmStatus = undefined;
		this.llmHeads = undefined;
		this.degraded = undefined;
		this.stalled = undefined;
		this.error = undefined;
		this.hadProviderAttempt = false;
		this.healAfterRestore = false;
		this.healRequested = false;
		this.clearStallWatchdog();
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
			this.resetSessionState();
		}
		this.render();
	}

	private get capabilitySummary(): CrusorAIRenderModel['capabilitySummary'] {
		const values = this.workbenchService.getCapabilities();
		return {
			available: values.filter(value => value.availability === 'available').length,
			blocked: values.filter(value => value.availability === 'blocked').length,
			total: values.length,
		};
	}

	private get model(): CrusorAIRenderModel {
		return {
			engineState: this.engineService.state,
			engineBuild: this.engineBuild,
			workspaceLabel: this.workspaceLabel,
			noWorkspace: this.workspaceFolderCount === 0,
			// P0: exact hint the renderer shows when no project folder is open.
			noWorkspaceHint: 'Open a folder to start a Crusor session.',
			workspaceSelectionRequired: this.workspaceFolderCount > 1 && !this.sessionFolder,
			workspaceChoices: this.workspaceChoices,
			engineSetupError: this.engineSetupError,
			sessionId: this.sessionId,
			mode: this.mode,
			reasoningEffort: this.reasoningEffort || 'none',
			running: this.running,
			cancelRequested: this.cancelRequested,
			interrupt: this.interrupt,
			turnStartedAt: this.turnStartedAt,
			// Wired: the engine now emits `context_status` frames (compaction start/done and
			// the overflow warning), projected by the bridge from the session-scoped
			// `context.status` event. Absent stays honest: no signal, no row.
			compacting: this.compacting,
			contextStatus: this.contextStatus,
			voiceHeard: this.voiceHeard,
			llmStatus: this.llmStatus,
			llmHeads: this.llmHeads,
			// The Thinking card is the FIRST-CLASS thought; the activity row
			// must not parrot it when reasoning is what the turn is doing.
			llmReasoningLive: Boolean(this.running && this.reasoningParts.length > 0 && this.hadProviderAttempt),
			stalled: this.stalled,
			degraded: this.degraded,
			turnOutcome: this.turnOutcome,
			userMessage: this.userMessage,
			assistantText: this.assistantText,
			parts: [...this.parts],
				reasoningParts: [...this.reasoningParts],
			tools: [...this.tools.values()],
			subAgents: [...this.subAgents.values()],
			isChild: this.isDelegateChildView(),
			parentSessionId: this.currentParentId(),
			parentMap: new Map(this.parentMap),
			subAgentGoal: this.currentSubAgentGoal(),
			parentTitle: this.currentParentTitle(),
			childSiblings: this.currentChildSiblings(),
			approval: this.pickTreeApproval(),
			clarify: this.pickTreeClarify(),
			todos: this.todos,
			todoRevision: this.todoRevision,
			plan: this.plan,
			verification: this.verification,
			telemetry: this.telemetry,
			capabilitySummary: this.capabilitySummary,
			error: this.error,
			engineFault: this.engineFault === undefined ? undefined : {
				message: this.engineFault,
				// Same two conditions scheduleRestart checks -- reporting 'retrying' when the backoff had
				// already given up, or when autoStart is off, would be a promise the code cannot keep.
				retrying: this.restartAttempts < 3 && this.configurationService.getValue<boolean>('crusorai.autoStart') !== false,
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
	/**
	 * In-place session open (Hermes openSession): the surface rebinds to the target and its
	 * transcript hydrates from the paged checkpoints. The previous session keeps running
	 * untouched -- its frames route to its list row (see foreignSessionId), never here.
	 */
	private navigateToSession(targetSessionId: string): void {
		if (!targetSessionId || targetSessionId === this.sessionId) { return; }
		this.stopChildLivePoll();
		// BACK to a stashed live surface: restore it exactly where it left
		// off, whether or not a run is still in flight. This is checked
		// FIRST — while viewing a running child, this.running is true, and
		// the way home must never be refused (field 2026-10-16: the back
		// arrow inside a running child answered 'Stop the current run
		// before switching sessions.').
		if (this.liveStash && this.liveStash.sessionId === targetSessionId) {
			const stash = this.liveStash;
			this.liveStash = undefined;
			this.restoreSurface(stash.snapshot);
			this.sessionId = targetSessionId;
			this.healAfterRestore = true;
			this.sessionStore.markRead(targetSessionId, true);
			this.setRememberedSession(targetSessionId);
			this.render();
			return;
		}
		// Departing a LIVE surface never blocks navigation: every session
		// is a place you can stand (OpenCode), and the run continues
		// server-side regardless of which one is on screen. The departed
		// surface is stashed so returning restores it exactly; while
		// away, its frames note its list row (see foreignSessionId). A
		// stash of a still-running surface is never overwritten by a
		// calmer one.
		if (this.running && this.sessionId) {
			const stashedIsRunning = !!this.liveStash && this.liveStash.snapshot.running;
			if (!stashedIsRunning || (this.liveStash && this.liveStash.sessionId === this.sessionId)) {
				this.liveStash = { sessionId: this.sessionId, snapshot: this.captureSurface(this.sessionId) };
			}
		}
		const previousSessionId = this.sessionId;
		const previousChildParentId = this.childParentId;
		// Pre-reset reads: the reset wipes the map and the records. A plausible child
		// hydrates its own record below; the ownership reads gate the optimistic link.
		const targetLooksChild = targetSessionId.startsWith('sub-') || this.parentMap.has(targetSessionId);
		const targetKnownParent = this.parentMap.get(targetSessionId);
		const previousKnownParent = previousSessionId ? this.parentMap.get(previousSessionId) : undefined;
		const previousOwnsTarget = !!previousSessionId && [...this.subAgents.values()].some(record =>
			(record.childThreadId === targetSessionId || record.id === targetSessionId)
			&& record.parentSessionId === previousSessionId);
		const navigatingToKnownParent = !!previousSessionId
			&& (previousChildParentId === targetSessionId || previousKnownParent === targetSessionId);
		this.resetSessionState();
		this.sessionId = targetSessionId;
		// Optimistic parentage ONLY when the previous session actually owns the target
		// (its subagent record says so, or the warm map agrees) — never on the way back
		// to a known parent. Linking every target as a child of the previous session is
		// what painted the child header (prompt disabled) on plain sessions opened from
		// History (field 2026-09-28).
		if (!navigatingToKnownParent && targetLooksChild && previousSessionId
			&& (previousOwnsTarget || targetKnownParent === previousSessionId)) {
			this.parentMap.set(targetSessionId, previousSessionId);
		}
		// The reset cleared childParentId; only a real link sets it back. Back-to-Parent
		// and history hops between normal sessions stay normal.
		if (this.parentMap.has(targetSessionId)) {
			this.childParentId = this.parentMap.get(targetSessionId);
		}
		// An explicit open IS the read: clear the dot before the frames arrive (Hermes marks
		// the session read before it focuses it), and remember it so a restart lands back here.
		this.sessionStore.markRead(targetSessionId, true);
		this.setRememberedSession(targetSessionId);
		this.pendingHydration = targetSessionId;
		const workspace = this.workspacePath;
		if (workspace) {
			// Transcript hydration comes from the paged checkpoints (session_messages), not the
			// journal: include_events:false keeps the resume's events out so the two views never
			// double-paint one transcript.
			this.send({ type: 'session_resume', session_id: targetSessionId, workspace, include_events: false });
			this.send({ type: 'session_messages', session_id: targetSessionId, workspace, limit: 120, order: 'latest' });
			// Sub-agent children hydrate their own record (goal/description/state) on open, so
			// the child header paints the delegated task even when the record map is cold
			// (restart or history navigation). Gated: an unknown id would upsert a junk
			// record and self-parent the session.
			if (targetLooksChild) {
				this.send({ type: 'subagent_status', session_id: targetSessionId, subagent_id: targetSessionId });
			}
		}
		this.requestSessionList();
		this.syncChildLivePoll();
		this.render();
	}

	/**
	 * Hermes "New Session": a blank surface with NO session id. The id is minted by the engine
	 * on the next prompt (session_create), so a draft the user abandons leaves no row behind.
	 * While a turn runs the surface is occupied -- stranding a live turn's frames is worse
	 * than refusing.
	 */
	newSession(): void {
		if (this.running) {
			this.error = 'Stop the current run before starting a new session.';
			this.render();
			return;
		}
		this.resetSessionState();
		this.render();
	}

	/**
	 * Workbench-list entry to navigateToSession: rebind the surface to an existing session.
	 * Same guards (no mid-turn switches), same checkpoint hydration.
	 */
	openSession(sessionId: string): void {
		this.navigateToSession(sessionId);
	}

	/**
	 * This session's own delegated goal when it is a sub-agent child: the record whose
	 * child thread is the active session. The child header paints this — never a hardcoded
	 * title (field 2026-09-28: every sub-agent view read "Main / Sub-agent").
	 */
	private currentSubAgentGoal(): string | undefined {
		if (!this.sessionId) { return undefined; }
		for (const record of this.subAgents.values()) {
			if (record.childThreadId === this.sessionId) {
				return record.goal || record.description || undefined;
			}
		}
		for (const record of this.subAgents.values()) {
			if (record.id === this.sessionId && record.parentSessionId) {
				return record.goal || record.description || undefined;
			}
		}
		return undefined;
	}

	/** Sibling sub-agents of the viewed child (same parent), OpenCode's
	 *  child-header switcher: id + a human label each, self excluded. */
	private currentChildSiblings(): readonly { readonly id: string; readonly label: string }[] | undefined {
		const parentId = this.childParentId ?? (this.sessionId ? this.parentMap.get(this.sessionId) : undefined);
		if (!parentId || !this.sessionId) { return undefined; }
		const siblings: { id: string; label: string }[] = [];
		for (const record of this.sessionStore.records()) {
			if (record.sessionId === this.sessionId) { continue; }
			const recordParent = record.parentSessionId ?? this.parentMap.get(record.sessionId);
			if (recordParent === parentId) { siblings.push({ id: record.sessionId, label: record.label }); }
		}
		for (const sub of this.subAgents.values()) {
			const id = sub.childThreadId ?? sub.id;
			if (id === this.sessionId || siblings.some(sibling => sibling.id === id)) { continue; }
			if ((sub.parentSessionId ?? this.parentMap.get(id)) === parentId) {
				siblings.push({ id, label: sub.description ?? sub.goal ?? sub.agentName ?? 'Sub-agent' });
			}
		}
		return siblings.length ? siblings : undefined;
	}

	/** The active session's parent label from the store, for the child breadcrumb. */
	private currentParentTitle(): string | undefined {
		const parentId = this.currentParentId();
		if (!parentId) { return undefined; }
		return this.sessionStore.records().find(record => record.sessionId === parentId)?.label;
	}

	/**
	 * The viewed session's parent, from EVERY lineage signal: the
	 * navigation link, the parent map, the child's own sub-agent
	 * record, and the durable session row. Whichever hop learned the
	 * lineage first, the others may never hear of it (cold panel,
	 * legacy rows) — the child chrome must not depend on one channel.
	 */
	private currentParentId(): string | undefined {
		if (!this.sessionId) { return this.childParentId; }
		return this.childParentId
			?? this.parentMap.get(this.sessionId)
			?? [...this.subAgents.values()].find(entry => (entry.childThreadId ?? entry.id) === this.sessionId)?.parentSessionId
			?? this.sessionStore.records().find(record => record.sessionId === this.sessionId)?.parentSessionId;
	}

	/**
	 * True when the open session is a delegated child, by any signal.
	 * The field failure (2026-10-16, "where am i this is not parent
	 * screen") was a child transcript painting under a parent
	 * identity — composer live, no back row — because the one signal
	 * consulted had not survived the trip. Never again one channel.
	 */
	private isDelegateChildView(): boolean {
		if (!this.sessionId) { return false; }
		return this.childParentId !== undefined
			|| this.parentMap.has(this.sessionId)
			|| this.sessionId.startsWith('sub-')
			|| [...this.subAgents.values()].some(entry => (entry.childThreadId ?? entry.id) === this.sessionId);
		// Deliberately NOT "the durable row names a parent": fork
		// continuations carry a parent id too, and they are sessions
		// the user chats in — only delegate signals mark a child.
	}

	private sessionRows(): readonly CrusorAISessionRow[] {
		const readState = new Map<string, boolean>();
		for (const facts of this.sessionStore.records()) {
			const isRead = this.sessionStore.isRead(facts.sessionId);
			if (isRead !== undefined) { readState.set(facts.sessionId, isRead); }
		}
		// The list shows ROOT sessions only (OpenCode: children are reached
		// through their parent's delegate cards, never as list rows — a
		// delegation-heavy session otherwise floods the Manager with
		// workers). Records stay in the store: titles, the session tree,
		// and navigation keep resolving children from them.
		const roots = this.sessionStore.records().filter(record => !record.parentSessionId && !this.parentMap.has(record.sessionId));
		return crusorSessionRows(roots, this.sessionId, Date.now(), readState);
	}

	/**
	 * Called before the mount check: a session nobody has painted is still a session the user
	 * ran. `changes` is left out on purpose until one diff counter is shared with the tool row --
	 * a count of files nobody measured is worse in a list than an absent field.
	 */
	private noteSession(): void {
		if (!this.sessionId) { return; }
		// The label is the engine's created title (fixed, unique). Until it lands the row
		// renders the generic placeholder — the first message is NEVER captured as the
		// title (field 2026-09-28). A generic fallback is never sticky: the titler's
		// live push upgrades it exactly once.
		const previousLabel = this.sessionStore.records().find(record => record.sessionId === this.sessionId)?.label;
		const facts: CrusorAISessionFacts = {
			sessionId: this.sessionId,
			label: previousLabel && !crusorSessionLabelIsFallback(previousLabel) ? previousLabel : crusorSessionLabel(undefined, this.sessionId),
			workspaceLabel: this.workspaceLabel,
			statusName: crusorSessionStatusName({ running: this.running, turnOutcome: this.turnOutcome, hasApproval: this.pickTreeApproval() !== undefined }),
			firstSeenAt: Date.now(),
			turnStartedAt: this.turnStartedAt,
			turnEndedAt: this.turnEndedAt,
		};
		this.sessionStore.note(facts);
	}

	/**
	 * Durable-list refresh (Hermes listSessions): the store's rows for every session come from
	 * here. Fire-and-forget; the reply is a sid-less session_info whose `sessions` payload must
	 * never clobber the active session id (see acceptFrame).
	 */
	private requestSessionList(): void {
		const workspace = this.workspacePath;
		if (!workspace || this.engineService.state !== CrusorAIEngineState.Ready) { return; }
		this.send({ type: 'session_list', session_id: this.sessionId, workspace, limit: 40, archived: 'exclude' });
	}

	/**
	 * One durable row (or optimistic draft row) into the store. Live status always wins for the
	 * ACTIVE session, whose label stays the user's own first message; anything else is history
	 * and paints without a lifecycle -- except an unread row, which surfaces as
	 * completed-unread so the attention dot survives a restart.
	 */
	private noteEngineRow(row: CrusorAIEngineSessionRow): void {
		const sessionId = row.session_id ?? row.id;
		if (!sessionId) { return; }
		const isActive = sessionId === this.sessionId;
		const statusName: CrusorAISessionStatusName | undefined = isActive
			? crusorSessionStatusName({ running: this.running, turnOutcome: this.turnOutcome, hasApproval: this.pickTreeApproval() !== undefined })
			: row.unread === true ? 'completed' : undefined;
		const base = crusorFactsFromEngineRow(row, { workspaceLabel: this.workspaceLabel, statusName, now: Date.now() });
		// Active label: the engine's created title wins (fixed, unique; the rename path
		// upgrades it the same way); otherwise the first-seen non-fallback label sticks.
		// No title yet: the generic placeholder — never the first message.
		const engineTitle = (row.title ?? '').trim();
		const previousLabel = this.sessionStore.records().find(record => record.sessionId === sessionId)?.label;
		const liveLabel = engineTitle || (previousLabel && !crusorSessionLabelIsFallback(previousLabel) ? previousLabel : crusorSessionLabel(undefined, sessionId));
		this.sessionStore.note(isActive
			? { ...base, label: liveLabel, turnStartedAt: this.turnStartedAt, turnEndedAt: this.turnEndedAt }
			: base);
		if (row.unread !== undefined) { this.sessionStore.markRead(sessionId, !row.unread); }
	}

	/**
	 * Frames for a session that is NOT the painted one. Crusor runs one foreground surface: a
	 * background turn's frames update its LIST row (and toast on completion), never the live
	 * transcript. Returns the foreign id, or undefined when the frame belongs to the active
	 * surface (or to no session yet).
	 */
	private foreignSessionId(frame: CrusorServerEvent): string | undefined {
		const sessionId = (frame as { session_id?: unknown }).session_id;
		if (typeof sessionId !== 'string' || !sessionId) { return undefined; }
		if (!this.sessionId || sessionId === this.sessionId) { return undefined; }
		return sessionId;
	}

	/**
	 * Background-turn traffic: the row paints Working / needs-input / finished, the transcript
	 * is untouched, and a finished background turn toasts (same toggle as a foreground one) and
	 * re-syncs the list so its title and counts land. The stored row is spread first so a note
	 * never clobbers the engine's label and durable fields with a guess.
	 */
	private noteForeignFrame(foreignId: string, frame: CrusorServerEvent): void {
		const previous = this.sessionStore.records().find(record => record.sessionId === foreignId);
		const label = previous?.label ?? 'Crusor session';
		const workspaceLabel = previous?.workspaceLabel ?? this.workspaceLabel;
		if (frame.type === 'turn_done' || frame.type === 'turn_failed') {
			// The stashed parent settled while the user was inside its
			// child: the snapshot is stale now — drop it so returning
			// hydrates the finished transcript. And if the CHILD is what
			// is open, its final steps just landed: snapshot it now.
			if (this.liveStash?.sessionId === foreignId) { this.liveStash = undefined; }
			if (this.sessionId && this.parentMap.get(this.sessionId) === foreignId) { this.requestChildSnapshot(); }
			const failed = frame.type === 'turn_failed';
			const cancelled = !failed && (frame as { cancelled?: boolean }).cancelled === true;
			this.sessionStore.note({
				...previous,
				sessionId: foreignId,
				label,
				workspaceLabel,
				statusName: failed ? 'failed' : 'completed',
				firstSeenAt: previous?.firstSeenAt ?? Date.now(),
				turnEndedAt: Date.now(),
			});
			this.sessionStore.markRead(foreignId, false);
			if (!cancelled) {
				this.notifyResponseReady(failed ? (frame as { error?: string }).error : `(${label}) ${((frame as { message?: string }).message ?? '').split('\n')[0]}`.trim(), failed);
			}
			this.requestSessionList();
			this.render();
			return;
		}
		const statusName: CrusorAISessionStatusName = frame.type === 'safety_request' || frame.type === 'clarify_request' ? 'needsInput' : 'inProgress';
		this.sessionStore.note({
			...previous,
			sessionId: foreignId,
			label,
			workspaceLabel,
			statusName,
			firstSeenAt: previous?.firstSeenAt ?? Date.now(),
			turnStartedAt: previous?.turnStartedAt ?? Date.now(),
		});
		this.render();
	}

	/** Hermes profileNavigationKey parity: the last open session per workspace survives a restart. */
	private rememberedSessionKey(): string | undefined {
		const workspace = this.workspacePath;
		if (workspace === undefined) { return undefined; }
		return `crusorai.lastSession.${encodeURIComponent(workspace)}`;
	}

	private getRememberedSession(): string | undefined {
		try {
			const key = this.rememberedSessionKey();
			const value = key ? window.localStorage.getItem(key) : undefined;
			return value || undefined;
		} catch { return undefined; }
	}

	private setRememberedSession(sessionId: string | undefined): void {
		try {
			const key = this.rememberedSessionKey();
			if (!key) { return; }
			if (sessionId) { window.localStorage.setItem(key, sessionId); }
			else { window.localStorage.removeItem(key); }
		} catch { /* storage is best-effort; the session still works */ }
	}

	/**
	 * Rebuild the transcript lane from paged checkpoint messages (Hermes hydrates the thread
	 * over REST the same way). Every turn lands in HISTORY -- the live surface stays empty so
	 * the next prompt starts a fresh turn, not an edit of the past. Tool calls rebuild their
	 * cards from the assistant's tool_calls plus the matching tool results (joined on
	 * tool_call_id); a result with no card falls back to truncated text rather than vanishing.
	 */
	private hydrateTranscript(messages: readonly CrusorSessionMessage[]): void {
		interface HydratedTurn { userMessage?: string; assistantText: string; parts: CrusorAITurnPart[]; reasoningParts: { text: string }[]; tools: CrusorAIToolView[] }
		const turns: HydratedTurn[] = [];
		let current: HydratedTurn = { assistantText: '', parts: [], reasoningParts: [], tools: [] };
		const toolIndex = new Map<string, CrusorAIToolView>();
		const dirty = (turn: HydratedTurn): boolean => turn.userMessage !== undefined || turn.assistantText !== '' || turn.parts.length > 0 || turn.reasoningParts.length > 0 || turn.tools.length > 0;
		const rollTurn = (): void => {
			if (dirty(current)) { turns.push(current); }
			current = { assistantText: '', parts: [], reasoningParts: [], tools: [] };
		};
		for (const message of messages) {
			if (message.role === 'user') {
				if (dirty(current) && current.userMessage !== undefined) { rollTurn(); }
				current.userMessage = current.userMessage ? `${current.userMessage}\n${message.content}` : message.content;
			} else if (message.role === 'assistant') {
				// Hermes thinking parts: persisted reasoning renders the Think card on history
				// turns exactly like live ones. The parts array drives the paint, so both the
				// entry AND its inline position pin are required (field 2026-09-28: entries
				// without pins never painted).
				if (message.reasoning) {
					current.reasoningParts.push({ text: message.reasoning });
					current.parts.push({ kind: 'reasoning', reasoningIndex: current.reasoningParts.length - 1 });
				}
				if (message.content) {
					current.assistantText += message.content;
					current.parts.push({ kind: 'text', text: message.content });
				}
				for (const call of message.tool_calls ?? []) {
					const id = call.id || `hydrate-${turns.length}-${current.tools.length}`;
					// Checkpoints carry no per-tool verdict: the turn completed, so the card paints
					// passed; a failed tool's stderr still shows in its result body.
					const tool: CrusorAIToolView = { id, name: call.name, state: 'passed', arguments: call.args };
					current.tools.push(tool);
					current.parts.push({ kind: 'tool', toolId: id });
					if (call.id) { toolIndex.set(call.id, tool); }
				}
			} else if (message.role === 'tool') {
				const target = (message.tool_call_id && toolIndex.get(message.tool_call_id)) ?? current.tools[current.tools.length - 1];
				if (target && message.content) {
					current.tools[current.tools.indexOf(target)] = { ...target, result: message.content };
				} else if (message.content) {
					const text = message.content.length > 2000 ? `${message.content.slice(0, 2000)}\u2026` : message.content;
					current.assistantText += text;
					current.parts.push({ kind: 'text', text });
				}
			}
		}
		rollTurn();
		const nextHistory = turns.slice(-20).map(turn => ({
			userMessage: turn.userMessage,
			assistantText: turn.assistantText,
			parts: turn.parts,
			reasoningParts: turn.reasoningParts,
			tools: turn.tools,
			subAgents: [],
			turnOutcome: 'completed' as const,
			plan: [],
		}));
		// A watched child is re-snapshotted every 3s. Byte-identical
		// hydration must keep the SAME turn objects: fresh ones defeat
		// the renderer's stream envelope and the lane is torn down and
		// rebuilt under the user's wheel every poll — the transcript
		// reads as unscrollable (field 2026-10-15).
		if (!sameHistoryTurns(nextHistory, this.history)) {
			this.history = nextHistory;
		}
		this.render();
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
		if (this.configurationService.getValue<boolean>('crusorai.autoStart') === false) { return; }
		const delay = 1_000 * (2 ** this.restartAttempts);
		this.restartTimer = setTimeout(() => {
			this.restartTimer = undefined;
			this.restartAttempts += 1;
			void this.ensureEngine();
		}, delay);
	}

	private async ensureEngine(): Promise<void> {
		if (this.engineService.state === CrusorAIEngineState.Ready) { return; }
		if (this.startPromise) { return this.startPromise; }
		// P0: no project folder -> no session, no engine start, no frames. The
		// composer is disabled, so this is never an error state; an engine-root
		// problem is still reported as an actionable engine-setup error below.
		const workspace = this.workspacePath;
		if (!workspace) {
			this.engineSetupError = false;
			// Field 2026-09-05: a dead engine with zero log lines is
			// undebuggable — every quiet path out of start() must speak.
			console.warn('[CrusorAI] engine start skipped: no workspace folder is open. Open a folder to enable the agent.');
			return;
		}
		this.error = undefined;
		const resumeSession = this.sessionId;
		this.startPromise = this.engineService.start(workspace).then(() => {
			this.engineSetupError = false;
			if (this.engineService.state !== CrusorAIEngineState.Ready) { return; }
			// The durable list is the session surface's memory: refresh it on every (re)connect.
			this.requestSessionList();
			if (resumeSession) {
				this.publishHostCapabilities(resumeSession);
				this.send({ type: 'session_resume', session_id: resumeSession, workspace });
				this.send({ type: 'events_replay', session_id: resumeSession });
				return;
			}
			// Fresh window, remembered session: land back where the user was (Hermes restores
			// the last open session per profile). The journal stays out -- the transcript
			// hydrates from the paged checkpoints, exactly like an in-app switch.
			const remembered = this.getRememberedSession();
			if (remembered) {
				this.sessionId = remembered;
				this.publishHostCapabilities(remembered);
				this.pendingHydration = remembered;
				this.send({ type: 'session_resume', session_id: remembered, workspace, include_events: false });
				this.send({ type: 'session_messages', session_id: remembered, workspace, limit: 120, order: 'latest' });
			}
		}).catch(error => {
			this.engineSetupError = error instanceof CrusorAIEngineSetupError;
			this.error = error instanceof Error ? error.message : String(error);
			console.error('[CrusorAI] engine start failed:', this.error);
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
		auxiliaryWindow.window.document.title = 'Crusor Manager';

		const root = document.createElement('div');
		root.className = 'crusorai-render-root crusorai-manager-editor';
		root.dataset.surface = 'manager';
		root.style.width = '100%';
		root.style.height = '100%';
		container.appendChild(root);

		const mount = mountCrusorAIRenderer(root, 'manager', this.host);
		mount.update(this.model);
		this._register(toDisposable(() => mount.dispose()));
	}

	private publishHostCapabilities(sessionId = this.sessionId): void {
		const workspace = this.workspacePath;
		if (!sessionId || !workspace || this.engineService.state !== CrusorAIEngineState.Ready) { return; }
		const statuses = new Map(this.workbenchService.getCapabilities().map(item => [item.id, item]));
		const readIds = new Set([
			'workspace.trust', 'editor.activeSelection', 'editor.dirtyText',
			'diagnostics.markers', 'language.symbols', 'language.definitions',
			'language.references', 'search.workspace', 'scm.state',
			'preview.open',
		]);
		const capabilities = CRUSOR_AI_WORKBENCH_CAPABILITIES
			.filter(item => item.risk === 'read' && readIds.has(item.id))
			.map(item => ({ ...item, ...statuses.get(item.id) }));
		this.send({ type: 'host_capabilities_update', session_id: sessionId, workspace, capabilities });
	}

	private async invokeHostCapability(frame: Extract<CrusorServerEvent, { type: 'host_tool_request' }>): Promise<void> {
		const started = Date.now();
		const workspace = this.workspacePath;
		if (!this.sessionId || frame.session_id !== this.sessionId || !workspace || frame.workspace !== workspace) {
			this.send({
				type: 'host_tool_result', session_id: frame.session_id, workspace: frame.workspace,
				request_id: frame.request_id, status: 'error',
				error: 'host tool request does not match the active Crusor workspace/session',
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
				case 'preview.open': {
					// The agent asked for the Preview window by name: route through
					// the same command the Preview chip runs (no preview-service DI
					// edge here — that would be a cycle). An explicit URL target is
					// honored; otherwise the service resolves the freshest evidence.
					// The command forwards the service's honest {ok, reason} so the
					// agent cannot claim success over a refused spawn (dead proxy,
					// dead dev server, nothing to preview).
					const url = typeof args['url'] === 'string' && args['url'].trim() ? args['url'].trim() : undefined;
					const outcome = await this.commandService.executeCommand('crusorai.openPreview', url ? { url } : undefined) as { ok?: boolean; reason?: string } | undefined;
					result = {
						opened: outcome?.ok !== false,
						...(outcome?.ok === false ? { refused_reason: outcome.reason ?? 'the preview could not be opened' } : {}),
						...(url ? { url } : {}),
					};
					break;
				}
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
		// A bounded wait, not an unbounded one: ensureEngine resolves when
		// start() settles, but a wedged sidecar must not eat the user's
		// click forever (field 2026-09-05: "send button not working" — the
		// click died in the old silent not-ready return with ZERO feedback).
		await Promise.race([
			this.ensureEngine(),
			new Promise<void>(resolve => setTimeout(resolve, 20_000)),
		]);
		if (this.engineService.state !== CrusorAIEngineState.Ready) {
			// The one dishonest thing the old code did: return silently. The
			// user typed a prompt and pressed send; the panel owes them the
			// state of the engine and an action (hermes: state the fact,
			// keep an option). start() failures already paint their own
			// message — only the quiet paths get words here. The draft is
			// preserved (cleared only after the ready check below).
			console.warn(`[CrusorAI] prompt not sent: engine state=${this.engineService.state}, workspace=${this.workspacePath ? 'ok' : 'MISSING'}`);
			if (!this.error) {
				this.error = `Crusor engine is ${this.engineService.state} — not accepting prompts yet. Give it a moment, or retry from the Manager panel.`;
			}
			this.render();
			return;
		}
		this.draft = '';
		this.error = undefined;
		this.lastSubmittedPrompt = text;
		if (!this.sessionId) {
			this.pendingPrompt = text;
			this.send({ type: 'session_create', workspace: this.workspacePath });
			this.render();
			return;
		}
		this.startTurn(text);
	}

	/**
	 * A turn opened by code outside the composer (today: the Preview window's
	 * reviewed batch, whose `prompt` frame is dispatched by the preview service
	 * itself). The engine will stream `turn_started` and everything after; the
	 * only thing missing without this is the USER half of the turn — the bubble
	 * and the fresh-turn bookkeeping. When a session is live, run exactly what
	 * `startTurn` runs minus the send and answer true: the caller's frame is
	 * the turn's prompt. Without a session, park the text as the pending
	 * prompt behind a `session_create` and answer false — the caller's frame
	 * would only be refused (session required), and the `session_info`
	 * handler starts the turn with the parked text instead.
	 */
	beginExternalTurn(text: string): boolean {
		if (this.sessionId) {
			this.archiveLiveTurn();
			this.resetTurnState(text);
			this.render();
			return true;
		}
		// The user bubble is NOT set here: the parked prompt replays through
		// startTurn on session_info, and pre-setting it would archive a
		// bubble-only turn and paint the message twice.
		this.pendingPrompt = text;
		this.send({ type: 'session_create', workspace: this.workspacePath });
		this.render();
		return false;
	}

	/** Push the live turn (if any) into history before a new one replaces it. */
	private archiveLiveTurn(): void {
		if (!(this.userMessage || this.assistantText || this.tools.size > 0)) { return; }
		this.history = [...this.history, {
			userMessage: this.userMessage,
			assistantText: this.assistantText,
			parts: [...this.parts],
			reasoningParts: this.reasoningParts,
			reasoningPending: this.reasoningPending,
			tools: [...this.tools.values()],
			subAgents: [...this.subAgents.values()],
			turnOutcome: this.turnOutcome,
			interrupt: this.interrupt,
			plan: this.plan,
		}].slice(-20); // keep last 20 turns
	}

	/** Measure the brake at turn end: which tool calls had already landed. */
	private stampInterrupt(): { landed: number; dropped: number } {
		let landed = 0;
		let dropped = 0;
		for (const tool of this.tools.values()) {
			if (tool.state === 'queued' || tool.state === 'approval' || tool.state === 'running') {
				dropped++;
			} else {
				landed++;
			}
		}
		return { landed, dropped };
	}

	/** Fresh-turn state: the user's text becomes the bubble; everything else clears. */
	private resetTurnState(text: string): void {
		this.interrupt = undefined;
		this.userMessage = text;
		this.assistantText = '';
		this.parts = [];
		this.reasoningParts = [];
		this.reasoningPending = false;
		this.hadProviderAttempt = false;
		this.tools.clear();
		this.subAgents.clear();
		this.clearApprovalsFor(this.sessionId);
		this.clearClarifiesFor(this.sessionId);
		this.plan = [];
		this.verification = undefined;
		this.running = true;
		this.cancelRequested = false;
		this.turnOutcome = 'running';
		this.turnStartedAt = Date.now();
	}

	private startTurn(text: string): void {
		this.archiveLiveTurn();
		this.resetTurnState(text);
		this.send({ type: 'prompt', session_id: this.sessionId, workspace: this.workspacePath, text, mode: this.mode, reasoning_effort: this.reasoningEffort || 'none' });
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

	/**
	 * token_retract: the engine discarded a generation whose text already
	 * streamed (dropped-toolcall re-prompt / failover) and is re-generating.
	 * Withdraw exactly the painted chars from the tail so the replacement
	 * answer does not glue onto the discarded one (field 2026-10-15: users
	 * got 2-3 concatenated answers from velona/GLM's empty tool_calls).
	 */
	private retractText(chars: number): void {
		let remaining = Math.min(Math.max(0, chars), this.assistantText.length);
		if (remaining <= 0) { return; }
		this.assistantText = this.assistantText.slice(0, this.assistantText.length - remaining);
		while (remaining > 0) {
			const last = this.parts[this.parts.length - 1];
			if (!last || last.kind !== 'text') { break; }
			if (last.text.length <= remaining) {
				remaining -= last.text.length;
				this.parts.pop();
			} else {
				this.parts[this.parts.length - 1] = { kind: 'text', text: last.text.slice(0, last.text.length - remaining) };
				remaining = 0;
			}
		}
	}

	private pushToolPart(toolId: string): void {
		if (!toolId || this.parts.some(p => p.kind === 'tool' && p.toolId === toolId)) { return; }
		this.parts.push({ kind: 'tool', toolId });
	}

	// Skills Hub (Phase 3): UI listeners for skills_hub_result frames. The
	// hub panel registers a listener per in-flight request; listener errors
	// are isolated so one broken panel never eats the frame dispatch.
	private readonly _hubListeners = new Set<(frame: { op: string; result: Record<string, unknown> }) => void>();

	sendSkillsHubOp(op: string, extra?: Record<string, unknown>): void {
		this.send({ type: 'skills_hub_op', session_id: this.sessionId, op, ...(extra ?? {}) } as CrusorClientMethod);
	}

	onSkillsHubResult(listener: (frame: { op: string; result: Record<string, unknown> }) => void): IDisposable {
		this._hubListeners.add(listener);
		return toDisposable(() => this._hubListeners.delete(listener));
	}

	/**
	 * One skills_hub_op request → its result dict (the Manager Skills tab's
	 * bridge). Same contract the palette's hubRequest uses: one matching
	 * frame, bounded wait, hard failure named — the tab paints it inline
	 * instead of hanging on a silent panel. Palette flows are modal, so a
	 * same-op request from QuickPick and this method cannot race in practice;
	 * within this method the tab's parallel reads use distinct ops.
	 */
	private skillsHubOp(op: string, extra: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
		return new Promise((resolve, reject) => {
			let listener: IDisposable | undefined;
			const timer = setTimeout(() => {
				listener?.dispose();
				reject(new Error(`the engine did not answer the '${op}' request — fully restart CrusorAI so the bridge runs the current build.`));
			}, 12000);
			listener = this.onSkillsHubResult(frame => {
				if (frame.op !== op) { return; }
				clearTimeout(timer);
				listener?.dispose();
				resolve((frame.result ?? {}) as Record<string, unknown>);
			});
			// connector ops (probe / attach / detach) read and write the
			// WORKSPACE's .crusorai/mcp.json — the engine has no other way
			// to know which folder is open.
			this.sendSkillsHubOp(op, (op.startsWith('connector') || op === 'skill_create') ? { ...extra, workspace: this.workspacePath } : extra);
		});
	}

	private readonly _oneshotListeners = new Set<(frame: { template: string; text: string; error?: string }) => void>();

	sendOneshot(template: string, extra?: Record<string, unknown>): void {
		this.send({ type: 'oneshot', session_id: this.sessionId, template, ...(extra ?? {}) } as CrusorClientMethod);
	}

	onOneshotResult(listener: (frame: { template: string; text: string; error?: string }) => void): IDisposable {
		this._oneshotListeners.add(listener);
		return toDisposable(() => this._oneshotListeners.delete(listener));
	}

	private _emitOneshotResult(frame: { template: string; text: string; error?: string }): void {
		for (const listener of Array.from(this._oneshotListeners)) {
			try {
				listener(frame);
			} catch {
				// isolated on purpose
			}
		}
	}

	private _emitSkillsHubResult(frame: { op: string; result: Record<string, unknown> }): void {
		for (const listener of Array.from(this._hubListeners)) {
			try {
				listener(frame);
			} catch {
				// isolated on purpose — a broken listener must not break the chain
			}
		}
	}

	private send(frame: CrusorClientMethod): void {
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
		// Hermes parity: soft stall is 5min, but toolless greetings (no tools) should not wait 7min for hard kill.
		// Match Hermes's immediate `message.complete` settle: if no tools and we have text, fail fast (30s) instead of 7min.
		const _isGreeting = this.tools.size === 0 && this.assistantText.length > 0;
		this.hardWatchdog = window.setTimeout(() => {
			this.hardWatchdog = undefined;
			if (!this.running) { return; }
			this.running = false;
			this.cancelRequested = false;
			this.turnStartedAt = undefined;
			this.turnEndedAt = Date.now();
			// Hermes parity: greeting already answered — silent complete, not failed
			if (_isGreeting) {
				this.turnOutcome = 'completed';
				this.error = undefined;
				this.degraded = undefined;
			} else {
				this.turnOutcome = 'failed';
				this.error = 'The engine stopped responding — the turn was ended locally. The reply above is everything it produced; send another message to continue.';
			}
			this.stalled = undefined;
			this.llmStatus = undefined;
			this.clearStallWatchdog();
			this.render();
		}, _isGreeting ? 12 * 1000 : 7 * 60 * 1000);
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

	private acceptFrame(frame: CrusorServerEvent): void {
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
				if (typeof candidate?.type === 'string') { this.acceptFrame(event as CrusorServerEvent); }
			}
			return;
		}
		if (frame.type === 'host_tool_request') {
			void this.invokeHostCapability(frame);
			return;
		}
		// Pending questions are session-TREE state (OpenCode): a child's
		// question must surface in any open view of its ancestors, so every
		// ask is tracked by request id BEFORE foreign routing can drop it to
		// a list-row chip. Settle (the ask tool's own tool_call_end) and turn
		// end retire the ask wherever it lives; buildModel re-derives what
		// this view shows from the map on every render.
		if (frame.type === 'clarify_request') {
			const asking = typeof frame.session_id === 'string' && frame.session_id ? frame.session_id : (this.sessionId ?? 'default');
			this.clarifies.set(frame.request_id, {
				sessionId: asking,
				requestId: frame.request_id,
				title: frame.title ?? '',
				// A tool id equal to the request id is no tool id at all
				// (older bridges stamped the queue item's id there): the
				// renderer matches a pending ask to its transcript tool
				// call by this field, and a request id can never match —
				// the ask painted read-only forever (field 2026-10-16).
				toolId: frame.tool_id && frame.tool_id !== frame.request_id ? frame.tool_id : undefined,
				questions: frame.questions,
			});
		} else if (frame.type === 'safety_request') {
			// Same tree rule as questions: a child's approval must surface in
			// an open ancestor view, not stall invisibly behind a row chip.
			const asking = typeof frame.session_id === 'string' && frame.session_id ? frame.session_id : (this.sessionId ?? 'default');
			this.approvals.set(frame.tool_id, {
				sessionId: asking,
				toolId: frame.tool_id,
				name: frame.name,
				diff: frame.diff,
				warning: typeof frame.warning === 'string' ? frame.warning : undefined,
			});
		} else if (frame.type === 'tool_call_end') {
			for (const [requestId, entry] of this.clarifies) {
				if (entry.toolId && entry.toolId === frame.tool_id) { this.clarifies.delete(requestId); }
			}
			this.approvals.delete(frame.tool_id);
		}
		// A background turn's traffic routes to its list row, never the live transcript.
		const foreignId = this.foreignSessionId(frame);
		if ((frame.type === 'turn_done' || frame.type === 'turn_failed') && foreignId) {
			this.clearClarifiesFor(foreignId);
			this.clearApprovalsFor(foreignId);
		}
		if (foreignId) {
			this.syncStashFrame(foreignId, frame);
			switch (frame.type) {
				case 'turn_started': case 'token': case 'token_retract': case 'reasoning': case 'plan_updated':
				case 'tool_call_start': case 'tool_call_args': case 'tool_call_end': case 'tool_output': case 'safety_request': case 'clarify_request':
				case 'todo_updated': case 'verification_updated': case 'telemetry': case 'turn_done':
				case 'turn_failed': case 'voice_text': case 'llm.request': case 'llm.response':
				case 'context_status': case 'runtime_degraded':
					this.noteForeignFrame(foreignId, frame);
					return;
			}
		}
		// First live frame for the VIEWED child: adopt its checkpoint-painted
		// tail turn into the live lane so the stream continues it in place.
		if (frame.type === 'token' || frame.type === 'token_retract' || frame.type === 'reasoning'
			|| frame.type === 'tool_call_start' || frame.type === 'tool_call_args' || frame.type === 'tool_output' || frame.type === 'plan_updated') {
			this.adoptHistoryTailIfLive();
		}
		if (frame.type === 'session_info') {
			// Durable list refresh: a session_list reply carries `sessions` and NO session_id --
			// it notes every row and leaves the active session alone. (An unconditional adopt
			// here used to wipe the active id on every list refresh.)
			if (frame.sessions) {
				for (const row of frame.sessions) { this.noteEngineRow(row); }
			}
			if (frame.session) { this.noteEngineRow(frame.session); }
			// Stop ack from the bridge: another surface (or a queued cancel)
			// may have pulled the brake — this pane's button must agree.
			if (typeof frame.cancel_requested === 'boolean') { this.cancelRequested = frame.cancel_requested; }
			// Live auto-title push (Hermes session.title parity): the engine titler runs
			// async after the turn and emits the same ack shape as rename. A titled row
			// is noted directly — even a foreign one — so no list refetch is needed.
			if (frame.session_id && frame.renamed === true && typeof frame.title === 'string'
				&& !frame.sessions && !frame.session && !frame.resumed) {
				this.noteEngineRow({ session_id: frame.session_id, id: frame.session_id, title: frame.title });
				this.render();
				return;
			}
			if (!frame.session_id) {
				this.render();
				return;
			}
			// A late ack for a session we already left (queued/cancel/steer/...) notes its row
			// above; the surface stays where the user put it.
			if (foreignId) {
				this.render();
				return;
			}
			const previousSessionId = this.sessionId;
			this.sessionId = frame.session_id;
			// A resume can resolve to a lineage tip that is NOT the requested id (fork
			// children): the surface binds the tip, because that is what the user now sees.
			// NEVER for a delegated child the user explicitly opened: its transcript
			// would keep painting under the parent's identity — live composer, no
			// back row, "where am i this is not parent screen" (field 2026-10-16).
			const openedIsDelegateChild = !!previousSessionId && (this.childParentId !== undefined
				|| this.parentMap.has(previousSessionId) || previousSessionId.startsWith('sub-')
				|| [...this.subAgents.values()].some(entry => (entry.childThreadId ?? entry.id) === previousSessionId));
			if (frame.resumed && frame.resolved_session_id && frame.resolved_session_id !== this.sessionId && !openedIsDelegateChild) {
				this.sessionId = frame.resolved_session_id;
				this.setRememberedSession(this.sessionId);
			}
			if (typeof frame.build === 'string' && frame.build) { this.engineBuild = frame.build; }
			if (previousSessionId !== frame.session_id) { this.publishHostCapabilities(frame.session_id); }
			if (typeof frame.cancel_requested === 'boolean') { this.cancelRequested = frame.cancel_requested; }
			// OpenCode parity: restore subagents + parentMap on resume (env path aware)
			for (const row of (frame as any).subagents ?? []) {
				const sid = row.subagent_id ?? row.child_thread_id;
				if (!sid) continue;
				const childId = row.child_thread_id ?? sid;
				const parentId = row.parent_session_id ?? this.sessionId;
				if (childId && parentId) this.parentMap.set(childId, parentId);
				this.subAgents.set(sid, {
					id: sid,
					state: subAgentState(row.state),
					goal: row.goal,
					description: row.description,
					mode: row.mode,
					duration: row.duration,
					parentSessionId: parentId,
					childThreadId: childId,
					background: row.background,
					toolCalls: row.tool_calls,
					agentName: row.agent_name,
					result: row.result,
				} as any);
			}
			if (this.sessionId && this.parentMap.has(this.sessionId)) {
				this.childParentId = this.parentMap.get(this.sessionId);
			}
			for (const event of frame.events ?? []) {
				const candidate = valueRecord(event);
				if (typeof candidate?.type === 'string') { this.acceptFrame(event as CrusorServerEvent); }
			}
			if (this.pendingPrompt) {
				const prompt = this.pendingPrompt;
				this.pendingPrompt = undefined;
				this.startTurn(prompt);
				return;
			}
			// Rename/pin/archive acks re-sync the list so the row shows the new truth.
			if (frame.renamed || frame.pin_updated || frame.archive_updated) { this.requestSessionList(); }
		} else if (frame.type === 'turn_started') {
			this.sessionId = frame.session_id;
			this.setRememberedSession(frame.session_id);
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

			this.hadProviderAttempt = false;
			this.clearStallWatchdog();
			this.armStallWatchdog();
		} else if (frame.type === 'token') {
			this.assistantText += frame.text;
			this.appendTextPart(frame.text);
		} else if (frame.type === 'token_retract') {
			this.retractText(frame.chars);
			// Reasoning is preserved so the thinking block stays visible in
			// the transcript after the turn completes.
		} else if (frame.type === 'reasoning') {
			// Hermes pattern: reasoning parts accumulate as an array.
			const repaired = separateGluedReasoningBlocks(frame.text);
			const tail = this.reasoningParts[this.reasoningParts.length - 1];
			if (tail && repaired.startsWith(tail.text)) {
				tail.text = repaired;
			} else if (tail && !tail.completedAt) {
				tail.text = tail.text + repaired;
			} else {
				// New reasoning block: record its index in the parts timeline so the
				// renderer knows exactly where in the turn it occurred (Hermes pattern:
				// a single ordered parts array for reasoning, text, and tools).
				const reasoningIndex = this.reasoningParts.length;
				this.reasoningParts.push({ text: repaired });
				this.parts.push({ kind: 'reasoning', reasoningIndex });
			}
			this.reasoningPending = true;
		} else if (frame.type === 'plan_updated') {
			this.plan = frame.steps.map(planStepView);
		} else if (frame.type === 'tool_call_start') {
			// Seal any open reasoning part before the tool call
			const openReasoning = this.reasoningParts[this.reasoningParts.length - 1];
			if (openReasoning && !openReasoning.completedAt) {
				openReasoning.completedAt = Date.now();
			}
			if (!this.tools.has(frame.tool_id)) {
				// Rebind a streamed preview whose provider never sent the
				// call id in its chunks (it streamed as stream-<index>):
				// the durable start adopts that card instead of doubling it.
				const orphanIndex = this.parts.findIndex(p => p.kind === 'tool' && p.toolId.startsWith('stream-')
					&& this.tools.get(p.toolId)?.name === frame.name
					&& this.tools.get(p.toolId)?.state === 'running');
				if (orphanIndex >= 0) {
					const orphanId = (this.parts[orphanIndex] as { toolId: string }).toolId;
					this.tools.delete(orphanId);
					this.parts[orphanIndex] = { kind: 'tool', toolId: frame.tool_id };
				}
			}
			this.tools.set(frame.tool_id, { id: frame.tool_id, name: frame.name, arguments: frame.arguments, state: 'running' });
			this.pushToolPart(frame.tool_id);
		} else if (frame.type === 'tool_call_args') {
			// Streamed tool-call arguments (OpenCode renders edit/write
			// cards from the streaming input): the card is BORN with the
			// first fragment and its content grows; the durable
			// tool_call_start above lands later with complete arguments.
			const existing = this.tools.get(frame.tool_id);
			if (existing) {
				if (existing.state === 'running' || existing.state === 'queued') {
					this.tools.set(frame.tool_id, { ...existing, arguments: frame.arguments ?? existing.arguments });
				}
			} else if (frame.name) {
				const openReasoning = this.reasoningParts[this.reasoningParts.length - 1];
				if (openReasoning && !openReasoning.completedAt) {
					openReasoning.completedAt = Date.now();
				}
				this.tools.set(frame.tool_id, { id: frame.tool_id, name: frame.name, arguments: frame.arguments, state: 'running' });
				this.pushToolPart(frame.tool_id);
			}
		} else if (frame.type === 'tool_output') {
			// Live shell output (OpenCode cursor-tail discipline): append to
			// the running tool's result, keep only the last 64 KB. The
			// tool_call_end frame that follows replaces this preview with
			// the durable full result.
			const existing = this.tools.get(frame.tool_id);
			if (existing && frame.text) {
				const prior = typeof existing.result === 'string' ? existing.result : '';
				this.tools.set(frame.tool_id, { ...existing, result: (prior + frame.text).slice(-65_536) });
			}
		} else if (frame.type === 'tool_call_end') {
			let existing = this.tools.get(frame.tool_id);
			if (!existing && frame.name) {
				// A child on the invoke path never receives a durable
				// tool_call_start, so a streamed preview accumulated
				// under a stream-<index> id (the provider had not sent
				// the call id in its chunks yet) can only be joined
				// here: adopt the orphan's part and arguments instead
				// of birthing a nameless duplicate beside it.
				const orphanIndex = this.parts.findIndex(p => p.kind === 'tool' && p.toolId.startsWith('stream-')
					&& this.tools.get(p.toolId)?.name === frame.name
					&& this.tools.get(p.toolId)?.state === 'running');
				if (orphanIndex >= 0) {
					const orphanId = (this.parts[orphanIndex] as { toolId: string }).toolId;
					existing = this.tools.get(orphanId);
					this.tools.delete(orphanId);
					this.parts[orphanIndex] = { kind: 'tool', toolId: frame.tool_id };
				}
			}
			const result = valueRecord(frame.result);
			this.tools.set(frame.tool_id, {
				id: frame.tool_id,
				// The end frame is durable and always carries the true
				// name: a row born here (children get no start frame)
				// must not be christened 'unknown' (field 2026-10-16:
				// the child's cards rendered "Unknown").
				name: existing?.name && existing.name !== 'unknown' ? existing.name : (frame.name ?? existing?.name ?? 'unknown'),
				arguments: existing?.arguments,
				result: frame.result,
				state: toolState(frame.status),
				duration: typeof result?.duration === 'string' ? result.duration : typeof result?.duration_ms === 'number' ? `${result.duration_ms}ms` : undefined,
			});
			// An end can be a tool's first frame entirely: the card
			// still needs its place in the timeline.
			this.pushToolPart(frame.tool_id);
		} else if (frame.type === 'safety_request') {
			const existing = this.tools.get(frame.tool_id);
			this.tools.set(frame.tool_id, { id: frame.tool_id, name: frame.name, arguments: existing?.arguments ?? frame.arguments ?? frame.diff, result: existing?.result, state: 'approval' });
			// An approval can arrive without a prior start frame; the card must
			// still have a place in the timeline. (The pending entry itself was
			// tracked tree-wide in the pre-routing hook above.)
			this.pushToolPart(frame.tool_id);
			// 1: Show in editor automatically like Copilot ChatEditingCodeEditorIntegration
			// (viewZones + diffDecorations on live file) — don't wait for user to click Review.
			// Best-effort: if diff has inline text, open inline diff preview.
			try { void this.openDiff(frame.tool_id); } catch { /* best effort */ }
		} else if (frame.type === 'clarify_request') {
			// Hermes ask-tool card: the batch of questions rides its own frame
			// (args alone can't drive the form — no qids to respond with). The
			// pending entry itself was tracked tree-wide in the pre-routing
			// hook above; here the viewed session only needs the tool's place
			// in its own transcript lane.
			if (frame.tool_id) { this.pushToolPart(frame.tool_id); }
		} else if (frame.type === 'todo_updated') {
			// Hermes todo panel: {todos, revision} reconciles atomically; keep
			// the revision even when the list went empty (the unpin decision).
			const items: CrusorTodoItem[] = [];
			for (const raw of frame.todos) {
				const row = raw as CrusorTodoItem;
				if (row && typeof row.id === 'string' && typeof row.content === 'string') {
					items.push({ id: row.id, content: row.content, status: row.status, ...(row.parent ? { parent: row.parent } : {}) });
				}
			}
			this.todos = items;
			this.todoRevision = frame.revision;
		} else if (frame.type === 'subagent_updated') {
			const { subagentId, childId, parentId } = this.mergeSubagentRecord(this.subAgents, frame, this.sessionId);
			// Never self-parent: an unknown-id status reply echoes the queried id as both
			// child and parent, which would misdetect a normal session as a child.
			if (childId && parentId && childId !== parentId) {
				this.parentMap.set(childId, parentId);
			}
			// Detect if current session is child
			if (this.sessionId && this.parentMap.has(this.sessionId)) {
				this.childParentId = this.parentMap.get(this.sessionId);
			}
			// The open session IS this child: its steps just moved —
			// refresh the transcript snapshot and re-decide liveness.
			if (subagentId === this.sessionId || childId === this.sessionId) {
				this.requestChildSnapshot();
				this.syncChildLivePoll();
			}
		} else if ((frame as any).type === 'skills_hub_result') {
			this._emitSkillsHubResult(frame as any);

		} else if ((frame as any).type === 'oneshot_result') {
			this._emitOneshotResult(frame as any);
		} else if ((frame as any).type === 'subagent_list') {
			// OpenCode parity: list children for parent
			for (const row of (frame as any).subagents ?? []) {
				const sid = row.subagent_id ?? row.child_thread_id;
				if (!sid) continue;
				const childId = row.child_thread_id ?? sid;
				const parentId = row.parent_session_id ?? this.sessionId;
				if (childId && parentId) this.parentMap.set(childId, parentId);
				this.subAgents.set(sid, {
					id: sid,
					state: subAgentState(row.state),
					goal: row.goal,
					description: row.description,
					mode: row.mode,
					duration: row.duration,
					parentSessionId: parentId,
					childThreadId: childId,
					background: row.background,
					toolCalls: row.tool_calls,
					agentName: row.agent_name,
					result: row.result,
				} as any);
			}
		} else if ((frame as any).type === 'subagent_background_completed') {
			// A background child finished: update its RECORD only. The
			// child's output is never appended to this session's voice —
			// that injection merged the child into the parent and showed
			// its answer twice (field 2026-10-16). The parent model
			// learns the result through the engine's own channel; here
			// the card simply reads Completed.
			const subId = (frame as any).subagent_id ?? (frame as any).child_thread_id;
			if (subId) {
				const existing = this.subAgents.get(subId);
				if (existing && existing.state !== 'completed') {
					this.subAgents.set(subId, { ...existing, state: 'completed' as const });
				}
			}
		} else if (frame.type === 'verification_updated') {
			this.verification = frame.status;
		} else if (frame.type === 'telemetry') {
			this.telemetry = { ...this.telemetry, input: frame.input, output: frame.output, cache: frame.cache, cost: frame.cost };
		} else if (frame.type === 'turn_done') {
			this.running = false;
			if ((frame as { cancelled?: boolean }).cancelled === true) {
				this.interrupt = this.stampInterrupt();
			}
			this.cancelRequested = false;
			this.turnStartedAt = undefined;
			this.turnEndedAt = Date.now();
			// A turn ended with an unanswered clarify: the blocking layer has
			// already timed the wait out — never leave a dead interactive card.
			this.clearClarifiesFor(this.sessionId);
			this.clearApprovalsFor(this.sessionId);
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
			// Seal any open reasoning part
			const openR = this.reasoningParts[this.reasoningParts.length - 1];
			if (openR && !openR.completedAt) { openR.completedAt = Date.now(); }
			this.reasoningPending = false;
			this.compacting = undefined;
			this.contextStatus = undefined;
			this.llmStatus = undefined;
			this.llmHeads = undefined;
			this.degraded = undefined;
			this.clearStallWatchdog();
			// --- Crusor notification: Response Ready (founder request 2026-09-21) ---
			// Show a native workbench notification when the agent finishes, so a
			// user who switched windows still knows the task is done. Mirrors
			// Cursor/Copilot's "Agent finished" toast. Respects `crusorai.notifyOnComplete`.
			if (!frame.cancelled) {
				this.notifyResponseReady(frame.message);
			}
			// The finished turn minted the durable row's title and counts: re-sync the list.
			this.requestSessionList();
			this.settleAdoptedTurn();
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
			this.notifyResponseReady(frame.error, true);
			this.requestSessionList();
			this.settleAdoptedTurn();
		} else if (frame.type === 'voice_text') {
			this.voiceHeard = { ok: frame.ok, text: frame.text ?? '', error: frame.error };
		} else if (frame.type === 'llm.request') {
			this.llmStatus = { model: frame.model ?? '', attempt: frame.attempt ?? 1 };
			this.llmHeads = frame.messages;
			this.hadProviderAttempt = true;
		} else if (frame.type === 'llm.response') {
			this.llmStatus = undefined;
			this.llmHeads = undefined;
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
			// Greeting with no tools — scan budget is irrelevant, don't show yellow degraded bar
			if (frame.reason && frame.reason.includes('scan budget') && this.tools.size === 0) {
				// suppress
			} else {
				this.degraded = frame.reason;
			}
		} else if (frame.type === 'session_messages') {
			// Transcript hydration for the session we most recently opened. A late page for a
			// session the user already left is dropped -- painting it would splice another
			// session's history under the active transcript.
			const forId = frame.requested_session_id ?? frame.session_id;
			if (forId !== this.pendingHydration && forId !== this.sessionId) { return; }
			// The viewed child is streaming live now: its stream outruns any
			// snapshot, and hydrating would replace the adopted tail turn
			// with a checkpoint copy and then stream over it twice.
			if (this.childLiveAdopted && forId === this.sessionId) { this.childRefreshInFlight = false; return; }
			if (this.childRefreshInFlight) {
				this.childRefreshInFlight = false;
				// An in-flight checkpoint read can come back empty mid-run;
				// a REFRESH keeps the painted transcript in that case.
				if (!frame.messages.length && this.history.length) { return; }
			}
			this.pendingHydration = undefined;
			this.hydrateTranscript(frame.messages);
			if (this.healAfterRestore && forId === this.sessionId) {
				// The settled turn now lives in history; clear the live-turn
				// fields so it cannot paint twice (once per lane).
				this.healAfterRestore = false;
				this.healRequested = false;
				this.userMessage = undefined;
				this.assistantText = '';
				this.parts = [];
				this.reasoningParts = [];
				this.reasoningPending = false;
				this.tools.clear();
			}
			return;
		} else if (frame.type === 'session_deleted') {
			const deletedId = frame.session_id;
			this.sessionStore.forget(deletedId);
			if (deletedId === this.sessionId) {
				// Our own session was deleted (here or elsewhere): land on a blank surface,
				// not a ghost.
				this.newSession();
			}
		} else if (frame.type === 'error') {
			this.error = frame.message;
		}
		// Back-from-child heal: the restored parent turn has settled;
		// rebuild it once from its checkpoint so tokens streamed while
		// the user watched the child are not silently missing.
		if (!this.running && this.healAfterRestore && !this.healRequested && this.sessionId) {
			const workspace = this.workspacePath;
			if (workspace) {
				this.healRequested = true;
				this.send({ type: 'session_messages', session_id: this.sessionId, workspace, limit: 120, order: 'latest' });
			}
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
			const approval = this.approvals.get(toolId)?.diff;
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
				resource ??= stringField(source, ['resource', 'file_path', 'path', 'relative_path']);
				if (originalText === undefined && value && 'old_text' in value && (typeof value.old_text === 'string' || value.old_text === null)) {
					originalText = typeof value.old_text === 'string' ? value.old_text : '';
				}
				if (modifiedText === undefined && typeof value?.new_text === 'string') { modifiedText = value.new_text; }
				if (modifiedText === undefined && typeof value?.content === 'string') { modifiedText = value.content; }
			}
			const label = `Crusor: ${tool?.name ?? 'proposed change'}`;
			if (originalText === undefined && modifiedText !== undefined && resource) {
				originalText = '';
			}
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

	private readonly syntaxColorCache = new Map<string, CrusorAISyntaxColors>();

	/**
	 * The active editor theme's real token colours for the file
	 * viewers: resolved through IColorTheme.getTokenStyleMetadata —
	 * the same machinery the editor itself paints with — and cached
	 * per language bucket until the theme changes.
	 */
	private syntaxColors(language: string): CrusorAISyntaxColors | undefined {
		const cached = this.syntaxColorCache.get(language);
		if (cached) { return cached; }
		try {
			const theme = this.themeService.getColorTheme();
			const editorLanguage = ({ python: 'python', hash: 'shellscript', json: 'json', html: 'html', markdown: 'markdown' } as Record<string, string>)[language] ?? 'typescript';
			const pick = (type: string, fallback?: string): string | undefined => {
				const style = theme.getTokenStyleMetadata(type, [], editorLanguage)
					?? (fallback ? theme.getTokenStyleMetadata(fallback, [], editorLanguage) : undefined);
				return style?.foreground !== undefined ? theme.tokenColorMap[style.foreground] : undefined;
			};
			const colors: CrusorAISyntaxColors = {
				comment: pick('comment'),
				string: pick('string'),
				keyword: pick('keyword'),
				number: pick('number'),
				type: pick('type', 'class'),
			};
			this.syntaxColorCache.set(language, colors);
			return colors;
		} catch (error) {
			return undefined;
		}
	}

	private resourceBrowserSrc(resource: string): string | undefined {
		// file:// is not loadable from the workbench DOM; FileAccess translates
		// it to the scheme the renderer may fetch (same path resolution as
		// revealFile — Windows drives, schemes, workspace-relative).
		try {
			return FileAccess.uriToBrowserUri(this.resourceUri(resource)).toString(true);
		} catch (error) {
			return undefined;
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

	private notifyResponseReady(detail?: string, isError = false): void {
		try {
			if (this.configurationService.getValue<boolean>('crusorai.notifyOnComplete') === false) { return; }
			const msg = isError ? 'Crusor — task ended with an issue' : 'Response Ready — Crusor';
			const detailLine = detail ? String(detail).split('\n')[0].slice(0, 160) : '';
			this.notificationService.notify({
				severity: isError ? Severity.Warning : Severity.Info,
				message: msg,
				source: detailLine ? `${detailLine}` : 'Crusor Agent finished',
				actions: {
					primary: [{
						id: CrusorAICommandId.Focus,
						label: 'Open Crusor',
						tooltip: 'Focus Crusor Agent',
						enabled: true,
						run: () => { void this.commandService.executeCommand(CrusorAICommandId.Focus); }
					}]
				}
			} as any);
		} catch { /* notification must never break turn */ }
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
		// Git-bash drive notation (field 2026-09-10: the model works in the
		// bash shell, so tool args and card rows carry `/d/TestCrusorAI/...`;
		// URI.file() reads that as a rootless path on the current drive ->
		// "The editor could not be opened because the file was not found"
		// while the file exists — the owner clicked the changed-file row and
		// got the dead editor). Convert to the real drive path first.
		const gitBash = /^\/([a-z])\/(.*)$/i.exec(resource);
		if (gitBash) { return URI.file(`${gitBash[1].toUpperCase()}:/${gitBash[2]}`); }
		if (/^(?:[a-z]:[\\/]|[\\/])/i.test(resource)) { return URI.file(resource); }
		if (/^[a-z][a-z0-9+.-]*:/i.test(resource)) { return URI.parse(resource); }
		return folder ? URI.joinPath(folder.uri, resource) : URI.file(resource);
	}
}
