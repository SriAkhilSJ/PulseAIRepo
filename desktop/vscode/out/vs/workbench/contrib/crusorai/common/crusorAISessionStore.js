/*---------------------------------------------------------------------------------------------
 * The one place that remembers which Crusor sessions exist. Both the Agent Manager's own list and
 * the workbench's session list are projections of this store; neither is allowed to keep a copy.
 *--------------------------------------------------------------------------------------------*/
import { Disposable } from '../../../../base/common/lifecycle.js';
import { Emitter } from '../../../../base/common/event.js';
import { createDecorator } from '../../../../platform/instantiation/common/instantiation.js';
export const ICrusorAISessionStore = createDecorator('crusorAISessionStore');
/** Sessions the manager remembers before the engine can list them. Oldest go first. */
const MAX_TRACKED_SESSIONS = 64;
function signature(facts) {
    const changes = facts.changes ? `${facts.changes.files}:${facts.changes.insertions}:${facts.changes.deletions}` : '';
    return [facts.label, facts.workspaceLabel, facts.statusName ?? '', facts.firstSeenAt ?? '', facts.turnStartedAt ?? '', facts.turnEndedAt ?? '', changes, facts.archived ?? ''].join('|');
}
export class CrusorAISessionStore extends Disposable {
    constructor() {
        super(...arguments);
        this._onDidChange = this._register(new Emitter());
        this.onDidChange = this._onDidChange.event;
        /** Insertion ordered on purpose: the projection sorts for display. */
        this.sessions = new Map();
        this.reads = new Map();
    }
    note(facts) {
        const previous = this.sessions.get(facts.sessionId);
        // `firstSeenAt` is a sighting, so the first one wins: a re-render must not move the age of
        // a session backwards to now.
        const merged = previous?.firstSeenAt !== undefined && previous.firstSeenAt <= (facts.firstSeenAt ?? Infinity)
            ? { ...facts, firstSeenAt: previous.firstSeenAt }
            : facts;
        if (previous && signature(previous) === signature(merged)) {
            return;
        }
        this.sessions.set(facts.sessionId, merged);
        while (this.sessions.size > MAX_TRACKED_SESSIONS) {
            const oldest = this.sessions.keys().next();
            if (oldest.done) {
                break;
            }
            this.sessions.delete(oldest.value);
            this.reads.delete(oldest.value);
        }
        this._onDidChange.fire();
    }
    forget(sessionId) {
        if (!this.sessions.delete(sessionId)) {
            return;
        }
        this.reads.delete(sessionId);
        this._onDidChange.fire();
    }
    markRead(sessionId, isRead) {
        if (this.reads.get(sessionId) === isRead) {
            return;
        }
        this.reads.set(sessionId, isRead);
        this._onDidChange.fire();
    }
    isRead(sessionId) {
        return this.reads.get(sessionId);
    }
    records() {
        return [...this.sessions.values()];
    }
}
