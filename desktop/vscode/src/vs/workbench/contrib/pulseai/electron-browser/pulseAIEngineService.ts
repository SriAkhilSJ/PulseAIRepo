/*---------------------------------------------------------------------------------------------
 * Desktop workbench client for the PulseAI utility-process/Python sidecar chain.
 *--------------------------------------------------------------------------------------------*/

import { Emitter } from '../../../../base/common/event.js';
import { Disposable, DisposableStore, MutableDisposable } from '../../../../base/common/lifecycle.js';
import { env } from '../../../../base/common/process.js';
import { ProxyChannel } from '../../../../base/parts/ipc/common/ipc.js';
import { IConfigurationService } from '../../../../platform/configuration/common/configuration.js';
import { ILogService } from '../../../../platform/log/common/log.js';
import { IUtilityProcessWorker, IUtilityProcessWorkerWorkbenchService } from '../../../services/utilityProcess/electron-browser/utilityProcessWorkerWorkbenchService.js';
import {
	IPulseAIEngineService,
	PulseAIEngineState,
	resolvePulseAIEngineRoot,
} from '../common/pulseAIEngineService.js';
import type { PulseClientMethod, PulseServerEvent } from '../common/pulseAIProtocol.js';
import { PULSE_AI_PROTOCOL_VERSION } from '../common/pulseAIProtocol.generated.js';
import {
	IPulseAIWorkerProcessService,
	PULSE_AI_WORKER_CHANNEL,
	PULSE_AI_WORKER_MODULE_ID,
} from '../common/pulseAIWorkerService.js';

const HANDSHAKE_TIMEOUT_MS = 8_000;

export class PulseAIEngineService extends Disposable implements IPulseAIEngineService {
	declare readonly _serviceBrand: undefined;
	private _state = PulseAIEngineState.Stopped;
	get state(): PulseAIEngineState { return this._state; }

	private readonly _onDidChangeState = this._register(new Emitter<PulseAIEngineState>());
	readonly onDidChangeState = this._onDidChangeState.event;
	private readonly _onDidReceiveFrame = this._register(new Emitter<PulseServerEvent>());
	readonly onDidReceiveFrame = this._onDidReceiveFrame.event;

	private readonly worker = this._register(new MutableDisposable<IUtilityProcessWorker>());
	private readonly session = this._register(new DisposableStore());
	private processService: IPulseAIWorkerProcessService | undefined;
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
			throw new Error('PulseAI session requires an opened workspace folder');
		}
		await this.stop();
		this.setState(PulseAIEngineState.Starting);
		try {
			const worker = await this.utilityProcessService.createWorker({
				moduleId: PULSE_AI_WORKER_MODULE_ID,
				type: 'pulseAIEngine',
				name: 'pulseai-engine',
			});
			this.worker.value = worker;
			const processService = ProxyChannel.toService<IPulseAIWorkerProcessService>(worker.client.getChannel(PULSE_AI_WORKER_CHANNEL));
			this.processService = processService;
			this.session.add(processService.onDidReceiveFrame(line => this.acceptFrame(line)));
			this.session.add(processService.onDidWriteStderr(line => this.logService.warn(`[PulseAI Engine] ${line}`)));
			this.session.add(processService.onDidChangeState(change => {
				if (change.state === 'crashed') {
					this.setState(PulseAIEngineState.Crashed);
					this.handshakeReject?.(new Error(change.detail ?? 'PulseAI sidecar crashed'));
				}
			}));
			void worker.onDidTerminate.then(({ reason }) => {
				if (this.worker.value === worker && this._state !== PulseAIEngineState.Stopped) {
					this.logService.error(`[PulseAI Engine] utility process terminated: ${reason?.code}/${reason?.signal}`);
					this.setState(PulseAIEngineState.Crashed);
				}
			});

			// P0: the session workspace and the engine package are DIFFERENT.
			// workspace binds the session; the engine root is where
			// `python -m src.bridge` lives and must never silently fall back to
			// the user's project folder. Only pulseai.engineRoot and
			// PULSEAI_ENGINE_ROOT are consulted (resolvePulseAIEngineRoot has no
			// workspace input, so start(workspace) provably cannot leak it).
			const engineRoot = resolvePulseAIEngineRoot(
				this.configurationService.getValue<string>('pulseai.engineRoot'),
				env['PULSEAI_ENGINE_ROOT'],
			);
			const pythonPath = this.configurationService.getValue<string>('pulseai.pythonPath')?.trim() || undefined;
			await processService.start({ engineRoot, pythonPath });
			const handshake = new Promise<void>((resolve, reject) => {
				this.handshakeResolve = resolve;
				this.handshakeReject = reject;
			});
			await processService.send(JSON.stringify({ type: 'hello', protocol: PULSE_AI_PROTOCOL_VERSION }));
			await Promise.race([
				handshake,
				new Promise<never>((_, reject) => setTimeout(() => reject(new Error('PulseAI bridge handshake timed out')), HANDSHAKE_TIMEOUT_MS)),
			]);
		} catch (error) {
			await this.releaseWorker();
			this.setState(PulseAIEngineState.Crashed);
			throw error;
		}
	}

	send(frame: PulseClientMethod): void {
		if (this._state !== PulseAIEngineState.Ready || !this.processService) {
			throw new Error(`PulseAI engine cannot send while ${this._state}`);
		}
		void this.processService.send(JSON.stringify(frame)).catch(error => {
			this.logService.error('[PulseAI Engine] failed to send bridge frame', error);
			this.setState(PulseAIEngineState.Degraded);
		});
	}

	async stop(): Promise<void> {
		await this.releaseWorker();
		this.setState(PulseAIEngineState.Stopped);
	}

	private async releaseWorker(): Promise<void> {
		this.handshakeResolve = undefined;
		this.handshakeReject = undefined;
		const service = this.processService;
		this.processService = undefined;
		this.session.clear();
		if (service) {
			try { await service.stop(); } catch (error) { this.logService.warn('[PulseAI Engine] stop failed', error); }
		}
		this.worker.clear();
	}

	private acceptFrame(line: string): void {
		try {
			const frame = JSON.parse(line) as PulseServerEvent;
			if (!frame || typeof frame !== 'object' || typeof frame.type !== 'string') {
				throw new Error('bridge frame is missing a string type');
			}
			if (frame.type === 'hello') {
				if (frame.protocol !== PULSE_AI_PROTOCOL_VERSION) {
					throw new Error(`PulseAI protocol mismatch: expected ${PULSE_AI_PROTOCOL_VERSION}, got ${frame.protocol}`);
				}
				this.setState(PulseAIEngineState.Ready);
				this.handshakeResolve?.();
				this.handshakeResolve = undefined;
				this.handshakeReject = undefined;
			}
			this._onDidReceiveFrame.fire(frame);
		} catch (error) {
			const failure = error instanceof Error ? error : new Error(String(error));
			this.logService.error('[PulseAI Engine] invalid bridge frame', failure);
			this.handshakeReject?.(failure);
			this.setState(PulseAIEngineState.Degraded);
		}
	}

	private setState(state: PulseAIEngineState): void {
		if (this._state === state) { return; }
		this._state = state;
		this._onDidChangeState.fire(state);
	}
}
