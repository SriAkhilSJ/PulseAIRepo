/*---------------------------------------------------------------------------------------------
 * CrusorAI engine service contract. The Electron implementation owns the Python sidecar.
 *--------------------------------------------------------------------------------------------*/

import { Event } from '../../../../base/common/event.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import type { CrusorClientMethod, CrusorServerEvent } from './crusorAIProtocol.js';

export const ICrusorAIEngineService = createDecorator<ICrusorAIEngineService>('crusorAIEngineService');

export const CRUSOR_AI_ENGINE_ROOT_NOT_CONFIGURED =
	'CrusorAI engine root is not configured: set crusorai.engineRoot or CRUSORAI_ENGINE_ROOT, or open a workspace that contains src/bridge.';

/**
 * Engine-setup failure (e.g. engineRoot missing/blank). Distinct from missing
 * workspace: the renderer shows this as an actionable setup error, never as
 * "Open a folder to start a Crusor session."
 */
export class CrusorAIEngineSetupError extends Error {
	constructor(message: string = CRUSOR_AI_ENGINE_ROOT_NOT_CONFIGURED) {
		super(message);
		this.name = 'CrusorAIEngineSetupError';
	}
}

/**
 * Resolve the engine package root. Priority:
 *  1. crusorai.engineRoot setting (explicit user config)
 *  2. CRUSORAI_ENGINE_ROOT env var
 *  3. Workspace auto-detect: if the opened workspace contains src/bridge,
 *     treat the workspace as the engine root (common for development).
 */
export function resolveCrusorAIEngineRoot(configured: string | undefined, envRoot: string | undefined, workspace?: string): string {
	const root = configured?.trim() || envRoot?.trim() || '';
	if (root) {
		return root;
	}
	// Auto-detect: if the workspace itself contains src/bridge, use it.
	if (workspace?.trim()) {
		return workspace.trim();
	}
	throw new CrusorAIEngineSetupError();
}

export const enum CrusorAIEngineState {
	Stopped = 'stopped',
	Starting = 'starting',
	Ready = 'ready',
	Degraded = 'degraded',
	Crashed = 'crashed',
}

export interface ICrusorAIEngineService {
	readonly _serviceBrand: undefined;
	readonly state: CrusorAIEngineState;
	readonly onDidChangeState: Event<CrusorAIEngineState>;
	readonly onDidReceiveFrame: Event<CrusorServerEvent>;

	start(workspace: string): Promise<void>;
	send(frame: CrusorClientMethod): void;
	stop(): Promise<void>;
}
