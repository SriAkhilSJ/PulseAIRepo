/*---------------------------------------------------------------------------------------------
 * PulseAI engine service contract. The Electron implementation owns the Python sidecar.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import type { PulseClientMethod, PulseServerEvent } from './pulseAIProtocol.js';

export const IPulseAIEngineService = createDecorator<IPulseAIEngineService>('pulseAIEngineService');

export const PULSE_AI_ENGINE_ROOT_NOT_CONFIGURED =
	'PulseAI engine root is not configured: set pulseai.engineRoot or PULSEAI_ENGINE_ROOT (the opened workspace is never used as the engine).';

/**
 * Engine-setup failure (e.g. engineRoot missing/blank). Distinct from missing
 * workspace: the renderer shows this as an actionable setup error, never as
 * "Open a folder to start a Pulse session."
 */
export class PulseAIEngineSetupError extends Error {
	constructor(message: string = PULSE_AI_ENGINE_ROOT_NOT_CONFIGURED) {
		super(message);
		this.name = 'PulseAIEngineSetupError';
	}
}

/**
 * Resolve the engine package root from its ONLY two sources. The session
 * workspace is deliberately not an input: start() pinning is proven by this
 * signature having no workspace parameter.
 */
export function resolvePulseAIEngineRoot(configured: string | undefined, envRoot: string | undefined): string {
	const root = configured?.trim() || envRoot?.trim() || '';
	if (!root) {
		throw new PulseAIEngineSetupError();
	}
	return root;
}

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
