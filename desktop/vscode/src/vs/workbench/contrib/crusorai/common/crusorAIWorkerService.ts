/*---------------------------------------------------------------------------------------------
 * Utility-process contract. The workbench exchanges JSON strings with a Node worker that owns
 * the Python sidecar; Python/process privileges never enter the renderer.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';

export const CRUSOR_AI_WORKER_CHANNEL = 'crusorAIWorker';
export const CRUSOR_AI_WORKER_MODULE_ID = 'vs/workbench/contrib/crusorai/node/crusorAIWorkerMain';

export type CrusorAIWorkerState = 'stopped' | 'starting' | 'running' | 'crashed';

export interface CrusorAIWorkerStateChange {
	readonly state: CrusorAIWorkerState;
	readonly detail?: string;
	readonly code?: number;
	readonly signal?: string;
}

export interface CrusorAIWorkerStartOptions {
	readonly engineRoot: string;
	readonly pythonPath?: string;
}

export interface ICrusorAIWorkerProcessService {
	readonly onDidReceiveFrame: Event<string>;
	readonly onDidWriteStderr: Event<string>;
	readonly onDidChangeState: Event<CrusorAIWorkerStateChange>;

	start(options: CrusorAIWorkerStartOptions): Promise<void>;
	send(frame: string): Promise<void>;
	stop(): Promise<void>;
}
