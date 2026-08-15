/*---------------------------------------------------------------------------------------------
 * PulseAI engine service contract. The Electron implementation owns the Python sidecar.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import type { PulseClientMethod, PulseServerEvent } from './pulseAIProtocol.js';

export const IPulseAIEngineService = createDecorator<IPulseAIEngineService>('pulseAIEngineService');

export const enum PulseAIEngineState {
	Stopped = 'stopped',
	Starting = 'starting',
	Ready = 'ready',
	Degraded = 'degraded',
	Crashed = 'crashed',
}

export interface IPulseAIEngineService {
	readonly _serviceBrand: undefined;
	readonly state: PulseAIEngineState;
	readonly onDidChangeState: Event<PulseAIEngineState>;
	readonly onDidReceiveFrame: Event<PulseServerEvent>;

	start(workspace: string): Promise<void>;
	send(frame: PulseClientMethod): void;
	stop(): Promise<void>;
}
