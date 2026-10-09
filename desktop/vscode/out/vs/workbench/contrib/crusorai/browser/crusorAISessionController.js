/*---------------------------------------------------------------------------------------------
 * Crusor as a session provider: the workbench's own Agent Sessions list, fed from Crusor's store.
 *
 * This is the whole registration -- one session type and one controller -- which is how the fork
 * builds its own manager (see `localAgentSessionsController.ts`). Everything it buys is already
 * written: sorting, sections, pin/archive/rename, the filter submenu, find, focus and a11y
 * commands, the attention dot, the needs-input crusor. Nothing here paints a pixel, so nothing
 * here can look like anyone's product but Crusor's.
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
import { Disposable } from '../../../../base/common/lifecycle.js';
import { Emitter } from '../../../../base/common/event.js';
import { WorkbenchPhase, registerWorkbenchContribution2 } from '../../../common/contributions.js';
import { ICommandService } from '../../../../platform/commands/common/commands.js';
import { ChatSessionStatus, IChatSessionsService, } from '../../chat/common/chatSessionsService.js';
import { CRUSOR_CHAT_SESSION_TYPE, crusorSessionIdFromUri, crusorSessionRows } from '../common/crusorAISessionProjection.js';
import { ICrusorAISessionStore } from '../common/crusorAISessionStore.js';
import { ICrusorAIRendererService } from '../common/crusorAIRendererService.js';
import { CrusorAICommandId } from '../common/crusorAI.js';
import { sessionOpenerRegistry } from '../../chat/browser/agentSessions/agentSessionsOpener.js';
function toChatSessionStatus(statusName) {
    switch (statusName) {
        case 'inProgress': return ChatSessionStatus.InProgress;
        case 'needsInput': return ChatSessionStatus.NeedsInput;
        case 'failed': return ChatSessionStatus.Failed;
        case 'completed': return ChatSessionStatus.Completed;
        default: return undefined;
    }
}
var CrusorAISessionController = /** @class */ (function (_super) {
    __extends(CrusorAISessionController, _super);
    function CrusorAISessionController(sessionStore, chatSessionsService) {
        var _this = _super.call(this) || this;
        _this.sessionStore = sessionStore;
        _this.chatSessionsService = chatSessionsService;
        _this.chatSessionType = CRUSOR_CHAT_SESSION_TYPE;
        _this._onDidChangeChatSessionItems = _this._register(new Emitter());
        _this.onDidChangeChatSessionItems = _this._onDidChangeChatSessionItems.event;
        // One line of registration, exactly where upstream's local controller registers itself
        // (localAgentSessionsController.ts:45). It returns an IDisposable, so unloading Crusor
        // removes the rows instead of leaving a hollow session type behind.
        _this._register(_this.chatSessionsService.registerChatSessionItemController(_this.chatSessionType, _this));
        _this._register(_this.sessionStore.onDidChange(function () {
            _this._onDidChangeChatSessionItems.fire({ addedOrUpdated: _this.items });
        }));
        return _this;
    }
    Object.defineProperty(CrusorAISessionController.prototype, "items", {
        get: function () {
            return crusorSessionRows(this.sessionStore.records(), undefined, Date.now(), this.readState())
                .map(function (row) { return (__assign(__assign({ resource: row.resource, label: row.label, description: row.description, status: toChatSessionStatus(row.statusName), timing: row.timing }, (row.changes ? { changes: row.changes } : {})), (row.archived !== undefined ? { archived: row.archived } : {}))); });
        },
        enumerable: false,
        configurable: true
    });
    /**
     * Crusor pushes frames over its stdio bridge, so there is nothing to pull. The event above is
     * the only source of truth; a refresh is a no-op rather than a fake re-query.
     */
    CrusorAISessionController.prototype.refresh = function (token) {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                // Intentionally empty: see the comment above.
                void token;
                return [2 /*return*/];
            });
        });
    };
    /**
     * `setChatSessionItemRead` is deliberately NOT implemented. Implementing it declares that the
     * controller owns read state, and an in-memory map would lose it on reload; leaving it
     * undefined keeps the host's persisted per-resource tracking, which is strictly better.
     */
    CrusorAISessionController.prototype.readState = function () {
        var ids = new Set();
        for (var _i = 0, _a = this.sessionStore.records(); _i < _a.length; _i++) {
            var facts = _a[_i];
            ids.add(facts.sessionId);
        }
        var found = false;
        var map = new Map();
        for (var _b = 0, ids_1 = ids; _b < ids_1.length; _b++) {
            var id = ids_1[_b];
            var isRead = this.sessionStore.isRead(id);
            if (isRead !== undefined) {
                map.set(id, isRead);
                found = true;
            }
        }
        return found ? map : undefined;
    };
    CrusorAISessionController.ID = 'workbench.contrib.crusorAISessionController';
    CrusorAISessionController = __decorate([
        __param(0, ICrusorAISessionStore),
        __param(1, IChatSessionsService)
    ], CrusorAISessionController);
    return CrusorAISessionController;
}(Disposable));
export { CrusorAISessionController };
/**
 * One opener for both surfaces. `openSessionByResource()` asks registered participants first and
 * only falls through to the chat editor path, so a click on a Crusor row inside the workbench's
 * list rebinds the Agent surface to that session instead of asking a chat provider to resolve a
 * resource it does not own (which is what would otherwise surface as an error toast).
 */
var CrusorAISessionOpener = /** @class */ (function (_super) {
    __extends(CrusorAISessionOpener, _super);
    function CrusorAISessionOpener() {
        var _this = _super.call(this) || this;
        _this._register(sessionOpenerRegistry.registerParticipant(_this));
        return _this;
    }
    CrusorAISessionOpener.prototype.handleOpenSession = function (accessor, session, openOptions) {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                return [2 /*return*/, this.handleOpenSessionResource(accessor, session.resource, openOptions)];
            });
        });
    };
    CrusorAISessionOpener.prototype.handleOpenSessionResource = function (accessor, resource, _openOptions) {
        return __awaiter(this, void 0, Promise, function () {
            var sessionId, commandService, rendererService;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        sessionId = crusorSessionIdFromUri(resource);
                        if (!sessionId) {
                            return [2 /*return*/, false];
                        }
                        commandService = accessor.get(ICommandService);
                        rendererService = accessor.get(ICrusorAIRendererService);
                        return [4 /*yield*/, commandService.executeCommand(CrusorAICommandId.Focus)];
                    case 1:
                        _a.sent();
                        rendererService.openSession(sessionId);
                        return [2 /*return*/, true];
                }
            });
        });
    };
    CrusorAISessionOpener.ID = 'workbench.contrib.crusorAISessionOpener';
    return CrusorAISessionOpener;
}(Disposable));
export { CrusorAISessionOpener };
registerWorkbenchContribution2(CrusorAISessionController.ID, CrusorAISessionController, WorkbenchPhase.AfterRestored);
registerWorkbenchContribution2(CrusorAISessionOpener.ID, CrusorAISessionOpener, WorkbenchPhase.AfterRestored);
