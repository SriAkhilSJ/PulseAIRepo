/*---------------------------------------------------------------------------------------------
 * CrusorAI engine service contract. The Electron implementation owns the Python sidecar.
 *--------------------------------------------------------------------------------------------*/
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
export const ICrusorAIEngineService = createDecorator('crusorAIEngineService');
export const CRUSOR_AI_ENGINE_ROOT_NOT_CONFIGURED = 'CrusorAI engine root is not configured: set crusorai.engineRoot or CRUSORAI_ENGINE_ROOT, or open a workspace that contains src/bridge.';
/**
 * Engine-setup failure (e.g. engineRoot missing/blank). Distinct from missing
 * workspace: the renderer shows this as an actionable setup error, never as
 * "Open a folder to start a Crusor session."
 */
export class CrusorAIEngineSetupError extends Error {
    constructor(message = CRUSOR_AI_ENGINE_ROOT_NOT_CONFIGURED) {
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
export function resolveCrusorAIEngineRoot(configured, envRoot, workspace) {
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
export var CrusorAIEngineState;
(function (CrusorAIEngineState) {
    CrusorAIEngineState["Stopped"] = "stopped";
    CrusorAIEngineState["Starting"] = "starting";
    CrusorAIEngineState["Ready"] = "ready";
    CrusorAIEngineState["Degraded"] = "degraded";
    CrusorAIEngineState["Crashed"] = "crashed";
})(CrusorAIEngineState || (CrusorAIEngineState = {}));
