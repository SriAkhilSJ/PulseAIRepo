/**
 * B-LIVE-002: terminal outcome semantics, executed rather than pattern-matched.
 *
 * The renderer's failure state used to be derived from "not cancelled"; a failed
 * engineering turn with no receipt therefore painted as a success. The decision
 * now lives in a pure module (common/crusorAITurnOutcome.ts) and this test runs
 * it directly, including the restored/legacy cases where success must never be
 * inferred from missing evidence.
 */
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const modulePath = resolve(
	'desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAITurnOutcome.ts',
);
const outcome = await import(pathToFileURL(modulePath).href);

const { terminalTurnOutcome, asTurnOutcome, restoredTurnOutcome, turnOutcomeReceipt } = outcome;

// --- live terminal frames --------------------------------------------------
assert.equal(
	terminalTurnOutcome({ completed: true, cancelled: false }),
	'completed',
	'a successful turn is completed',
);
assert.equal(
	terminalTurnOutcome({ completed: false, cancelled: false }),
	'failed',
	'a failed turn without a receipt is failed',
);
assert.equal(
	terminalTurnOutcome({ completed: false, cancelled: true }),
	'cancelled',
	'a stopped turn is cancelled',
);
assert.equal(
	terminalTurnOutcome({ completed: true, cancelled: true }),
	'cancelled',
	'a user stop wins over an inferred completion',
);

// --- authoritative receipt status -----------------------------------------
assert.equal(terminalTurnOutcome({ completed: false, terminalStatus: 'COMPLETED' }), 'completed');
assert.equal(terminalTurnOutcome({ completed: true, terminalStatus: 'FAILED' }), 'failed');
assert.equal(terminalTurnOutcome({ completed: false, terminalStatus: 'INTERRUPTED' }), 'incomplete');
assert.equal(terminalTurnOutcome({ completed: false, terminalStatus: 'WATCHDOG' }), 'incomplete');
assert.equal(terminalTurnOutcome({ completed: false, terminalStatus: 'DENIED' }), 'denied');
assert.equal(terminalTurnOutcome({ cancelled: true, terminalStatus: 'COMPLETED' }), 'cancelled');

// --- missing evidence never implies success -------------------------------
assert.equal(terminalTurnOutcome({}), 'unknown', 'no flags and no receipt is unknown');
assert.equal(terminalTurnOutcome({ terminalStatus: '' }), 'unknown');
assert.equal(terminalTurnOutcome({ terminalStatus: 'PARTIAL' }), 'unknown', 'an unrecognised label is not success');

// --- durable evidence status (no canonical receipt in the frame) -----------
assert.equal(
	terminalTurnOutcome({ completed: false, evidenceStatus: 'watchdog' }),
	'incomplete',
	'a watchdog stall is incomplete, not a user cancellation',
);
assert.equal(terminalTurnOutcome({ completed: false, evidenceStatus: 'interrupted' }), 'incomplete');
assert.equal(terminalTurnOutcome({ completed: false, evidenceStatus: 'failed' }), 'failed');
assert.equal(
	terminalTurnOutcome({ completed: true, evidenceStatus: 'unavailable' }),
	'completed',
	'an unavailable manifest still lets the completed flag decide',
);

// --- restoration -----------------------------------------------------------
assert.equal(asTurnOutcome('FAILED'), 'failed', 'wire values are case-insensitive');
assert.equal(asTurnOutcome('  cancelled '), 'cancelled');
assert.equal(asTurnOutcome(''), undefined);
assert.equal(asTurnOutcome(undefined), undefined);
assert.equal(asTurnOutcome('something-else'), undefined);

assert.equal(restoredTurnOutcome(undefined, 'turn-1'), 'unknown', 'legacy session without outcomes is unknown');
assert.equal(restoredTurnOutcome({}, 'turn-1'), 'unknown', 'a missing entry is unknown');
assert.equal(restoredTurnOutcome({ 'turn-2': 'completed' }, 'turn-1'), 'unknown', 'another turn does not apply');
assert.equal(restoredTurnOutcome({ 'turn-1': 'failed' }, 'turn-1'), 'failed');
assert.equal(restoredTurnOutcome({ 'turn-1': 'interrupted' }, 'turn-1'), 'unknown');
assert.equal(restoredTurnOutcome({ 'turn-1': 'incomplete' }, 'turn-1'), 'incomplete');
assert.equal(restoredTurnOutcome({ 'turn-1': 'completed' }, undefined), 'unknown', 'no turn id is unknown');

// --- user-visible receipts -------------------------------------------------
assert.equal(turnOutcomeReceipt('completed'), undefined, 'success never paints a receipt row');
assert.equal(turnOutcomeReceipt('running'), undefined);
assert.equal(turnOutcomeReceipt('idle'), undefined);
assert.equal(turnOutcomeReceipt('failed').label, 'Run failed');
assert.equal(turnOutcomeReceipt('cancelled').label, 'Run cancelled');
assert.equal(turnOutcomeReceipt('denied').label, 'Run denied');
assert.equal(turnOutcomeReceipt('incomplete').label, 'Run incomplete');
assert.equal(turnOutcomeReceipt('unknown').label, 'Outcome not recorded');

console.log('crusorai turn-outcome contract ok');
