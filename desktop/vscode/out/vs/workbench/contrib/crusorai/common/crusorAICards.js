/*---------------------------------------------------------------------------------------------
 * Typed Agent UI cards. Versioned, schema-validated presentation data only.
 * Model output is untrusted: no HTML, CSS, JavaScript or component names cross
 * this boundary, and unknown card types fail safe into a visible indicator.
 *--------------------------------------------------------------------------------------------*/
export const CRUSOR_CARD_SCHEMA_VERSION = 1;
export const CRUSOR_CARD_TYPES = [
    'activity', 'plan', 'file_change', 'approval', 'tool',
    'test_results', 'verification', 'delivery', 'cost',
];
/**
 * Card types that are journaled, replayed and accounted for but never paint a
 * dedicated card in the coding conversation.
 *
 * Restored Agentic card timeline (2026-11-12): Activity, Plan, File Change,
 * Tool, Approval and Test Results cards render in the conversation again,
 * pinned chronologically into the turn. Verification, Delivery and Cost stay
 * internal per the standing policy:
 *
 *   verification  -> TurnReceipt / verification_updated frame (never a card)
 *   delivery      -> TurnReceipt / turn_done message
 *   cost          -> telemetry frame + FinOps ledger
 *
 * Backend event generation, persistence, journaling, replay and FinOps records
 * are untouched: only the presentation policy changes.
 */
export const CRUSOR_INTERNAL_CARD_TYPES = [
    'verification', 'delivery', 'cost',
];
/** The one user-facing card policy (live and restored history use it). */
export function isUserFacingCard(card) {
    return !CRUSOR_INTERNAL_CARD_TYPES.includes(card.cardType);
}
export function userFacingCards(cards) {
    return cards.filter(isUserFacingCard);
}
const MAX_TEXT = 8_000;
const MAX_DIFF = 40_000;
const MAX_ITEMS = 200;
const MAX_DEPTH = 6;
const CONTROL_CHARS = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g;
function isRecord(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}
function text(value, limit = MAX_TEXT) {
    if (value === undefined || value === null) {
        return '';
    }
    const raw = typeof value === 'string' ? value : String(value);
    const clean = raw.replace(CONTROL_CHARS, '');
    return clean.length <= limit ? clean : `${clean.slice(0, limit)}…`;
}
function safeValue(value, depth = 0) {
    if (depth > MAX_DEPTH) {
        return undefined;
    }
    if (value === null || typeof value === 'boolean') {
        return value;
    }
    if (typeof value === 'number') {
        return Number.isFinite(value) ? value : undefined;
    }
    if (typeof value === 'string') {
        return text(value);
    }
    if (Array.isArray(value)) {
        return value.slice(0, MAX_ITEMS).map(item => safeValue(item, depth + 1));
    }
    if (isRecord(value)) {
        const out = {};
        for (const [key, item] of Object.entries(value).slice(0, MAX_ITEMS)) {
            if (key === '__proto__' || key === 'constructor' || key === 'prototype') {
                continue;
            }
            const safe = safeValue(item, depth + 1);
            if (safe !== undefined) {
                out[key.slice(0, 120)] = safe;
            }
        }
        return out;
    }
    return undefined;
}
function safeData(raw, cardType) {
    if (!isRecord(raw)) {
        return {};
    }
    const data = safeValue(raw);
    if (cardType === 'approval') {
        data.diff = text(data.diff, MAX_DIFF);
        data.digest = text(data.digest, 200);
    }
    return data;
}
/** Validate an untrusted wire card. Unknown card types stay visible but inert. */
export function normalizeCrusorCard(raw) {
    if (!isRecord(raw)) {
        return undefined;
    }
    const version = raw.schema_version;
    if (typeof version !== 'number' || !Number.isInteger(version) || version < 1 || version > CRUSOR_CARD_SCHEMA_VERSION) {
        return undefined;
    }
    const declaredType = text(raw.card_type ?? raw.type, 80);
    const cardId = text(raw.card_id, 200);
    if (!cardId) {
        return undefined;
    }
    const known = CRUSOR_CARD_TYPES.includes(declaredType);
    if (!known) {
        return {
            schemaVersion: CRUSOR_CARD_SCHEMA_VERSION,
            cardType: 'unsupported',
            declaredType: declaredType || 'unknown',
            supported: false,
            cardId,
            sessionId: text(raw.session_id, 200),
            turnId: text(raw.turn_id, 200),
            data: {},
        };
    }
    return {
        schemaVersion: CRUSOR_CARD_SCHEMA_VERSION,
        cardType: declaredType,
        declaredType,
        supported: true,
        cardId,
        sessionId: text(raw.session_id, 200),
        turnId: text(raw.turn_id, 200),
        data: safeData(raw.data, declaredType),
    };
}
/** Accept only a v1 `agent_card` frame envelope, then validate its card. */
export function cardFromFrame(frame) {
    if (!isRecord(frame) || frame.type !== 'agent_card') {
        return undefined;
    }
    return normalizeCrusorCard(frame.card);
}
/**
 * Card state grouped by conversation turn.
 *
 * One session holds many independent turns; the SAME card id in two turns is
 * two distinct cards, never an overwrite. Updates replace in place (stable
 * order), duplicate replay is idempotent, and clearing a session is one call.
 * The renderer must never key cards by card id alone.
 */
export class CrusorCardStore {
    constructor() {
        this.turns = new Map();
    }
    /** Insert or replace one card. `fallbackTurnId` covers legacy cards that
     *  were persisted without a turn id while the current turn is known.
     *  Returns true when this (turn, card) identity is new. */
    update(card, fallbackTurnId = '') {
        const turnId = card.turnId || fallbackTurnId;
        let entry = this.turns.get(turnId);
        if (!entry) {
            entry = { cards: new Map(), order: [] };
            this.turns.set(turnId, entry);
        }
        const added = !entry.cards.has(card.cardId);
        if (added) {
            entry.order.push(card.cardId);
        }
        entry.cards.set(card.cardId, card);
        return added;
    }
    /** This turn's cards, in stable first-arrival order. */
    cardsFor(turnId) {
        const entry = this.turns.get(turnId);
        if (!entry) {
            return [];
        }
        return entry.order
            .map(id => entry.cards.get(id))
            .filter((card) => !!card);
    }
    turnIds() {
        return [...this.turns.keys()];
    }
    /** Every card, grouped order preserved (diagnostics/tests only). */
    all() {
        const out = [];
        for (const entry of this.turns.values()) {
            for (const id of entry.order) {
                const card = entry.cards.get(id);
                if (card) {
                    out.push(card);
                }
            }
        }
        return out;
    }
    size() {
        return this.all().length;
    }
    clearTurn(turnId) {
        this.turns.delete(turnId);
    }
    clear() {
        this.turns.clear();
    }
    snapshot() {
        return [...this.turns.entries()]
            .map(([turnId, entry]) => ({
            turnId,
            cards: entry.order
                .map(id => entry.cards.get(id))
                .filter((card) => !!card),
        }))
            .filter(entry => entry.cards.length > 0);
    }
    restore(turns) {
        this.turns.clear();
        for (const turn of turns) {
            for (const card of turn.cards) {
                this.update(card, turn.turnId);
            }
        }
    }
}
/** Human-safe one-line summary used by compact/narrow layouts. */
export function cardHeadline(card) {
    const d = card.data;
    switch (card.cardType) {
        case 'activity': return text(d.label ?? d.stage, 160) || 'Working';
        case 'plan': return text(d.summary, 160) || 'Plan';
        case 'file_change': return `${text(d.operation, 40) || 'change'} ${text(d.path, 200)}`.trim();
        case 'approval': return `${text(d.operation, 40) || 'change'} ${text(d.path, 200)}`.trim() || 'Approval requested';
        case 'tool': return text(d.description, 160) || text(d.name, 120) || 'Tool';
        case 'test_results': return `${text(d.passed, 12)} passed / ${text(d.failed, 12)} failed`;
        case 'verification': return text(d.status, 60) || 'Verification';
        case 'delivery': return text(d.verdict, 160) || text(d.status, 60) || 'Delivery';
        case 'cost': return text(d.cost_inr, 40) ? `₹${text(d.cost_inr, 40)}` : 'Cost unknown';
        default: return `Unsupported card: ${card.declaredType}`;
    }
}
