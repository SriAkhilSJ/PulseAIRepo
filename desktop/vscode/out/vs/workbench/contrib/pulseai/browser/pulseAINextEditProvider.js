/*---------------------------------------------------------------------------------------------
 * PulseAI Next Edit Suggestions (NES) — predicts where the user should edit next.
 * Shows lightbulb-style suggestions after the user makes a change.
 *--------------------------------------------------------------------------------------------*/
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
import { IPulseAIEngineService } from '../common/pulseAIEngineService.js';
let PulseAINextEditProvider = class PulseAINextEditProvider extends Disposable {
    constructor(engineService) {
        super();
        this.engineService = engineService;
        this.suggestions = new Map();
        this.requestCounter = 0;
        this.enabled = true;
        this._register(this.engineService.onDidReceiveFrame(frame => this.handleFrame(frame)));
    }
    setSuggestionHandler(handler) {
        this.handler = handler;
    }
    /**
     * Called after a file edit to request next edit predictions.
     */
    requestNextEdits(resource, workspace) {
        if (!this.enabled) {
            return;
        }
        const request_id = `nes-${++this.requestCounter}`;
        this.engineService.send({
            type: 'next_edit_suggestions',
            request_id,
            resource,
            workspace,
            max_suggestions: 5,
        });
    }
    /**
     * Called when a file change is recorded to update the predictor's context.
     */
    recordChange(resource, line, column, oldText, newText, workspace) {
        // The Python-side predictor tracks changes via its own mechanism.
        // This method is for the VSCode side to know something changed.
    }
    /**
     * Get cached suggestions for a resource.
     */
    getSuggestions(resource) {
        return this.suggestions.get(resource) ?? [];
    }
    /**
     * Clear suggestions for a resource (after accepting one, for example).
     */
    clearSuggestions(resource) {
        this.suggestions.delete(resource);
    }
    handleFrame(frame) {
        if (frame.type !== 'next_edit_result') {
            return;
        }
        const result = frame;
        const suggestions = (result.suggestions ?? []);
        // Group by resource
        const byResource = new Map();
        for (const s of suggestions) {
            const existing = byResource.get(s.resource) ?? [];
            existing.push(s);
            byResource.set(s.resource, existing);
        }
        // Update cached suggestions
        for (const [resource, items] of byResource) {
            this.suggestions.set(resource, items);
            // Notify the handler of the first suggestion
            if (this.handler && items.length > 0) {
                this.handler(items[0]);
            }
        }
    }
};
PulseAINextEditProvider = __decorate([
    __param(0, IPulseAIEngineService)
], PulseAINextEditProvider);
export { PulseAINextEditProvider };
