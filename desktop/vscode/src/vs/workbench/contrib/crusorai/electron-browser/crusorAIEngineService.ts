/*---------------------------------------------------------------------------------------------
 * Desktop workbench client for the CrusorAI utility-process/Python sidecar chain.
 *--------------------------------------------------------------------------------------------*/

import { Emitter } from '../../../../base/common/event.js';
import { Disposable, DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { env } from '../../../../base/common/process.js';
import { ProxyChannel } from '../../../../base/parts/ipc/common/ipc.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { IUtilityProcessWorker, IUtilityProcessWorkerWorkbenchService } from '../../../services/utilityProcess/electron-browser/utilityProcessWorkerWorkbenchService.js';
import {
	ICrusorAIEngineService,
	CrusorAIEngineState,
	resolveCrusorAIEngineRoot,
} from '../common/crusorAIEngineService.js';
import type { CrusorClientMethod, CrusorServerEvent } from '../common/crusorAIProtocol.js';
import { CRUSOR_AI_PROTOCOL_VERSION } from '../common/crusorAIProtocol.generated.js';
import {
	ICrusorAIWorkerProcessService,
	CRUSOR_AI_WORKER_CHANNEL,
	CRUSOR_AI_WORKER_MODULE_ID,
} from '../common/crusorAIWorkerService.js';

// Cold-start tolerant (2026-09-05 field: after pulling new engine code the
// bridge's first Python import recompiles caches and can exceed any tight
// budget — the 8s timeout killed the engine with zero stderr, because the
// sidecar was still IMPORTING, not hanging). Still bounded; the second
// start is warm and fast either way.
const HANDSHAKE_TIMEOUT_MS = 45_000;

export class CrusorAIEngineService extends Disposable implements ICrusorAIEngineService {
	declare readonly _serviceBrand: undefined;
	private _state = CrusorAIEngineState.Stopped;
	get state(): CrusorAIEngineState { return this._state; }

	private readonly _onDidChangeState = this._register(new Emitter<CrusorAIEngineState>());
	readonly onDidChangeState = this._onDidChangeState.event;
	private readonly _onDidReceiveFrame = this._register(new Emitter<CrusorServerEvent>());
	readonly onDidReceiveFrame = this._onDidReceiveFrame.event;

	private readonly worker = this._register(new MutableDisposable<IUtilityProcessWorker>());
	private readonly session = this._register(new DisposableStore());
	private processService: ICrusorAIWorkerProcessService | undefined;
	private handshakeResolve: (() => void) | undefined;
	private handshakeReject: ((error: Error) => void) | undefined;

	constructor(
		@IUtilityProcessWorkerWorkbenchService private readonly utilityProcessService: IUtilityProcessWorkerWorkbenchService,
		@IConfigurationService private readonly configurationService: IConfigurationService,
		@ILogService private readonly logService: ILogService,
	) {
		super();
	}

	async start(workspace: string): Promise<void> {
		if (!workspace?.trim()) {
			throw new Error('CrusorAI session requires an opened workspace folder');
		}
		await this.stop();
		this.setState(CrusorAIEngineState.Starting);
		try {
			const worker = await this.utilityProcessService.createWorker({
				moduleId: CRUSOR_AI_WORKER_MODULE_ID,
				type: 'crusorAIEngine',
				name: 'crusorai-engine',
			});
			this.worker.value = worker;
			const processService = ProxyChannel.toService<ICrusorAIWorkerProcessService>(worker.client.getChannel(CRUSOR_AI_WORKER_CHANNEL));
			this.processService = processService;
			this.session.add(processService.onDidReceiveFrame(line => this.acceptFrame(line)));
			this.session.add(processService.onDidWriteStderr(line => this.logService.warn(`[CrusorAI Engine] ${line}`)));
			this.session.add(processService.onDidChangeState(change => {
				if (change.state === 'crashed') {
					this.setState(CrusorAIEngineState.Crashed);
					this.handshakeReject?.(new Error(change.detail ?? 'CrusorAI sidecar crashed'));
				}
			}));
			void worker.onDidTerminate.then(({ reason }) => {
				if (this.worker.value === worker && this._state !== CrusorAIEngineState.Stopped) {
					this.logService.error(`[CrusorAI Engine] utility process terminated: ${reason?.code}/${reason?.signal}`);
					this.setState(CrusorAIEngineState.Crashed);
				}
			});

		// P0: the session workspace and the engine package are DIFFERENT.
		// workspace binds the session; the engine root is where
		// `python -m src.bridge` lives. crusorai.engineRoot and
		// CRUSORAI_ENGINE_ROOT are checked first. As a dev convenience,
		// if the workspace itself contains src/bridge it is used as the engine root.
		const engineRoot = resolveCrusorAIEngineRoot(
			this.configurationService.getValue<string>('crusorai.engineRoot'),
			env['CRUSORAI_ENGINE_ROOT'],
			workspace,
		);
			const pythonPath = this.configurationService.getValue<string>('crusorai.pythonPath')?.trim() || undefined;
			await processService.start({ engineRoot, pythonPath });
			const handshake = new Promise<void>((resolve, reject) => {
				this.handshakeResolve = resolve;
				this.handshakeReject = reject;
			});
			await processService.send(JSON.stringify({ type: 'hello', protocol: CRUSOR_AI_PROTOCOL_VERSION }));
			await Promise.race([
				handshake,
				new Promise<never>((_, reject) => setTimeout(() => reject(new Error('CrusorAI bridge handshake timed out')), HANDSHAKE_TIMEOUT_MS)),
			]);
		} catch (error) {
			// The renderer dev console is where the user reads — a crashed
			// engine with no reason in that console is undebuggable (field
			// 2026-09-05: "send button not working", zero log lines).
			this.logService.error(
				`[CrusorAI Engine] start failed: ${error instanceof Error ? error.message : String(error)}`,
			);
			await this.releaseWorker();
			this.setState(CrusorAIEngineState.Crashed);
			throw error;
		}
	}

	send(frame: CrusorClientMethod): void {
		if (this._state !== CrusorAIEngineState.Ready || !this.processService) {
			throw new Error(`CrusorAI engine cannot send while ${this._state}`);
		}
		void this.processService.send(JSON.stringify(frame)).catch(error => {
			this.logService.error('[CrusorAI Engine] failed to send bridge frame', error);
			this.setState(CrusorAIEngineState.Degraded);
		});
	}

	async stop(): Promise<void> {
		await this.releaseWorker();
		this.setState(CrusorAIEngineState.Stopped);
	}

	private async releaseWorker(): Promise<void> {
		this.handshakeResolve = undefined;
		this.handshakeReject = undefined;
		const service = this.processService;
		this.processService = undefined;
		this.session.clear();
		if (service) {
			try { await service.stop(); } catch (error) { this.logService.warn('[CrusorAI Engine] stop failed', error); }
		}
		this.worker.clear();
	}

	private acceptFrame(line: string): void {
		try {
			const frame = JSON.parse(line) as CrusorServerEvent;
			if (!frame || typeof frame !== 'object' || typeof frame.type !== 'string') {
				throw new Error('bridge frame is missing a string type');
			}
			if (frame.type === 'hello') {
				if (frame.protocol !== CRUSOR_AI_PROTOCOL_VERSION) {
					throw new Error(`CrusorAI protocol mismatch: expected ${CRUSOR_AI_PROTOCOL_VERSION}, got ${frame.protocol}`);
				}
				this.setState(CrusorAIEngineState.Ready);
				this.handshakeResolve?.();
				this.handshakeResolve = undefined;
				this.handshakeReject = undefined;
			}
			this._onDidReceiveFrame.fire(frame);
		} catch (error) {
			const failure = error instanceof Error ? error : new Error(String(error));
			this.logService.error('[CrusorAI Engine] invalid bridge frame', failure);
			this.handshakeReject?.(failure);
			this.setState(CrusorAIEngineState.Degraded);
		}
	}

	private setState(state: CrusorAIEngineState): void {
		if (this._state === state) { return; }
		this._state = state;
		this._onDidChangeState.fire(state);
	}
}
