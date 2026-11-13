"""Renderer-side per-turn card ownership (source contracts).

The DOM behaviour is proven by the real Electron acceptance; these assertions
pin the state model so a refactor cannot silently reintroduce a single global
card map or drop a turn's cards during hydration.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CARDS = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "common" / "crusorAICards.ts"
SERVICE = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "crusorAIRendererService.ts"
RENDERER = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "crusorAIRenderer.ts"


def test_card_store_is_keyed_by_turn_not_by_card_id_alone() -> None:
    text = CARDS.read_text(encoding="utf-8")

    assert "export class CrusorCardStore" in text
    assert "private readonly turns = new Map<string" in text
    assert "const turnId = card.turnId || fallbackTurnId;" in text
    assert "cardsFor(turnId: string)" in text
    assert "restore(turns: readonly CrusorCardTurnSnapshot[])" in text


def test_service_holds_cards_per_turn_and_snapshots_them() -> None:
    text = SERVICE.read_text(encoding="utf-8")

    assert "private readonly cardStore = new CrusorCardStore();" in text
    assert "private currentTurnId: string | undefined;" in text
    assert "cardTurns: this.cardStore.snapshot()," in text
    assert "this.cardStore.restore(snapshot.cardTurns);" in text
    assert "cards: this.cardStore.cardsFor(this.currentTurnId ?? '')," in text
    # The old global map/order is what let turns share one bottom stack.
    assert "private readonly cards = new Map<string, CrusorCardView>()" not in text
    assert "cardOrder" not in text


def test_session_switch_clears_turn_card_state() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    reset = text[text.index("private resetSessionState()"):text.index("private selectWorkspace(")]

    assert "this.cardStore.clear();" in reset
    assert "this.currentTurnId = undefined;" in reset


def test_hydration_assigns_only_each_turns_cards() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    hydration = text[text.index("private hydrateTranscript("):text.index("private render(): void")]

    assert "turnId?: string" in hydration
    assert "message.turn_id" in hydration
    assert "this.cardStore.cardsFor(turn.turnId)" in hydration
    assert "this.cardStore.cardsFor(singleBucket)" in hydration
    # Legacy ambiguity must never fall back to the newest turn.
    assert "windowTurns.length === 1 && this.cardStore.turnIds().length === 1" in hydration
    assert "warnUnclaimedCards" in hydration


def test_session_messages_rebuilds_when_settled_and_merges_while_running() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    start = text.index("frame.type === 'session_messages'")
    segment = text[start:start + 1600]

    assert "if (!this.running) { this.cardStore.clear(); }" in segment
    assert "this.cardStore.update(card);" in segment
    assert "this.hydrateTranscript(frame.messages, frame.turn_outcomes);" in segment
    assert "this.cards.clear()" not in segment


def test_history_renderer_passes_each_turns_cards_and_turn_id() -> None:
    text = RENDERER.read_text(encoding="utf-8")

    assert "cards: turn.cards," in text
    assert "turnId: turn.turnId," in text
    assert "turnId: model.currentTurnId," in text
    assert "response.dataset.turnId = spec.turnId;" in text
    assert "readonly turnId?: string;" in text
    assert "readonly cards?: readonly CrusorCardView[];" in text


def test_live_card_updates_route_to_the_owning_turn() -> None:
    text = SERVICE.read_text(encoding="utf-8")
    start = text.index("frame.type === 'agent_card'")
    segment = text[start:start + 1600]

    assert "const turnId = card.turnId || this.currentTurnId || '';" in segment
    assert "this.cardStore.update(card, turnId);" in segment
    assert "this.syncHistoryCards(turnId);" in segment


def test_user_facing_policy_hides_internal_cards() -> None:
    text = CARDS.read_text(encoding="utf-8")

    # Agentic cards render in the timeline; the three accounting/verification
    # surfaces stay internal (they still journal and replay).
    assert "CRUSOR_INTERNAL_CARD_TYPES = [" in text
    assert "'verification', 'delivery', 'cost'," in text
    assert "export function isUserFacingCard" in text
    assert "export function userFacingCards" in text


def test_card_stack_applies_the_user_facing_policy() -> None:
    text = RENDERER.read_text(encoding="utf-8")

    assert "const visible = userFacingCards(cards);" in text
    assert "if (!visible.length) { return undefined; }" in text


def test_timeline_renders_card_parts_in_place() -> None:
    renderer = RENDERER.read_text(encoding="utf-8")
    service = SERVICE.read_text(encoding="utf-8")

    assert "part.kind === 'card'" in renderer
    assert "flushCards();" in renderer
    assert "const pinned = new Set(parts.filter(p => p.kind === 'card')" in renderer
    assert "private pushCardPart(" in service
    assert "this.pushCardPart(card.cardId);" in service
    assert "private withCardPins(" in service
    assert "const early = visible.filter(card => card.cardType === 'plan');" in service
    assert "out.splice(lastText, 0, ...latePins);" in service


def test_internal_and_duplicate_tool_cards_are_not_pinned() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    start = service.index("frame.type === 'agent_card'")
    segment = service[start:start + 1200]

    assert "isUserFacingCard(card) && card.cardType !== 'tool'" in segment
    assert "card.cardType !== 'tool' || !toolIds.has(" in service


def test_engineering_progress_is_backed_by_agentic_cards() -> None:
    """Engineering progress reaches the UI through the Agentic activity card."""
    service = SERVICE.read_text(encoding="utf-8")
    renderer = RENDERER.read_text(encoding="utf-8")

    # Activity cards are user-facing again and pin chronologically.
    cards = CARDS.read_text(encoding="utf-8")
    assert "'activity', 'plan', 'file_change', 'approval', 'tool'," in cards
    assert "isUserFacingCard(card) && card.cardType !== 'tool'" in service
    assert "const hint = model.cancelRequested" in renderer
    assert "engineeringActivity" not in service
    assert "engineeringActivity" not in renderer
