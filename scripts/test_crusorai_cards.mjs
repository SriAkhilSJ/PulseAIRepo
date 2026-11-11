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

console.log('crusorai card contract ok');
