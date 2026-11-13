/*---------------------------------------------------------------------------------------------
 * Terminal turn outcome semantics.
 *
 * The bridge is the authority on how a turn ended. A turn that did not complete must never be
 * painted as a success just because the receipt is missing (B-LIVE-002): the previous derivation
 * treated "not cancelled" as "completed", so an engineering failure whose receipt was absent
 * rendered as a normal answer with the error as prose.
 *
 * This module is deliberately DOM-free and import-free so the exact decision can be executed by
 * a test (scripts/test_crusorai_turn_outcome.mjs) instead of being asserted as source text.
 *--------------------------------------------------------------------------------------------*/
const OUTCOME_BY_STATUS = {
    COMPLETED: 'completed',
    SUCCESS: 'completed',
    SUCCEEDED: 'completed',
    CANCELLED: 'cancelled',
    CANCELED: 'cancelled',
    DENIED: 'denied',
    FAILED: 'failed',
    ERROR: 'failed',
    INCOMPLETE: 'incomplete',
    INTERRUPTED: 'incomplete',
    WATCHDOG: 'incomplete',
};
/**
 * Derive the outcome of a finished turn.
 *
 * Order is the contract:
 *  1. an explicit user cancellation wins (the run was stopped, whatever the label says);
 *  2. an authoritative receipt status wins over any inferred flag;
 *  3. otherwise the bridge's `completed` flag decides;
 *  4. with neither, the outcome is unknown — never success.
 */
export function terminalTurnOutcome(signal) {
    if (signal.cancelled === true) {
        return 'cancelled';
    }
    const receiptStatus = String(signal.terminalStatus ?? '').trim().toUpperCase();
    const fromReceipt = receiptStatus ? OUTCOME_BY_STATUS[receiptStatus] : undefined;
    if (fromReceipt) {
        return fromReceipt;
    }
    // No canonical receipt: the evidence manifest still names the terminal
    // reason (a watchdog stall is `watchdog`, not a user stop and not a success).
    const evidenceStatus = String(signal.evidenceStatus ?? '').trim().toUpperCase();
    const fromEvidence = evidenceStatus ? OUTCOME_BY_STATUS[evidenceStatus] : undefined;
    if (fromEvidence) {
        return fromEvidence;
    }
    if (signal.completed === true) {
        return 'completed';
    }
    if (signal.completed === false) {
        return 'failed';
    }
    return 'unknown';
}
/** Narrow an arbitrary wire value to a settled outcome, for restored turns. */
export function asTurnOutcome(value) {
    const text = String(value ?? '').trim().toLowerCase();
    if (!text) {
        return undefined;
    }
    const settled = [
        'completed', 'failed', 'cancelled', 'denied', 'incomplete', 'unknown',
    ];
    return settled.includes(text)
        ? text
        : undefined;
}
/**
 * The outcome to attach to a restored turn. A turn whose durable terminal event is missing keeps
 * the ambiguous label; it is not upgraded to `completed`.
 */
export function restoredTurnOutcome(outcomes, turnId) {
    if (!turnId) {
        return 'unknown';
    }
    return asTurnOutcome(outcomes?.[turnId]) ?? 'unknown';
}
/** Outcomes that get an explicit receipt row in the transcript. */
export function turnOutcomeReceipt(outcome) {
    switch (outcome) {
        case 'failed': return { label: 'Run failed', glyph: 'error' };
        case 'cancelled': return { label: 'Run cancelled', glyph: 'circle-slash' };
        case 'denied': return { label: 'Run denied', glyph: 'circle-slash' };
        case 'incomplete': return { label: 'Run incomplete', glyph: 'warning' };
        case 'unknown': return { label: 'Outcome not recorded', glyph: 'question' };
        default: return undefined;
    }
}
