/*---------------------------------------------------------------------------------------------
 * Web-safe fallback. Desktop registration replaces this descriptor with the utility-process host.
 *--------------------------------------------------------------------------------------------*/

import { Emitter } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import type { CrusorClientMethod, CrusorServerEvent } from '../common/crusorAIProtocol.js';
import { ICrusorAIEngineService, CrusorAIEngineState } from '../common/crusorAIEngineService.js';

export class CrusorAIUnavailableEngineService extends Disposable implements ICrusorAIEngineService {
	declare readonly _serviceBrand: undefined;
	private _state = CrusorAIEngineState.Stopped;
	get state(): CrusorAIEngineState { return this._state; }

	private readonly _onDidChangeState = this._register(new Emitter<CrusorAIEngineState>());
	readonly onDidChangeState = this._onDidChangeState.event;
	private readonly _onDidReceiveFrame = this._register(new Emitter<CrusorServerEvent>());
	readonly onDidReceiveFrame = this._onDidReceiveFrame.event;

	async start(_workspace: string): Promise<void> {
		this._state = CrusorAIEngineState.Degraded;
		this._onDidChangeState.fire(this._state);
		throw new Error('The local CrusorAI engine is available in the desktop product only');
	}

	send(_frame: CrusorClientMethod): void {
		throw new Error('The local CrusorAI engine is unavailable in this host');
	}

	async stop(): Promise<void> {
		this._state = CrusorAIEngineState.Stopped;
		this._onDidChangeState.fire(this._state);
	}
}
