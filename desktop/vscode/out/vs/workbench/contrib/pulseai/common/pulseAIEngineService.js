/*---------------------------------------------------------------------------------------------
 * PulseAI engine service contract. The Electron implementation owns the Python sidecar.
 *--------------------------------------------------------------------------------------------*/
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
export const IPulseAIEngineService = createDecorator('pulseAIEngineService');
export const PULSE_AI_ENGINE_ROOT_NOT_CONFIGURED = 'PulseAI engine root is not configured: set pulseai.engineRoot or PULSEAI_ENGINE_ROOT, or open a workspace that contains src/bridge.';
/**
 * Engine-setup failure (e.g. engineRoot missing/blank). Distinct from missing
 * workspace: the renderer shows this as an actionable setup error, never as
 * "Open a folder to start a Pulse session."
 */
export class PulseAIEngineSetupError extends Error {
    constructor(message = PULSE_AI_ENGINE_ROOT_NOT_CONFIGURED) {
        super(message);
        this.name = 'PulseAIEngineSetupError';
    }
}
/**
 * Resolve the engine package root. Priority:
 *  1. pulseai.engineRoot setting (explicit user config)
 *  2. PULSEAI_ENGINE_ROOT env var
 *  3. Workspace auto-detect: if the opened workspace contains src/bridge,
 *     treat the workspace as the engine root (common for development).
 */
export function resolvePulseAIEngineRoot(configured, envRoot, workspace) {
    const root = configured?.trim() || envRoot?.trim() || '';
    if (root) {
        return root;
    }
    // Auto-detect: if the workspace itself contains src/bridge, use it.
    if (workspace?.trim()) {
        return workspace.trim();
    }
    throw new PulseAIEngineSetupError();
}
export var PulseAIEngineState;
(function (PulseAIEngineState) {
    PulseAIEngineState["Stopped"] = "stopped";
    PulseAIEngineState["Starting"] = "starting";
    PulseAIEngineState["Ready"] = "ready";
    PulseAIEngineState["Degraded"] = "degraded";
    PulseAIEngineState["Crashed"] = "crashed";
})(PulseAIEngineState || (PulseAIEngineState = {}));
