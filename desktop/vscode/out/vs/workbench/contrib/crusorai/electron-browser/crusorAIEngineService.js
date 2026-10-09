/*---------------------------------------------------------------------------------------------
 * Desktop workbench client for the CrusorAI utility-process/Python sidecar chain.
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
import { Emitter } from '../../../../base/common/event.js';
import { Disposable, DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { env } from '../../../../base/common/process.js';
import { ProxyChannel } from '../../../../base/parts/ipc/common/ipc.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { IUtilityProcessWorkerWorkbenchService } from '../../../services/utilityProcess/electron-browser/utilityProcessWorkerWorkbenchService.js';
import { CrusorAIEngineState, resolveCrusorAIEngineRoot, } from '../common/crusorAIEngineService.js';
import { CRUSOR_AI_PROTOCOL_VERSION } from '../common/crusorAIProtocol.generated.js';
import { CRUSOR_AI_WORKER_CHANNEL, CRUSOR_AI_WORKER_MODULE_ID, } from '../common/crusorAIWorkerService.js';
// Cold-start tolerant (2026-09-05 field: after pulling new engine code the
// bridge's first Python import recompiles caches and can exceed any tight
// budget — the 8s timeout killed the engine with zero stderr, because the
// sidecar was still IMPORTING, not hanging). Still bounded; the second
// start is warm and fast either way.
var HANDSHAKE_TIMEOUT_MS = 45000;
var CrusorAIEngineService = /** @class */ (function (_super) {
    __extends(CrusorAIEngineService, _super);
    function CrusorAIEngineService(utilityProcessService, configurationService, logService) {
        var _this = _super.call(this) || this;
        _this.utilityProcessService = utilityProcessService;
        _this.configurationService = configurationService;
        _this.logService = logService;
        _this._state = CrusorAIEngineState.Stopped;
        _this._onDidChangeState = _this._register(new Emitter());
        _this.onDidChangeState = _this._onDidChangeState.event;
        _this._onDidReceiveFrame = _this._register(new Emitter());
        _this.onDidReceiveFrame = _this._onDidReceiveFrame.event;
        _this.worker = _this._register(new MutableDisposable());
        _this.session = _this._register(new DisposableStore());
        return _this;
    }
    Object.defineProperty(CrusorAIEngineService.prototype, "state", {
        get: function () { return this._state; },
        enumerable: false,
        configurable: true
    });
    CrusorAIEngineService.prototype.start = function (workspace) {
        return __awaiter(this, void 0, Promise, function () {
            var worker_1, processService, engineRoot, pythonPath, handshake, error_1;
            var _this = this;
            var _a;
            return __generator(this, function (_b) {
                switch (_b.label) {
                    case 0:
                        if (!(workspace === null || workspace === void 0 ? void 0 : workspace.trim())) {
                            throw new Error('CrusorAI session requires an opened workspace folder');
                        }
                        return [4 /*yield*/, this.stop()];
                    case 1:
                        _b.sent();
                        this.setState(CrusorAIEngineState.Starting);
                        _b.label = 2;
                    case 2:
                        _b.trys.push([2, 7, , 9]);
                        return [4 /*yield*/, this.utilityProcessService.createWorker({
                                moduleId: CRUSOR_AI_WORKER_MODULE_ID,
                                type: 'crusorAIEngine',
                                name: 'crusorai-engine',
                            })];
                    case 3:
                        worker_1 = _b.sent();
                        this.worker.value = worker_1;
                        processService = ProxyChannel.toService(worker_1.client.getChannel(CRUSOR_AI_WORKER_CHANNEL));
                        this.processService = processService;
                        this.session.add(processService.onDidReceiveFrame(function (line) { return _this.acceptFrame(line); }));
                        this.session.add(processService.onDidWriteStderr(function (line) { return _this.logService.warn("[CrusorAI Engine] ".concat(line)); }));
                        this.session.add(processService.onDidChangeState(function (change) {
                            var _a, _b;
                            if (change.state === 'crashed') {
                                _this.setState(CrusorAIEngineState.Crashed);
                                (_a = _this.handshakeReject) === null || _a === void 0 ? void 0 : _a.call(_this, new Error((_b = change.detail) !== null && _b !== void 0 ? _b : 'CrusorAI sidecar crashed'));
                            }
                        }));
                        void worker_1.onDidTerminate.then(function (_a) {
                            var reason = _a.reason;
                            if (_this.worker.value === worker_1 && _this._state !== CrusorAIEngineState.Stopped) {
                                _this.logService.error("[CrusorAI Engine] utility process terminated: ".concat(reason === null || reason === void 0 ? void 0 : reason.code, "/").concat(reason === null || reason === void 0 ? void 0 : reason.signal));
                                _this.setState(CrusorAIEngineState.Crashed);
                            }
                        });
                        engineRoot = resolveCrusorAIEngineRoot(this.configurationService.getValue('crusorai.engineRoot'), env['CRUSORAI_ENGINE_ROOT'], workspace);
                        pythonPath = ((_a = this.configurationService.getValue('crusorai.pythonPath')) === null || _a === void 0 ? void 0 : _a.trim()) || undefined;
                        return [4 /*yield*/, processService.start({ engineRoot: engineRoot, pythonPath: pythonPath })];
                    case 4:
                        _b.sent();
                        handshake = new Promise(function (resolve, reject) {
                            _this.handshakeResolve = resolve;
                            _this.handshakeReject = reject;
                        });
                        return [4 /*yield*/, processService.send(JSON.stringify({ type: 'hello', protocol: CRUSOR_AI_PROTOCOL_VERSION }))];
                    case 5:
                        _b.sent();
                        return [4 /*yield*/, Promise.race([
                                handshake,
                                new Promise(function (_, reject) { return setTimeout(function () { return reject(new Error('CrusorAI bridge handshake timed out')); }, HANDSHAKE_TIMEOUT_MS); }),
                            ])];
                    case 6:
                        _b.sent();
                        return [3 /*break*/, 9];
                    case 7:
                        error_1 = _b.sent();
                        // The renderer dev console is where the user reads — a crashed
                        // engine with no reason in that console is undebuggable (field
                        // 2026-09-05: "send button not working", zero log lines).
                        this.logService.error("[CrusorAI Engine] start failed: ".concat(error_1 instanceof Error ? error_1.message : String(error_1)));
                        return [4 /*yield*/, this.releaseWorker()];
                    case 8:
                        _b.sent();
                        this.setState(CrusorAIEngineState.Crashed);
                        throw error_1;
                    case 9: return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIEngineService.prototype.send = function (frame) {
        var _this = this;
        if (this._state !== CrusorAIEngineState.Ready || !this.processService) {
            throw new Error("CrusorAI engine cannot send while ".concat(this._state));
        }
        void this.processService.send(JSON.stringify(frame)).catch(function (error) {
            _this.logService.error('[CrusorAI Engine] failed to send bridge frame', error);
            _this.setState(CrusorAIEngineState.Degraded);
        });
    };
    CrusorAIEngineService.prototype.stop = function () {
        return __awaiter(this, void 0, Promise, function () {
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: return [4 /*yield*/, this.releaseWorker()];
                    case 1:
                        _a.sent();
                        this.setState(CrusorAIEngineState.Stopped);
                        return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIEngineService.prototype.releaseWorker = function () {
        return __awaiter(this, void 0, Promise, function () {
            var service, error_2;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        this.handshakeResolve = undefined;
                        this.handshakeReject = undefined;
                        service = this.processService;
                        this.processService = undefined;
                        this.session.clear();
                        if (!service) return [3 /*break*/, 4];
                        _a.label = 1;
                    case 1:
                        _a.trys.push([1, 3, , 4]);
                        return [4 /*yield*/, service.stop()];
                    case 2:
                        _a.sent();
                        return [3 /*break*/, 4];
                    case 3:
                        error_2 = _a.sent();
                        this.logService.warn('[CrusorAI Engine] stop failed', error_2);
                        return [3 /*break*/, 4];
                    case 4:
                        this.worker.clear();
                        return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIEngineService.prototype.acceptFrame = function (line) {
        var _a, _b;
        try {
            var frame = JSON.parse(line);
            if (!frame || typeof frame !== 'object' || typeof frame.type !== 'string') {
                throw new Error('bridge frame is missing a string type');
            }
            if (frame.type === 'hello') {
                if (frame.protocol !== CRUSOR_AI_PROTOCOL_VERSION) {
                    throw new Error("CrusorAI protocol mismatch: expected ".concat(CRUSOR_AI_PROTOCOL_VERSION, ", got ").concat(frame.protocol));
                }
                this.setState(CrusorAIEngineState.Ready);
                (_a = this.handshakeResolve) === null || _a === void 0 ? void 0 : _a.call(this);
                this.handshakeResolve = undefined;
                this.handshakeReject = undefined;
            }
            this._onDidReceiveFrame.fire(frame);
        }
        catch (error) {
            var failure = error instanceof Error ? error : new Error(String(error));
            this.logService.error('[CrusorAI Engine] invalid bridge frame', failure);
            (_b = this.handshakeReject) === null || _b === void 0 ? void 0 : _b.call(this, failure);
            this.setState(CrusorAIEngineState.Degraded);
        }
    };
    CrusorAIEngineService.prototype.setState = function (state) {
        if (this._state === state) {
            return;
        }
        this._state = state;
        this._onDidChangeState.fire(state);
    };
    CrusorAIEngineService = __decorate([
        __param(0, IUtilityProcessWorkerWorkbenchService),
        __param(1, IConfigurationService),
        __param(2, ILogService)
    ], CrusorAIEngineService);
    return CrusorAIEngineService;
}(Disposable));
export { CrusorAIEngineService };
