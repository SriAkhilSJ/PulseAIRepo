/*---------------------------------------------------------------------------------------------
 * The tail activity row -- "breathing" and "thinking" -- ported from hermes-agent
 * `assistant-ui/thread/turn-activity.ts` and `components/chat/activity-timer.ts` @ a9c783f2,
 * with the reveal/label rules from `thread/status.tsx`, and kept DOM-free so the same numbers
 * the webview computes (`pulse-webview/src/hermes-ui/model/turn-activity.ts`,
 * `model/activity-timer.ts`, `components/status-line.tsx`) can be executed against it in a test.
 *--------------------------------------------------------------------------------------------*/

import { isSilentTool } from './pulseAIRunSummary.js';

/**
 * Seconds of silence before an unnamed wait earns a row of its own.
 *
 * Long enough that the pause between one tool call finishing and the next arriving stays
 * silent -- a row that appeared for 300ms between every call would strobe down a long run --
 * short enough that a real gap is timed almost as soon as it starts.
 */
export const TURN_QUIET_S = 2;

/**
 * Long enough that a tool whose arguments arrive in a few frames never gets to strobe a label,
 * short enough that a real wait is named almost immediately.
 */
export const DRAFTING_REVEAL_MS = 200;

/** Compaction is in flight -- it outranks every other hint. */
export const COMPACTION_LABEL = 'Summarizing thread';

/** The row's `aria-label` and the visible label's stand-in when there is nothing to name yet. */
export const UNNAMED_WAIT_LABEL = 'Pulse is working';

export interface PulseActivityPart {
	readonly type: string;
	readonly toolName?: string;
	readonly text?: string;
	readonly result?: unknown;
}

/**
 * What the tail message has produced so far, as a value that changes exactly when the turn
 * makes visible progress.
 *
 * Part count and text length cover streamed prose and each new call. Settled calls are counted
 * separately because a result lands by MUTATING the part that was already there: neither the
 * count nor the text changes, so a signature without it reads a finished tool call as more of
 * the same silence and dates the gap after it from whenever the call started.
 */
export function activitySignature(parts: readonly PulseActivityPart[]): string {
	let textLength = 0;
	let settledTools = 0;

	for (const part of parts) {
		if (typeof part.text === 'string') {
			textLength += part.text.length;
		}

		if (part.type === 'tool-call' && part.result !== undefined) {
			settledTools += 1;
		}
	}

	return `${parts.length}:${textLength}:${settledTools}`;
}

/**
 * Whether a tool call is already narrating this wait.
 *
 * A call in flight renders its own row, with its own timer, so a second spinner under it would
 * count the same seconds twice. Silent tools don't: Pulse's `think` receipts are hoisted into
 * the reasoning disclosure, so a wait on one of those is as unnarrated as a wait on nothing.
 */
export function toolNarratesWait(parts: readonly PulseActivityPart[]): boolean {
	return parts.some(part => part.type === 'tool-call' && part.result === undefined && !isSilentTool(part.toolName ?? ''));
}

/**
 * The fork's copy of upstream's timer registry (`model/activity-timer.ts`), which exists because
 * a number measured *while watching* must outlive the thing doing the watching: the transcript
 * repaints wholesale on every frame, so an elapsed count kept in a row would reset constantly
 * and a finished duration would be lost the moment its row scrolled away. Keyed, module-level,
 * and never cleared between renders -- `closeMeasurement` retires an origin and remembers it.
 */
const startedAtByKey = new Map<string, number>();
const durationByKey = new Map<string, number>();

/** Whole seconds since this key's origin, arming the origin on first use. */
export function elapsedFor(key: string, now: number): number {
	const origin = startedAtByKey.get(key) ?? now;
	startedAtByKey.set(key, origin);
	return Math.max(0, Math.floor((now - origin) / 1000));
}

/** Stop watching `key` and keep the number. Idempotent: closing twice reports the same duration. */
export function closeMeasurement(key: string, now: number): number | undefined {
	const origin = startedAtByKey.get(key);
	if (origin === undefined) { return durationByKey.get(key); }
	const finalElapsed = Math.max(durationByKey.get(key) ?? 0, Math.floor((now - origin) / 1000));
	durationByKey.set(key, finalElapsed);
	startedAtByKey.delete(key);
	return finalElapsed;
}

/** The remembered duration for `key`, or undefined if it was never watched at all. */
export function measuredDuration(key: string): number | undefined {
	return durationByKey.get(key);
}

/** `45s`, then `1:05`. Never a moving decimal: a ticking fraction reads as a benchmark. */
export function formatElapsed(seconds: number): string {
	if (seconds < 60) {
		return `${seconds}s`;
	}

	return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/** Whole seconds since `origin`; 0 when there is no origin yet or the clock went backwards. */
export function elapsedSeconds(now: number, origin: number | undefined): number {
	if (origin === undefined) { return 0; }
	return Math.max(0, Math.floor((now - origin) / 1000));
}

/** The settled states of the fork's tool lifecycle -- `result` presence is what upstream reads. */
const SETTLED_STATES = new Set(['completed', 'passed', 'failed', 'cancelled']);

/**
 * The fork's render model, expressed as the part list upstream computes over.
 *
 * `assistantText` and `reasoning` become text parts (their lengths are the visible progress);
 * each call becomes a tool-call part whose `result` is present only once the call has settled,
 * which is the same signal the webview gets from the store.
 */
export function activityParts(model: {
	readonly assistantText: string;
	readonly reasoning?: string;
	readonly tools: readonly { readonly name: string; readonly state: string; readonly result?: unknown }[];
}): PulseActivityPart[] {
	const parts: PulseActivityPart[] = [];
	if (model.reasoning) { parts.push({ type: 'reasoning', text: model.reasoning }); }
	if (model.assistantText) { parts.push({ type: 'text', text: model.assistantText }); }
	for (const tool of model.tools) {
		const settled = SETTLED_STATES.has(tool.state);
		parts.push({ type: 'tool-call', toolName: tool.name, result: settled ? tool.result ?? true : undefined });
	}
	return parts;
}

/** The call the wait is named after: the newest one still in flight, if any. */
export function draftingToolName(tools: readonly { readonly name: string; readonly state: string }[]): string {
	for (let index = tools.length - 1; index >= 0; index--) {
		const tool = tools[index];
		if (tool.state === 'running' || tool.state === 'queued' || tool.state === 'pending') { return tool.name; }
	}
	return '';
}

/**
 * What to call the wait, if it deserves a name. Compaction outranks a draft -- it is rarer,
 * slower, and explains a transcript that looks like it reset. An unrevealed hint name is the
 * empty string, and an empty label is what keeps a fast tool from flashing a row.
 */
export function statusHintLabel(compacting: boolean | undefined, hintName: string, revealed: boolean): string {
	if (compacting) { return COMPACTION_LABEL; }
	return revealed && hintName ? hintName : '';
}

/**
 * Whether the row shows at all: the turn is busy, nobody is being asked a question, no tool
 * row is already narrating, and there is something to say -- a named wait, or a quiet spell
 * long enough to time.
 */
export function activityRowVisible(input: {
	readonly working: boolean;
	readonly awaitingInput: boolean;
	readonly toolNarrating: boolean;
	readonly hint: string;
	readonly quietSince: number | undefined;
}): boolean {
	return input.working
		&& !input.awaitingInput
		&& !input.toolNarrating
		&& (input.hint.length > 0 || input.quietSince !== undefined);
}

/**
 * Which row to show, if any -- the whole decision, so it can be tested without a DOM.
 *
 * Upstream splits this across two components: `ResponseLoadingIndicator` renders whenever the tail
 * message has produced nothing yet, and `TurnActivityIndicator` additionally waits for a named
 * hint or a quiet spell of TURN_QUIET_S. Collapsing the two into one gate would have lost the
 * first case -- a turn that has sent nothing for 400ms would have shown no row at all, which is
 * exactly the blank moment the spinner exists to fill.
 */
export type PulseActivitySlot = 'aui_response-loading' | 'aui_turn-activity';

export function activityRowMode(input: {
	readonly parts: readonly PulseActivityPart[];
	readonly working: boolean;
	readonly awaitingInput: boolean;
	readonly toolNarrating: boolean;
	readonly hint: string;
	readonly quietSince: number | undefined;
}): PulseActivitySlot | undefined {
	if (!input.working || input.awaitingInput) { return undefined; }
	if (!input.parts.length) { return 'aui_response-loading'; }
	return activityRowVisible(input) ? 'aui_turn-activity' : undefined;
}

/**
 * What the timer counts from. Compaction owns the whole turn, so it keeps counting from the
 * turn's start; anything else counts from the moment the turn last produced something.
 */
export function activityOrigin(input: {
	readonly compacting: boolean | undefined;
	readonly turnStartedAt: number | undefined;
	readonly quietSince: number | undefined;
}): number | undefined {
	return input.compacting ? input.turnStartedAt : (input.quietSince ?? input.turnStartedAt);
}
