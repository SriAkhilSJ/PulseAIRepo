/*---------------------------------------------------------------------------------------------
 * The Agent Manager's rows in the workbench's own vocabulary rather than a private one: one
 * session type, the shared ChatSessionStatus lifecycle, real timing, and a change set that is
 * omitted instead of guessed.
 *
 * Pure and DOM-free on purpose. The renderer paints these rows; it does not decide what they
 * mean -- that happens here, where src/tests/test_hermes_session_projection_parity.py can bundle
 * the file and pin every branch without a browser.
 *--------------------------------------------------------------------------------------------*/
import { URI } from '../../../../base/common/uri.js';
/**
 * Crusor's chat session type. `getChatSessionType()` (chat/common/model/chatUri.ts) returns
 * `resource.scheme` for any contributed type, so the type id and the URI scheme are the same
 * string: inventing a second scheme would be a second identity for one session.
 */
export const CRUSOR_CHAT_SESSION_TYPE = 'crusorai';
/**
 * The id is percent-encoded into the path and read back out of `URI.path`, never out of
 * `toString()`: an id containing `/` or `%` would otherwise survive a round trip here and be
 * re-escaped by `toString()`. Nothing parses the serialised form for a contributed type, and every
 * per-resource key the workbench stores is built from this same function, so both ends agree.
 */
export function crusorSessionUri(sessionId) {
    return URI.from({ scheme: CRUSOR_CHAT_SESSION_TYPE, path: `/${encodeURIComponent(sessionId)}` });
}
export function isCrusorSessionUri(resource) {
    return resource.scheme === CRUSOR_CHAT_SESSION_TYPE;
}
export function crusorSessionIdFromUri(resource) {
    if (!isCrusorSessionUri(resource)) {
        return undefined;
    }
    const head = resource.path.split('/').filter(part => part.length > 0)[0];
    if (!head) {
        return undefined;
    }
    try {
        return decodeURIComponent(head);
    }
    catch {
        return head;
    }
}
/**
 * Lifecycle from the only signals the engine sends, in the order the meaning requires: an open
 * approval outranks "running", because that is exactly what needsInput is for -- the fork's list
 * crusors on it (`agentSessionsViewer.ts` renders a ring) and shows a spinner for InProgress.
 *
 * `idle` with no turn yet returns undefined rather than 'completed': the fork treats
 * Completed-and-unread as attention (agentSessionsModel.ts:227), so a brand new session would
 * light up as something to look at before it has done anything.
 */
export function crusorSessionStatusName(input) {
    if (input.hasApproval) {
        return 'needsInput';
    }
    if (input.turnOutcome === 'failed') {
        return 'failed';
    }
    if (input.running || input.turnOutcome === 'running') {
        return 'inProgress';
    }
    if (input.turnOutcome === 'completed' || input.turnOutcome === 'cancelled') {
        return 'completed';
    }
    return undefined;
}
/** A row label is the user's own first message, whitespace-collapsed and cut at word loss. */
export function crusorSessionLabel(userMessage, sessionId) {
    const text = (userMessage ?? '').replace(/\s+/g, ' ').trim();
    if (!text) {
        return sessionId ? 'Crusor session' : 'New Crusor session';
    }
    return text.length > 90 ? `${text.slice(0, 89)}\u2026` : text;
}
/** Whole seconds since an epoch timestamp, never negative, undefined when there is no origin. */
export function crusorSessionElapsedSeconds(now, origin) {
    if (origin === undefined || !Number.isFinite(origin) || now < origin) {
        return undefined;
    }
    return Math.floor((now - origin) / 1000);
}
/**
 * The duration text for a list row, which follows the fork's list rules rather than our
 * transcript lane's: an in-progress session says what it is doing, anything under a minute reads
 * as "now", and older rows count whole minutes. Both surfaces share the model, not the copy.
 */
export function crusorSessionElapsedLabel(seconds, statusName) {
    if (statusName === 'inProgress') {
        return 'Working\u2026';
    }
    if (statusName === 'needsInput') {
        return 'Needs input';
    }
    if (seconds === undefined) {
        return '';
    }
    return seconds < 60 ? 'now' : `${Math.floor(seconds / 60)}m`;
}
/** True when a row should be marked unread-attention: finished, and not opened since. */
export function crusorSessionNeedsAttention(input) {
    if (input.archived === true || input.statusName !== 'completed') {
        return false;
    }
    // The engine's durable unread bit is the source of truth after a restart; the in-memory
    // isRead map only exists for sessions sighted this run.
    if (input.unread !== undefined) {
        return input.unread;
    }
    return input.isRead !== true;
}
export function crusorSessionRow(facts, activeSessionId, now, isRead) {
    const origin = facts.turnEndedAt ?? facts.lastActiveAt ?? facts.turnStartedAt ?? facts.firstSeenAt;
    const seconds = crusorSessionElapsedSeconds(now, origin);
    return {
        resource: crusorSessionUri(facts.sessionId),
        label: facts.label,
        description: facts.workspaceLabel,
        statusName: facts.statusName,
        timing: {
            created: facts.createdAt ?? facts.firstSeenAt ?? now,
            lastRequestStarted: facts.turnStartedAt,
            lastRequestEnded: facts.turnEndedAt ?? facts.lastActiveAt,
        },
        // Omitted, not zeroed: callers must be able to tell "no diff reported" from "no changes".
        ...(facts.changes ? { changes: facts.changes } : {}),
        ...(facts.archived !== undefined ? { archived: facts.archived } : {}),
        elapsedLabel: crusorSessionElapsedLabel(seconds, facts.statusName),
        isActive: facts.sessionId === activeSessionId,
        needsAttention: crusorSessionNeedsAttention({ statusName: facts.statusName, archived: facts.archived, isRead, unread: facts.unread }),
        seconds,
    };
}
/** The row the fork's list would call "last updated": the most recent of the three it knows. */
function lastActivity(row) {
    return Math.max(row.timing.created, row.timing.lastRequestStarted ?? 0, row.timing.lastRequestEnded ?? 0);
}
/**
 * The whole list, newest activity first, deduplicated by session id. Sorting lives here so the
 * Manager and the workbench's own list cannot drift into two different orders of the same
 * sessions -- which is the failure mode this projection exists to prevent.
 */
export function crusorSessionRows(records, activeSessionId, now, readState) {
    return records
        .map(facts => crusorSessionRow(facts, activeSessionId, now, readState?.get(facts.sessionId)))
        .sort((left, right) => lastActivity(right) - lastActivity(left));
}
/** A durable row's label: the stored title, else the preview's first line, never blank. */
export function crusorEngineRowLabel(row) {
    const title = (row.title ?? '').replace(/\s+/g, ' ').trim();
    if (title) {
        return title.length > 90 ? `${title.slice(0, 89)}\u2026` : title;
    }
    const preview = (row.preview ?? '').replace(/\s+/g, ' ').trim();
    if (preview) {
        return preview.length > 90 ? `${preview.slice(0, 89)}\u2026` : preview;
    }
    return 'Crusor session';
}
/**
 * Engine row -> facts. The caller owns live status (running/outcome/approvals); the row owns
 * everything durable. `firstSeenAt` stays a sighting -- `createdAt` is the server-side created.
 */
export function crusorFactsFromEngineRow(row, input) {
    return {
        sessionId: row.session_id ?? row.id ?? '',
        label: crusorEngineRowLabel(row),
        workspaceLabel: input.workspaceLabel,
        statusName: input.statusName,
        firstSeenAt: input.now,
        archived: row.archived,
        pinned: row.pinned,
        unread: row.unread,
        messageCount: row.message_count,
        preview: row.preview,
        createdAt: row.created_at,
        lastActiveAt: row.last_active,
        parentSessionId: row.parent_session_id ?? undefined,
        lineageRootId: row.lineage_root_id ?? undefined,
        lazy: row.lazy,
    };
}
