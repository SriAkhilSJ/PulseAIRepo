/*---------------------------------------------------------------------------------------------
 * The one place that remembers which Pulse sessions exist. Both the Agent Manager's own list and
 * the workbench's session list are projections of this store; neither is allowed to keep a copy.
 *--------------------------------------------------------------------------------------------*/

import { Disposable } from '../../../../base/common/lifecycle.js';
import { Emitter, Event } from '../../../../base/common/event.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
import type { PulseAISessionFacts } from './pulseAISessionProjection.js';

export const IPulseAISessionStore = createDecorator<IPulseAISessionStore>('pulseAISessionStore');

export interface IPulseAISessionStore {
	readonly _serviceBrand: undefined;

	/** Upsert. Merges into an existing session and fires only when something visible changed. */
	note(facts: PulseAISessionFacts): void;

	forget(sessionId: string): void;

	/**
	 * Read state for our own surface. The workbench's list deliberately does not read this: the
	 * controller leaves `IChatSessionItem.isRead` undefined so the host's own persisted read
	 * tracking (storage per resource) applies there instead of an in-memory guess.
	 */
	markRead(sessionId: string, isRead: boolean): void;
	isRead(sessionId: string): boolean | undefined;

	records(): readonly PulseAISessionFacts[];
	readonly onDidChange: Event<void>;
}

/** Sessions the manager remembers before the engine can list them. Oldest go first. */
const MAX_TRACKED_SESSIONS = 64;

function signature(facts: PulseAISessionFacts): string {
	const changes = facts.changes ? `${facts.changes.files}:${facts.changes.insertions}:${facts.changes.deletions}` : '';
	return [facts.label, facts.workspaceLabel, facts.statusName ?? '', facts.firstSeenAt ?? '', facts.turnStartedAt ?? '', facts.turnEndedAt ?? '', changes, facts.archived ?? ''].join('|');
}

export class PulseAISessionStore extends Disposable implements IPulseAISessionStore {
	declare readonly _serviceBrand: undefined;

	private readonly _onDidChange = this._register(new Emitter<void>());
	readonly onDidChange: Event<void> = this._onDidChange.event;

	/** Insertion ordered on purpose: the projection sorts for display. */
	private readonly sessions = new Map<string, PulseAISessionFacts>();
	private readonly reads = new Map<string, boolean>();

	note(facts: PulseAISessionFacts): void {
		const previous = this.sessions.get(facts.sessionId);
		// `firstSeenAt` is a sighting, so the first one wins: a re-render must not move the age of
		// a session backwards to now.
		const merged: PulseAISessionFacts = previous?.firstSeenAt !== undefined && previous.firstSeenAt <= (facts.firstSeenAt ?? Infinity)
			? { ...facts, firstSeenAt: previous.firstSeenAt }
			: facts;
		if (previous && signature(previous) === signature(merged)) {
			return;
		}
		this.sessions.set(facts.sessionId, merged);
		while (this.sessions.size > MAX_TRACKED_SESSIONS) {
			const oldest = this.sessions.keys().next();
			if (oldest.done) { break; }
			this.sessions.delete(oldest.value);
			this.reads.delete(oldest.value);
		}
		this._onDidChange.fire();
	}

	forget(sessionId: string): void {
		if (!this.sessions.delete(sessionId)) { return; }
		this.reads.delete(sessionId);
		this._onDidChange.fire();
	}

	markRead(sessionId: string, isRead: boolean): void {
		if (this.reads.get(sessionId) === isRead) { return; }
		this.reads.set(sessionId, isRead);
		this._onDidChange.fire();
	}

	isRead(sessionId: string): boolean | undefined {
		return this.reads.get(sessionId);
	}

	records(): readonly PulseAISessionFacts[] {
		return [...this.sessions.values()];
	}
}
