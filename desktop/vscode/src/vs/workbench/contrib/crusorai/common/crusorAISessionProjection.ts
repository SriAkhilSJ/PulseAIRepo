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
 * Named lifecycle instead of `ChatSessionStatus`, which is a `const enum` in
 * chat/common/chatSessionsService.ts. The controller converts these names to the enum with a
 * switch, so the mapping is checked by the compiler, and this file stays free of chat's module
 * graph -- which is what lets the projection be bundled for tests.
 */
export type CrusorAISessionStatusName = 'inProgress' | 'completed' | 'needsInput' | 'failed';

export interface CrusorAISessionChanges {
	readonly files: number;
	readonly insertions: number;
	readonly deletions: number;
}

/**
 * Everything the IDE can honestly say about one Crusor session. Every field here is observed
 * from an engine frame or from the workbench's own clock; nothing is inferred from a model name,
 * a plan, or a UI state.
 */
export interface CrusorAISessionFacts {
	readonly sessionId: string;
	readonly label: string;
	readonly workspaceLabel: string;
	readonly statusName?: CrusorAISessionStatusName;
	/**
	 * First moment the IDE saw this session id. The engine sends no creation timestamp, so this
	 * is a sighting and not a server-side `created` -- it must never be presented as one.
	 */
	readonly firstSeenAt?: number;
	readonly turnStartedAt?: number;
	readonly turnEndedAt?: number;
	/**
	 * Left undefined until a shared diff counter exists. `changes.files` is what the fork's list
	 * prints as "N files +A -D", so a number counted twice, or zero because nothing was counted,
	 * would be a worse lie than the field being absent. See CRUSOR_COPILOT_REGISTRATION_REVIEW.md.
	 */
	readonly changes?: CrusorAISessionChanges;
	readonly archived?: boolean;
	/**
	 * Durable-store fields, observed from `session_list` rows (or the `session` payload on
	 * create/resume) rather than live frames. All optional: live-only sessions never carry them.
	 */
	readonly pinned?: boolean;
	readonly unread?: boolean;
	readonly messageCount?: number;
	readonly preview?: string;
	readonly createdAt?: number;
	readonly lastActiveAt?: number;
	readonly parentSessionId?: string;
	readonly lineageRootId?: string;
	readonly lazy?: boolean;
}

export interface CrusorAISessionItem {
	readonly resource: URI;
	readonly label: string;
	readonly description: string;
	readonly statusName?: CrusorAISessionStatusName;
	readonly timing: {
		readonly created: number;
		readonly lastRequestStarted: number | undefined;
		readonly lastRequestEnded: number | undefined;
	};
	readonly changes?: CrusorAISessionChanges;
	readonly archived?: boolean;
}

/**
 * The id is percent-encoded into the path and read back out of `URI.path`, never out of
 * `toString()`: an id containing `/` or `%` would otherwise survive a round trip here and be
 * re-escaped by `toString()`. Nothing parses the serialised form for a contributed type, and every
 * per-resource key the workbench stores is built from this same function, so both ends agree.
 */
export function crusorSessionUri(sessionId: string): URI {
	return URI.from({ scheme: CRUSOR_CHAT_SESSION_TYPE, path: `/${encodeURIComponent(sessionId)}` });
}

export function isCrusorSessionUri(resource: URI): boolean {
	return resource.scheme === CRUSOR_CHAT_SESSION_TYPE;
}

export function crusorSessionIdFromUri(resource: URI): string | undefined {
	if (!isCrusorSessionUri(resource)) {
		return undefined;
	}
	const head = resource.path.split('/').filter(part => part.length > 0)[0];
	if (!head) {
		return undefined;
	}
	try {
		return decodeURIComponent(head);
	} catch {
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
export function crusorSessionStatusName(input: {
	readonly running: boolean;
	readonly turnOutcome: 'idle' | 'running' | 'completed' | 'cancelled' | 'failed';
	readonly hasApproval?: boolean;
}): CrusorAISessionStatusName | undefined {
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
export function crusorSessionLabel(userMessage: string | undefined, sessionId: string | undefined): string {
	const text = (userMessage ?? '').replace(/\s+/g, ' ').trim();
	if (!text) {
		return sessionId ? 'Crusor session' : 'New Crusor session';
	}
	return text.length > 90 ? `${text.slice(0, 89)}\u2026` : text;
}

/** True when a label is the generated fallback rather than a user's message — safe to overwrite. Derived from the single source so the two spellings cannot drift. */
export function crusorSessionLabelIsFallback(label: string | undefined): boolean {
	return label === crusorSessionLabel(undefined, 'x') || label === crusorSessionLabel(undefined, undefined);
}

/** Whole seconds since an epoch timestamp, never negative, undefined when there is no origin. */
export function crusorSessionElapsedSeconds(now: number, origin: number | undefined): number | undefined {
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
export function crusorSessionElapsedLabel(seconds: number | undefined, statusName: CrusorAISessionStatusName | undefined): string {
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
export function crusorSessionNeedsAttention(input: {
	readonly statusName?: CrusorAISessionStatusName;
	readonly archived?: boolean;
	readonly isRead?: boolean;
	readonly unread?: boolean;
}): boolean {
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

/** One row of the Manager list: what the fork would show, in our words. */
export interface CrusorAISessionRow extends CrusorAISessionItem {
	readonly elapsedLabel: string;
	readonly isActive: boolean;
	readonly needsAttention: boolean;
	readonly seconds: number | undefined;
}

export function crusorSessionRow(facts: CrusorAISessionFacts, activeSessionId: string | undefined, now: number, isRead: boolean | undefined): CrusorAISessionRow {
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
function lastActivity(row: CrusorAISessionRow): number {
	return Math.max(row.timing.created, row.timing.lastRequestStarted ?? 0, row.timing.lastRequestEnded ?? 0);
}

/**
 * The whole list, newest activity first, deduplicated by session id. Sorting lives here so the
 * Manager and the workbench's own list cannot drift into two different orders of the same
 * sessions -- which is the failure mode this projection exists to prevent.
 */
export function crusorSessionRows(records: readonly CrusorAISessionFacts[], activeSessionId: string | undefined, now: number, readState?: ReadonlyMap<string, boolean>): readonly CrusorAISessionRow[] {
	return records
		.map(facts => crusorSessionRow(facts, activeSessionId, now, readState?.get(facts.sessionId)))
		.sort((left, right) => lastActivity(right) - lastActivity(left));
}

/**
 * Structural engine row (`session_list` payloads and the `session` object on create/resume).
 * Structural -- not the protocol interface -- so this file stays out of the protocol module graph
 * and keeps bundling for tests.
 */
export interface CrusorAIEngineSessionRow {
	readonly session_id?: string;
	readonly id?: string;
	readonly title?: string;
	readonly workspace?: string;
	readonly source?: string;
	readonly model?: string;
	readonly created_at?: number;
	readonly last_active?: number;
	readonly message_count?: number;
	readonly preview?: string;
	readonly pinned?: boolean;
	readonly archived?: boolean;
	readonly hidden?: boolean;
	readonly unread?: boolean;
	readonly parent_session_id?: string | null;
	readonly lineage_root_id?: string | null;
	readonly lazy?: boolean;
}

/** A durable row's label: the stored title, else the preview's first line, never blank. */
/**
 * History labels are engine titles (created by the auto-titler, fixed, unique).
 * The preview (first user message) is NEVER a label (field 2026-09-28): untitled
 * rows render the generic placeholder until the titler's live push lands.
 */
export function crusorEngineRowLabel(row: CrusorAIEngineSessionRow): string {
	const title = (row.title ?? '').replace(/\s+/g, ' ').trim();
	if (title) {
		return title.length > 90 ? `${title.slice(0, 89)}\u2026` : title;
	}
	return 'Crusor session';
}

/**
 * Engine row -> facts. The caller owns live status (running/outcome/approvals); the row owns
 * everything durable. `firstSeenAt` stays a sighting -- `createdAt` is the server-side created.
 */
export function crusorFactsFromEngineRow(row: CrusorAIEngineSessionRow, input: { workspaceLabel: string; statusName?: CrusorAISessionStatusName; now: number }): CrusorAISessionFacts {
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
