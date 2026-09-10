/*---------------------------------------------------------------------------------------------
 * PulseAI Next Edit Suggestions (NES) — predicts where the user should edit next.
 * Shows lightbulb-style suggestions after the user makes a change.
 *--------------------------------------------------------------------------------------------*/
import { Disposable } from '../../../../base/common/lifecycle.js';
import { IPulseAIEngineService } from '../common/pulseAIEngineService.js';
export class PulseAINextEditProvider extends Disposable {
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
}
