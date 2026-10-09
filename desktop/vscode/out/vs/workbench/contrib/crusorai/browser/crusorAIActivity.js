/*---------------------------------------------------------------------------------------------
 * The tail activity row -- "breathing" and "thinking" -- ported from hermes-agent
 * `assistant-ui/thread/turn-activity.ts` and `components/chat/activity-timer.ts` @ a9c783f2,
 * with the reveal/label rules from `thread/status.tsx`, and kept DOM-free so the same numbers
 * the webview computes (`crusor-webview/src/hermes-ui/model/turn-activity.ts`,
 * `model/activity-timer.ts`, `components/status-line.tsx`) can be executed against it in a test.
 *--------------------------------------------------------------------------------------------*/
import { isSilentTool } from './crusorAIRunSummary.js';
/**
 * Seconds of silence before an unnamed wait earns a row of its own.
 *
 * Long enough that the pause between one tool call finishing and the next arriving stays
 * silent -- a row that appeared for 300ms between every call would strobe down a long run --
 * short enough that a real gap is timed almost as soon as it starts.
 */
export var TURN_QUIET_S = 2;
/**
 * Long enough that a tool whose arguments arrive in a few frames never gets to strobe a label,
 * short enough that a real wait is named almost immediately.
 */
export var DRAFTING_REVEAL_MS = 200;
/** Compaction is in flight -- it outranks every other hint. */
export var COMPACTION_LABEL = 'Summarizing thread';
/** The row's `aria-label` and the visible label's stand-in when there is nothing to name yet. */
export var UNNAMED_WAIT_LABEL = 'Crusor is working';
/**
 * What the tail message has produced so far, as a value that changes exactly when the turn
 * makes visible progress.
 *
 * Part count and text length cover streamed prose and each new call. Settled calls are counted
 * separately because a result lands by MUTATING the part that was already there: neither the
 * count nor the text changes, so a signature without it reads a finished tool call as more of
 * the same silence and dates the gap after it from whenever the call started.
 */
export function activitySignature(parts) {
    var textLength = 0;
    var settledTools = 0;
    for (var _i = 0, parts_1 = parts; _i < parts_1.length; _i++) {
        var part = parts_1[_i];
        if (typeof part.text === 'string') {
            textLength += part.text.length;
        }
        if (part.type === 'tool-call' && part.result !== undefined) {
            settledTools += 1;
        }
    }
    return "".concat(parts.length, ":").concat(textLength, ":").concat(settledTools);
}
/**
 * Whether a tool call is already narrating this wait.
 *
 * A call in flight renders its own row, with its own timer, so a second spinner under it would
 * count the same seconds twice. Silent tools don't: Crusor's `think` receipts are hoisted into
 * the reasoning disclosure, so a wait on one of those is as unnarrated as a wait on nothing.
 */
export function toolNarratesWait(parts) {
    return parts.some(function (part) { var _a; return part.type === 'tool-call' && part.result === undefined && !isSilentTool((_a = part.toolName) !== null && _a !== void 0 ? _a : ''); });
}
/**
 * The fork's copy of upstream's timer registry (`model/activity-timer.ts`), which exists because
 * a number measured *while watching* must outlive the thing doing the watching: the transcript
 * repaints wholesale on every frame, so an elapsed count kept in a row would reset constantly
 * and a finished duration would be lost the moment its row scrolled away. Keyed, module-level,
 * and never cleared between renders -- `closeMeasurement` retires an origin and remembers it.
 */
var startedAtByKey = new Map();
var durationByKey = new Map();
/** Whole seconds since this key's origin, arming the origin on first use. */
export function elapsedFor(key, now) {
    var _a;
    var origin = (_a = startedAtByKey.get(key)) !== null && _a !== void 0 ? _a : now;
    startedAtByKey.set(key, origin);
    return Math.max(0, Math.floor((now - origin) / 1000));
}
/** Stop watching `key` and keep the number. Idempotent: closing twice reports the same duration. */
export function closeMeasurement(key, now) {
    var _a;
    var origin = startedAtByKey.get(key);
    if (origin === undefined) {
        return durationByKey.get(key);
    }
    var finalElapsed = Math.max((_a = durationByKey.get(key)) !== null && _a !== void 0 ? _a : 0, Math.floor((now - origin) / 1000));
    durationByKey.set(key, finalElapsed);
    startedAtByKey.delete(key);
    return finalElapsed;
}
/** The remembered duration for `key`, or undefined if it was never watched at all. */
export function measuredDuration(key) {
    return durationByKey.get(key);
}
/** `45s`, then `1:05`. Never a moving decimal: a ticking fraction reads as a benchmark. */
export function formatElapsed(seconds) {
    if (seconds < 60) {
        return "".concat(seconds, "s");
    }
    return "".concat(Math.floor(seconds / 60), ":").concat(String(seconds % 60).padStart(2, '0'));
}
/** Whole seconds since `origin`; 0 when there is no origin yet or the clock went backwards. */
export function elapsedSeconds(now, origin) {
    if (origin === undefined) {
        return 0;
    }
    return Math.max(0, Math.floor((now - origin) / 1000));
}
/** The settled states of the fork's tool lifecycle -- `result` presence is what upstream reads. */
var SETTLED_STATES = new Set(['completed', 'passed', 'failed', 'cancelled']);
/**
 * The fork's render model, expressed as the part list upstream computes over.
 *
 * `assistantText` and `reasoning` become text parts (their lengths are the visible progress);
 * each call becomes a tool-call part whose `result` is present only once the call has settled,
 * which is the same signal the webview gets from the store.
 */
export function activityParts(model) {
    var _a;
    var parts = [];
    if (model.reasoning) {
        parts.push({ type: 'reasoning', text: model.reasoning });
    }
    if (model.assistantText) {
        parts.push({ type: 'text', text: model.assistantText });
    }
    for (var _i = 0, _b = model.tools; _i < _b.length; _i++) {
        var tool = _b[_i];
        var settled = SETTLED_STATES.has(tool.state);
        parts.push({ type: 'tool-call', toolName: tool.name, result: settled ? (_a = tool.result) !== null && _a !== void 0 ? _a : true : undefined });
    }
    return parts;
}
/** The call the wait is named after: the newest one still in flight, if any. */
export function draftingToolName(tools) {
    for (var index = tools.length - 1; index >= 0; index--) {
        var tool = tools[index];
        if (tool.state === 'running' || tool.state === 'queued' || tool.state === 'pending') {
            return tool.name;
        }
    }
    return '';
}
/**
 * What to call the wait, if it deserves a name. Compaction outranks a draft -- it is rarer,
 * slower, and explains a transcript that looks like it reset. An unrevealed hint name is the
 * empty string, and an empty label is what keeps a fast tool from flashing a row.
 */
export function statusHintLabel(compacting, hintName, revealed) {
    if (compacting) {
        return COMPACTION_LABEL;
    }
    return revealed && hintName ? hintName : '';
}
/**
 * Whether the row shows at all: the turn is busy, nobody is being asked a question, no tool
 * row is already narrating, and there is something to say -- a named wait, or a quiet spell
 * long enough to time.
 */
export function activityRowVisible(input) {
    return input.working
        && !input.awaitingInput
        && !input.toolNarrating
        && (input.hint.length > 0 || input.quietSince !== undefined);
}
export function activityRowMode(input) {
    if (!input.working || input.awaitingInput) {
        return undefined;
    }
    if (!input.parts.length) {
        return 'aui_response-loading';
    }
    return activityRowVisible(input) ? 'aui_turn-activity' : undefined;
}
/**
 * What the timer counts from. Compaction owns the whole turn, so it keeps counting from the
 * turn's start; anything else counts from the moment the turn last produced something.
 */
export function activityOrigin(input) {
    var _a;
    return input.compacting ? input.turnStartedAt : ((_a = input.quietSince) !== null && _a !== void 0 ? _a : input.turnStartedAt);
}
