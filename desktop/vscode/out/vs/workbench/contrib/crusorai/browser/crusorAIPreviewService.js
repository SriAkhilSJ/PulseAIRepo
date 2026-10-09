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
import { Disposable, DisposableStore, MutableDisposable, toDisposable } from '../../../../base/common/lifecycle.js';
import { isWindows } from '../../../../base/common/platform.js';
import { Emitter } from '../../../../base/common/event.js';
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
import { CrusorPreviewSource, CrusorPreviewWindowCommand, CrusorPreviewWindowEvent, buildPreviewPrompt, buildPreviewRelaunchPrompt, detectPreviewAvailability, evidenceFromToolCall, isBatchEmpty, previewWindowQuery, summarizeBatch, } from '../common/crusorAIPreview.js';
import { installCrusorTheme } from './crusorTheme.js';
export var ICrusorAIPreviewService = createDecorator('crusorAIPreviewService');
/** The preview window chrome, as shipped inside the app. */
var PREVIEW_WINDOW_RESOURCE = 'vs/workbench/contrib/crusorai/browser/media/crusor-preview/index.html';
var ENDPOINT_DIR = ['preview'];
var CrusorAIPreviewService = /** @class */ (function (_super) {
    __extends(CrusorAIPreviewService, _super);
    function CrusorAIPreviewService(engine, auxiliaryWindows, pathService, fileService, themeService, workspaceService, editorService, sessionStore, renderer, commandService, logService, requestService, notificationService) {
        var _this = _super.call(this) || this;
        _this.engine = engine;
        _this.auxiliaryWindows = auxiliaryWindows;
        _this.pathService = pathService;
        _this.fileService = fileService;
        _this.themeService = themeService;
        _this.workspaceService = workspaceService;
        _this.editorService = editorService;
        _this.sessionStore = sessionStore;
        _this.renderer = renderer;
        _this.commandService = commandService;
        _this.logService = logService;
        _this.requestService = requestService;
        _this.notificationService = notificationService;
        _this._onDidChangeAvailability = _this._register(new Emitter());
        _this.onDidChangeAvailability = _this._onDidChangeAvailability.event;
        _this._onDidChangeWindow = _this._register(new Emitter());
        _this.onDidChangeWindow = _this._onDidChangeWindow.event;
        _this._onDidChangeHealth = _this._register(new Emitter());
        _this.onDidChangeHealth = _this._onDidChangeHealth.event;
        /** The preview target's observed state (drives the Preview tab's color and click behavior). */
        _this._health = 'closed';
        /** Set when a preview-sourced turn is dispatched; consumed at that turn's end to reload the frame. */
        _this.pendingPreviewTurn = false;
        /** Per-session turnEndedAt high-water marks: detects a COMPLETED turn without guessing from event shapes. */
        _this.lastSeenTurnEnd = new Map();
        /** Evidence accumulates for the whole session: a dev server started ten turns ago still counts. */
        _this.evidence = [];
        _this._availability = { available: false, reason: '' };
        _this.host = _this._register(new MutableDisposable());
        /** Dedupe for target-error notifications: one toast per outage, not one per Reload click. */
        _this.lastTargetError = { url: '', at: 0 };
        _this._register(_this.engine.onDidReceiveFrame(function (frame) { return _this.absorb(frame); }));
        // Turn-end watcher: when a preview-sourced turn completes, command the
        // window to reload so the fix (or the relaunch) is VISIBLE without the
        // user pressing anything. Session records carry turnEndedAt.
        _this._register(_this.sessionStore.onDidChange(function () { return _this.onSessionsChanged(); }));
        return _this;
    }
    Object.defineProperty(CrusorAIPreviewService.prototype, "isWindowOpen", {
        get: function () { return this.host.value !== undefined; },
        enumerable: false,
        configurable: true
    });
    Object.defineProperty(CrusorAIPreviewService.prototype, "availability", {
        get: function () {
            return this._availability;
        },
        enumerable: false,
        configurable: true
    });
    Object.defineProperty(CrusorAIPreviewService.prototype, "health", {
        get: function () {
            return this._health;
        },
        set: function (next) {
            if (this._health === next) {
                return;
            }
            this._health = next;
            this._onDidChangeHealth.fire(next);
        },
        enumerable: false,
        configurable: true
    });
    /** Turn-end watcher: reload the live window the moment a preview turn completes. */
    CrusorAIPreviewService.prototype.onSessionsChanged = function () {
        var _a, _b;
        if (!this.pendingPreviewTurn) {
            return;
        }
        for (var _i = 0, _c = this.sessionStore.records(); _i < _c.length; _i++) {
            var record = _c[_i];
            var ended = (_a = record.turnEndedAt) !== null && _a !== void 0 ? _a : 0;
            var seen = (_b = this.lastSeenTurnEnd.get(record.sessionId)) !== null && _b !== void 0 ? _b : 0;
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
    };
    /**
     * Retarget the live window at the RAW target with a FRESH endpoint handshake.
     * The window re-registers through the proxy and frames the inspectable copy —
     * sending the raw URL alone used to make it frame the dev server directly:
     * a green chip on a window no click could ever inspect. The secret rotates
     * on every proxy restart, so it is re-read here, not cached.
     */
    CrusorAIPreviewService.prototype.retargetWindow = function (frame) {
        return __awaiter(this, void 0, Promise, function () {
            var endpoint;
            var _a, _b, _c, _d, _e, _f, _g, _h;
            return __generator(this, function (_j) {
                switch (_j.label) {
                    case 0: return [4 /*yield*/, this.resolveEndpoint()];
                    case 1:
                        endpoint = _j.sent();
                        if (!endpoint) {
                            this.logService.warn('[crusor-preview] retarget: proxy gone — leaving the window on its last frame');
                            return [2 /*return*/];
                        }
                        this.postToWindow(frame, CrusorPreviewWindowCommand.SetTarget, {
                            target: (_b = (_a = this.currentTarget) === null || _a === void 0 ? void 0 : _a.url) !== null && _b !== void 0 ? _b : '',
                            file: (_d = (_c = this.currentTarget) === null || _c === void 0 ? void 0 : _c.file) !== null && _d !== void 0 ? _d : '',
                            label: (_f = (_e = this.currentTarget) === null || _e === void 0 ? void 0 : _e.label) !== null && _f !== void 0 ? _f : '',
                            kind: ((_g = this.currentTarget) === null || _g === void 0 ? void 0 : _g.file) ? 'file' : 'url',
                            endpoint: endpoint.origin,
                            secret: (_h = endpoint.secret) !== null && _h !== void 0 ? _h : '',
                        });
                        return [2 /*return*/];
                }
            });
        });
    };
    /** Fold a streamed frame into the evidence that decides availability (step 1). */
    CrusorAIPreviewService.prototype.absorb = function (frame) {
        var record = frame;
        if ((record === null || record === void 0 ? void 0 : record.type) !== 'tool_call_start' || !record.name) {
            return;
        }
        var evidence = evidenceFromToolCall(record.name, record.arguments);
        if (!evidence) {
            return;
        }
        this.evidence.push(evidence);
        if (this.evidence.length > 400) {
            this.evidence.splice(0, this.evidence.length - 400);
        }
        var next = detectPreviewAvailability(this.evidence);
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
    };
    // ── the endpoint (src/preview/endpoint.py publishes it; the IDE only reads) ───────────────
    /**
     * True liveness probe: `started_at` in the registration file is the proxy's boot time, not a
     * health signal, so an old file says nothing about the proxy behind it. Any HTTP answer (even
     * an error status) proves the process is listening; only a connection failure means it is gone.
     * The request runs through the main process, so the renderer CSP's connect-src list does not
     * apply to this loopback GET.
     */
    CrusorAIPreviewService.prototype.proxyAlive = function (endpoint) {
        return __awaiter(this, void 0, Promise, function () {
            var health, _a;
            var _b;
            return __generator(this, function (_c) {
                switch (_c.label) {
                    case 0:
                        if (!endpoint.origin) {
                            return [2 /*return*/, false];
                        }
                        health = "".concat(endpoint.origin.replace(/\/$/, '')).concat((_b = endpoint.health_path) !== null && _b !== void 0 ? _b : '/crusor-preview/health');
                        _c.label = 1;
                    case 1:
                        _c.trys.push([1, 3, , 4]);
                        return [4 /*yield*/, this.requestService.request({ type: 'GET', url: health, timeout: 3000, callSite: 'crusorAIPreviewService.proxyAlive' }, CancellationToken.None)];
                    case 2:
                        _c.sent();
                        return [2 /*return*/, true];
                    case 3:
                        _a = _c.sent();
                        return [2 /*return*/, false];
                    case 4: return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIPreviewService.prototype.endpointDirectory = function () {
        return URI.joinPath.apply(URI, __spreadArray([this.pathService.userHome({ preferLocal: true }), '.crusorai'], ENDPOINT_DIR, false));
    };
    Object.defineProperty(CrusorAIPreviewService.prototype, "workspacePath", {
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
        get: function () {
            var folders = this.workspaceService.getWorkspace().folders;
            return folders.length === 1 ? folders[0].uri.fsPath : undefined;
        },
        enumerable: false,
        configurable: true
    });
    /**
     * The freshest published endpoint for this workspace. The proxy writes one file per session, and
     * the workbench is not told which session id owns the local proxy, so the workspace path decides:
     * a preview server started for THIS folder is the one worth framing.
     */
    CrusorAIPreviewService.prototype.resolveEndpoint = function () {
        return __awaiter(this, void 0, Promise, function () {
            var open, directory, children, error_1, candidates, _i, _a, child, content, endpoint, matchesOpen, error_2, newest, age;
            var _b, _c;
            return __generator(this, function (_d) {
                switch (_d.label) {
                    case 0:
                        open = this.workspaceService.getWorkspace().folders.map(function (folder) { return folder.uri.fsPath; });
                        if (!open.length) {
                            return [2 /*return*/, undefined];
                        }
                        directory = this.endpointDirectory();
                        _d.label = 1;
                    case 1:
                        _d.trys.push([1, 3, , 4]);
                        return [4 /*yield*/, this.fileService.resolve(directory)];
                    case 2:
                        children = _d.sent();
                        return [3 /*break*/, 4];
                    case 3:
                        error_1 = _d.sent();
                        this.logService.trace('[crusor-preview] no endpoint directory yet', error_1);
                        return [2 /*return*/, undefined];
                    case 4:
                        candidates = [];
                        _i = 0, _a = (_b = children.children) !== null && _b !== void 0 ? _b : [];
                        _d.label = 5;
                    case 5:
                        if (!(_i < _a.length)) return [3 /*break*/, 10];
                        child = _a[_i];
                        if (!child.name.endsWith('.json')) {
                            return [3 /*break*/, 9];
                        }
                        _d.label = 6;
                    case 6:
                        _d.trys.push([6, 8, , 9]);
                        return [4 /*yield*/, this.fileService.readFile(child.resource)];
                    case 7:
                        content = _d.sent();
                        endpoint = JSON.parse(content.value.toString());
                        if (!(endpoint === null || endpoint === void 0 ? void 0 : endpoint.origin)) {
                            return [3 /*break*/, 9];
                        }
                        matchesOpen = function (candidate) { return isWindows
                            ? open.some(function (folder) { return folder.toLowerCase() === candidate.toLowerCase(); })
                            : open.includes(candidate); };
                        if (endpoint.workspace && !matchesOpen(endpoint.workspace)) {
                            return [3 /*break*/, 9];
                        }
                        candidates.push({ endpoint: endpoint, path: child.resource });
                        return [3 /*break*/, 9];
                    case 8:
                        error_2 = _d.sent();
                        this.logService.trace('[crusor-preview] unreadable endpoint', child.resource.toString(), error_2);
                        return [3 /*break*/, 9];
                    case 9:
                        _i++;
                        return [3 /*break*/, 5];
                    case 10:
                        if (!candidates.length) {
                            return [2 /*return*/, undefined];
                        }
                        candidates.sort(function (a, b) { var _a, _b; return ((_a = b.endpoint.started_at) !== null && _a !== void 0 ? _a : 0) - ((_b = a.endpoint.started_at) !== null && _b !== void 0 ? _b : 0); });
                        newest = candidates[0].endpoint;
                        age = Date.now() - ((_c = newest.started_at) !== null && _c !== void 0 ? _c : 0) * 1000;
                        if (!(age > 12 * 60 * 60 * 1000)) return [3 /*break*/, 12];
                        return [4 /*yield*/, this.proxyAlive(newest)];
                    case 11:
                        // An old registration is stale only if the proxy behind it is gone: probe the health
                        // endpoint before rejecting. A dev proxy that has been serving for a day is healthy —
                        // age alone must never block Preview (a healthy long-lived proxy used to be rejected
                        // here, which is exactly the "Preview does nothing" report this replaced).
                        if (!(_d.sent())) {
                            this.logService.warn('[crusor-preview] newest endpoint is stale and its proxy does not answer', newest.origin);
                            return [2 /*return*/, undefined];
                        }
                        this.logService.info('[crusor-preview] long-lived but healthy preview proxy accepted', newest.origin);
                        _d.label = 12;
                    case 12: return [2 /*return*/, newest];
                }
            });
        });
    };
    // ── step 2: the window ────────────────────────────────────────────────────────────────────
    CrusorAIPreviewService.prototype.openPreview = function (target) {
        return __awaiter(this, void 0, Promise, function () {
            var endpoint, resolved, targetAlive, kind, uri, query, url, frame, auxiliary, store, host;
            var _this = this;
            var _a, _b, _c, _d;
            return __generator(this, function (_e) {
                switch (_e.label) {
                    case 0:
                        if (this.host.value) {
                            // Already open: the auxiliary window keeps its state, and re-opening would lose the batch.
                            this._onDidChangeWindow.fire(true);
                            return [2 /*return*/, { ok: true }];
                        }
                        return [4 /*yield*/, this.resolveEndpoint()];
                    case 1:
                        endpoint = _e.sent();
                        if (!endpoint) {
                            this.logService.warn('[crusor-preview] no preview proxy published for this workspace');
                            this.notificationService.warn(localize('crusorai.preview.noEndpoint', 'Crusor Preview: no preview proxy is registered for this workspace. Run a preview batch (or start your dev server through the agent), then press Preview again.'));
                            return [2 /*return*/, { ok: false, reason: 'no preview proxy is registered for this workspace' }];
                        }
                        resolved = target !== null && target !== void 0 ? target : this.targetFromAvailability();
                        if (!resolved.url && !resolved.file) {
                            this.logService.warn('[crusor-preview] no target to preview');
                            this.notificationService.warn(localize('crusorai.preview.noTarget', 'Crusor Preview: nothing to preview yet — ask the agent to build or run your app, then press Preview.'));
                            return [2 /*return*/, { ok: false, reason: 'no target to preview yet' }];
                        }
                        return [4 /*yield*/, this.proxyAlive(endpoint)];
                    case 2:
                        // Pre-flight conditions (the cheap ones first): a dead proxy or a dead
                        // dev server used to open a white window and cost a whole LLM turn to
                        // discover. The engine probe in the preview.open receipt stays the agent
                        // path; this one protects the human click path. URL targets only — a
                        // workspace file cannot be probed with a socket.
                        if (!(_e.sent())) {
                            this.logService.warn('[crusor-preview] proxy dead — refusing to spawn a dead window');
                            this.notificationService.warn(localize('crusorai.preview.proxyDown', 'Crusor Preview: the preview proxy is not running. Ask Crusor to start it, then press Preview again.'));
                            return [2 /*return*/, { ok: false, reason: 'the preview proxy is not running' }];
                        }
                        if (!resolved.url) return [3 /*break*/, 4];
                        return [4 /*yield*/, this.targetReachable(resolved.url)];
                    case 3:
                        targetAlive = _e.sent();
                        if (!targetAlive.ok) {
                            this.logService.warn('[crusor-preview] target refused pre-flight —', targetAlive.detail);
                            this.health = 'down';
                            this.currentTarget = resolved;
                            this.notificationService.warn(localize('crusorai.preview.targetDown', 'Crusor Preview: {0} is not answering. Click the red Preview tab to ask Crusor to restart it.', resolved.url));
                            return [2 /*return*/, { ok: false, reason: targetAlive.detail }];
                        }
                        _e.label = 4;
                    case 4:
                        this.health = 'starting';
                        this.currentTarget = resolved;
                        kind = resolved.file ? 'file' : 'url';
                        uri = FileAccess.asBrowserUri(PREVIEW_WINDOW_RESOURCE).toString(true);
                        query = previewWindowQuery(endpoint, {
                            kind: kind,
                            target: (_a = resolved.url) !== null && _a !== void 0 ? _a : '',
                            file: (_b = resolved.file) !== null && _b !== void 0 ? _b : '',
                            label: (_c = resolved.label) !== null && _c !== void 0 ? _c : '',
                            session: (_d = endpoint.session_id) !== null && _d !== void 0 ? _d : '',
                        });
                        url = "".concat(uri, "?").concat(query);
                        frame = document.createElement('iframe');
                        frame.className = 'crusor-preview-window-frame';
                        frame.setAttribute('title', 'Crusor Preview');
                        // Absolute, over the auxiliary window's content area. The window's own `container` div is left
                        // alone on purpose: it is positioned and laid out by the workbench, and overwriting its styles
                        // from here is how an auxiliary window ends up unable to render its own parts.
                        frame.style.cssText = 'position:absolute;inset:0;z-index:100;display:block;width:100%;height:100%;border:0;background:#1f1f1f;';
                        frame.setAttribute('src', url);
                        return [4 /*yield*/, this.auxiliaryWindows.open({
                                // A preview wants room: it is a page rendered at a real size, not a panel. The OS titlebar
                                // stays: it is how the window is moved and closed, since the preview iframe covers the
                                // window's content area and our own chrome cannot drag a frameless window from inside a frame.
                                bounds: { width: 1180, height: 840 },
                                nativeTitlebar: true,
                                backgroundColor: '#1f1f1f',
                            })];
                    case 5:
                        auxiliary = _e.sent();
                        store = new DisposableStore();
                        store.add(auxiliary);
                        host = auxiliary.window.document.body;
                        host.appendChild(frame);
                        // The same derived-token machine the Agent pane runs, on this window's container: the preview
                        // chrome and the injected overlay wear the live theme, not a palette of their own.
                        store.add(installCrusorTheme(auxiliary.container, this.themeService));
                        store.add(this.themeService.onDidColorThemeChange(function () { return _this.pushTheme(frame, auxiliary.container); }));
                        store.add(this.listen(frame));
                        store.add(toDisposable(function () {
                            _this._onDidChangeWindow.fire(false);
                            _this.currentFrame = undefined;
                            _this.health = 'closed';
                            frame.remove();
                        }));
                        this.host.value = store;
                        this.currentFrame = frame;
                        this._onDidChangeWindow.fire(true);
                        this.logService.info('[crusor-preview] window opened', url);
                        return [2 /*return*/, { ok: true }];
                }
            });
        });
    };
    /**
     * HTTP reachability for a URL target, from the renderer via the main
     * process (loopback CSP-safe, same as proxyAlive). ANY answer counts as
     * alive — a 500 compile-error page still means the server is up; a
     * connection refusal means the click would spawn a white window.
     */
    CrusorAIPreviewService.prototype.targetReachable = function (url) {
        return __awaiter(this, void 0, Promise, function () {
            var parsed, controller, timer, error_3, aborted, _a;
            return __generator(this, function (_b) {
                switch (_b.label) {
                    case 0:
                        try {
                            parsed = new URL(url);
                        }
                        catch (_c) {
                            return [2 /*return*/, { ok: false, detail: "not a usable URL: ".concat(url) }];
                        }
                        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
                            return [2 /*return*/, { ok: false, detail: "not an http(s) URL: ".concat(url) }];
                        }
                        controller = new AbortController();
                        timer = setTimeout(function () { return controller.abort(); }, 3000);
                        _b.label = 1;
                    case 1:
                        _b.trys.push([1, 3, 8, 9]);
                        return [4 /*yield*/, fetch(url, { mode: 'no-cors', cache: 'no-store', signal: controller.signal })];
                    case 2:
                        _b.sent();
                        return [2 /*return*/, { ok: true, detail: 'answered' }];
                    case 3:
                        error_3 = _b.sent();
                        aborted = error_3 instanceof Error && error_3.name === 'AbortError';
                        _b.label = 4;
                    case 4:
                        _b.trys.push([4, 6, , 7]);
                        return [4 /*yield*/, this.requestService.request({ type: 'GET', url: url, timeout: 3000, callSite: 'crusorAIPreviewService.targetReachable' }, CancellationToken.None)];
                    case 5:
                        _b.sent();
                        return [2 /*return*/, { ok: true, detail: 'answered (via request service)' }];
                    case 6:
                        _a = _b.sent();
                        return [2 /*return*/, { ok: false, detail: aborted
                                    ? "".concat(parsed.host, " did not answer within 3s")
                                    : "nothing is listening on ".concat(parsed.host) }];
                    case 7: return [3 /*break*/, 9];
                    case 8:
                        clearTimeout(timer);
                        return [7 /*endfinally*/];
                    case 9: return [2 /*return*/];
                }
            });
        });
    };
    /**
     * The user clicked the red (down) Preview tab: hand the restart to the agent
     * as one scoped turn (start dev server → verify HTTP 200 → preview.open with
     * target_reachable check), not another dead window.
     */
    CrusorAIPreviewService.prototype.requestRelaunch = function () {
        return __awaiter(this, void 0, Promise, function () {
            var workspace, text, frame, error_4;
            var _a, _b, _c, _d, _e, _f, _g;
            return __generator(this, function (_h) {
                switch (_h.label) {
                    case 0:
                        workspace = this.workspacePath;
                        if (!workspace) {
                            this.notificationService.warn(localize('crusorai.preview.relaunchNoWorkspace', 'Crusor Preview: open one project folder first — the relaunch turn must name its workspace.'));
                            return [2 /*return*/];
                        }
                        text = buildPreviewRelaunchPrompt((_a = this.currentTarget) !== null && _a !== void 0 ? _a : this.targetFromAvailability());
                        frame = {
                            type: 'prompt',
                            session_id: (_b = this.latestSessionId()) !== null && _b !== void 0 ? _b : '',
                            workspace: workspace,
                            text: text,
                            mode: 'agent',
                            preview_batch: {
                                source: 'crusor-preview',
                                target: (_d = (_c = this.currentTarget) === null || _c === void 0 ? void 0 : _c.url) !== null && _d !== void 0 ? _d : '',
                                target_label: (_f = (_e = this.currentTarget) === null || _e === void 0 ? void 0 : _e.label) !== null && _f !== void 0 ? _f : '',
                                kind: ((_g = this.currentTarget) === null || _g === void 0 ? void 0 : _g.file) ? 'file' : 'url',
                                viewport: 'responsive',
                                count: 0,
                                summary: 'preview relaunch request (target down)',
                            },
                        };
                        // Same composer-parity gate as sendBatchToAgent: the user bubble plus a
                        // live session, else the session_info handler opens a fresh one.
                        if (this.renderer.beginExternalTurn(text)) {
                            this.engine.send(frame);
                            // The relaunch turn ends with the server either back or explained:
                            // the watcher reloads the frame, and target-ok/target-error re-paint
                            // the tab. If the agent re-opens the window instead, preview.open's
                            // pre-flight gates a fresh spawn on a live target first.
                            this.pendingPreviewTurn = true;
                            this.logService.info('[crusor-preview] relaunch requested — the agent will restart the dev server and re-open the preview');
                            this.notificationService.info(localize('crusorai.preview.relaunchSent', 'Crusor Preview: asked Crusor to bring the preview back — watch the Agent tab.'));
                        }
                        else {
                            this.logService.info('[crusor-preview] relaunch: no live Agent session; the request opens a fresh session');
                        }
                        _h.label = 1;
                    case 1:
                        _h.trys.push([1, 3, , 4]);
                        return [4 /*yield*/, this.commandService.executeCommand(CrusorAICommandId.Focus)];
                    case 2:
                        _h.sent();
                        return [3 /*break*/, 4];
                    case 3:
                        error_4 = _h.sent();
                        this.logService.warn('[crusor-preview] could not focus the Agent surface', error_4);
                        return [3 /*break*/, 4];
                    case 4: return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIPreviewService.prototype.closePreview = function () {
        this.host.clear();
        this.currentFrame = undefined;
        this.health = 'closed';
    };
    CrusorAIPreviewService.prototype.targetFromAvailability = function () {
        var availability = this._availability;
        if (availability.reason === 'dev-server' && availability.url) {
            return { url: availability.url, label: availability.label };
        }
        if (availability.file) {
            return { file: availability.file, label: availability.label };
        }
        return { label: availability.label };
    };
    /** The preview window's palette is the pane's palette: the same derived-token machine. */
    CrusorAIPreviewService.prototype.pushTheme = function (frame, container) {
        var _a;
        var computed = (_a = container.ownerDocument.defaultView) === null || _a === void 0 ? void 0 : _a.getComputedStyle(container);
        if (!computed) {
            return;
        }
        var read = function (name) { return computed.getPropertyValue(name).trim() || undefined; };
        var theme = {
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
        this.postToWindow(frame, CrusorPreviewWindowCommand.Configure, { theme: theme });
    };
    CrusorAIPreviewService.prototype.postToWindow = function (frame, command, payload) {
        if (payload === void 0) { payload = {}; }
        var target = frame.contentWindow;
        if (!target) {
            return;
        }
        target.postMessage(__assign({ source: CrusorPreviewSource.Workbench, command: command }, payload), '*');
    };
    /** Messages from the preview window: the batch, a source request, and the window's own chrome. */
    CrusorAIPreviewService.prototype.listen = function (frame) {
        var _this = this;
        var _a;
        var listener = function (event) {
            var _a;
            var data = event === null || event === void 0 ? void 0 : event.data;
            if (!data || data.source !== CrusorPreviewSource.Window) {
                return;
            }
            switch (data.type) {
                case CrusorPreviewWindowEvent.Ready:
                    _this.pushTheme(frame, (_a = frame.parentElement) !== null && _a !== void 0 ? _a : frame);
                    break;
                case CrusorPreviewWindowEvent.TargetOk:
                    // The window's own load handler says the framed app rendered:
                    // the only state allowed to paint the Preview tab green.
                    _this.health = 'live';
                    _this.logService.info('[crusor-preview] target is live', data['url']);
                    break;
                case CrusorPreviewWindowEvent.ReviewSubmit:
                    void _this.sendBatchToAgent(data.batch);
                    break;
                case CrusorPreviewWindowEvent.OpenSource:
                    void _this.revealSource(data.element);
                    break;
                case CrusorPreviewWindowEvent.CloseRequest:
                    _this.closePreview();
                    break;
                case CrusorPreviewWindowEvent.Viewport:
                    _this.logService.trace('[crusor-preview]', data.type, data);
                    break;
                case CrusorPreviewWindowEvent.TargetError: {
                    // The window already explains itself in-place; this makes the
                    // outage impossible to miss AND turns the Preview tab red so
                    // the next click becomes a relaunch request, not a dead window.
                    var url = typeof data['url'] === 'string' ? data['url'] : '';
                    var now = Date.now();
                    _this.logService.warn('[crusor-preview] target error', data);
                    if (url !== _this.lastTargetError.url || now - _this.lastTargetError.at > 15000) {
                        _this.lastTargetError = { url: url, at: now };
                        _this.notificationService.warn('Crusor Preview: the framed app failed to render'
                            + (url ? " (".concat(url, ")") : '')
                            + ' — click the red Preview tab and Crusor will bring it back.');
                    }
                    _this.health = 'down';
                    break;
                }
                case CrusorPreviewWindowEvent.Inspect:
                case CrusorPreviewWindowEvent.ElementSelected:
                case CrusorPreviewWindowEvent.FixAdded:
                    _this.logService.trace('[crusor-preview]', data.type, data);
                    break;
                default:
                    break;
            }
        };
        (_a = frame.ownerDocument.defaultView) === null || _a === void 0 ? void 0 : _a.addEventListener('message', listener);
        return toDisposable(function () { var _a; return (_a = frame.ownerDocument.defaultView) === null || _a === void 0 ? void 0 : _a.removeEventListener('message', listener); });
    };
    // ── step 9: the handoff ───────────────────────────────────────────────────────────────────
    /**
     * Dispatch the reviewed batch. The text is built here (via the shared contract module) because
     * the composer must be able to show exactly what is sent; the Python builder in
     * `src/preview/prompt.py` is the canonical one for engine-side hosts, and the two are pinned
     * against each other (src/tests/test_preview_contract.py).
     */
    CrusorAIPreviewService.prototype.sendBatchToAgent = function (batch) {
        return __awaiter(this, void 0, Promise, function () {
            var workspace, text, frame, error_5;
            var _a, _b, _c;
            return __generator(this, function (_d) {
                switch (_d.label) {
                    case 0:
                        if (isBatchEmpty(batch)) {
                            return [2 /*return*/];
                        }
                        workspace = this.workspacePath;
                        if (!workspace) {
                            this.logService.warn('[crusor-preview] batch not sent: no single project folder is open '
                                + '(open one folder, or pick one in a multi-root workspace) — a preview turn must name its workspace');
                            return [2 /*return*/];
                        }
                        text = buildPreviewPrompt(batch);
                        frame = {
                            type: 'prompt',
                            session_id: batch.sessionId || this.latestSessionId() || '',
                            workspace: workspace,
                            text: text,
                            mode: 'agent',
                            preview_batch: {
                                source: 'crusor-preview',
                                target: batch.target,
                                target_label: (_a = batch.targetLabel) !== null && _a !== void 0 ? _a : '',
                                kind: (_b = batch.kind) !== null && _b !== void 0 ? _b : 'url',
                                viewport: (_c = batch.viewport) !== null && _c !== void 0 ? _c : 'responsive',
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
                            this.engine.send(frame);
                            // This turn ends with the fixes either applied or explained: the
                            // turn-end watcher reloads the frame so the result is visible with
                            // zero clicks, and the load outcome re-drives the health state.
                            this.pendingPreviewTurn = true;
                            this.logService.info('[crusor-preview] sent', summarizeBatch(batch));
                        }
                        else {
                            // Parked behind a session_create: the session_info handler starts the
                            // fresh turn with this text. Its end is still ours to watch — the
                            // turn-end watcher reloads the frame exactly as for a live session.
                            this.pendingPreviewTurn = true;
                            this.logService.info('[crusor-preview] no live Agent session; the batch opens a fresh session');
                        }
                        _d.label = 1;
                    case 1:
                        _d.trys.push([1, 3, , 4]);
                        return [4 /*yield*/, this.commandService.executeCommand(CrusorAICommandId.Focus)];
                    case 2:
                        _d.sent();
                        return [3 /*break*/, 4];
                    case 3:
                        error_5 = _d.sent();
                        this.logService.warn('[crusor-preview] could not focus the Agent surface', error_5);
                        return [3 /*break*/, 4];
                    case 4: return [2 /*return*/];
                }
            });
        });
    };
    /** The session the composer is talking to: the most recently active one the store knows about. */
    CrusorAIPreviewService.prototype.latestSessionId = function () {
        var _a, _b, _c;
        var records = this.sessionStore.records();
        if (!records.length) {
            return undefined;
        }
        var best = records[0];
        var bestAt = 0;
        for (var _i = 0, records_1 = records; _i < records_1.length; _i++) {
            var record = records_1[_i];
            var at = (_c = (_b = (_a = record.turnEndedAt) !== null && _a !== void 0 ? _a : record.turnStartedAt) !== null && _b !== void 0 ? _b : record.firstSeenAt) !== null && _c !== void 0 ? _c : 0;
            if (at >= bestAt) {
                best = record;
                bestAt = at;
            }
        }
        return best.sessionId;
    };
    /** The element carries enough to find its source; the editor is where the user can act on it. */
    CrusorAIPreviewService.prototype.revealSource = function (element) {
        return __awaiter(this, void 0, Promise, function () {
            var file, folder, resource, error_6;
            var _a, _b;
            return __generator(this, function (_c) {
                switch (_c.label) {
                    case 0:
                        file = (_b = (_a = element === null || element === void 0 ? void 0 : element.fingerprint) === null || _a === void 0 ? void 0 : _a.source) === null || _b === void 0 ? void 0 : _b.file;
                        if (!file) {
                            this.logService.trace('[crusor-preview] no stamped source for this element', element === null || element === void 0 ? void 0 : element.selector);
                            return [2 /*return*/];
                        }
                        folder = this.workspaceService.getWorkspace().folders[0];
                        if (!folder) {
                            return [2 /*return*/];
                        }
                        resource = URI.joinPath.apply(URI, __spreadArray([folder.uri], file.split('/'), false));
                        _c.label = 1;
                    case 1:
                        _c.trys.push([1, 3, , 4]);
                        return [4 /*yield*/, this.editorService.openEditor({ resource: resource, options: { pinned: false } })];
                    case 2:
                        _c.sent();
                        return [3 /*break*/, 4];
                    case 3:
                        error_6 = _c.sent();
                        this.logService.warn('[crusor-preview] could not open', file, error_6);
                        return [3 /*break*/, 4];
                    case 4: return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIPreviewService = __decorate([
        __param(0, ICrusorAIEngineService),
        __param(1, IAuxiliaryWindowService),
        __param(2, IPathService),
        __param(3, IFileService),
        __param(4, IThemeService),
        __param(5, IWorkspaceContextService),
        __param(6, IEditorService),
        __param(7, ICrusorAISessionStore),
        __param(8, ICrusorAIRendererService),
        __param(9, ICommandService),
        __param(10, ILogService),
        __param(11, IRequestService),
        __param(12, INotificationService)
    ], CrusorAIPreviewService);
    return CrusorAIPreviewService;
}(Disposable));
export { CrusorAIPreviewService };
