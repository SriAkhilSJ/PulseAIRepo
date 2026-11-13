import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';

const modulePath = resolve(
	'desktop/vscode/src/vs/workbench/contrib/crusorai/common/crusorAICards.ts',
);
const cards = await import(pathToFileURL(modulePath).href);

const plan = cards.normalizeCrusorCard({
	schema_version: 1,
	card_type: 'plan',
	card_id: 'turn-1:plan',
	turn_id: 'turn-1',
	session_id: 's-1',
	data: { summary: 'Ship it 🚀', steps: [{ text: 'one', status: 'completed' }] },
});
assert.equal(plan.supported, true);
assert.equal(plan.cardType, 'plan');
assert.equal(plan.data.summary, 'Ship it 🚀');

const approval = cards.normalizeCrusorCard({
	schema_version: 1,
	card_type: 'approval',
	card_id: 'a-1',
	data: { path: 'hello.md', diff: '--- a\n+++ b\n+ok', digest: 'sha256:x', status: 'pending' },
});
assert.equal(approval.cardType, 'approval');
assert.match(approval.data.diff, /\+ok/);

const unknown = cards.normalizeCrusorCard({
	schema_version: 1, card_type: 'evil_component', card_id: 'x-1', data: { html: '<script>alert(1)</script>' },
});
assert.equal(unknown.supported, false);
assert.equal(unknown.cardType, 'unsupported');
assert.equal(unknown.data.html, undefined);

const polluted = cards.normalizeCrusorCard({
	schema_version: 1, card_type: 'tool', card_id: 't-1',
	data: JSON.parse('{"name":"x","__proto__":{"polluted":true},"constructor":{"bad":true}}'),
});
assert.equal(polluted.data.polluted, undefined);
assert.equal(({}).polluted, undefined);

assert.equal(cards.normalizeCrusorCard({ schema_version: 99, card_type: 'plan', card_id: 'z' }), undefined);
assert.equal(cards.normalizeCrusorCard({ schema_version: 1, card_type: 'plan', card_id: '' }), undefined);
assert.equal(cards.normalizeCrusorCard('<img src=x onerror=alert(1)>'), undefined);

const cost = cards.normalizeCrusorCard({
	schema_version: 1, card_type: 'cost', card_id: 'c-1',
	data: { model: 'm', input_tokens: 10, output_tokens: 2, cost_inr: null, certainty: 'unknown' },
});
assert.equal(cards.cardHeadline(cost), 'Cost unknown');

const fromFrame = cards.cardFromFrame({ type: 'agent_card', card: { schema_version: 1, card_type: 'activity', card_id: 'act', data: { label: 'Planning' } } });
assert.equal(fromFrame.cardType, 'activity');
assert.equal(cards.cardFromFrame({ type: 'token', card: {} }), undefined);

// --- per-turn card ownership ------------------------------------------------
const makeCard = (turnId, cardId, cardType = 'activity', label = cardId) => {
	const card = cards.normalizeCrusorCard({
		schema_version: 1,
		card_type: cardType,
		card_id: cardId,
		turn_id: turnId,
		session_id: 's-1',
		data: { label, status: 'running' },
	});
	assert.ok(card, `fixture ${cardType}/${cardId} must normalize`);
	return card;
};

const store = new cards.CrusorCardStore();
store.update(makeCard('turn-1', 'a'));
store.update(makeCard('turn-1', 'p', 'plan'));
store.update(makeCard('turn-2', 'a'));            // SAME card id, other turn
store.update(makeCard('turn-2', 'p', 'plan'));
assert.deepEqual(store.cardsFor('turn-1').map(card => card.cardId), ['a', 'p']);
assert.deepEqual(store.cardsFor('turn-2').map(card => card.cardId), ['a', 'p']);
assert.equal(store.size(), 4);
assert.deepEqual(store.turnIds(), ['turn-1', 'turn-2']);

// update in place: same identity, stable position, latest payload
store.update(makeCard('turn-1', 'p', 'plan', 'Planning changes'));
assert.deepEqual(store.cardsFor('turn-1').map(card => card.cardId), ['a', 'p']);
assert.equal(store.cardsFor('turn-1')[1].data.label, 'Planning changes');
assert.equal(store.cardsFor('turn-2')[1].data.label, 'p');

// duplicate replay is idempotent and the snapshot round-trips
const snapshot = store.snapshot();
store.restore(snapshot);
store.restore(snapshot);
assert.equal(store.size(), 4);
assert.deepEqual(store.snapshot(), snapshot);

// a card persisted without a turn id belongs only to the supplied turn
const legacyCard = cards.normalizeCrusorCard({ schema_version: 1, card_type: 'activity', card_id: 'legacy', data: {} });
store.update(legacyCard, 'turn-3');
assert.deepEqual(store.cardsFor('turn-3').map(card => card.cardId), ['legacy']);
assert.equal(store.cardsFor('turn-1').length, 2);

// session switch: one turn or the whole store can be dropped
store.clearTurn('turn-2');
assert.equal(store.turnIds().includes('turn-2'), false);
assert.equal(store.cardsFor('turn-1').length, 2);
store.clear();
assert.equal(store.size(), 0);
assert.deepEqual(store.turnIds(), []);

// --- user-facing policy (restored conversational model) ---------------------
// The seven phase-era surfaces are journaled but never paint a card. Only the
// two overlapping conversational affordances stay policy-visible; the renderer
// still suppresses the typed tool card when its inline row exists.
const policy = new cards.CrusorCardStore();
policy.update(makeCard('t', 'act', 'activity'));
policy.update(makeCard('t', 'plan', 'plan'));
policy.update(makeCard('t', 'tool', 'tool'));
policy.update(makeCard('t', 'file', 'file_change'));
policy.update(makeCard('t', 'appr', 'approval'));
policy.update(makeCard('t', 'tests', 'test_results'));
policy.update(makeCard('t', 'ver', 'verification'));
policy.update(makeCard('t', 'del', 'delivery'));
policy.update(makeCard('t', 'cost', 'cost'));
assert.deepEqual(policy.cardsFor('t').map(card => card.cardType), [
	'activity', 'plan', 'tool', 'file_change', 'approval', 'test_results',
	'verification', 'delivery', 'cost',
], 'the store keeps every card for journal/replay');
assert.deepEqual(cards.userFacingCards(policy.cardsFor('t')).map(card => card.cardType), [
	'activity', 'plan', 'tool', 'file_change', 'approval', 'test_results',
], 'Agentic cards are user-facing; verification/delivery/cost stay internal');
for (const type of ['verification', 'delivery', 'cost']) {
	const card = policy.cardsFor('t').find(entry => entry.cardType === type);
	assert.equal(cards.isUserFacingCard(card), false, `${type} must stay internal`);
}
for (const type of ['activity', 'plan', 'tool', 'file_change', 'approval', 'test_results']) {
	const card = policy.cardsFor('t').find(entry => entry.cardType === type);
	assert.equal(cards.isUserFacingCard(card), true, `${type} must remain visible`);
}
assert.equal(cards.isUserFacingCard(cards.normalizeCrusorCard({
	schema_version: 1, card_type: 'evil', card_id: 'unknown', data: {},
})), true); // unknown types stay visible as a safe indicator

console.log('crusorai card contract ok');
