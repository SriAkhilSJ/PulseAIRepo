/*---------------------------------------------------------------------------------------------
 * One shared event model and host adapter for the compact Agent view and Crusor Manager.
 *--------------------------------------------------------------------------------------------*/
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
import { Disposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { FileAccess } from '../../../../base/common/network.js';
import { URI } from '../../../../base/common/uri.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { IAuxiliaryWindowService } from '../../../services/auxiliaryWindow/browser/auxiliaryWindowService.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { ICrusorAIEngineService, CrusorAIEngineSetupError } from '../common/crusorAIEngineService.js';
import { CRUSOR_AI_WORKBENCH_CAPABILITIES } from '../common/crusorAIWorkbenchCapabilities.js';
import { separateGluedReasoningBlocks } from './crusorAIReasoningBlocks.js';
import { ICrusorAISessionStore } from '../common/crusorAISessionStore.js';
import { crusorFactsFromEngineRow, crusorSessionLabel, crusorSessionLabelIsFallback, crusorSessionRows, crusorSessionStatusName } from '../common/crusorAISessionProjection.js';
import { ICrusorAIWorkbenchService } from '../common/crusorAIWorkbenchService.js';
import { mountCrusorAIRenderer, } from './crusorAIRenderer.js';
function valueRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value) ? value : undefined;
}
function toolState(status) {
    const value = status.toLowerCase();
    if (value.includes('fail') || value.includes('error') || value.includes('denied') || value.includes('cancel')) {
        return 'failed';
    }
    if (value.includes('pass') || value.includes('success') || value.includes('complete') || value === 'ok') {
        return 'passed';
    }
    if (value.includes('approval') || value.includes('permission')) {
        return 'approval';
    }
    if (value.includes('run') || value.includes('start') || value.includes('progress')) {
        return 'running';
    }
    return 'queued';
}
function planText(step) {
    if (typeof step === 'string') {
        return step;
    }
    const record = valueRecord(step);
    for (const key of ['title', 'text', 'description', 'goal']) {
        if (typeof record?.[key] === 'string') {
            return record[key];
        }
    }
    return 'Plan step';
}
const PLAN_STATUSES = ['pending', 'in_progress', 'completed', 'failed'];
function planStepView(step) {
    const raw = (typeof step === 'object' && step !== null)
        ? step.status
        : undefined;
    const status = typeof raw === 'string' ? raw : '';
    return {
        text: planText(step),
        status: (PLAN_STATUSES.includes(status)
            ? status
            : 'pending'),
    };
}
function stringField(source, keys) {
    const value = valueRecord(source);
    for (const key of keys) {
        if (typeof value?.[key] === 'string' && value[key]) {
            return value[key];
        }
    }
    return undefined;
}
let CrusorAIRendererService = class CrusorAIRendererService extends Disposable {
    constructor(engineService, workbenchService, workspaceContextService, configurationService, commandService, clipboardService, auxiliaryWindowService, sessionStore, notificationService) {
        super();
        this.engineService = engineService;
        this.workbenchService = workbenchService;
        this.workspaceContextService = workspaceContextService;
        this.configurationService = configurationService;
        this.commandService = commandService;
        this.clipboardService = clipboardService;
        this.auxiliaryWindowService = auxiliaryWindowService;
        this.sessionStore = sessionStore;
        this.notificationService = notificationService;
        this.mounts = new Set();
        this.tools = new Map();
        this.seenEventIds = new Set();
        this.eventIdOrder = [];
        this.restartAttempts = 0;
        this.draft = '';
        this.mode = 'agent';
        /** Think level ('' = inherit the engine's REASONING_EFFORT env default). */
        this.reasoningEffort = '';
        this.running = false;
        this.cancelRequested = false;
        /** Live hermes todo_list state, reconciled atomically on {todos, revision}. */
        this.todos = [];
        this.todoRevision = 0;
        this.turnOutcome = 'idle';
        this.assistantText = '';
        /**
         * Ordered timeline (hermes message.parts): one entry per text segment and
         * tool call, in arrival order. `assistantText` stays the concatenated
         * string for copy/inspector; the TRANSCRIPT paints from `parts` so tools
         * sit where they happened and the final answer lands last. Cleared at
         * turn boundaries with the rest of the turn state.
         */
        this.parts = [];
        /** Reasoning parts seen this turn — each LLM call that produces reasoning adds a new part. */
        this.reasoningParts = [];
        this.reasoningPending = false;
        this.subAgents = new Map();
        /** OpenCode parity: parentMap child_thread_id -> parent_session_id for navigation */
        this.parentMap = new Map();
        this.plan = [];
        this.telemetry = {};
        this.engineSetupError = false;
        /** A provider attempt has been named this turn (llm.request seen).
         * Reasoning arriving AFTER this is real model thought — a buffered
         * endpoint delivers it as a single whole-text frame — while reasoning
         * before any provider attempt is the legacy liveness dress-up. */
        this.hadProviderAttempt = false;
        this.history = [];
        this.host = {
            setDraft: value => { this.draft = value; },
            setMode: mode => {
                if (this.running || this.mode === mode) {
                    return;
                }
                this.mode = mode;
                this.render();
            },
            // hermes reasoning-effort: a manual pick sticks for the session; it
            // rides the NEXT prompt frame, so a mid-turn change needs no cancel.
            setReasoningEffort: value => {
                if (this.reasoningEffort === value) {
                    return;
                }
                this.reasoningEffort = value;
                this.render();
            },
            submitPrompt: text => { void this.submitPrompt(text); },
            cancel: () => {
                if (!this.running || this.cancelRequested) {
                    return;
                }
                this.cancelRequested = true;
                this.send({ type: 'cancel', session_id: this.sessionId });
                this.render();
            },
            steer: text => { this.send({ type: 'steer', session_id: this.sessionId, text }); this.draft = ''; this.render(); },
            replyToSafety: (toolId, approved, alwaysAllow) => {
                this.send({ type: 'safety_reply', session_id: this.sessionId, tool_id: toolId, approved, always_allow: alwaysAllow });
                const tool = this.tools.get(toolId);
                if (tool) {
                    this.tools.set(toolId, { ...tool, state: approved ? 'running' : 'failed' });
                }
                this.approval = undefined;
                this.render();
            },
            replyToClarify: (requestId, answers, timedOut) => {
                // The clarify card rides ONE batch reply (hermes #18450): answers per
                // qid; an explicit Skip resolves the batch empty (deliberate, not a
                // timeout). The pending card stays up in its submitting state until
                // the clarify tool_call_end swaps in the settled Q&A.
                this.send({ type: 'clarify_reply', session_id: this.sessionId, request_id: requestId, answers, timed_out: timedOut });
                this.render();
            },
            openDiff: toolId => { void this.openDiff(toolId); },
            revealFile: resource => { void this.revealFile(resource); },
            resourceSrc: resource => this.resourceBrowserSrc(resource),
            restoreCheckpoint: checkpointHash => {
                const workspace = this.workspacePath;
                if (workspace) {
                    this.send({ type: 'checkpoint_restore', session_id: this.sessionId, workspace, checkpoint_hash: checkpointHash });
                }
            },
            retryEngine: () => {
                if (this.restartTimer !== undefined) {
                    clearTimeout(this.restartTimer);
                    this.restartTimer = undefined;
                }
                this.restartAttempts = 0;
                // Clear the fault the moment a manual retry starts: leaving it up claims the engine is still
                // broken while it is being restarted, and the row's own action would look like a no-op.
                this.engineFault = undefined;
                void this.ensureEngine();
            },
            selectWorkspace: uri => this.selectWorkspace(uri),
            openFolder: () => { void this.commandService.executeCommand('workbench.action.files.openFolder'); },
            openEngineSettings: () => { void this.commandService.executeCommand("crusorai.openSettings" /* CrusorAICommandId.OpenSettings */); },
            openManager: () => { this.openManagerWindow(); },
            copyToClipboard: text => {
                // Real clipboard (field: navigator.clipboard.writeText is
                // permission-blocked inside the webview). The workbench service
                // owns the privileged path; never let clipboard trouble throw.
                try {
                    this.clipboardService.writeText(text);
                }
                catch { /* best effort */ }
            },
            navigateToSession: (sessionId) => { this.navigateToSession(sessionId); },
            newSession: () => { this.newSession(); },
            isChildSession: () => !!(this.childParentId || (this.sessionId && (this.sessionId.startsWith('sub-') || this.parentMap.has(this.sessionId)))),
        };
        this._register(this.engineService.onDidChangeState(state => {
            if (state === "ready" /* CrusorAIEngineState.Ready */) {
                this.restartAttempts = 0;
                this.engineFault = undefined;
            }
            else if (state === "crashed" /* CrusorAIEngineState.Crashed */ || state === "degraded" /* CrusorAIEngineState.Degraded */) {
                // The only trace of a dying sidecar used to be a log line: the process exit is reported by
                // the engine service, `scheduleRestart` swallows exhaustion, and a turn in flight never
                // receives turn_done -- so the panel kept painting a live run that had no engine behind it.
                // A setup failure already has its own actionable row, so it is not overwritten here.
                if (!this.engineSetupError) {
                    this.engineFault = state === "crashed" /* CrusorAIEngineState.Crashed */
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
        this._register(toDisposable(() => {
            if (this.renderFrame !== undefined) {
                cancelAnimationFrame(this.renderFrame);
            }
            if (this.restartTimer !== undefined) {
                clearTimeout(this.restartTimer);
            }
        }));
    }
    mount(root /* HTMLElement */, surface) {
        const mount = mountCrusorAIRenderer(root, surface, this.host);
        this.mounts.add(mount);
        mount.update(this.model);
        if (this.configurationService.getValue('crusorai.autoStart') !== false) {
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
    get sessionFolder() {
        const folders = this.workspaceContextService.getWorkspace().folders;
        if (folders.length === 0) {
            return undefined;
        }
        if (folders.length === 1) {
            return folders[0];
        }
        if (this.selectedWorkspaceUri) {
            const selected = folders.find(folder => folder.uri.toString() === this.selectedWorkspaceUri?.toString());
            if (selected) {
                return selected;
            }
            this.selectedWorkspaceUri = undefined;
        }
        return undefined;
    }
    get workspacePath() {
        return this.sessionFolder?.uri.fsPath;
    }
    get workspaceLabel() {
        return this.sessionFolder?.name ?? 'Local workspace';
    }
    get workspaceFolderCount() {
        return this.workspaceContextService.getWorkspace().folders.length;
    }
    get workspaceChoices() {
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
    resetSessionState() {
        this.sessionId = undefined;
        this.running = false;
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
        this.approval = undefined;
        this.clarify = undefined;
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
        this.clearStallWatchdog();
    }
    selectWorkspace(uri) {
        const folders = this.workspaceContextService.getWorkspace().folders;
        const matched = folders.find(folder => folder.uri.toString() === uri);
        if (!matched) {
            return;
        }
        const changed = this.selectedWorkspaceUri?.toString() !== uri;
        this.selectedWorkspaceUri = matched.uri;
        if (changed) {
            // Retain the selection for the SESSION; a folder switch resets the
            // session binding so frames always carry the same workspace.
            this.resetSessionState();
        }
        this.render();
    }
    get capabilitySummary() {
        const values = this.workbenchService.getCapabilities();
        return {
            available: values.filter(value => value.availability === 'available').length,
            blocked: values.filter(value => value.availability === 'blocked').length,
            total: values.length,
        };
    }
    get model() {
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
            reasoningEffort: this.reasoningEffort || undefined,
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
            isChild: !!(this.childParentId || (this.sessionId && (this.sessionId.startsWith('sub-') || this.parentMap.has(this.sessionId)))),
            parentSessionId: this.childParentId ?? (this.sessionId ? this.parentMap.get(this.sessionId) : undefined),
            parentMap: new Map(this.parentMap),
            subAgentGoal: this.currentSubAgentGoal(),
            parentTitle: this.currentParentTitle(),
            approval: this.approval,
            clarify: this.clarify,
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
                retrying: this.restartAttempts < 3 && this.configurationService.getValue('crusorai.autoStart') !== false,
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
    navigateToSession(targetSessionId) {
        if (!targetSessionId || targetSessionId === this.sessionId) {
            return;
        }
        // Switching away mid-turn would strand the live run's frames on a surface that no
        // longer owns them. The user stops the run first; the list stays clickable between turns.
        if (this.running) {
            this.error = 'Stop the current run before switching sessions.';
            this.render();
            return;
        }
        const previousSessionId = this.sessionId;
        const previousChildParentId = this.childParentId;
        // Pre-reset reads: the reset wipes the map and the records. A plausible child
        // hydrates its own record below; the ownership reads gate the optimistic link.
        const targetLooksChild = targetSessionId.startsWith('sub-') || this.parentMap.has(targetSessionId);
        const targetKnownParent = this.parentMap.get(targetSessionId);
        const previousKnownParent = previousSessionId ? this.parentMap.get(previousSessionId) : undefined;
        const previousOwnsTarget = !!previousSessionId && [...this.subAgents.values()].some(record => (record.childThreadId === targetSessionId || record.id === targetSessionId)
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
        this.render();
    }
    /**
     * Hermes "New Session": a blank surface with NO session id. The id is minted by the engine
     * on the next prompt (session_create), so a draft the user abandons leaves no row behind.
     * While a turn runs the surface is occupied -- stranding a live turn's frames is worse
     * than refusing.
     */
    newSession() {
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
    openSession(sessionId) {
        this.navigateToSession(sessionId);
    }
    /**
     * This session's own delegated goal when it is a sub-agent child: the record whose
     * child thread is the active session. The child header paints this — never a hardcoded
     * title (field 2026-09-28: every sub-agent view read "Main / Sub-agent").
     */
    currentSubAgentGoal() {
        if (!this.sessionId) {
            return undefined;
        }
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
    /** The active session's parent label from the store, for the child breadcrumb. */
    currentParentTitle() {
        const parentId = this.childParentId ?? (this.sessionId ? this.parentMap.get(this.sessionId) : undefined);
        if (!parentId) {
            return undefined;
        }
        return this.sessionStore.records().find(record => record.sessionId === parentId)?.label;
    }
    sessionRows() {
        const readState = new Map();
        for (const facts of this.sessionStore.records()) {
            const isRead = this.sessionStore.isRead(facts.sessionId);
            if (isRead !== undefined) {
                readState.set(facts.sessionId, isRead);
            }
        }
        return crusorSessionRows(this.sessionStore.records(), this.sessionId, Date.now(), readState);
    }
    /**
     * Called before the mount check: a session nobody has painted is still a session the user
     * ran. `changes` is left out on purpose until one diff counter is shared with the tool row --
     * a count of files nobody measured is worse in a list than an absent field.
     */
    noteSession() {
        if (!this.sessionId) {
            return;
        }
        // The label is the engine's created title (fixed, unique). Until it lands the row
        // renders the generic placeholder — the first message is NEVER captured as the
        // title (field 2026-09-28). A generic fallback is never sticky: the titler's
        // live push upgrades it exactly once.
        const previousLabel = this.sessionStore.records().find(record => record.sessionId === this.sessionId)?.label;
        const facts = {
            sessionId: this.sessionId,
            label: previousLabel && !crusorSessionLabelIsFallback(previousLabel) ? previousLabel : crusorSessionLabel(undefined, this.sessionId),
            workspaceLabel: this.workspaceLabel,
            statusName: crusorSessionStatusName({ running: this.running, turnOutcome: this.turnOutcome, hasApproval: this.approval !== undefined }),
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
    requestSessionList() {
        const workspace = this.workspacePath;
        if (!workspace || this.engineService.state !== "ready" /* CrusorAIEngineState.Ready */) {
            return;
        }
        this.send({ type: 'session_list', session_id: this.sessionId, workspace, limit: 40, archived: 'exclude' });
    }
    /**
     * One durable row (or optimistic draft row) into the store. Live status always wins for the
     * ACTIVE session, whose label stays the user's own first message; anything else is history
     * and paints without a lifecycle -- except an unread row, which surfaces as
     * completed-unread so the attention dot survives a restart.
     */
    noteEngineRow(row) {
        const sessionId = row.session_id ?? row.id;
        if (!sessionId) {
            return;
        }
        const isActive = sessionId === this.sessionId;
        const statusName = isActive
            ? crusorSessionStatusName({ running: this.running, turnOutcome: this.turnOutcome, hasApproval: this.approval !== undefined })
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
        if (row.unread !== undefined) {
            this.sessionStore.markRead(sessionId, !row.unread);
        }
    }
    /**
     * Frames for a session that is NOT the painted one. Crusor runs one foreground surface: a
     * background turn's frames update its LIST row (and toast on completion), never the live
     * transcript. Returns the foreign id, or undefined when the frame belongs to the active
     * surface (or to no session yet).
     */
    foreignSessionId(frame) {
        const sessionId = frame.session_id;
        if (typeof sessionId !== 'string' || !sessionId) {
            return undefined;
        }
        if (!this.sessionId || sessionId === this.sessionId) {
            return undefined;
        }
        return sessionId;
    }
    /**
     * Background-turn traffic: the row paints Working / needs-input / finished, the transcript
     * is untouched, and a finished background turn toasts (same toggle as a foreground one) and
     * re-syncs the list so its title and counts land. The stored row is spread first so a note
     * never clobbers the engine's label and durable fields with a guess.
     */
    noteForeignFrame(foreignId, frame) {
        const previous = this.sessionStore.records().find(record => record.sessionId === foreignId);
        const label = previous?.label ?? 'Crusor session';
        const workspaceLabel = previous?.workspaceLabel ?? this.workspaceLabel;
        if (frame.type === 'turn_done' || frame.type === 'turn_failed') {
            const failed = frame.type === 'turn_failed';
            const cancelled = !failed && frame.cancelled === true;
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
                this.notifyResponseReady(failed ? frame.error : `(${label}) ${(frame.message ?? '').split('\n')[0]}`.trim(), failed);
            }
            this.requestSessionList();
            this.render();
            return;
        }
        const statusName = frame.type === 'safety_request' || frame.type === 'clarify_request' ? 'needsInput' : 'inProgress';
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
    rememberedSessionKey() {
        const workspace = this.workspacePath;
        if (workspace === undefined) {
            return undefined;
        }
        return `crusorai.lastSession.${encodeURIComponent(workspace)}`;
    }
    getRememberedSession() {
        try {
            const key = this.rememberedSessionKey();
            const value = key ? window.localStorage.getItem(key) : undefined;
            return value || undefined;
        }
        catch {
            return undefined;
        }
    }
    setRememberedSession(sessionId) {
        try {
            const key = this.rememberedSessionKey();
            if (!key) {
                return;
            }
            if (sessionId) {
                window.localStorage.setItem(key, sessionId);
            }
            else {
                window.localStorage.removeItem(key);
            }
        }
        catch { /* storage is best-effort; the session still works */ }
    }
    /**
     * Rebuild the transcript lane from paged checkpoint messages (Hermes hydrates the thread
     * over REST the same way). Every turn lands in HISTORY -- the live surface stays empty so
     * the next prompt starts a fresh turn, not an edit of the past. Tool calls rebuild their
     * cards from the assistant's tool_calls plus the matching tool results (joined on
     * tool_call_id); a result with no card falls back to truncated text rather than vanishing.
     */
    hydrateTranscript(messages) {
        const turns = [];
        let current = { assistantText: '', parts: [], reasoningParts: [], tools: [] };
        const toolIndex = new Map();
        const dirty = (turn) => turn.userMessage !== undefined || turn.assistantText !== '' || turn.parts.length > 0 || turn.reasoningParts.length > 0 || turn.tools.length > 0;
        const rollTurn = () => {
            if (dirty(current)) {
                turns.push(current);
            }
            current = { assistantText: '', parts: [], reasoningParts: [], tools: [] };
        };
        for (const message of messages) {
            if (message.role === 'user') {
                if (dirty(current) && current.userMessage !== undefined) {
                    rollTurn();
                }
                current.userMessage = current.userMessage ? `${current.userMessage}\n${message.content}` : message.content;
            }
            else if (message.role === 'assistant') {
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
                    const tool = { id, name: call.name, state: 'passed', arguments: call.args };
                    current.tools.push(tool);
                    current.parts.push({ kind: 'tool', toolId: id });
                    if (call.id) {
                        toolIndex.set(call.id, tool);
                    }
                }
            }
            else if (message.role === 'tool') {
                const target = (message.tool_call_id && toolIndex.get(message.tool_call_id)) ?? current.tools[current.tools.length - 1];
                if (target && message.content) {
                    current.tools[current.tools.indexOf(target)] = { ...target, result: message.content };
                }
                else if (message.content) {
                    const text = message.content.length > 2000 ? `${message.content.slice(0, 2000)}\u2026` : message.content;
                    current.assistantText += text;
                    current.parts.push({ kind: 'text', text });
                }
            }
        }
        rollTurn();
        this.history = turns.slice(-20).map(turn => ({
            userMessage: turn.userMessage,
            assistantText: turn.assistantText,
            parts: turn.parts,
            reasoningParts: turn.reasoningParts,
            tools: turn.tools,
            subAgents: [],
            turnOutcome: 'completed',
            plan: [],
        }));
        this.render();
    }
    render() {
        this.noteSession();
        if (this.mounts.size === 0 || this.renderFrame !== undefined) {
            return;
        }
        this.renderFrame = requestAnimationFrame(() => {
            this.renderFrame = undefined;
            const model = this.model;
            for (const mount of this.mounts) {
                mount.update(model);
            }
        });
    }
    scheduleRestart() {
        if (this.restartTimer !== undefined || this.mounts.size === 0 || this.restartAttempts >= 3) {
            return;
        }
        if (this.configurationService.getValue('crusorai.autoStart') === false) {
            return;
        }
        const delay = 1_000 * (2 ** this.restartAttempts);
        this.restartTimer = setTimeout(() => {
            this.restartTimer = undefined;
            this.restartAttempts += 1;
            void this.ensureEngine();
        }, delay);
    }
    async ensureEngine() {
        if (this.engineService.state === "ready" /* CrusorAIEngineState.Ready */) {
            return;
        }
        if (this.startPromise) {
            return this.startPromise;
        }
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
            if (this.engineService.state !== "ready" /* CrusorAIEngineState.Ready */) {
                return;
            }
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
    async openManagerWindow() {
        // Opening the manager IS what "read" means, and it is the only honest clear for the
        // attention dot: the workbench's own list keeps its persisted tracking instead.
        if (this.sessionId) {
            this.sessionStore.markRead(this.sessionId, true);
        }
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
    publishHostCapabilities(sessionId = this.sessionId) {
        const workspace = this.workspacePath;
        if (!sessionId || !workspace || this.engineService.state !== "ready" /* CrusorAIEngineState.Ready */) {
            return;
        }
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
    async invokeHostCapability(frame) {
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
            let result;
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
                    const outcome = await this.commandService.executeCommand('crusorai.openPreview', url ? { url } : undefined);
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
                        ? args['resources'].filter((item) => typeof item === 'string').slice(0, 50)
                        : undefined;
                    result = this.workbenchService.getDiagnostics(resources);
                    break;
                }
                case 'language.symbols':
                    if (typeof args['resource'] !== 'string') {
                        throw new Error('language.symbols requires resource');
                    }
                    result = await this.workbenchService.getDocumentSymbols(args['resource']);
                    break;
                case 'language.definitions':
                case 'language.references': {
                    if (typeof args['resource'] !== 'string') {
                        throw new Error(`${frame.capability_id} requires resource`);
                    }
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
                    if (typeof args['query'] !== 'string' || !args['query'].trim()) {
                        throw new Error('search.workspace requires query');
                    }
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
        }
        catch (error) {
            this.send({
                type: 'host_tool_result', session_id: frame.session_id, workspace,
                request_id: frame.request_id, status: 'error',
                error: error instanceof Error ? error.message : String(error),
                duration_ms: Date.now() - started,
            });
        }
    }
    async submitPrompt(text) {
        // A bounded wait, not an unbounded one: ensureEngine resolves when
        // start() settles, but a wedged sidecar must not eat the user's
        // click forever (field 2026-09-05: "send button not working" — the
        // click died in the old silent not-ready return with ZERO feedback).
        await Promise.race([
            this.ensureEngine(),
            new Promise(resolve => setTimeout(resolve, 20_000)),
        ]);
        if (this.engineService.state !== "ready" /* CrusorAIEngineState.Ready */) {
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
    beginExternalTurn(text) {
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
    archiveLiveTurn() {
        if (!(this.userMessage || this.assistantText || this.tools.size > 0)) {
            return;
        }
        this.history = [...this.history, {
                userMessage: this.userMessage,
                assistantText: this.assistantText,
                parts: [...this.parts],
                reasoningParts: this.reasoningParts,
                reasoningPending: this.reasoningPending,
                tools: [...this.tools.values()],
                subAgents: [...this.subAgents.values()],
                turnOutcome: this.turnOutcome,
                plan: this.plan,
            }].slice(-20); // keep last 20 turns
    }
    /** Fresh-turn state: the user's text becomes the bubble; everything else clears. */
    resetTurnState(text) {
        this.userMessage = text;
        this.assistantText = '';
        this.parts = [];
        this.reasoningParts = [];
        this.reasoningPending = false;
        this.hadProviderAttempt = false;
        this.tools.clear();
        this.subAgents.clear();
        this.approval = undefined;
        this.clarify = undefined;
        this.plan = [];
        this.verification = undefined;
        this.running = true;
        this.cancelRequested = false;
        this.turnOutcome = 'running';
        this.turnStartedAt = Date.now();
    }
    startTurn(text) {
        this.archiveLiveTurn();
        this.resetTurnState(text);
        this.send({ type: 'prompt', session_id: this.sessionId, workspace: this.workspacePath, text, mode: this.mode, reasoning_effort: this.reasoningEffort || undefined });
        this.render();
    }
    /**
     * Timeline writers (hermes parts ingestion): text extends the LAST text
     * segment — a token that follows tool calls opens a NEW segment instead of
     * teleporting into the pre-tool text, which is what keeps interleave order
     * truthful. Tools pin their position once; updates go through the tools
     * map, never the timeline.
     */
    appendTextPart(chunk) {
        if (!chunk) {
            return;
        }
        const last = this.parts[this.parts.length - 1];
        if (last?.kind === 'text') {
            this.parts[this.parts.length - 1] = { kind: 'text', text: last.text + chunk };
        }
        else {
            this.parts.push({ kind: 'text', text: chunk });
        }
    }
    pushToolPart(toolId) {
        if (!toolId || this.parts.some(p => p.kind === 'tool' && p.toolId === toolId)) {
            return;
        }
        this.parts.push({ kind: 'tool', toolId });
    }
    send(frame) {
        try {
            this.engineService.send(frame);
        }
        catch (error) {
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
    armStallWatchdog() {
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
            if (!this.running) {
                return;
            }
            this.running = false;
            this.cancelRequested = false;
            this.turnStartedAt = undefined;
            this.turnEndedAt = Date.now();
            // Hermes parity: greeting already answered — silent complete, not failed
            if (_isGreeting) {
                this.turnOutcome = 'completed';
                this.error = undefined;
                this.degraded = undefined;
            }
            else {
                this.turnOutcome = 'failed';
                this.error = 'The engine stopped responding — the turn was ended locally. The reply above is everything it produced; send another message to continue.';
            }
            this.stalled = undefined;
            this.llmStatus = undefined;
            this.clearStallWatchdog();
            this.render();
        }, _isGreeting ? 12 * 1000 : 7 * 60 * 1000);
    }
    clearHardWatchdog() {
        if (this.hardWatchdog !== undefined) {
            clearTimeout(this.hardWatchdog);
            this.hardWatchdog = undefined;
        }
    }
    clearStallWatchdog() {
        if (this.stallWatchdog !== undefined) {
            window.clearTimeout(this.stallWatchdog);
            this.stallWatchdog = undefined;
        }
        this.clearHardWatchdog();
        this.stalled = undefined;
    }
    acceptFrame(frame) {
        if ('event_id' in frame && frame.event_id && !this.rememberEvent(frame.event_id)) {
            return;
        }
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
                if (typeof candidate?.type === 'string') {
                    this.acceptFrame(event);
                }
            }
            return;
        }
        if (frame.type === 'host_tool_request') {
            void this.invokeHostCapability(frame);
            return;
        }
        // A background turn's traffic routes to its list row, never the live transcript.
        const foreignId = this.foreignSessionId(frame);
        if (foreignId) {
            switch (frame.type) {
                case 'turn_started':
                case 'token':
                case 'reasoning':
                case 'plan_updated':
                case 'tool_call_start':
                case 'tool_call_end':
                case 'safety_request':
                case 'clarify_request':
                case 'todo_updated':
                case 'verification_updated':
                case 'telemetry':
                case 'turn_done':
                case 'turn_failed':
                case 'voice_text':
                case 'llm.request':
                case 'llm.response':
                case 'context_status':
                case 'runtime_degraded':
                    this.noteForeignFrame(foreignId, frame);
                    return;
            }
        }
        if (frame.type === 'session_info') {
            // Durable list refresh: a session_list reply carries `sessions` and NO session_id --
            // it notes every row and leaves the active session alone. (An unconditional adopt
            // here used to wipe the active id on every list refresh.)
            if (frame.sessions) {
                for (const row of frame.sessions) {
                    this.noteEngineRow(row);
                }
            }
            if (frame.session) {
                this.noteEngineRow(frame.session);
            }
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
            if (frame.resumed && frame.resolved_session_id && frame.resolved_session_id !== this.sessionId) {
                this.sessionId = frame.resolved_session_id;
                this.setRememberedSession(this.sessionId);
            }
            if (typeof frame.build === 'string' && frame.build) {
                this.engineBuild = frame.build;
            }
            if (previousSessionId !== frame.session_id) {
                this.publishHostCapabilities(frame.session_id);
            }
            if (typeof frame.cancel_requested === 'boolean') {
                this.cancelRequested = frame.cancel_requested;
            }
            // OpenCode parity: restore subagents + parentMap on resume (env path aware)
            for (const row of frame.subagents ?? []) {
                const sid = row.subagent_id ?? row.child_thread_id;
                if (!sid)
                    continue;
                const childId = row.child_thread_id ?? sid;
                const parentId = row.parent_session_id ?? this.sessionId;
                if (childId && parentId)
                    this.parentMap.set(childId, parentId);
                this.subAgents.set(sid, {
                    id: sid,
                    state: (row.state ?? 'pending'),
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
                });
            }
            if (this.sessionId && this.parentMap.has(this.sessionId)) {
                this.childParentId = this.parentMap.get(this.sessionId);
            }
            for (const event of frame.events ?? []) {
                const candidate = valueRecord(event);
                if (typeof candidate?.type === 'string') {
                    this.acceptFrame(event);
                }
            }
            if (this.pendingPrompt) {
                const prompt = this.pendingPrompt;
                this.pendingPrompt = undefined;
                this.startTurn(prompt);
                return;
            }
            // Rename/pin/archive acks re-sync the list so the row shows the new truth.
            if (frame.renamed || frame.pin_updated || frame.archive_updated) {
                this.requestSessionList();
            }
        }
        else if (frame.type === 'turn_started') {
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
        }
        else if (frame.type === 'token') {
            this.assistantText += frame.text;
            this.appendTextPart(frame.text);
            // Reasoning is preserved so the thinking block stays visible in
            // the transcript after the turn completes.
        }
        else if (frame.type === 'reasoning') {
            // Hermes pattern: reasoning parts accumulate as an array.
            const repaired = separateGluedReasoningBlocks(frame.text);
            const tail = this.reasoningParts[this.reasoningParts.length - 1];
            if (tail && repaired.startsWith(tail.text)) {
                tail.text = repaired;
            }
            else if (tail && !tail.completedAt) {
                tail.text = tail.text + repaired;
            }
            else {
                // New reasoning block: record its index in the parts timeline so the
                // renderer knows exactly where in the turn it occurred (Hermes pattern:
                // a single ordered parts array for reasoning, text, and tools).
                const reasoningIndex = this.reasoningParts.length;
                this.reasoningParts.push({ text: repaired });
                this.parts.push({ kind: 'reasoning', reasoningIndex });
            }
            this.reasoningPending = true;
        }
        else if (frame.type === 'plan_updated') {
            this.plan = frame.steps.map(planStepView);
        }
        else if (frame.type === 'tool_call_start') {
            // Seal any open reasoning part before the tool call
            const openReasoning = this.reasoningParts[this.reasoningParts.length - 1];
            if (openReasoning && !openReasoning.completedAt) {
                openReasoning.completedAt = Date.now();
            }
            this.tools.set(frame.tool_id, { id: frame.tool_id, name: frame.name, arguments: frame.arguments, state: 'running' });
            this.pushToolPart(frame.tool_id);
        }
        else if (frame.type === 'tool_call_end') {
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
            if (this.approval?.toolId === frame.tool_id) {
                this.approval = undefined;
            }
            if (this.clarify?.toolId === frame.tool_id) {
                this.clarify = undefined;
            }
        }
        else if (frame.type === 'safety_request') {
            const existing = this.tools.get(frame.tool_id);
            this.tools.set(frame.tool_id, { id: frame.tool_id, name: frame.name, arguments: existing?.arguments ?? frame.arguments ?? frame.diff, result: existing?.result, state: 'approval' });
            // An approval can arrive without a prior start frame; the card must
            // still have a place in the timeline.
            this.pushToolPart(frame.tool_id);
            this.approval = {
                toolId: frame.tool_id,
                name: frame.name,
                diff: frame.diff,
                warning: typeof frame.warning === 'string' ? frame.warning : undefined,
            };
            // 1: Show in editor automatically like Copilot ChatEditingCodeEditorIntegration
            // (viewZones + diffDecorations on live file) — don't wait for user to click Review.
            // Best-effort: if diff has inline text, open inline diff preview.
            try {
                void this.openDiff(frame.tool_id);
            }
            catch { /* best effort */ }
        }
        else if (frame.type === 'clarify_request') {
            // Hermes ask-tool card: the batch of questions rides its own frame
            // (args alone can't drive the form — no qids to respond with).
            this.clarify = {
                requestId: frame.request_id,
                title: frame.title ?? '',
                toolId: frame.tool_id,
                questions: frame.questions,
            };
            if (frame.tool_id) {
                this.pushToolPart(frame.tool_id);
            }
        }
        else if (frame.type === 'todo_updated') {
            // Hermes todo panel: {todos, revision} reconciles atomically; keep
            // the revision even when the list went empty (the unpin decision).
            const items = [];
            for (const raw of frame.todos) {
                const row = raw;
                if (row && typeof row.id === 'string' && typeof row.content === 'string') {
                    items.push({ id: row.id, content: row.content, status: row.status, ...(row.parent ? { parent: row.parent } : {}) });
                }
            }
            this.todos = items;
            this.todoRevision = frame.revision;
        }
        else if (frame.type === 'subagent_updated') {
            const subagent_id = frame.subagent_id;
            const existing = this.subAgents.get(subagent_id) ?? { id: subagent_id, state: 'pending' };
            const state = frame.state ?? existing.state;
            const duration = frame.duration;
            const result = frame.result;
            const childId = frame.child_thread_id ?? subagent_id;
            const parentId = frame.parent_session_id ?? frame.parentSessionId ?? this.sessionId;
            const desc = frame.description ?? existing.description;
            // Never self-parent: an unknown-id status reply echoes the queried id as both
            // child and parent, which would misdetect a normal session as a child.
            if (childId && parentId && childId !== parentId) {
                this.parentMap.set(childId, parentId);
            }
            // Detect if current session is child
            if (this.sessionId && this.parentMap.has(this.sessionId)) {
                this.childParentId = this.parentMap.get(this.sessionId);
            }
            this.subAgents.set(subagent_id, {
                ...existing,
                id: subagent_id,
                state: state,
                goal: frame.goal ?? existing.goal,
                description: desc ?? existing.description,
                mode: frame.mode ?? existing.mode,
                progress: frame.progress ?? existing.progress,
                result: result ?? existing.result,
                duration: duration ?? existing.duration,
                parentSessionId: parentId ?? existing.parentSessionId,
                childThreadId: childId ?? existing.childThreadId,
                background: frame.background ?? existing.background,
                toolCalls: frame.tool_calls ?? frame.toolCalls ?? existing.toolCalls,
                agentName: frame.agent_name ?? frame.agentName ?? existing.mode,
            });
        }
        else if (frame.type === 'subagent_list') {
            // OpenCode parity: list children for parent
            for (const row of frame.subagents ?? []) {
                const sid = row.subagent_id ?? row.child_thread_id;
                if (!sid)
                    continue;
                const childId = row.child_thread_id ?? sid;
                const parentId = row.parent_session_id ?? this.sessionId;
                if (childId && parentId)
                    this.parentMap.set(childId, parentId);
                this.subAgents.set(sid, {
                    id: sid,
                    state: (row.state ?? 'pending'),
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
                });
            }
        }
        else if (frame.type === 'subagent_background_completed') {
            // Background task finished, inject into transcript as token + update subagent
            const subId = frame.subagent_id;
            const text = frame.text ?? '';
            if (text) {
                this.assistantText += text;
                this.appendTextPart(text);
            }
            if (subId) {
                const existing = this.subAgents.get(subId);
                if (existing) {
                    this.subAgents.set(subId, { ...existing, state: 'completed', result: text });
                }
            }
        }
        else if (frame.type === 'verification_updated') {
            this.verification = frame.status;
        }
        else if (frame.type === 'telemetry') {
            this.telemetry = { ...this.telemetry, input: frame.input, output: frame.output, cache: frame.cache, cost: frame.cost };
        }
        else if (frame.type === 'turn_done') {
            this.running = false;
            this.cancelRequested = false;
            this.turnStartedAt = undefined;
            this.turnEndedAt = Date.now();
            // A turn ended with an unanswered clarify: the blocking layer has
            // already timed the wait out — never leave a dead interactive card.
            this.clarify = undefined;
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
            if (openR && !openR.completedAt) {
                openR.completedAt = Date.now();
            }
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
        }
        else if (frame.type === 'turn_failed') {
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
        }
        else if (frame.type === 'voice_text') {
            this.voiceHeard = { ok: frame.ok, text: frame.text ?? '', error: frame.error };
        }
        else if (frame.type === 'llm.request') {
            this.llmStatus = { model: frame.model ?? '', attempt: frame.attempt ?? 1 };
            this.llmHeads = frame.messages;
            this.hadProviderAttempt = true;
        }
        else if (frame.type === 'llm.response') {
            this.llmStatus = undefined;
            this.llmHeads = undefined;
        }
        else if (frame.type === 'context_status') {
            const severity = frame.severity === 'warning' ? 'warning' : 'info';
            if (frame.phase === 'compacted') {
                this.compacting = undefined;
            }
            else if (frame.phase === 'compress' || frame.phase === 'pre_api') {
                this.compacting = true;
            }
            this.contextStatus = {
                message: frame.message,
                severity,
                phase: frame.phase,
                usagePercent: typeof frame.usage_percent === 'number' ? frame.usage_percent : undefined,
            };
        }
        else if (frame.type === 'runtime_degraded') {
            // Greeting with no tools — scan budget is irrelevant, don't show yellow degraded bar
            if (frame.reason && frame.reason.includes('scan budget') && this.tools.size === 0) {
                // suppress
            }
            else {
                this.degraded = frame.reason;
            }
        }
        else if (frame.type === 'session_messages') {
            // Transcript hydration for the session we most recently opened. A late page for a
            // session the user already left is dropped -- painting it would splice another
            // session's history under the active transcript.
            const forId = frame.requested_session_id ?? frame.session_id;
            if (forId !== this.pendingHydration && forId !== this.sessionId) {
                return;
            }
            this.pendingHydration = undefined;
            this.hydrateTranscript(frame.messages);
            return;
        }
        else if (frame.type === 'session_deleted') {
            const deletedId = frame.session_id;
            this.sessionStore.forget(deletedId);
            if (deletedId === this.sessionId) {
                // Our own session was deleted (here or elsewhere): land on a blank surface,
                // not a ghost.
                this.newSession();
            }
        }
        else if (frame.type === 'error') {
            this.error = frame.message;
        }
        this.render();
    }
    rememberEvent(eventId) {
        if (this.seenEventIds.has(eventId)) {
            return false;
        }
        this.seenEventIds.add(eventId);
        this.eventIdOrder.push(eventId);
        if (this.eventIdOrder.length > 20_000) {
            const removed = this.eventIdOrder.splice(0, 2_000);
            for (const id of removed) {
                this.seenEventIds.delete(id);
            }
        }
        return true;
    }
    async openDiff(toolId) {
        try {
            const tool = this.tools.get(toolId);
            const approval = this.approval?.toolId === toolId ? this.approval.diff : undefined;
            const sources = [approval, tool?.result, tool?.arguments];
            let original;
            let modified;
            let originalText;
            let modifiedText;
            let resource;
            for (const source of sources) {
                const value = valueRecord(source);
                original ??= stringField(source, ['original_uri', 'original', 'before_uri', 'base_uri']);
                modified ??= stringField(source, ['modified_uri', 'modified', 'after_uri']);
                resource ??= stringField(source, ['resource', 'file_path', 'path', 'relative_path']);
                if (originalText === undefined && value && 'old_text' in value && (typeof value.old_text === 'string' || value.old_text === null)) {
                    originalText = typeof value.old_text === 'string' ? value.old_text : '';
                }
                if (modifiedText === undefined && typeof value?.new_text === 'string') {
                    modifiedText = value.new_text;
                }
                if (modifiedText === undefined && typeof value?.content === 'string') {
                    modifiedText = value.content;
                }
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
            await this.workbenchService.openNativeDiff(this.resourceUri(original).toString(), this.resourceUri(modified).toString(), label);
        }
        catch (error) {
            this.error = error instanceof Error ? error.message : String(error);
            this.render();
        }
    }
    resourceBrowserSrc(resource) {
        // file:// is not loadable from the workbench DOM; FileAccess translates
        // it to the scheme the renderer may fetch (same path resolution as
        // revealFile — Windows drives, schemes, workspace-relative).
        try {
            return FileAccess.uriToBrowserUri(this.resourceUri(resource)).toString(true);
        }
        catch (error) {
            return undefined;
        }
    }
    async revealFile(resource) {
        try {
            await this.workbenchService.openResource(this.resourceUri(resource).toString());
        }
        catch (error) {
            this.error = error instanceof Error ? error.message : String(error);
            this.render();
        }
    }
    notifyResponseReady(detail, isError = false) {
        try {
            if (this.configurationService.getValue('crusorai.notifyOnComplete') === false) {
                return;
            }
            const msg = isError ? 'Crusor — task ended with an issue' : 'Response Ready — Crusor';
            const detailLine = detail ? String(detail).split('\n')[0].slice(0, 160) : '';
            this.notificationService.notify({
                severity: isError ? Severity.Warning : Severity.Info,
                message: msg,
                source: detailLine ? `${detailLine}` : 'Crusor Agent finished',
                actions: {
                    primary: [{
                            id: "crusorai.focus" /* CrusorAICommandId.Focus */,
                            label: 'Open Crusor',
                            tooltip: 'Focus Crusor Agent',
                            enabled: true,
                            run: () => { void this.commandService.executeCommand("crusorai.focus" /* CrusorAICommandId.Focus */); }
                        }]
                }
            });
        }
        catch { /* notification must never break turn */ }
    }
    resourceUri(resource) {
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
        if (gitBash) {
            return URI.file(`${gitBash[1].toUpperCase()}:/${gitBash[2]}`);
        }
        if (/^(?:[a-z]:[\\/]|[\\/])/i.test(resource)) {
            return URI.file(resource);
        }
        if (/^[a-z][a-z0-9+.-]*:/i.test(resource)) {
            return URI.parse(resource);
        }
        return folder ? URI.joinPath(folder.uri, resource) : URI.file(resource);
    }
};
CrusorAIRendererService = __decorate([
    __param(0, ICrusorAIEngineService),
    __param(1, ICrusorAIWorkbenchService),
    __param(2, IWorkspaceContextService),
    __param(3, IConfigurationService),
    __param(4, ICommandService),
    __param(5, IClipboardService),
    __param(6, IAuxiliaryWindowService),
    __param(7, ICrusorAISessionStore),
    __param(8, INotificationService)
], CrusorAIRendererService);
export { CrusorAIRendererService };
