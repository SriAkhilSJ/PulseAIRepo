/*---------------------------------------------------------------------------------------------
 * Utility-process contract. The workbench exchanges JSON strings with a Node worker that owns
 * the Python sidecar; Python/process privileges never enter the renderer.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';

export const PULSE_AI_WORKER_CHANNEL = 'pulseAIWorker';
export const PULSE_AI_WORKER_MODULE_ID = 'vs/workbench/contrib/pulseai/node/pulseAIWorkerMain';

export type PulseAIWorkerState = 'stopped' | 'starting' | 'running' | 'crashed';

export interface PulseAIWorkerStateChange {
	readonly state: PulseAIWorkerState;
	readonly detail?: string;
	readonly code?: number;
	readonly signal?: string;
}

export interface PulseAIWorkerStartOptions {
	readonly engineRoot: string;
	readonly pythonPath?: string;
}

export interface IPulseAIWorkerProcessService {
	readonly onDidReceiveFrame: Event<string>;
	readonly onDidWriteStderr: Event<string>;
	readonly onDidChangeState: Event<PulseAIWorkerStateChange>;

	start(options: PulseAIWorkerStartOptions): Promise<void>;
	send(frame: string): Promise<void>;
	stop(): Promise<void>;
}
