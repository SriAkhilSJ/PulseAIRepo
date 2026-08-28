/*---------------------------------------------------------------------------------------------
 * PulseAI Next Edit Suggestions (NES) — predicts where the user should edit next.
 * Shows lightbulb-style suggestions after the user makes a change.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { IPulseAIEngineService } from '../common/pulseAIEngineService.js';
import type { PulseServerEvent } from '../common/pulseAIProtocol.js';

export interface NESuggestion {
	readonly resource: string;
	readonly line: number;
	readonly column: number;
	readonly endLine: number;
	readonly endColumn: number;
	readonly title: string;
	readonly description: string;
	readonly confidence: number;
	readonly category: string;
}

export type NESuggestionHandler = (suggestion: NESuggestion) => void;

export class PulseAINextEditProvider extends Disposable {
	declare readonly _serviceBrand: undefined;

	private readonly suggestions = new Map<string, NESuggestion[]>();
	private requestCounter = 0;
	private enabled = true;
	private handler: NESuggestionHandler | undefined;

	constructor(
		@IPulseAIEngineService private readonly engineService: IPulseAIEngineService,
	) {
		super();
		this._register(this.engineService.onDidReceiveFrame(frame => this.handleFrame(frame)));
	}

	setSuggestionHandler(handler: NESuggestionHandler): void {
		this.handler = handler;
	}

	/**
	 * Called after a file edit to request next edit predictions.
	 */
	requestNextEdits(resource: string, workspace: string): void {
		if (!this.enabled) { return; }

		const request_id = `nes-${++this.requestCounter}`;
		this.engineService.send({
			type: 'next_edit_suggestions',
			request_id,
			resource,
			workspace,
			max_suggestions: 5,
		} as any);
	}

	/**
	 * Called when a file change is recorded to update the predictor's context.
	 */
	recordChange(resource: string, line: number, column: number, oldText: string, newText: string, workspace: string): void {
		// The Python-side predictor tracks changes via its own mechanism.
		// This method is for the VSCode side to know something changed.
	}

	/**
	 * Get cached suggestions for a resource.
	 */
	getSuggestions(resource: string): readonly NESuggestion[] {
		return this.suggestions.get(resource) ?? [];
	}

	/**
	 * Clear suggestions for a resource (after accepting one, for example).
	 */
	clearSuggestions(resource: string): void {
		this.suggestions.delete(resource);
	}

	private handleFrame(frame: PulseServerEvent): void {
		if (frame.type !== 'next_edit_result') { return; }
		const result = frame as any;
		const suggestions = (result.suggestions ?? []) as NESuggestion[];

		// Group by resource
		const byResource = new Map<string, NESuggestion[]>();
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
