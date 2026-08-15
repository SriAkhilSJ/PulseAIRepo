/*---------------------------------------------------------------------------------------------
 * Web-safe fallback. Desktop registration replaces this descriptor with the utility-process host.
 *--------------------------------------------------------------------------------------------*/

import { Emitter } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import type { PulseClientMethod, PulseServerEvent } from '../common/pulseAIProtocol.js';
import { IPulseAIEngineService, PulseAIEngineState } from '../common/pulseAIEngineService.js';

export class PulseAIUnavailableEngineService extends Disposable implements IPulseAIEngineService {
	declare readonly _serviceBrand: undefined;
	private _state = PulseAIEngineState.Stopped;
	get state(): PulseAIEngineState { return this._state; }

	private readonly _onDidChangeState = this._register(new Emitter<PulseAIEngineState>());
	readonly onDidChangeState = this._onDidChangeState.event;
	private readonly _onDidReceiveFrame = this._register(new Emitter<PulseServerEvent>());
	readonly onDidReceiveFrame = this._onDidReceiveFrame.event;

	async start(_workspace: string): Promise<void> {
		this._state = PulseAIEngineState.Degraded;
		this._onDidChangeState.fire(this._state);
		throw new Error('The local PulseAI engine is available in the desktop product only');
	}

	send(_frame: PulseClientMethod): void {
		throw new Error('The local PulseAI engine is unavailable in this host');
	}

	async stop(): Promise<void> {
		this._state = PulseAIEngineState.Stopped;
		this._onDidChangeState.fire(this._state);
	}
}
