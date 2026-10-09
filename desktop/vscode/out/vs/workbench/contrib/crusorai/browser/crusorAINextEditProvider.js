/*---------------------------------------------------------------------------------------------
 * CrusorAI Next Edit Suggestions (NES) — predicts where the user should edit next.
 * Shows lightbulb-style suggestions after the user makes a change.
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
var __decorate = (this && this.__decorate) || function (decorators, target, key, desc) {
    var c = arguments.length, r = c < 3 ? target : desc === null ? desc = Object.getOwnPropertyDescriptor(target, key) : desc, d;
    if (typeof Reflect === "object" && typeof Reflect.decorate === "function") r = Reflect.decorate(decorators, target, key, desc);
    else for (var i = decorators.length - 1; i >= 0; i--) if (d = decorators[i]) r = (c < 3 ? d(r) : c > 3 ? d(target, key, r) : d(target, key)) || r;
    return c > 3 && r && Object.defineProperty(target, key, r), r;
};
var __param = (this && this.__param) || function (paramIndex, decorator) {
    return function (target, key) { decorator(target, key, paramIndex); }
};
import { Disposable } from '../../../../base/common/lifecycle.js';
import { ICrusorAIEngineService } from '../common/crusorAIEngineService.js';
var CrusorAINextEditProvider = /** @class */ (function (_super) {
    __extends(CrusorAINextEditProvider, _super);
    function CrusorAINextEditProvider(engineService) {
        var _this = _super.call(this) || this;
        _this.engineService = engineService;
        _this.suggestions = new Map();
        _this.requestCounter = 0;
        _this.enabled = true;
        _this._register(_this.engineService.onDidReceiveFrame(function (frame) { return _this.handleFrame(frame); }));
        return _this;
    }
    CrusorAINextEditProvider.prototype.setSuggestionHandler = function (handler) {
        this.handler = handler;
    };
    /**
     * Called after a file edit to request next edit predictions.
     */
    CrusorAINextEditProvider.prototype.requestNextEdits = function (resource, workspace) {
        if (!this.enabled) {
            return;
        }
        var request_id = "nes-".concat(++this.requestCounter);
        this.engineService.send({
            type: 'next_edit_suggestions',
            request_id: request_id,
            resource: resource,
            workspace: workspace,
            max_suggestions: 5,
        });
    };
    /**
     * Called when a file change is recorded to update the predictor's context.
     */
    CrusorAINextEditProvider.prototype.recordChange = function (resource, line, column, oldText, newText, workspace) {
        // The Python-side predictor tracks changes via its own mechanism.
        // This method is for the VSCode side to know something changed.
    };
    /**
     * Get cached suggestions for a resource.
     */
    CrusorAINextEditProvider.prototype.getSuggestions = function (resource) {
        var _a;
        return (_a = this.suggestions.get(resource)) !== null && _a !== void 0 ? _a : [];
    };
    /**
     * Clear suggestions for a resource (after accepting one, for example).
     */
    CrusorAINextEditProvider.prototype.clearSuggestions = function (resource) {
        this.suggestions.delete(resource);
    };
    CrusorAINextEditProvider.prototype.handleFrame = function (frame) {
        var _a, _b;
        if (frame.type !== 'next_edit_result') {
            return;
        }
        var result = frame;
        var suggestions = ((_a = result.suggestions) !== null && _a !== void 0 ? _a : []);
        // Group by resource
        var byResource = new Map();
        for (var _i = 0, suggestions_1 = suggestions; _i < suggestions_1.length; _i++) {
            var s = suggestions_1[_i];
            var existing = (_b = byResource.get(s.resource)) !== null && _b !== void 0 ? _b : [];
            existing.push(s);
            byResource.set(s.resource, existing);
        }
        // Update cached suggestions
        for (var _c = 0, byResource_1 = byResource; _c < byResource_1.length; _c++) {
            var _d = byResource_1[_c], resource = _d[0], items = _d[1];
            this.suggestions.set(resource, items);
            // Notify the handler of the first suggestion
            if (this.handler && items.length > 0) {
                this.handler(items[0]);
            }
        }
    };
    CrusorAINextEditProvider = __decorate([
        __param(0, ICrusorAIEngineService)
    ], CrusorAINextEditProvider);
    return CrusorAINextEditProvider;
}(Disposable));
export { CrusorAINextEditProvider };
