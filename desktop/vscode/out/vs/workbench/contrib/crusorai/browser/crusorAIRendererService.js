/*---------------------------------------------------------------------------------------------
 * One shared event model and host adapter for the compact Agent view and Crusor Manager.
 *--------------------------------------------------------------------------------------------*/
var __extends = (this && this.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();
var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g = Object.create((typeof Iterator === "function" ? Iterator : Object).prototype);
    return g.next = verb(0), g["throw"] = verb(1), g["return"] = verb(2), typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
var __spreadArray = (this && this.__spreadArray) || function (to, from, pack) {
    if (pack || arguments.length === 2) for (var i = 0, l = from.length, ar; i < l; i++) {
        if (ar || !(i in from)) {
            if (!ar) ar = Array.prototype.slice.call(from, 0, i);
            ar[i] = from[i];
        }
    }
    return to.concat(ar || Array.prototype.slice.call(from));
};
import { Disposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { FileAccess } from '../../../../base/common/network.js';
import { URI } from '../../../../base/common/uri.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { IClipboardService } from '../../../../platform/clipboard/common/clipboardService.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { IWorkspaceContextService } from '../../../../platform/workspace/common/workspace.js';
import { IAuxiliaryWindowService } from '../../../services/auxiliaryWindow/browser/auxiliaryWindowService.js';
import { CrusorAICommandId } from '../common/crusorAI.js';
import { INotificationService, Severity } from '../../../../platform/notification/common/notification.js';
import { ICrusorAIEngineService, CrusorAIEngineSetupError, CrusorAIEngineState } from '../common/crusorAIEngineService.js';
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
    var value = status.toLowerCase();
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
    var record = valueRecord(step);
    for (var _i = 0, _a = ['title', 'text', 'description', 'goal']; _i < _a.length; _i++) {
        var key = _a[_i];
        if (typeof (record === null || record === void 0 ? void 0 : record[key]) === 'string') {
            return record[key];
        }
    }
    return 'Plan step';
}
var PLAN_STATUSES = ['pending', 'in_progress', 'completed', 'failed'];
function planStepView(step) {
    var raw = (typeof step === 'object' && step !== null)
        ? step.status
        : undefined;
    var status = typeof raw === 'string' ? raw : '';
    return {
        text: planText(step),
        status: (PLAN_STATUSES.includes(status)
            ? status
            : 'pending'),
    };
}
function stringField(source, keys) {
    var value = valueRecord(source);
    for (var _i = 0, keys_1 = keys; _i < keys_1.length; _i++) {
        var key = keys_1[_i];
        if (typeof (value === null || value === void 0 ? void 0 : value[key]) === 'string' && value[key]) {
            return value[key];
        }
    }
    return undefined;
}
var CrusorAIRendererService = /** @class */ (function (_super) {
    __extends(CrusorAIRendererService, _super);
    function CrusorAIRendererService(engineService, workbenchService, workspaceContextService, configurationService, commandService, clipboardService, auxiliaryWindowService, sessionStore, notificationService) {
        var _this = _super.call(this) || this;
        _this.engineService = engineService;
        _this.workbenchService = workbenchService;
        _this.workspaceContextService = workspaceContextService;
        _this.configurationService = configurationService;
        _this.commandService = commandService;
        _this.clipboardService = clipboardService;
        _this.auxiliaryWindowService = auxiliaryWindowService;
        _this.sessionStore = sessionStore;
        _this.notificationService = notificationService;
        _this.mounts = new Set();
        _this.tools = new Map();
        _this.seenEventIds = new Set();
        _this.eventIdOrder = [];
        _this.restartAttempts = 0;
        _this.draft = '';
        _this.mode = 'agent';
        /** Think level ('' = inherit the engine's REASONING_EFFORT env default). */
        _this.reasoningEffort = '';
        _this.running = false;
        _this.cancelRequested = false;
        /** Live hermes todo_list state, reconciled atomically on {todos, revision}. */
        _this.todos = [];
        _this.todoRevision = 0;
        _this.turnOutcome = 'idle';
        _this.assistantText = '';
        /**
         * Ordered timeline (hermes message.parts): one entry per text segment and
         * tool call, in arrival order. `assistantText` stays the concatenated
         * string for copy/inspector; the TRANSCRIPT paints from `parts` so tools
         * sit where they happened and the final answer lands last. Cleared at
         * turn boundaries with the rest of the turn state.
         */
        _this.parts = [];
        /** Reasoning parts seen this turn — each LLM call that produces reasoning adds a new part. */
        _this.reasoningParts = [];
        _this.reasoningPending = false;
        _this.subAgents = new Map();
        /** OpenCode parity: parentMap child_thread_id -> parent_session_id for navigation */
        _this.parentMap = new Map();
        _this.plan = [];
        _this.telemetry = {};
        _this.engineSetupError = false;
        /** A provider attempt has been named this turn (llm.request seen).
         * Reasoning arriving AFTER this is real model thought — a buffered
         * endpoint delivers it as a single whole-text frame — while reasoning
         * before any provider attempt is the legacy liveness dress-up. */
        _this.hadProviderAttempt = false;
        _this.history = [];
        _this.host = {
            setDraft: function (value) { _this.draft = value; },
            setMode: function (mode) {
                if (_this.running || _this.mode === mode) {
                    return;
                }
                _this.mode = mode;
                _this.render();
            },
            // hermes reasoning-effort: a manual pick sticks for the session; it
            // rides the NEXT prompt frame, so a mid-turn change needs no cancel.
            setReasoningEffort: function (value) {
                if (_this.reasoningEffort === value) {
                    return;
                }
                _this.reasoningEffort = value;
                _this.render();
            },
            submitPrompt: function (text) { void _this.submitPrompt(text); },
            cancel: function () {
                if (!_this.running || _this.cancelRequested) {
                    return;
                }
                _this.cancelRequested = true;
                _this.send({ type: 'cancel', session_id: _this.sessionId });
                _this.render();
            },
            steer: function (text) { _this.send({ type: 'steer', session_id: _this.sessionId, text: text }); _this.draft = ''; _this.render(); },
            replyToSafety: function (toolId, approved, alwaysAllow) {
                _this.send({ type: 'safety_reply', session_id: _this.sessionId, tool_id: toolId, approved: approved, always_allow: alwaysAllow });
                var tool = _this.tools.get(toolId);
                if (tool) {
                    _this.tools.set(toolId, __assign(__assign({}, tool), { state: approved ? 'running' : 'failed' }));
                }
                _this.approval = undefined;
                _this.render();
            },
            replyToClarify: function (requestId, answers, timedOut) {
                // The clarify card rides ONE batch reply (hermes #18450): answers per
                // qid; an explicit Skip resolves the batch empty (deliberate, not a
                // timeout). The pending card stays up in its submitting state until
                // the clarify tool_call_end swaps in the settled Q&A.
                _this.send({ type: 'clarify_reply', session_id: _this.sessionId, request_id: requestId, answers: answers, timed_out: timedOut });
                _this.render();
            },
            openDiff: function (toolId) { void _this.openDiff(toolId); },
            revealFile: function (resource) { void _this.revealFile(resource); },
            resourceSrc: function (resource) { return _this.resourceBrowserSrc(resource); },
            restoreCheckpoint: function (checkpointHash) {
                var workspace = _this.workspacePath;
                if (workspace) {
                    _this.send({ type: 'checkpoint_restore', session_id: _this.sessionId, workspace: workspace, checkpoint_hash: checkpointHash });
                }
            },
            retryEngine: function () {
                if (_this.restartTimer !== undefined) {
                    clearTimeout(_this.restartTimer);
                    _this.restartTimer = undefined;
                }
                _this.restartAttempts = 0;
                // Clear the fault the moment a manual retry starts: leaving it up claims the engine is still
                // broken while it is being restarted, and the row's own action would look like a no-op.
                _this.engineFault = undefined;
                void _this.ensureEngine();
            },
            selectWorkspace: function (uri) { return _this.selectWorkspace(uri); },
            openFolder: function () { void _this.commandService.executeCommand('workbench.action.files.openFolder'); },
            openEngineSettings: function () { void _this.commandService.executeCommand(CrusorAICommandId.OpenSettings); },
            openManager: function () { _this.openManagerWindow(); },
            // Composer + -> the Add… dialog (native QuickPick; each row routes to
            // its registered command — one code path with the palette).
            skillsHubOp: function (op, extra) { return _this.skillsHubOp(op, extra); },
            copyToClipboard: function (text) {
                // Real clipboard (field: navigator.clipboard.writeText is
                // permission-blocked inside the webview). The workbench service
                // owns the privileged path; never let clipboard trouble throw.
                try {
                    _this.clipboardService.writeText(text);
                }
                catch ( /* best effort */_a) { /* best effort */ }
            },
            // Composer + dialog, One-Shot tab (field 2026-10-02 rev 4): one quick
            // job over the oneshot envelope — same request/response pairing as
            // the hub op hook.
            oneshotRun: function (template, instructions, variables) {
                return new Promise(function (resolve, reject) {
                    var listener;
                    // 60s: one-shots are REAL model calls — a slow provider is
                    // normal-ish; the engine bounds the call itself at 50s, so a
                    // timeout here means the frame never got answered at all.
                    var timer = setTimeout(function () {
                        listener === null || listener === void 0 ? void 0 : listener.dispose();
                        reject(new Error('One-shot: the engine did not answer in 60s. Try once more — if it repeats, fully restart CrusorAI so the bridge runs this build (the engine log prints a "[bridge] oneshot" line for every attempt).'));
                    }, 60000);
                    listener = _this.onOneshotResult(function (frame) {
                        clearTimeout(timer);
                        listener === null || listener === void 0 ? void 0 : listener.dispose();
                        if (frame.error) {
                            reject(new Error(frame.error));
                            return;
                        }
                        resolve({ text: frame.text });
                    });
                    _this.sendOneshot(template, { instructions: instructions, variables: variables });
                });
            },
            navigateToSession: function (sessionId) { _this.navigateToSession(sessionId); },
            newSession: function () { _this.newSession(); },
            isChildSession: function () { return !!(_this.childParentId || (_this.sessionId && (_this.sessionId.startsWith('sub-') || _this.parentMap.has(_this.sessionId)))); },
        };
        // Skills Hub (Phase 3): UI listeners for skills_hub_result frames. The
        // hub panel registers a listener per in-flight request; listener errors
        // are isolated so one broken panel never eats the frame dispatch.
        _this._hubListeners = new Set();
        _this._oneshotListeners = new Set();
        _this._register(_this.engineService.onDidChangeState(function (state) {
            if (state === CrusorAIEngineState.Ready) {
                _this.restartAttempts = 0;
                _this.engineFault = undefined;
            }
            else if (state === CrusorAIEngineState.Crashed || state === CrusorAIEngineState.Degraded) {
                // The only trace of a dying sidecar used to be a log line: the process exit is reported by
                // the engine service, `scheduleRestart` swallows exhaustion, and a turn in flight never
                // receives turn_done -- so the panel kept painting a live run that had no engine behind it.
                // A setup failure already has its own actionable row, so it is not overwritten here.
                if (!_this.engineSetupError) {
                    _this.engineFault = state === CrusorAIEngineState.Crashed
                        ? 'The Crusor engine process stopped while this session was open.'
                        : 'The Crusor engine could not accept the request, so it never reached the model.';
                    if (_this.running) {
                        _this.running = false;
                        _this.turnOutcome = 'failed';
                    }
                }
                _this.scheduleRestart();
            }
            _this.render();
        }));
        _this._register(_this.engineService.onDidReceiveFrame(function (frame) { return _this.acceptFrame(frame); }));
        _this._register(_this.workbenchService.onDidResolveDiff(function (event) {
            _this.host.replyToSafety(event.toolId, event.approved);
        }));
        _this._register(_this.workbenchService.onDidChangeCapabilities(function () {
            _this.publishHostCapabilities();
            _this.render();
        }));
        _this._register(toDisposable(function () {
            if (_this.renderFrame !== undefined) {
                cancelAnimationFrame(_this.renderFrame);
            }
            if (_this.restartTimer !== undefined) {
                clearTimeout(_this.restartTimer);
            }
        }));
        return _this;
    }
    CrusorAIRendererService.prototype.mount = function (root /* HTMLElement */, surface) {
        var _this = this;
        var mount = mountCrusorAIRenderer(root, surface, this.host);
        this.mounts.add(mount);
        mount.update(this.model);
        if (this.configurationService.getValue('crusorai.autoStart') !== false) {
            void this.ensureEngine();
        }
        return toDisposable(function () {
            _this.mounts.delete(mount);
            mount.dispose();
        });
    };
    Object.defineProperty(CrusorAIRendererService.prototype, "sessionFolder", {
        /**
         * P0 workspace acquisition: the session folder comes ONLY from
         * IWorkspaceContextService.getWorkspace().folders. Zero folders -> undefined
         * (submission blocked). One folder -> its exact uri.fsPath. Multiple folders
         * -> the explicitly retained selection (never folders[0] implicitly).
         */
        get: function () {
            var _this = this;
            var folders = this.workspaceContextService.getWorkspace().folders;
            if (folders.length === 0) {
                return undefined;
            }
            if (folders.length === 1) {
                return folders[0];
            }
            if (this.selectedWorkspaceUri) {
                var selected = folders.find(function (folder) { var _a; return folder.uri.toString() === ((_a = _this.selectedWorkspaceUri) === null || _a === void 0 ? void 0 : _a.toString()); });
                if (selected) {
                    return selected;
                }
                this.selectedWorkspaceUri = undefined;
            }
            return undefined;
        },
        enumerable: false,
        configurable: true
    });
    Object.defineProperty(CrusorAIRendererService.prototype, "workspacePath", {
        get: function () {
            var _a;
            return (_a = this.sessionFolder) === null || _a === void 0 ? void 0 : _a.uri.fsPath;
        },
        enumerable: false,
        configurable: true
    });
    Object.defineProperty(CrusorAIRendererService.prototype, "workspaceLabel", {
        get: function () {
            var _a, _b;
            return (_b = (_a = this.sessionFolder) === null || _a === void 0 ? void 0 : _a.name) !== null && _b !== void 0 ? _b : 'Local workspace';
        },
        enumerable: false,
        configurable: true
    });
    Object.defineProperty(CrusorAIRendererService.prototype, "workspaceFolderCount", {
        get: function () {
            return this.workspaceContextService.getWorkspace().folders.length;
        },
        enumerable: false,
        configurable: true
    });
    Object.defineProperty(CrusorAIRendererService.prototype, "workspaceChoices", {
        get: function () {
            return this.workspaceContextService.getWorkspace().folders.map(function (folder) { return ({
                label: folder.name,
                uri: folder.uri.toString(),
            }); });
        },
        enumerable: false,
        configurable: true
    });
    /**
     * Blank-surface reset: every field that belongs to one session's visible turn state. One
     * method because folder switches, session switches and New Session must clear exactly the
     * same surface -- two copies drifted once already (history survived navigation).
     */
    CrusorAIRendererService.prototype.resetSessionState = function () {
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
    };
    CrusorAIRendererService.prototype.selectWorkspace = function (uri) {
        var _a;
        var folders = this.workspaceContextService.getWorkspace().folders;
        var matched = folders.find(function (folder) { return folder.uri.toString() === uri; });
        if (!matched) {
            return;
        }
        var changed = ((_a = this.selectedWorkspaceUri) === null || _a === void 0 ? void 0 : _a.toString()) !== uri;
        this.selectedWorkspaceUri = matched.uri;
        if (changed) {
            // Retain the selection for the SESSION; a folder switch resets the
            // session binding so frames always carry the same workspace.
            this.resetSessionState();
        }
        this.render();
    };
    Object.defineProperty(CrusorAIRendererService.prototype, "capabilitySummary", {
        get: function () {
            var values = this.workbenchService.getCapabilities();
            return {
                available: values.filter(function (value) { return value.availability === 'available'; }).length,
                blocked: values.filter(function (value) { return value.availability === 'blocked'; }).length,
                total: values.length,
            };
        },
        enumerable: false,
        configurable: true
    });
    Object.defineProperty(CrusorAIRendererService.prototype, "model", {
        get: function () {
            var _a;
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
                parts: __spreadArray([], this.parts, true),
                reasoningParts: __spreadArray([], this.reasoningParts, true),
                tools: __spreadArray([], this.tools.values(), true),
                subAgents: __spreadArray([], this.subAgents.values(), true),
                isChild: !!(this.childParentId || (this.sessionId && (this.sessionId.startsWith('sub-') || this.parentMap.has(this.sessionId)))),
                parentSessionId: (_a = this.childParentId) !== null && _a !== void 0 ? _a : (this.sessionId ? this.parentMap.get(this.sessionId) : undefined),
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
        },
        enumerable: false,
        configurable: true
    });
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
    CrusorAIRendererService.prototype.navigateToSession = function (targetSessionId) {
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
        var previousSessionId = this.sessionId;
        var previousChildParentId = this.childParentId;
        // Pre-reset reads: the reset wipes the map and the records. A plausible child
        // hydrates its own record below; the ownership reads gate the optimistic link.
        var targetLooksChild = targetSessionId.startsWith('sub-') || this.parentMap.has(targetSessionId);
        var targetKnownParent = this.parentMap.get(targetSessionId);
        var previousKnownParent = previousSessionId ? this.parentMap.get(previousSessionId) : undefined;
        var previousOwnsTarget = !!previousSessionId && __spreadArray([], this.subAgents.values(), true).some(function (record) {
            return (record.childThreadId === targetSessionId || record.id === targetSessionId)
                && record.parentSessionId === previousSessionId;
        });
        var navigatingToKnownParent = !!previousSessionId
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
        var workspace = this.workspacePath;
        if (workspace) {
            // Transcript hydration comes from the paged checkpoints (session_messages), not the
            // journal: include_events:false keeps the resume's events out so the two views never
            // double-paint one transcript.
            this.send({ type: 'session_resume', session_id: targetSessionId, workspace: workspace, include_events: false });
            this.send({ type: 'session_messages', session_id: targetSessionId, workspace: workspace, limit: 120, order: 'latest' });
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
    };
    /**
     * Hermes "New Session": a blank surface with NO session id. The id is minted by the engine
     * on the next prompt (session_create), so a draft the user abandons leaves no row behind.
     * While a turn runs the surface is occupied -- stranding a live turn's frames is worse
     * than refusing.
     */
    CrusorAIRendererService.prototype.newSession = function () {
        if (this.running) {
            this.error = 'Stop the current run before starting a new session.';
            this.render();
            return;
        }
        this.resetSessionState();
        this.render();
    };
    /**
     * Workbench-list entry to navigateToSession: rebind the surface to an existing session.
     * Same guards (no mid-turn switches), same checkpoint hydration.
     */
    CrusorAIRendererService.prototype.openSession = function (sessionId) {
        this.navigateToSession(sessionId);
    };
    /**
     * This session's own delegated goal when it is a sub-agent child: the record whose
     * child thread is the active session. The child header paints this — never a hardcoded
     * title (field 2026-09-28: every sub-agent view read "Main / Sub-agent").
     */
    CrusorAIRendererService.prototype.currentSubAgentGoal = function () {
        if (!this.sessionId) {
            return undefined;
        }
        for (var _i = 0, _a = this.subAgents.values(); _i < _a.length; _i++) {
            var record = _a[_i];
            if (record.childThreadId === this.sessionId) {
                return record.goal || record.description || undefined;
            }
        }
        for (var _b = 0, _c = this.subAgents.values(); _b < _c.length; _b++) {
            var record = _c[_b];
            if (record.id === this.sessionId && record.parentSessionId) {
                return record.goal || record.description || undefined;
            }
        }
        return undefined;
    };
    /** The active session's parent label from the store, for the child breadcrumb. */
    CrusorAIRendererService.prototype.currentParentTitle = function () {
        var _a, _b;
        var parentId = (_a = this.childParentId) !== null && _a !== void 0 ? _a : (this.sessionId ? this.parentMap.get(this.sessionId) : undefined);
        if (!parentId) {
            return undefined;
        }
        return (_b = this.sessionStore.records().find(function (record) { return record.sessionId === parentId; })) === null || _b === void 0 ? void 0 : _b.label;
    };
    CrusorAIRendererService.prototype.sessionRows = function () {
        var readState = new Map();
        for (var _i = 0, _a = this.sessionStore.records(); _i < _a.length; _i++) {
            var facts = _a[_i];
            var isRead = this.sessionStore.isRead(facts.sessionId);
            if (isRead !== undefined) {
                readState.set(facts.sessionId, isRead);
            }
        }
        return crusorSessionRows(this.sessionStore.records(), this.sessionId, Date.now(), readState);
    };
    /**
     * Called before the mount check: a session nobody has painted is still a session the user
     * ran. `changes` is left out on purpose until one diff counter is shared with the tool row --
     * a count of files nobody measured is worse in a list than an absent field.
     */
    CrusorAIRendererService.prototype.noteSession = function () {
        var _this = this;
        var _a;
        if (!this.sessionId) {
            return;
        }
        // The label is the engine's created title (fixed, unique). Until it lands the row
        // renders the generic placeholder — the first message is NEVER captured as the
        // title (field 2026-09-28). A generic fallback is never sticky: the titler's
        // live push upgrades it exactly once.
        var previousLabel = (_a = this.sessionStore.records().find(function (record) { return record.sessionId === _this.sessionId; })) === null || _a === void 0 ? void 0 : _a.label;
        var facts = {
            sessionId: this.sessionId,
            label: previousLabel && !crusorSessionLabelIsFallback(previousLabel) ? previousLabel : crusorSessionLabel(undefined, this.sessionId),
            workspaceLabel: this.workspaceLabel,
            statusName: crusorSessionStatusName({ running: this.running, turnOutcome: this.turnOutcome, hasApproval: this.approval !== undefined }),
            firstSeenAt: Date.now(),
            turnStartedAt: this.turnStartedAt,
            turnEndedAt: this.turnEndedAt,
        };
        this.sessionStore.note(facts);
    };
    /**
     * Durable-list refresh (Hermes listSessions): the store's rows for every session come from
     * here. Fire-and-forget; the reply is a sid-less session_info whose `sessions` payload must
     * never clobber the active session id (see acceptFrame).
     */
    CrusorAIRendererService.prototype.requestSessionList = function () {
        var workspace = this.workspacePath;
        if (!workspace || this.engineService.state !== CrusorAIEngineState.Ready) {
            return;
        }
        this.send({ type: 'session_list', session_id: this.sessionId, workspace: workspace, limit: 40, archived: 'exclude' });
    };
    /**
     * One durable row (or optimistic draft row) into the store. Live status always wins for the
     * ACTIVE session, whose label stays the user's own first message; anything else is history
     * and paints without a lifecycle -- except an unread row, which surfaces as
     * completed-unread so the attention dot survives a restart.
     */
    CrusorAIRendererService.prototype.noteEngineRow = function (row) {
        var _a, _b, _c;
        var sessionId = (_a = row.session_id) !== null && _a !== void 0 ? _a : row.id;
        if (!sessionId) {
            return;
        }
        var isActive = sessionId === this.sessionId;
        var statusName = isActive
            ? crusorSessionStatusName({ running: this.running, turnOutcome: this.turnOutcome, hasApproval: this.approval !== undefined })
            : row.unread === true ? 'completed' : undefined;
        var base = crusorFactsFromEngineRow(row, { workspaceLabel: this.workspaceLabel, statusName: statusName, now: Date.now() });
        // Active label: the engine's created title wins (fixed, unique; the rename path
        // upgrades it the same way); otherwise the first-seen non-fallback label sticks.
        // No title yet: the generic placeholder — never the first message.
        var engineTitle = ((_b = row.title) !== null && _b !== void 0 ? _b : '').trim();
        var previousLabel = (_c = this.sessionStore.records().find(function (record) { return record.sessionId === sessionId; })) === null || _c === void 0 ? void 0 : _c.label;
        var liveLabel = engineTitle || (previousLabel && !crusorSessionLabelIsFallback(previousLabel) ? previousLabel : crusorSessionLabel(undefined, sessionId));
        this.sessionStore.note(isActive
            ? __assign(__assign({}, base), { label: liveLabel, turnStartedAt: this.turnStartedAt, turnEndedAt: this.turnEndedAt }) : base);
        if (row.unread !== undefined) {
            this.sessionStore.markRead(sessionId, !row.unread);
        }
    };
    /**
     * Frames for a session that is NOT the painted one. Crusor runs one foreground surface: a
     * background turn's frames update its LIST row (and toast on completion), never the live
     * transcript. Returns the foreign id, or undefined when the frame belongs to the active
     * surface (or to no session yet).
     */
    CrusorAIRendererService.prototype.foreignSessionId = function (frame) {
        var sessionId = frame.session_id;
        if (typeof sessionId !== 'string' || !sessionId) {
            return undefined;
        }
        if (!this.sessionId || sessionId === this.sessionId) {
            return undefined;
        }
        return sessionId;
    };
    /**
     * Background-turn traffic: the row paints Working / needs-input / finished, the transcript
     * is untouched, and a finished background turn toasts (same toggle as a foreground one) and
     * re-syncs the list so its title and counts land. The stored row is spread first so a note
     * never clobbers the engine's label and durable fields with a guess.
     */
    CrusorAIRendererService.prototype.noteForeignFrame = function (foreignId, frame) {
        var _a, _b, _c, _d, _e, _f;
        var previous = this.sessionStore.records().find(function (record) { return record.sessionId === foreignId; });
        var label = (_a = previous === null || previous === void 0 ? void 0 : previous.label) !== null && _a !== void 0 ? _a : 'Crusor session';
        var workspaceLabel = (_b = previous === null || previous === void 0 ? void 0 : previous.workspaceLabel) !== null && _b !== void 0 ? _b : this.workspaceLabel;
        if (frame.type === 'turn_done' || frame.type === 'turn_failed') {
            var failed = frame.type === 'turn_failed';
            var cancelled = !failed && frame.cancelled === true;
            this.sessionStore.note(__assign(__assign({}, previous), { sessionId: foreignId, label: label, workspaceLabel: workspaceLabel, statusName: failed ? 'failed' : 'completed', firstSeenAt: (_c = previous === null || previous === void 0 ? void 0 : previous.firstSeenAt) !== null && _c !== void 0 ? _c : Date.now(), turnEndedAt: Date.now() }));
            this.sessionStore.markRead(foreignId, false);
            if (!cancelled) {
                this.notifyResponseReady(failed ? frame.error : "(".concat(label, ") ").concat(((_d = frame.message) !== null && _d !== void 0 ? _d : '').split('\n')[0]).trim(), failed);
            }
            this.requestSessionList();
            this.render();
            return;
        }
        var statusName = frame.type === 'safety_request' || frame.type === 'clarify_request' ? 'needsInput' : 'inProgress';
        this.sessionStore.note(__assign(__assign({}, previous), { sessionId: foreignId, label: label, workspaceLabel: workspaceLabel, statusName: statusName, firstSeenAt: (_e = previous === null || previous === void 0 ? void 0 : previous.firstSeenAt) !== null && _e !== void 0 ? _e : Date.now(), turnStartedAt: (_f = previous === null || previous === void 0 ? void 0 : previous.turnStartedAt) !== null && _f !== void 0 ? _f : Date.now() }));
        this.render();
    };
    /** Hermes profileNavigationKey parity: the last open session per workspace survives a restart. */
    CrusorAIRendererService.prototype.rememberedSessionKey = function () {
        var workspace = this.workspacePath;
        if (workspace === undefined) {
            return undefined;
        }
        return "crusorai.lastSession.".concat(encodeURIComponent(workspace));
    };
    CrusorAIRendererService.prototype.getRememberedSession = function () {
        try {
            var key = this.rememberedSessionKey();
            var value = key ? window.localStorage.getItem(key) : undefined;
            return value || undefined;
        }
        catch (_a) {
            return undefined;
        }
    };
    CrusorAIRendererService.prototype.setRememberedSession = function (sessionId) {
        try {
            var key = this.rememberedSessionKey();
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
        catch ( /* storage is best-effort; the session still works */_a) { /* storage is best-effort; the session still works */ }
    };
    /**
     * Rebuild the transcript lane from paged checkpoint messages (Hermes hydrates the thread
     * over REST the same way). Every turn lands in HISTORY -- the live surface stays empty so
     * the next prompt starts a fresh turn, not an edit of the past. Tool calls rebuild their
     * cards from the assistant's tool_calls plus the matching tool results (joined on
     * tool_call_id); a result with no card falls back to truncated text rather than vanishing.
     */
    CrusorAIRendererService.prototype.hydrateTranscript = function (messages) {
        var _a, _b;
        var turns = [];
        var current = { assistantText: '', parts: [], reasoningParts: [], tools: [] };
        var toolIndex = new Map();
        var dirty = function (turn) { return turn.userMessage !== undefined || turn.assistantText !== '' || turn.parts.length > 0 || turn.reasoningParts.length > 0 || turn.tools.length > 0; };
        var rollTurn = function () {
            if (dirty(current)) {
                turns.push(current);
            }
            current = { assistantText: '', parts: [], reasoningParts: [], tools: [] };
        };
        for (var _i = 0, messages_1 = messages; _i < messages_1.length; _i++) {
            var message = messages_1[_i];
            if (message.role === 'user') {
                if (dirty(current) && current.userMessage !== undefined) {
                    rollTurn();
                }
                current.userMessage = current.userMessage ? "".concat(current.userMessage, "\n").concat(message.content) : message.content;
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
                for (var _c = 0, _d = (_a = message.tool_calls) !== null && _a !== void 0 ? _a : []; _c < _d.length; _c++) {
                    var call = _d[_c];
                    var id = call.id || "hydrate-".concat(turns.length, "-").concat(current.tools.length);
                    // Checkpoints carry no per-tool verdict: the turn completed, so the card paints
                    // passed; a failed tool's stderr still shows in its result body.
                    var tool = { id: id, name: call.name, state: 'passed', arguments: call.args };
                    current.tools.push(tool);
                    current.parts.push({ kind: 'tool', toolId: id });
                    if (call.id) {
                        toolIndex.set(call.id, tool);
                    }
                }
            }
            else if (message.role === 'tool') {
                var target = (_b = (message.tool_call_id && toolIndex.get(message.tool_call_id))) !== null && _b !== void 0 ? _b : current.tools[current.tools.length - 1];
                if (target && message.content) {
                    current.tools[current.tools.indexOf(target)] = __assign(__assign({}, target), { result: message.content });
                }
                else if (message.content) {
                    var text = message.content.length > 2000 ? "".concat(message.content.slice(0, 2000), "\u2026") : message.content;
                    current.assistantText += text;
                    current.parts.push({ kind: 'text', text: text });
                }
            }
        }
        rollTurn();
        this.history = turns.slice(-20).map(function (turn) { return ({
            userMessage: turn.userMessage,
            assistantText: turn.assistantText,
            parts: turn.parts,
            reasoningParts: turn.reasoningParts,
            tools: turn.tools,
            subAgents: [],
            turnOutcome: 'completed',
            plan: [],
        }); });
        this.render();
    };
    CrusorAIRendererService.prototype.render = function () {
        var _this = this;
        this.noteSession();
        if (this.mounts.size === 0 || this.renderFrame !== undefined) {
            return;
        }
        this.renderFrame = requestAnimationFrame(function () {
            _this.renderFrame = undefined;
            var model = _this.model;
            for (var _i = 0, _a = _this.mounts; _i < _a.length; _i++) {
                var mount = _a[_i];
                mount.update(model);
            }
        });
    };
    CrusorAIRendererService.prototype.scheduleRestart = function () {
        var _this = this;
        if (this.restartTimer !== undefined || this.mounts.size === 0 || this.restartAttempts >= 3) {
            return;
        }
        if (this.configurationService.getValue('crusorai.autoStart') === false) {
            return;
        }
        var delay = 1000 * (Math.pow(2, this.restartAttempts));
        this.restartTimer = setTimeout(function () {
            _this.restartTimer = undefined;
            _this.restartAttempts += 1;
            void _this.ensureEngine();
        }, delay);
    };
    CrusorAIRendererService.prototype.ensureEngine = function () {
        return __awaiter(this, void 0, Promise, function () {
            var workspace, resumeSession;
            var _this = this;
            return __generator(this, function (_a) {
                if (this.engineService.state === CrusorAIEngineState.Ready) {
                    return [2 /*return*/];
                }
                if (this.startPromise) {
                    return [2 /*return*/, this.startPromise];
                }
                workspace = this.workspacePath;
                if (!workspace) {
                    this.engineSetupError = false;
                    // Field 2026-09-05: a dead engine with zero log lines is
                    // undebuggable — every quiet path out of start() must speak.
                    console.warn('[CrusorAI] engine start skipped: no workspace folder is open. Open a folder to enable the agent.');
                    return [2 /*return*/];
                }
                this.error = undefined;
                resumeSession = this.sessionId;
                this.startPromise = this.engineService.start(workspace).then(function () {
                    _this.engineSetupError = false;
                    if (_this.engineService.state !== CrusorAIEngineState.Ready) {
                        return;
                    }
                    // The durable list is the session surface's memory: refresh it on every (re)connect.
                    _this.requestSessionList();
                    if (resumeSession) {
                        _this.publishHostCapabilities(resumeSession);
                        _this.send({ type: 'session_resume', session_id: resumeSession, workspace: workspace });
                        _this.send({ type: 'events_replay', session_id: resumeSession });
                        return;
                    }
                    // Fresh window, remembered session: land back where the user was (Hermes restores
                    // the last open session per profile). The journal stays out -- the transcript
                    // hydrates from the paged checkpoints, exactly like an in-app switch.
                    var remembered = _this.getRememberedSession();
                    if (remembered) {
                        _this.sessionId = remembered;
                        _this.publishHostCapabilities(remembered);
                        _this.pendingHydration = remembered;
                        _this.send({ type: 'session_resume', session_id: remembered, workspace: workspace, include_events: false });
                        _this.send({ type: 'session_messages', session_id: remembered, workspace: workspace, limit: 120, order: 'latest' });
                    }
                }).catch(function (error) {
                    _this.engineSetupError = error instanceof CrusorAIEngineSetupError;
                    _this.error = error instanceof Error ? error.message : String(error);
                    console.error('[CrusorAI] engine start failed:', _this.error);
                }).finally(function () {
                    _this.startPromise = undefined;
                    _this.render();
                });
                return [2 /*return*/, this.startPromise];
            });
        });
    };
    CrusorAIRendererService.prototype.openManagerWindow = function () {
        return __awaiter(this, void 0, Promise, function () {
            var auxiliaryWindow, container, root, mount;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        // Opening the manager IS what "read" means, and it is the only honest clear for the
                        // attention dot: the workbench's own list keeps its persisted tracking instead.
                        if (this.sessionId) {
                            this.sessionStore.markRead(this.sessionId, true);
                        }
                        return [4 /*yield*/, this.auxiliaryWindowService.open({
                                bounds: { x: 200, y: 100, width: 1100, height: 750 },
                            })];
                    case 1:
                        auxiliaryWindow = _a.sent();
                        container = auxiliaryWindow.container;
                        auxiliaryWindow.window.document.title = 'Crusor Manager';
                        root = document.createElement('div');
                        root.className = 'crusorai-render-root crusorai-manager-editor';
                        root.dataset.surface = 'manager';
                        root.style.width = '100%';
                        root.style.height = '100%';
                        container.appendChild(root);
                        mount = mountCrusorAIRenderer(root, 'manager', this.host);
                        mount.update(this.model);
                        this._register(toDisposable(function () { return mount.dispose(); }));
                        return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIRendererService.prototype.publishHostCapabilities = function (sessionId) {
        if (sessionId === void 0) { sessionId = this.sessionId; }
        var workspace = this.workspacePath;
        if (!sessionId || !workspace || this.engineService.state !== CrusorAIEngineState.Ready) {
            return;
        }
        var statuses = new Map(this.workbenchService.getCapabilities().map(function (item) { return [item.id, item]; }));
        var readIds = new Set([
            'workspace.trust', 'editor.activeSelection', 'editor.dirtyText',
            'diagnostics.markers', 'language.symbols', 'language.definitions',
            'language.references', 'search.workspace', 'scm.state',
            'preview.open',
        ]);
        var capabilities = CRUSOR_AI_WORKBENCH_CAPABILITIES
            .filter(function (item) { return item.risk === 'read' && readIds.has(item.id); })
            .map(function (item) { return (__assign(__assign({}, item), statuses.get(item.id))); });
        this.send({ type: 'host_capabilities_update', session_id: sessionId, workspace: workspace, capabilities: capabilities });
    };
    CrusorAIRendererService.prototype.invokeHostCapability = function (frame) {
        return __awaiter(this, void 0, Promise, function () {
            var started, workspace, args, status, result, _a, url, outcome, resources, line, column, _b, requested, maxResults, error_1;
            var _c, _d, _e, _f;
            return __generator(this, function (_g) {
                switch (_g.label) {
                    case 0:
                        started = Date.now();
                        workspace = this.workspacePath;
                        if (!this.sessionId || frame.session_id !== this.sessionId || !workspace || frame.workspace !== workspace) {
                            this.send({
                                type: 'host_tool_result', session_id: frame.session_id, workspace: frame.workspace,
                                request_id: frame.request_id, status: 'error',
                                error: 'host tool request does not match the active Crusor workspace/session',
                                duration_ms: Date.now() - started,
                            });
                            return [2 /*return*/];
                        }
                        args = (_c = valueRecord(frame.arguments)) !== null && _c !== void 0 ? _c : {};
                        _g.label = 1;
                    case 1:
                        _g.trys.push([1, 22, , 23]);
                        status = this.workbenchService.getCapabilities().find(function (item) { return item.id === frame.capability_id; });
                        if ((status === null || status === void 0 ? void 0 : status.availability) !== 'available') {
                            throw new Error("host capability is ".concat((_d = status === null || status === void 0 ? void 0 : status.availability) !== null && _d !== void 0 ? _d : 'unavailable', ": ").concat(frame.capability_id));
                        }
                        result = void 0;
                        _a = frame.capability_id;
                        switch (_a) {
                            case 'workspace.trust': return [3 /*break*/, 2];
                            case 'preview.open': return [3 /*break*/, 3];
                            case 'editor.activeSelection': return [3 /*break*/, 5];
                            case 'editor.dirtyText': return [3 /*break*/, 7];
                            case 'diagnostics.markers': return [3 /*break*/, 9];
                            case 'language.symbols': return [3 /*break*/, 10];
                            case 'language.definitions': return [3 /*break*/, 12];
                            case 'language.references': return [3 /*break*/, 12];
                            case 'search.workspace': return [3 /*break*/, 17];
                            case 'scm.state': return [3 /*break*/, 19];
                        }
                        return [3 /*break*/, 20];
                    case 2:
                        result = { trusted: this.workbenchService.isWorkspaceTrusted() };
                        return [3 /*break*/, 21];
                    case 3:
                        url = typeof args['url'] === 'string' && args['url'].trim() ? args['url'].trim() : undefined;
                        return [4 /*yield*/, this.commandService.executeCommand('crusorai.openPreview', url ? { url: url } : undefined)];
                    case 4:
                        outcome = _g.sent();
                        result = __assign(__assign({ opened: (outcome === null || outcome === void 0 ? void 0 : outcome.ok) !== false }, ((outcome === null || outcome === void 0 ? void 0 : outcome.ok) === false ? { refused_reason: (_e = outcome.reason) !== null && _e !== void 0 ? _e : 'the preview could not be opened' } : {})), (url ? { url: url } : {}));
                        return [3 /*break*/, 21];
                    case 5: return [4 /*yield*/, this.workbenchService.getActiveEditorContext(args['includeVisibleText'] === true)];
                    case 6:
                        result = _g.sent();
                        return [3 /*break*/, 21];
                    case 7: return [4 /*yield*/, this.workbenchService.getActiveEditorContext(true)];
                    case 8:
                        result = _g.sent();
                        return [3 /*break*/, 21];
                    case 9:
                        {
                            resources = Array.isArray(args['resources'])
                                ? args['resources'].filter(function (item) { return typeof item === 'string'; }).slice(0, 50)
                                : undefined;
                            result = this.workbenchService.getDiagnostics(resources);
                            return [3 /*break*/, 21];
                        }
                        _g.label = 10;
                    case 10:
                        if (typeof args['resource'] !== 'string') {
                            throw new Error('language.symbols requires resource');
                        }
                        return [4 /*yield*/, this.workbenchService.getDocumentSymbols(args['resource'])];
                    case 11:
                        result = _g.sent();
                        return [3 /*break*/, 21];
                    case 12:
                        if (typeof args['resource'] !== 'string') {
                            throw new Error("".concat(frame.capability_id, " requires resource"));
                        }
                        line = Number(args['line']);
                        column = Number(args['column']);
                        if (!Number.isInteger(line) || line < 1 || !Number.isInteger(column) || column < 1) {
                            throw new Error("".concat(frame.capability_id, " requires positive integer line and column"));
                        }
                        if (!(frame.capability_id === 'language.definitions')) return [3 /*break*/, 14];
                        return [4 /*yield*/, this.workbenchService.getDefinitions(args['resource'], line, column)];
                    case 13:
                        _b = _g.sent();
                        return [3 /*break*/, 16];
                    case 14: return [4 /*yield*/, this.workbenchService.getReferences(args['resource'], line, column)];
                    case 15:
                        _b = _g.sent();
                        _g.label = 16;
                    case 16:
                        result = _b;
                        return [3 /*break*/, 21];
                    case 17:
                        if (typeof args['query'] !== 'string' || !args['query'].trim()) {
                            throw new Error('search.workspace requires query');
                        }
                        requested = Number((_f = args['maxResults']) !== null && _f !== void 0 ? _f : 100);
                        maxResults = Number.isFinite(requested) ? Math.max(1, Math.min(Math.trunc(requested), 500)) : 100;
                        return [4 /*yield*/, this.workbenchService.searchWorkspace(args['query'], maxResults)];
                    case 18:
                        result = _g.sent();
                        return [3 /*break*/, 21];
                    case 19:
                        result = this.workbenchService.getSCMState();
                        return [3 /*break*/, 21];
                    case 20: throw new Error("host capability is not allowed: ".concat(frame.capability_id));
                    case 21:
                        this.send({
                            type: 'host_tool_result', session_id: frame.session_id,
                            workspace: workspace,
                            request_id: frame.request_id, status: 'ok',
                            result: result,
                            duration_ms: Date.now() - started,
                        });
                        return [3 /*break*/, 23];
                    case 22:
                        error_1 = _g.sent();
                        this.send({
                            type: 'host_tool_result', session_id: frame.session_id,
                            workspace: workspace,
                            request_id: frame.request_id, status: 'error',
                            error: error_1 instanceof Error ? error_1.message : String(error_1),
                            duration_ms: Date.now() - started,
                        });
                        return [3 /*break*/, 23];
                    case 23: return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIRendererService.prototype.submitPrompt = function (text) {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: 
                    // A bounded wait, not an unbounded one: ensureEngine resolves when
                    // start() settles, but a wedged sidecar must not eat the user's
                    // click forever (field 2026-09-05: "send button not working" — the
                    // click died in the old silent not-ready return with ZERO feedback).
                    return [4 /*yield*/, Promise.race([
                            this.ensureEngine(),
                            new Promise(function (resolve) { return setTimeout(resolve, 20000); }),
                        ])];
                    case 1:
                        // A bounded wait, not an unbounded one: ensureEngine resolves when
                        // start() settles, but a wedged sidecar must not eat the user's
                        // click forever (field 2026-09-05: "send button not working" — the
                        // click died in the old silent not-ready return with ZERO feedback).
                        _a.sent();
                        if (this.engineService.state !== CrusorAIEngineState.Ready) {
                            // The one dishonest thing the old code did: return silently. The
                            // user typed a prompt and pressed send; the panel owes them the
                            // state of the engine and an action (hermes: state the fact,
                            // keep an option). start() failures already paint their own
                            // message — only the quiet paths get words here. The draft is
                            // preserved (cleared only after the ready check below).
                            console.warn("[CrusorAI] prompt not sent: engine state=".concat(this.engineService.state, ", workspace=").concat(this.workspacePath ? 'ok' : 'MISSING'));
                            if (!this.error) {
                                this.error = "Crusor engine is ".concat(this.engineService.state, " \u2014 not accepting prompts yet. Give it a moment, or retry from the Manager panel.");
                            }
                            this.render();
                            return [2 /*return*/];
                        }
                        this.draft = '';
                        this.error = undefined;
                        if (!this.sessionId) {
                            this.pendingPrompt = text;
                            this.send({ type: 'session_create', workspace: this.workspacePath });
                            this.render();
                            return [2 /*return*/];
                        }
                        this.startTurn(text);
                        return [2 /*return*/];
                }
            });
        });
    };
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
    CrusorAIRendererService.prototype.beginExternalTurn = function (text) {
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
    };
    /** Push the live turn (if any) into history before a new one replaces it. */
    CrusorAIRendererService.prototype.archiveLiveTurn = function () {
        if (!(this.userMessage || this.assistantText || this.tools.size > 0)) {
            return;
        }
        this.history = __spreadArray(__spreadArray([], this.history, true), [{
                userMessage: this.userMessage,
                assistantText: this.assistantText,
                parts: __spreadArray([], this.parts, true),
                reasoningParts: this.reasoningParts,
                reasoningPending: this.reasoningPending,
                tools: __spreadArray([], this.tools.values(), true),
                subAgents: __spreadArray([], this.subAgents.values(), true),
                turnOutcome: this.turnOutcome,
                interrupt: this.interrupt,
                plan: this.plan,
            }], false).slice(-20); // keep last 20 turns
    };
    /** Measure the brake at turn end: which tool calls had already landed. */
    CrusorAIRendererService.prototype.stampInterrupt = function () {
        var landed = 0;
        var dropped = 0;
        for (var _i = 0, _a = this.tools.values(); _i < _a.length; _i++) {
            var tool = _a[_i];
            if (tool.state === 'queued' || tool.state === 'approval' || tool.state === 'running') {
                dropped++;
            }
            else {
                landed++;
            }
        }
        return { landed: landed, dropped: dropped };
    };
    /** Fresh-turn state: the user's text becomes the bubble; everything else clears. */
    CrusorAIRendererService.prototype.resetTurnState = function (text) {
        this.interrupt = undefined;
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
    };
    CrusorAIRendererService.prototype.startTurn = function (text) {
        this.archiveLiveTurn();
        this.resetTurnState(text);
        this.send({ type: 'prompt', session_id: this.sessionId, workspace: this.workspacePath, text: text, mode: this.mode, reasoning_effort: this.reasoningEffort || undefined });
        this.render();
    };
    /**
     * Timeline writers (hermes parts ingestion): text extends the LAST text
     * segment — a token that follows tool calls opens a NEW segment instead of
     * teleporting into the pre-tool text, which is what keeps interleave order
     * truthful. Tools pin their position once; updates go through the tools
     * map, never the timeline.
     */
    CrusorAIRendererService.prototype.appendTextPart = function (chunk) {
        if (!chunk) {
            return;
        }
        var last = this.parts[this.parts.length - 1];
        if ((last === null || last === void 0 ? void 0 : last.kind) === 'text') {
            this.parts[this.parts.length - 1] = { kind: 'text', text: last.text + chunk };
        }
        else {
            this.parts.push({ kind: 'text', text: chunk });
        }
    };
    CrusorAIRendererService.prototype.pushToolPart = function (toolId) {
        if (!toolId || this.parts.some(function (p) { return p.kind === 'tool' && p.toolId === toolId; })) {
            return;
        }
        this.parts.push({ kind: 'tool', toolId: toolId });
    };
    CrusorAIRendererService.prototype.sendSkillsHubOp = function (op, extra) {
        this.send(__assign({ type: 'skills_hub_op', session_id: this.sessionId, op: op }, (extra !== null && extra !== void 0 ? extra : {})));
    };
    CrusorAIRendererService.prototype.onSkillsHubResult = function (listener) {
        var _this = this;
        this._hubListeners.add(listener);
        return toDisposable(function () { return _this._hubListeners.delete(listener); });
    };
    /**
     * One skills_hub_op request → its result dict (the Manager Skills tab's
     * bridge). Same contract the palette's hubRequest uses: one matching
     * frame, bounded wait, hard failure named — the tab paints it inline
     * instead of hanging on a silent panel. Palette flows are modal, so a
     * same-op request from QuickPick and this method cannot race in practice;
     * within this method the tab's parallel reads use distinct ops.
     */
    CrusorAIRendererService.prototype.skillsHubOp = function (op, extra) {
        var _this = this;
        if (extra === void 0) { extra = {}; }
        return new Promise(function (resolve, reject) {
            var listener;
            var timer = setTimeout(function () {
                listener === null || listener === void 0 ? void 0 : listener.dispose();
                reject(new Error("the engine did not answer the '".concat(op, "' request \u2014 fully restart CrusorAI so the bridge runs the current build.")));
            }, 12000);
            listener = _this.onSkillsHubResult(function (frame) {
                var _a;
                if (frame.op !== op) {
                    return;
                }
                clearTimeout(timer);
                listener === null || listener === void 0 ? void 0 : listener.dispose();
                resolve(((_a = frame.result) !== null && _a !== void 0 ? _a : {}));
            });
            // connector ops (probe / attach / detach) read and write the
            // WORKSPACE's .crusorai/mcp.json — the engine has no other way
            // to know which folder is open.
            _this.sendSkillsHubOp(op, (op.startsWith('connector') || op === 'skill_create') ? __assign(__assign({}, extra), { workspace: _this.workspacePath }) : extra);
        });
    };
    CrusorAIRendererService.prototype.sendOneshot = function (template, extra) {
        this.send(__assign({ type: 'oneshot', session_id: this.sessionId, template: template }, (extra !== null && extra !== void 0 ? extra : {})));
    };
    CrusorAIRendererService.prototype.onOneshotResult = function (listener) {
        var _this = this;
        this._oneshotListeners.add(listener);
        return toDisposable(function () { return _this._oneshotListeners.delete(listener); });
    };
    CrusorAIRendererService.prototype._emitOneshotResult = function (frame) {
        for (var _i = 0, _a = Array.from(this._oneshotListeners); _i < _a.length; _i++) {
            var listener = _a[_i];
            try {
                listener(frame);
            }
            catch (_b) {
                // isolated on purpose
            }
        }
    };
    CrusorAIRendererService.prototype._emitSkillsHubResult = function (frame) {
        for (var _i = 0, _a = Array.from(this._hubListeners); _i < _a.length; _i++) {
            var listener = _a[_i];
            try {
                listener(frame);
            }
            catch (_b) {
                // isolated on purpose — a broken listener must not break the chain
            }
        }
    };
    CrusorAIRendererService.prototype.send = function (frame) {
        try {
            this.engineService.send(frame);
        }
        catch (error) {
            this.error = error instanceof Error ? error.message : String(error);
            this.render();
        }
    };
    /**
     * Hermes session-states.ts watchdog, 5-minute window (their tuning note:
     * under ~4min paints healthy typechecks/test runs as suspect; 8min arrives
     * after the user gave up). One timer per turn; every frame re-arms it via
     * acceptFrame. Firing only flips the presentation hint.
     */
    CrusorAIRendererService.prototype.armStallWatchdog = function () {
        var _this = this;
        this.clearStallWatchdog();
        this.stallWatchdog = window.setTimeout(function () {
            _this.stallWatchdog = undefined;
            if (_this.running) {
                _this.stalled = true;
                _this.render();
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
        var _isGreeting = this.tools.size === 0 && this.assistantText.length > 0;
        this.hardWatchdog = window.setTimeout(function () {
            _this.hardWatchdog = undefined;
            if (!_this.running) {
                return;
            }
            _this.running = false;
            _this.cancelRequested = false;
            _this.turnStartedAt = undefined;
            _this.turnEndedAt = Date.now();
            // Hermes parity: greeting already answered — silent complete, not failed
            if (_isGreeting) {
                _this.turnOutcome = 'completed';
                _this.error = undefined;
                _this.degraded = undefined;
            }
            else {
                _this.turnOutcome = 'failed';
                _this.error = 'The engine stopped responding — the turn was ended locally. The reply above is everything it produced; send another message to continue.';
            }
            _this.stalled = undefined;
            _this.llmStatus = undefined;
            _this.clearStallWatchdog();
            _this.render();
        }, _isGreeting ? 12 * 1000 : 7 * 60 * 1000);
    };
    CrusorAIRendererService.prototype.clearHardWatchdog = function () {
        if (this.hardWatchdog !== undefined) {
            clearTimeout(this.hardWatchdog);
            this.hardWatchdog = undefined;
        }
    };
    CrusorAIRendererService.prototype.clearStallWatchdog = function () {
        if (this.stallWatchdog !== undefined) {
            window.clearTimeout(this.stallWatchdog);
            this.stallWatchdog = undefined;
        }
        this.clearHardWatchdog();
        this.stalled = undefined;
    };
    CrusorAIRendererService.prototype.acceptFrame = function (frame) {
        var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k, _l, _m, _o, _p, _q, _r, _s, _t, _u, _v, _w, _x, _y, _z, _0, _1, _2, _3, _4, _5, _6, _7, _8, _9, _10, _11;
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
            for (var _i = 0, _12 = frame.events; _i < _12.length; _i++) {
                var event = _12[_i];
                var candidate = valueRecord(event);
                if (typeof (candidate === null || candidate === void 0 ? void 0 : candidate.type) === 'string') {
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
        var foreignId = this.foreignSessionId(frame);
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
                for (var _13 = 0, _14 = frame.sessions; _13 < _14.length; _13++) {
                    var row = _14[_13];
                    this.noteEngineRow(row);
                }
            }
            if (frame.session) {
                this.noteEngineRow(frame.session);
            }
            // Stop ack from the bridge: another surface (or a queued cancel)
            // may have pulled the brake — this pane's button must agree.
            if (typeof frame.cancel_requested === 'boolean') {
                this.cancelRequested = frame.cancel_requested;
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
            var previousSessionId = this.sessionId;
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
            for (var _15 = 0, _16 = (_a = frame.subagents) !== null && _a !== void 0 ? _a : []; _15 < _16.length; _15++) {
                var row = _16[_15];
                var sid = (_b = row.subagent_id) !== null && _b !== void 0 ? _b : row.child_thread_id;
                if (!sid)
                    continue;
                var childId = (_c = row.child_thread_id) !== null && _c !== void 0 ? _c : sid;
                var parentId = (_d = row.parent_session_id) !== null && _d !== void 0 ? _d : this.sessionId;
                if (childId && parentId)
                    this.parentMap.set(childId, parentId);
                this.subAgents.set(sid, {
                    id: sid,
                    state: ((_e = row.state) !== null && _e !== void 0 ? _e : 'pending'),
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
            for (var _17 = 0, _18 = (_f = frame.events) !== null && _f !== void 0 ? _f : []; _17 < _18.length; _17++) {
                var event = _18[_17];
                var candidate = valueRecord(event);
                if (typeof (candidate === null || candidate === void 0 ? void 0 : candidate.type) === 'string') {
                    this.acceptFrame(event);
                }
            }
            if (this.pendingPrompt) {
                var prompt = this.pendingPrompt;
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
            var repaired = separateGluedReasoningBlocks(frame.text);
            var tail = this.reasoningParts[this.reasoningParts.length - 1];
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
                var reasoningIndex = this.reasoningParts.length;
                this.reasoningParts.push({ text: repaired });
                this.parts.push({ kind: 'reasoning', reasoningIndex: reasoningIndex });
            }
            this.reasoningPending = true;
        }
        else if (frame.type === 'plan_updated') {
            this.plan = frame.steps.map(planStepView);
        }
        else if (frame.type === 'tool_call_start') {
            // Seal any open reasoning part before the tool call
            var openReasoning = this.reasoningParts[this.reasoningParts.length - 1];
            if (openReasoning && !openReasoning.completedAt) {
                openReasoning.completedAt = Date.now();
            }
            this.tools.set(frame.tool_id, { id: frame.tool_id, name: frame.name, arguments: frame.arguments, state: 'running' });
            this.pushToolPart(frame.tool_id);
        }
        else if (frame.type === 'tool_call_end') {
            var existing = this.tools.get(frame.tool_id);
            var result = valueRecord(frame.result);
            this.tools.set(frame.tool_id, {
                id: frame.tool_id,
                name: (_g = existing === null || existing === void 0 ? void 0 : existing.name) !== null && _g !== void 0 ? _g : 'unknown',
                arguments: existing === null || existing === void 0 ? void 0 : existing.arguments,
                result: frame.result,
                state: toolState(frame.status),
                duration: typeof (result === null || result === void 0 ? void 0 : result.duration) === 'string' ? result.duration : typeof (result === null || result === void 0 ? void 0 : result.duration_ms) === 'number' ? "".concat(result.duration_ms, "ms") : undefined,
            });
            if (((_h = this.approval) === null || _h === void 0 ? void 0 : _h.toolId) === frame.tool_id) {
                this.approval = undefined;
            }
            if (((_j = this.clarify) === null || _j === void 0 ? void 0 : _j.toolId) === frame.tool_id) {
                this.clarify = undefined;
            }
        }
        else if (frame.type === 'safety_request') {
            var existing = this.tools.get(frame.tool_id);
            this.tools.set(frame.tool_id, { id: frame.tool_id, name: frame.name, arguments: (_l = (_k = existing === null || existing === void 0 ? void 0 : existing.arguments) !== null && _k !== void 0 ? _k : frame.arguments) !== null && _l !== void 0 ? _l : frame.diff, result: existing === null || existing === void 0 ? void 0 : existing.result, state: 'approval' });
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
            catch ( /* best effort */_19) { /* best effort */ }
        }
        else if (frame.type === 'clarify_request') {
            // Hermes ask-tool card: the batch of questions rides its own frame
            // (args alone can't drive the form — no qids to respond with).
            this.clarify = {
                requestId: frame.request_id,
                title: (_m = frame.title) !== null && _m !== void 0 ? _m : '',
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
            var items = [];
            for (var _20 = 0, _21 = frame.todos; _20 < _21.length; _20++) {
                var raw = _21[_20];
                var row = raw;
                if (row && typeof row.id === 'string' && typeof row.content === 'string') {
                    items.push(__assign({ id: row.id, content: row.content, status: row.status }, (row.parent ? { parent: row.parent } : {})));
                }
            }
            this.todos = items;
            this.todoRevision = frame.revision;
        }
        else if (frame.type === 'subagent_updated') {
            var subagent_id = frame.subagent_id;
            var existing = (_o = this.subAgents.get(subagent_id)) !== null && _o !== void 0 ? _o : { id: subagent_id, state: 'pending' };
            var state = (_p = frame.state) !== null && _p !== void 0 ? _p : existing.state;
            var duration = frame.duration;
            var result = frame.result;
            var childId = (_q = frame.child_thread_id) !== null && _q !== void 0 ? _q : subagent_id;
            var parentId = (_s = (_r = frame.parent_session_id) !== null && _r !== void 0 ? _r : frame.parentSessionId) !== null && _s !== void 0 ? _s : this.sessionId;
            var desc = (_t = frame.description) !== null && _t !== void 0 ? _t : existing.description;
            // Never self-parent: an unknown-id status reply echoes the queried id as both
            // child and parent, which would misdetect a normal session as a child.
            if (childId && parentId && childId !== parentId) {
                this.parentMap.set(childId, parentId);
            }
            // Detect if current session is child
            if (this.sessionId && this.parentMap.has(this.sessionId)) {
                this.childParentId = this.parentMap.get(this.sessionId);
            }
            this.subAgents.set(subagent_id, __assign(__assign({}, existing), { id: subagent_id, state: state, goal: (_u = frame.goal) !== null && _u !== void 0 ? _u : existing.goal, description: desc !== null && desc !== void 0 ? desc : existing.description, mode: (_v = frame.mode) !== null && _v !== void 0 ? _v : existing.mode, progress: (_w = frame.progress) !== null && _w !== void 0 ? _w : existing.progress, result: result !== null && result !== void 0 ? result : existing.result, duration: duration !== null && duration !== void 0 ? duration : existing.duration, parentSessionId: parentId !== null && parentId !== void 0 ? parentId : existing.parentSessionId, childThreadId: childId !== null && childId !== void 0 ? childId : existing.childThreadId, background: (_x = frame.background) !== null && _x !== void 0 ? _x : existing.background, toolCalls: (_z = (_y = frame.tool_calls) !== null && _y !== void 0 ? _y : frame.toolCalls) !== null && _z !== void 0 ? _z : existing.toolCalls, agentName: (_1 = (_0 = frame.agent_name) !== null && _0 !== void 0 ? _0 : frame.agentName) !== null && _1 !== void 0 ? _1 : existing.mode }));
        }
        else if (frame.type === 'skills_hub_result') {
            this._emitSkillsHubResult(frame);
        }
        else if (frame.type === 'oneshot_result') {
            this._emitOneshotResult(frame);
        }
        else if (frame.type === 'subagent_list') {
            // OpenCode parity: list children for parent
            for (var _22 = 0, _23 = (_2 = frame.subagents) !== null && _2 !== void 0 ? _2 : []; _22 < _23.length; _22++) {
                var row = _23[_22];
                var sid = (_3 = row.subagent_id) !== null && _3 !== void 0 ? _3 : row.child_thread_id;
                if (!sid)
                    continue;
                var childId = (_4 = row.child_thread_id) !== null && _4 !== void 0 ? _4 : sid;
                var parentId = (_5 = row.parent_session_id) !== null && _5 !== void 0 ? _5 : this.sessionId;
                if (childId && parentId)
                    this.parentMap.set(childId, parentId);
                this.subAgents.set(sid, {
                    id: sid,
                    state: ((_6 = row.state) !== null && _6 !== void 0 ? _6 : 'pending'),
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
            var subId = frame.subagent_id;
            var text = (_7 = frame.text) !== null && _7 !== void 0 ? _7 : '';
            if (text) {
                this.assistantText += text;
                this.appendTextPart(text);
            }
            if (subId) {
                var existing = this.subAgents.get(subId);
                if (existing) {
                    this.subAgents.set(subId, __assign(__assign({}, existing), { state: 'completed', result: text }));
                }
            }
        }
        else if (frame.type === 'verification_updated') {
            this.verification = frame.status;
        }
        else if (frame.type === 'telemetry') {
            this.telemetry = __assign(__assign({}, this.telemetry), { input: frame.input, output: frame.output, cache: frame.cache, cost: frame.cost });
        }
        else if (frame.type === 'turn_done') {
            this.running = false;
            if (frame.cancelled === true) {
                this.interrupt = this.stampInterrupt();
            }
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
            var openR = this.reasoningParts[this.reasoningParts.length - 1];
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
            this.voiceHeard = { ok: frame.ok, text: (_8 = frame.text) !== null && _8 !== void 0 ? _8 : '', error: frame.error };
        }
        else if (frame.type === 'llm.request') {
            this.llmStatus = { model: (_9 = frame.model) !== null && _9 !== void 0 ? _9 : '', attempt: (_10 = frame.attempt) !== null && _10 !== void 0 ? _10 : 1 };
            this.llmHeads = frame.messages;
            this.hadProviderAttempt = true;
        }
        else if (frame.type === 'llm.response') {
            this.llmStatus = undefined;
            this.llmHeads = undefined;
        }
        else if (frame.type === 'context_status') {
            var severity = frame.severity === 'warning' ? 'warning' : 'info';
            if (frame.phase === 'compacted') {
                this.compacting = undefined;
            }
            else if (frame.phase === 'compress' || frame.phase === 'pre_api') {
                this.compacting = true;
            }
            this.contextStatus = {
                message: frame.message,
                severity: severity,
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
            var forId = (_11 = frame.requested_session_id) !== null && _11 !== void 0 ? _11 : frame.session_id;
            if (forId !== this.pendingHydration && forId !== this.sessionId) {
                return;
            }
            this.pendingHydration = undefined;
            this.hydrateTranscript(frame.messages);
            return;
        }
        else if (frame.type === 'session_deleted') {
            var deletedId = frame.session_id;
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
    };
    CrusorAIRendererService.prototype.rememberEvent = function (eventId) {
        if (this.seenEventIds.has(eventId)) {
            return false;
        }
        this.seenEventIds.add(eventId);
        this.eventIdOrder.push(eventId);
        if (this.eventIdOrder.length > 20000) {
            var removed = this.eventIdOrder.splice(0, 2000);
            for (var _i = 0, removed_1 = removed; _i < removed_1.length; _i++) {
                var id = removed_1[_i];
                this.seenEventIds.delete(id);
            }
        }
        return true;
    };
    CrusorAIRendererService.prototype.openDiff = function (toolId) {
        return __awaiter(this, void 0, Promise, function () {
            var tool, approval, sources, original, modified, originalText, modifiedText, resource, _i, sources_1, source, value, label, error_2;
            var _a, _b;
            return __generator(this, function (_c) {
                switch (_c.label) {
                    case 0:
                        _c.trys.push([0, 4, , 5]);
                        tool = this.tools.get(toolId);
                        approval = ((_a = this.approval) === null || _a === void 0 ? void 0 : _a.toolId) === toolId ? this.approval.diff : undefined;
                        sources = [approval, tool === null || tool === void 0 ? void 0 : tool.result, tool === null || tool === void 0 ? void 0 : tool.arguments];
                        original = void 0;
                        modified = void 0;
                        originalText = void 0;
                        modifiedText = void 0;
                        resource = void 0;
                        for (_i = 0, sources_1 = sources; _i < sources_1.length; _i++) {
                            source = sources_1[_i];
                            value = valueRecord(source);
                            original !== null && original !== void 0 ? original : (original = stringField(source, ['original_uri', 'original', 'before_uri', 'base_uri']));
                            modified !== null && modified !== void 0 ? modified : (modified = stringField(source, ['modified_uri', 'modified', 'after_uri']));
                            resource !== null && resource !== void 0 ? resource : (resource = stringField(source, ['resource', 'file_path', 'path', 'relative_path']));
                            if (originalText === undefined && value && 'old_text' in value && (typeof value.old_text === 'string' || value.old_text === null)) {
                                originalText = typeof value.old_text === 'string' ? value.old_text : '';
                            }
                            if (modifiedText === undefined && typeof (value === null || value === void 0 ? void 0 : value.new_text) === 'string') {
                                modifiedText = value.new_text;
                            }
                            if (modifiedText === undefined && typeof (value === null || value === void 0 ? void 0 : value.content) === 'string') {
                                modifiedText = value.content;
                            }
                        }
                        label = "Crusor: ".concat((_b = tool === null || tool === void 0 ? void 0 : tool.name) !== null && _b !== void 0 ? _b : 'proposed change');
                        if (originalText === undefined && modifiedText !== undefined && resource) {
                            originalText = '';
                        }
                        if (!(originalText !== undefined && modifiedText !== undefined)) return [3 /*break*/, 2];
                        return [4 /*yield*/, this.workbenchService.openInlineDiff(__assign({ toolId: toolId, label: label, original: originalText, modified: modifiedText }, (resource ? { resource: resource } : {})))];
                    case 1:
                        _c.sent();
                        return [2 /*return*/];
                    case 2:
                        modified !== null && modified !== void 0 ? modified : (modified = resource);
                        if (!original || !modified) {
                            throw new Error('This tool receipt does not include inline text or native original/modified diff resources.');
                        }
                        return [4 /*yield*/, this.workbenchService.openNativeDiff(this.resourceUri(original).toString(), this.resourceUri(modified).toString(), label)];
                    case 3:
                        _c.sent();
                        return [3 /*break*/, 5];
                    case 4:
                        error_2 = _c.sent();
                        this.error = error_2 instanceof Error ? error_2.message : String(error_2);
                        this.render();
                        return [3 /*break*/, 5];
                    case 5: return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIRendererService.prototype.resourceBrowserSrc = function (resource) {
        // file:// is not loadable from the workbench DOM; FileAccess translates
        // it to the scheme the renderer may fetch (same path resolution as
        // revealFile — Windows drives, schemes, workspace-relative).
        try {
            return FileAccess.uriToBrowserUri(this.resourceUri(resource)).toString(true);
        }
        catch (error) {
            return undefined;
        }
    };
    CrusorAIRendererService.prototype.revealFile = function (resource) {
        return __awaiter(this, void 0, Promise, function () {
            var error_3;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        _a.trys.push([0, 2, , 3]);
                        return [4 /*yield*/, this.workbenchService.openResource(this.resourceUri(resource).toString())];
                    case 1:
                        _a.sent();
                        return [3 /*break*/, 3];
                    case 2:
                        error_3 = _a.sent();
                        this.error = error_3 instanceof Error ? error_3.message : String(error_3);
                        this.render();
                        return [3 /*break*/, 3];
                    case 3: return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIRendererService.prototype.notifyResponseReady = function (detail, isError) {
        var _this = this;
        if (isError === void 0) { isError = false; }
        try {
            if (this.configurationService.getValue('crusorai.notifyOnComplete') === false) {
                return;
            }
            var msg = isError ? 'Crusor — task ended with an issue' : 'Response Ready — Crusor';
            var detailLine = detail ? String(detail).split('\n')[0].slice(0, 160) : '';
            this.notificationService.notify({
                severity: isError ? Severity.Warning : Severity.Info,
                message: msg,
                source: detailLine ? "".concat(detailLine) : 'Crusor Agent finished',
                actions: {
                    primary: [{
                            id: CrusorAICommandId.Focus,
                            label: 'Open Crusor',
                            tooltip: 'Focus Crusor Agent',
                            enabled: true,
                            run: function () { void _this.commandService.executeCommand(CrusorAICommandId.Focus); }
                        }]
                }
            });
        }
        catch ( /* notification must never break turn */_a) { /* notification must never break turn */ }
    };
    CrusorAIRendererService.prototype.resourceUri = function (resource) {
        var folder = this.workspaceContextService.getWorkspace().folders[0];
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
        var gitBash = /^\/([a-z])\/(.*)$/i.exec(resource);
        if (gitBash) {
            return URI.file("".concat(gitBash[1].toUpperCase(), ":/").concat(gitBash[2]));
        }
        if (/^(?:[a-z]:[\\/]|[\\/])/i.test(resource)) {
            return URI.file(resource);
        }
        if (/^[a-z][a-z0-9+.-]*:/i.test(resource)) {
            return URI.parse(resource);
        }
        return folder ? URI.joinPath(folder.uri, resource) : URI.file(resource);
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
    return CrusorAIRendererService;
}(Disposable));
export { CrusorAIRendererService };
