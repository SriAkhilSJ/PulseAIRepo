/*---------------------------------------------------------------------------------------------
 * CrusorAI engine service contract. The Electron implementation owns the Python sidecar.
 *--------------------------------------------------------------------------------------------*/
var __extends = (this && this.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
export var ICrusorAIEngineService = createDecorator('crusorAIEngineService');
export var CRUSOR_AI_ENGINE_ROOT_NOT_CONFIGURED = 'CrusorAI engine root is not configured: set crusorai.engineRoot or CRUSORAI_ENGINE_ROOT, or open a workspace that contains src/bridge.';
/**
 * Engine-setup failure (e.g. engineRoot missing/blank). Distinct from missing
 * workspace: the renderer shows this as an actionable setup error, never as
 * "Open a folder to start a Crusor session."
 */
var CrusorAIEngineSetupError = /** @class */ (function (_super) {
    __extends(CrusorAIEngineSetupError, _super);
    function CrusorAIEngineSetupError(message) {
        if (message === void 0) { message = CRUSOR_AI_ENGINE_ROOT_NOT_CONFIGURED; }
        var _this = _super.call(this, message) || this;
        _this.name = 'CrusorAIEngineSetupError';
        return _this;
    }
    return CrusorAIEngineSetupError;
}(Error));
export { CrusorAIEngineSetupError };
/**
 * Resolve the engine package root. Priority:
 *  1. crusorai.engineRoot setting (explicit user config)
 *  2. CRUSORAI_ENGINE_ROOT env var
 *  3. Workspace auto-detect: if the opened workspace contains src/bridge,
 *     treat the workspace as the engine root (common for development).
 */
export function resolveCrusorAIEngineRoot(configured, envRoot, workspace) {
    var root = (configured === null || configured === void 0 ? void 0 : configured.trim()) || (envRoot === null || envRoot === void 0 ? void 0 : envRoot.trim()) || '';
    if (root) {
        return root;
    }
    // Auto-detect: if the workspace itself contains src/bridge, use it.
    if (workspace === null || workspace === void 0 ? void 0 : workspace.trim()) {
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
