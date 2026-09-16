/*---------------------------------------------------------------------------------------------
 * Desktop workbench client for the CrusorAI utility-process/Python sidecar chain.
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
import { Emitter } from '../../../../base/common/event.js';
import { Disposable, DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { env } from '../../../../base/common/process.js';
import { ProxyChannel } from '../../../../base/parts/ipc/common/ipc.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { IUtilityProcessWorkerWorkbenchService } from '../../../services/utilityProcess/electron-browser/utilityProcessWorkerWorkbenchService.js';
import { resolveCrusorAIEngineRoot, } from '../common/crusorAIEngineService.js';
import { CRUSOR_AI_PROTOCOL_VERSION } from '../common/crusorAIProtocol.generated.js';
import { CRUSOR_AI_WORKER_CHANNEL, CRUSOR_AI_WORKER_MODULE_ID, } from '../common/crusorAIWorkerService.js';
// Cold-start tolerant (2026-09-05 field: after pulling new engine code the
// bridge's first Python import recompiles caches and can exceed any tight
// budget — the 8s timeout killed the engine with zero stderr, because the
// sidecar was still IMPORTING, not hanging). Still bounded; the second
// start is warm and fast either way.
const HANDSHAKE_TIMEOUT_MS = 45_000;
let CrusorAIEngineService = class CrusorAIEngineService extends Disposable {
    get state() { return this._state; }
    constructor(utilityProcessService, configurationService, logService) {
        super();
        this.utilityProcessService = utilityProcessService;
        this.configurationService = configurationService;
        this.logService = logService;
        this._state = "stopped" /* CrusorAIEngineState.Stopped */;
        this._onDidChangeState = this._register(new Emitter());
        this.onDidChangeState = this._onDidChangeState.event;
        this._onDidReceiveFrame = this._register(new Emitter());
        this.onDidReceiveFrame = this._onDidReceiveFrame.event;
        this.worker = this._register(new MutableDisposable());
        this.session = this._register(new DisposableStore());
    }
    async start(workspace) {
        if (!workspace?.trim()) {
            throw new Error('CrusorAI session requires an opened workspace folder');
        }
        await this.stop();
        this.setState("starting" /* CrusorAIEngineState.Starting */);
        try {
            const worker = await this.utilityProcessService.createWorker({
                moduleId: CRUSOR_AI_WORKER_MODULE_ID,
                type: 'crusorAIEngine',
                name: 'crusorai-engine',
            });
            this.worker.value = worker;
            const processService = ProxyChannel.toService(worker.client.getChannel(CRUSOR_AI_WORKER_CHANNEL));
            this.processService = processService;
            this.session.add(processService.onDidReceiveFrame(line => this.acceptFrame(line)));
            this.session.add(processService.onDidWriteStderr(line => this.logService.warn(`[CrusorAI Engine] ${line}`)));
            this.session.add(processService.onDidChangeState(change => {
                if (change.state === 'crashed') {
                    this.setState("crashed" /* CrusorAIEngineState.Crashed */);
                    this.handshakeReject?.(new Error(change.detail ?? 'CrusorAI sidecar crashed'));
                }
            }));
            void worker.onDidTerminate.then(({ reason }) => {
                if (this.worker.value === worker && this._state !== "stopped" /* CrusorAIEngineState.Stopped */) {
                    this.logService.error(`[CrusorAI Engine] utility process terminated: ${reason?.code}/${reason?.signal}`);
                    this.setState("crashed" /* CrusorAIEngineState.Crashed */);
                }
            });
            // P0: the session workspace and the engine package are DIFFERENT.
            // workspace binds the session; the engine root is where
            // `python -m src.bridge` lives. crusorai.engineRoot and
            // CRUSORAI_ENGINE_ROOT are checked first. As a dev convenience,
            // if the workspace itself contains src/bridge it is used as the engine root.
            const engineRoot = resolveCrusorAIEngineRoot(this.configurationService.getValue('crusorai.engineRoot'), env['CRUSORAI_ENGINE_ROOT'], workspace);
            const pythonPath = this.configurationService.getValue('crusorai.pythonPath')?.trim() || undefined;
            await processService.start({ engineRoot, pythonPath });
            const handshake = new Promise((resolve, reject) => {
                this.handshakeResolve = resolve;
                this.handshakeReject = reject;
            });
            await processService.send(JSON.stringify({ type: 'hello', protocol: CRUSOR_AI_PROTOCOL_VERSION }));
            await Promise.race([
                handshake,
                new Promise((_, reject) => setTimeout(() => reject(new Error('CrusorAI bridge handshake timed out')), HANDSHAKE_TIMEOUT_MS)),
            ]);
        }
        catch (error) {
            // The renderer dev console is where the user reads — a crashed
            // engine with no reason in that console is undebuggable (field
            // 2026-09-05: "send button not working", zero log lines).
            this.logService.error(`[CrusorAI Engine] start failed: ${error instanceof Error ? error.message : String(error)}`);
            await this.releaseWorker();
            this.setState("crashed" /* CrusorAIEngineState.Crashed */);
            throw error;
        }
    }
    send(frame) {
        if (this._state !== "ready" /* CrusorAIEngineState.Ready */ || !this.processService) {
            throw new Error(`CrusorAI engine cannot send while ${this._state}`);
        }
        void this.processService.send(JSON.stringify(frame)).catch(error => {
            this.logService.error('[CrusorAI Engine] failed to send bridge frame', error);
            this.setState("degraded" /* CrusorAIEngineState.Degraded */);
        });
    }
    async stop() {
        await this.releaseWorker();
        this.setState("stopped" /* CrusorAIEngineState.Stopped */);
    }
    async releaseWorker() {
        this.handshakeResolve = undefined;
        this.handshakeReject = undefined;
        const service = this.processService;
        this.processService = undefined;
        this.session.clear();
        if (service) {
            try {
                await service.stop();
            }
            catch (error) {
                this.logService.warn('[CrusorAI Engine] stop failed', error);
            }
        }
        this.worker.clear();
    }
    acceptFrame(line) {
        try {
            const frame = JSON.parse(line);
            if (!frame || typeof frame !== 'object' || typeof frame.type !== 'string') {
                throw new Error('bridge frame is missing a string type');
            }
            if (frame.type === 'hello') {
                if (frame.protocol !== CRUSOR_AI_PROTOCOL_VERSION) {
                    throw new Error(`CrusorAI protocol mismatch: expected ${CRUSOR_AI_PROTOCOL_VERSION}, got ${frame.protocol}`);
                }
                this.setState("ready" /* CrusorAIEngineState.Ready */);
                this.handshakeResolve?.();
                this.handshakeResolve = undefined;
                this.handshakeReject = undefined;
            }
            this._onDidReceiveFrame.fire(frame);
        }
        catch (error) {
            const failure = error instanceof Error ? error : new Error(String(error));
            this.logService.error('[CrusorAI Engine] invalid bridge frame', failure);
            this.handshakeReject?.(failure);
            this.setState("degraded" /* CrusorAIEngineState.Degraded */);
        }
    }
    setState(state) {
        if (this._state === state) {
            return;
        }
        this._state = state;
        this._onDidChangeState.fire(state);
    }
};
CrusorAIEngineService = __decorate([
    __param(0, IUtilityProcessWorkerWorkbenchService),
    __param(1, IConfigurationService),
    __param(2, ILogService)
], CrusorAIEngineService);
export { CrusorAIEngineService };
