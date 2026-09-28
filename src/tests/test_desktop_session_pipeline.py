"""Structural pins for the desktop session pipeline (Hermes session-handling port).

New Session (blank draft, engine-minted id) · in-place open with checkpoint
hydration · durable list refresh · remembered session per workspace ·
background-turn routing to list rows. The workbench TypeScript is pinned by
substring, the repo's established style for code no Python test can execute.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CRUSOR = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai"


def _text(*parts: str) -> str:
    return CRUSOR.joinpath(*parts).read_text(encoding="utf-8")


def test_new_session_blanks_the_surface_without_an_id():
    service = _text("browser", "crusorAIRendererService.ts")
    iface = _text("common", "crusorAIRendererService.ts")
    contribution = _text("browser", "crusorAI.contribution.ts")
    # The id is minted by the engine on the next prompt: newSession() itself
    # must only clear, and it must refuse while a turn owns the surface.
    assert "\n\tnewSession(): void {" in service
    assert "this.resetSessionState();" in service
    assert "Stop the current run before starting a new session." in service
    assert "newSession(): void;" in iface
    # The crusorai.newSession command is wired to the service, not the old
    # store-event no-op.
    assert "ICrusorAIRendererService).newSession()" in contribution
    assert "_onDidChange?.fire?.()" not in contribution


def test_blank_surface_reset_is_one_shared_method():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "private resetSessionState(): void {" in service
    # Folder switches, session switches and New Session clear the same
    # surface: two copies drifted once already (history survived navigation).
    assert service.count("this.resetSessionState();") == 3
    assert "this.pendingHydration = undefined;" in service
    assert "this.sessionId = undefined;" in service


def test_session_list_refresh_never_clobbers_the_active_id():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "private requestSessionList(): void {" in service
    assert "type: 'session_list'" in service
    # A list reply carries `sessions` and NO session_id: rows are noted, the
    # active id is adopted only when the frame actually names one.
    assert "for (const row of frame.sessions) { this.noteEngineRow(row); }" in service
    assert "if (frame.session) { this.noteEngineRow(frame.session); }" in service
    guard = service.index("if (!frame.session_id) {")
    adopt = service.index("this.sessionId = frame.session_id;")
    assert guard < adopt
    # A late ack for a session we already left must not steal the surface back.
    assert "if (foreignId) {" in service


def test_navigation_rebinds_and_hydrates_from_checkpoints():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "Stop the current run before switching sessions." in service
    # An explicit open IS the read, and the session is remembered per workspace.
    assert "this.sessionStore.markRead(targetSessionId, true);" in service
    assert "this.setRememberedSession(targetSessionId);" in service
    assert "this.pendingHydration = targetSessionId;" in service
    # Transcript hydration comes from paged checkpoints, not the journal: the
    # resume keeps its events out so the two views never double-paint.
    assert "include_events: false" in service
    assert "type: 'session_messages'" in service
    assert "type: 'session_resume', session_id: targetSessionId" in service


def test_transcript_hydration_groups_messages_into_history_turns():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "private hydrateTranscript(messages: readonly CrusorSessionMessage[]): void {" in service
    # Stale pages (a reply for a session the user already left) are dropped.
    assert "if (forId !== this.pendingHydration && forId !== this.sessionId) { return; }" in service
    # Tool results rejoin their cards on tool_call_id; hydration lands in
    # history (bounded like archived turns), never the live surface.
    assert "toolIndex.get(message.tool_call_id)" in service
    assert "turns.slice(-20)" in service
    assert "turnOutcome: 'completed' as const" in service


def test_background_turns_route_to_their_list_row():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "private foreignSessionId(frame: CrusorServerEvent): string | undefined {" in service
    assert "this.noteForeignFrame(foreignId, frame);" in service
    # Terminal foreign frames unread-dot the row and toast; mid-turn traffic
    # paints Working (or needs-input for approvals) without touching the live
    # transcript.
    assert "this.sessionStore.markRead(foreignId, false);" in service
    assert "'needsInput' : 'inProgress'" in service


def test_remembered_session_restores_on_engine_ready():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "crusorai.lastSession." in service
    assert "const remembered = this.getRememberedSession();" in service
    assert "this.pendingHydration = remembered;" in service
    # A fresh window's restore hydrates like an in-app switch (no journal).
    assert "type: 'session_resume', session_id: remembered, workspace, include_events: false" in service
    # Everyadopted live session is remembered, not just navigated ones.
    assert "this.setRememberedSession(frame.session_id);" in service


def test_deleted_active_session_lands_on_a_blank_surface():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "} else if (frame.type === 'session_deleted') {" in service
    assert "this.sessionStore.forget(deletedId);" in service
    assert "if (deletedId === this.sessionId) {" in service


def test_resume_resolves_to_the_lineage_tip():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "frame.resolved_session_id" in service
    assert "this.sessionId = frame.resolved_session_id;" in service


def test_mutation_acks_resync_the_list():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "frame.renamed || frame.pin_updated || frame.archive_updated" in service
    # Finished turns mint the durable row's title and counts: re-sync there too.
    assert service.count("this.requestSessionList();") >= 4


def test_manager_rows_open_their_session_in_place():
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "crusorSessionIdFromUri" in renderer
    assert "host.navigateToSession!(target)" in renderer
    # No more disabled rows: every non-active row is clickable.
    assert "button.disabled = !row.isActive;" not in renderer
    # The Manager "+" and the Agent header both start a blank session.
    assert renderer.count("host.newSession?.()") == 2
    assert "button('New session', 'crusorai-agent-manager-button'" in renderer


def test_workbench_list_click_opens_the_session():
    controller = _text("browser", "crusorAISessionController.ts")
    service = _text("browser", "crusorAIRendererService.ts")
    iface = _text("common", "crusorAIRendererService.ts")
    assert "accessor.get(ICrusorAIRendererService).openSession(sessionId);" in controller
    assert "CrusorAICommandId.Focus" in controller
    assert "openSession(sessionId: string): void;" in iface
    assert "openSession(sessionId: string): void {" in service


def test_engine_rows_map_to_facts_without_live_guesses():
    projection = _text("common", "crusorAISessionProjection.ts")
    store = _text("common", "crusorAISessionStore.ts")
    assert "export function crusorFactsFromEngineRow(" in projection
    assert "export function crusorEngineRowLabel(" in projection
    for field in ("pinned", "unread", "messageCount", "preview", "createdAt",
                  "lastActiveAt", "parentSessionId", "lineageRootId", "lazy"):
        assert f"readonly {field}" in projection
    # The durable unread bit drives attention after a restart; the store
    # signature tracks the visible durable fields.
    assert "input.unread" in projection
    assert "facts.unread" in store and "facts.messageCount" in store


def test_protocol_carries_include_events_and_tool_call_ids():
    protocol = _text("common", "crusorAIProtocol.ts")
    assert "readonly include_events?: boolean" in protocol
    assert protocol.count("readonly include_events?: boolean") == 2
    assert "readonly tool_calls?: readonly { readonly id?: string; readonly name: string;" in protocol
