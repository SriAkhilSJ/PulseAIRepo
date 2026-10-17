"""Structural pins for the shared native Crusor Agent / Manager renderer."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORK = ROOT / "desktop" / "vscode"
CRUSOR = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai"
UI = ROOT / "ui" / "src"   # not tracked in this repo; see the skip in the catalog pin


def _text(*parts: str) -> str:
    return CRUSOR.joinpath(*parts).read_text(encoding="utf-8")


def _catalog_names(text: str) -> set[str]:
    return set(re.findall(r"^\s*([a-z_]+): tool\(", text, re.MULTILINE))


def test_agent_and_manager_mount_one_shared_renderer_service():
    view = _text("browser", "crusorAIViewPane.ts")
    manager = _text("browser", "crusorAIManagerEditor.ts")
    registration = _text("browser", "crusorAI.contribution.ts")
    assert "crusorAIRendererService.mount(root, 'agent')" in view
    assert "crusorAIRendererService.mount(this.root, 'manager')" in manager
    assert "registerSingleton(ICrusorAIRendererService, CrusorAIRendererService" in registration
    assert "boot-status" not in view
    assert "boot-main" not in manager


def test_renderer_boundary_is_browser_safe_and_text_only():
    renderer = _text("browser", "crusorAIRenderer.ts")
    service = _text("browser", "crusorAIRendererService.ts")
    for source in (renderer, service):
        # Ban node/electron IMPORTS, not any substring ("node:" also matches
        # TypeScript parameter annotations like `datasetSet(node: HTMLElement)`).
        assert not re.search(r"""from\s+['"]node:""", source)
        assert "electron-browser/" not in source
        assert ".innerHTML" not in source
    assert "ICrusorAIEngineService" in service
    assert "ICrusorAIWorkbenchService" in service
    assert "onDidReceiveFrame" in service
    assert "CrusorClientMethod" in service
    assert "openNativeDiff" in service
    assert "openInlineDiff" in service
    assert "old_text" in service and "new_text" in service
    assert "session_resume" in service
    assert "events_replay" in service
    assert "rememberEvent" in service
    assert "cancelRequested" in service
    assert "frame.cancel_requested" in service
    assert "Stopping." in renderer
    assert "Run cancelled" in renderer
    # Terminal mapping uses the frame's real cancel flag: an ended-incomplete
    # run (completed:false, cancelled:false) must NOT paint "Run cancelled" —
    # the task verdict already landed in-band via finalize's trailing receipt.
    assert "frame.cancelled ? 'cancelled' : 'completed'" in service
    assert "scheduleRestart" in service
    assert "restartAttempts >= 3" in service
    assert "requestAnimationFrame" in service
    assert "preventScroll: true" in renderer
    assert "wasNearBottom" in renderer
    assert "Review change" in renderer


def test_web_fallback_and_desktop_override_share_the_engine_contract():
    common = _text("browser", "crusorAI.contribution.ts")
    fallback = _text("browser", "crusorAIUnavailableEngineService.ts")
    desktop = _text("electron-browser", "crusorAI.desktop.contribution.ts")
    assert "registerSingleton(ICrusorAIEngineService, CrusorAIUnavailableEngineService" in common
    assert "registerSingleton(ICrusorAIEngineService, CrusorAIEngineService" in desktop
    assert "child_process" not in fallback
    assert "CrusorAIEngineState.Degraded" in fallback


def test_native_and_lab_catalogs_cover_the_same_36_tools():
    if not UI.is_dir():
        pytest.skip(
            f"{UI.relative_to(ROOT)} is not present in this checkout: the lab catalog this "
            "compares against lives in a tree the repo does not track. Skip is honest; a "
            "silent pass would mean the pin compared nothing."
        )
    native = _catalog_names(_text("common", "crusorAIToolCatalog.ts"))
    lab = _catalog_names((UI / "runtime" / "toolCatalog.ts").read_text(encoding="utf-8"))
    assert len(native) == 37
    assert native == lab


def test_renderer_gates_sessions_on_an_open_project_folder():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "Open a folder to start a Crusor session." in service
    assert "if (!workspace) {" in service
    assert "session_create', workspace" in service
    assert "start(workspace).then" in service
    assert "Open a workspace or configure crusorai.engineRoot" not in service


def test_terminal_disclosure_has_bounded_output_and_completion_evidence():
    renderer = _text("browser", "crusorAIRenderer.ts")
    for receipt in (
        "function boundedText", "earlier characters omitted", "dataset.slot = 'bash-command'",
        "terminal-output", "exitCode", "duration", "copyButton(command, host)", "Reveal location",
    ):
        assert receipt in renderer


def test_agent_layout_keeps_progressive_disclosure_and_stable_docks_native():
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    for behavior in (
        "function planStrip", "function createActivityState", "function emptyState", "function thinkingBlock",
        "crusorai-section-heading", "host.submitPrompt(value)", "planOpen",
    ):
        assert behavior in renderer
    assert "openManager(): void" in renderer
    # Manager's popup-vs-tab routing is a deferred owner decision, so that assertion lives
    # in its own strict-xfail test at the bottom of this file: the Agent-UI lane must not
    # be blocked by a choice the owner has not made, and the choice cannot be made quietly.
    # Activity runs, not a flat list: both transcript branches fold through the shared rule.
    assert "function toolSection" in renderer
    assert "agentColumn(" in renderer
    # Hermes message-parts order (owner report #4, 2026-09-04): tool groups
    # fold INSIDE the assistant turn at their arrival position — never a flat
    # lane-level block after the text. One painter (assistantTurn), both
    # transcript branches, every consecutive tool run through the shared rule.
    assert renderer.count("lane.append(toolSection(") == 0, "tool groups paint inside the turn timeline, not as a lane-level block"
    assert "function assistantTurn(" in renderer
    assert renderer.count("response.append(toolSection(run, host, openTools, closedTools, live, false, spec.clarify, spec.subAgents))") == 1, "consecutive tool runs fold through the shared grouping rule"
    assert "textPart(part.text, spec.current && index === lastTextIndex ? 'session-turn-content' : undefined)" in renderer, "the streaming slot rides the LAST text segment only (inside the OpenCode text-part)"
    assert "dataset.component = 'tool-run'" in renderer and "dataset.runKey = key" in renderer
    assert "runLive = live && runTools.some(tool => tool.state === 'running'" in renderer, \
        "a settled turn must not narrate in the present tense"
    for style in (
        ".crusorai-empty-hero", ".crusorai-scaffold-status", ".crusorai-plan-strip", ".crusorai-disclosure-row",
        "prefers-reduced-motion", "@media (max-width: 420px)",
        "container-name: crusorai-manager-editor", "@container crusorai-manager-editor (max-width: 610px)",
        "var(--vscode-focusBorder)", "var(--vscode-sideBar-background)",
    ):
        assert style in css
    assert "kilocode" not in renderer.lower()
    assert "kilocode" not in css.lower()


def test_execution_mode_picker_is_functional_and_theme_driven():
	renderer = _text("browser", "crusorAIRenderer.ts")
	service = _text("browser", "crusorAIRendererService.ts")
	protocol = _text("common", "crusorAIProtocol.ts")
	generated = _text("common", "crusorAIProtocol.generated.ts")
	css = _text("browser", "media", "crusorAI.css")
	for mode in ("agent", "plan", "debug", "ask"):
		assert f"id: '{mode}'" in renderer
		assert f"'{mode}'" in generated
	assert "setMode(mode: CrusorExecutionMode)" in renderer
	assert "readonly mode?: CrusorExecutionMode" in protocol
	assert "mode: this.mode" in service
	assert "this.send({ type: 'prompt'" in service
	assert ".crusorai-mode-menu" in css
	for token in ("--vscode-menu-background", "--vscode-menu-foreground", "--vscode-focusBorder"):
		assert token in css
	assert "#071118" not in css
	assert "#061115" not in css


def test_hermes_task_and_ask_pipeline_is_wired_end_to_end():
	"""The hermes task tool (todo_list) and ask tool (clarify) ride their own
	frames into the panel: the clarify card answers per qid through
	clarify_reply; the todo panel reconciles on {todos, revision} and lives
	between the transcript and the composer (the composer status stack)."""
	renderer = _text("browser", "crusorAIRenderer.ts")
	service = _text("browser", "crusorAIRendererService.ts")
	protocol = _text("common", "crusorAIProtocol.ts")
	css = _text("browser", "media", "crusorAI.css")
	for frame in ("clarify_request", "todo_updated", "clarify_reply"):
		assert frame in protocol, f"{frame} must be typed in the payload contract"
	assert "replyToClarify" in renderer and "replyToClarify" in service
	assert "'clarify_request'" in service and "'todo_updated'" in service
	# The clarify card is interactive (choices + Other row + Skip/Continue), the
	# todo panel speaks checkbox glyphs, and both are hermes-shaped.
	for piece in ("crusorai-clarify-choice", "Other (type your answer)", "crusorai-key-badge"):
		assert piece in renderer, piece
	assert "crusorai-clarify-form" in css and ".crusorai-key-badge" in css
	assert "todoStack(" in renderer and ".crusorai-todo-row" in css
	assert "crusorai-todo-ring" in renderer, "pending items speak dashed ring, not spinner-and-dot"
	# The approval dock is OpenCode's permission dock (founder 2026-10-15,
	# captured session-permission-dock): header "Permission required", the
	# resource patterns as code rows, footer Deny | Allow always | Allow once,
	# with Always behind the confirm dialog.
	for piece in ("crusorai-permission-footer", "crusorai-permission-once", "Permission required", "Allow once", "crusorai-dialog-overlay"):
		assert piece in renderer, piece
	assert "crusorai-permission-patterns" in renderer and "crusorai-permission-footer" in css
	# Field 2026-10-17: the dock's hint is one plain restated sentence
	# (OpenCode's per-tool permission description) — the guard's chat
	# markdown ("**Safety Check:** … Reply with: 'yes'…") never paints
	# raw, and no surface shows a JSON dump of the approval payload.
	assert "function approvalHintText" in renderer
	assert "element('div', 'crusorai-permission-hint', approvalHintText(approval))" in renderer, (
		"the hint line is the restated sentence, never the raw warning")
	assert "This file already exists. Running this will overwrite it." in renderer
	assert "git-ignored, so nothing can restore it" in renderer
	assert "${name} ${JSON.stringify(diff)}" not in renderer, "approval text is never a JSON dump"
	# The hint's plain-language contract rides with the engine: the
	# "always" verdict grants (session, tool, resource) and the veto
	# classes re-ask forever (executed in test_permission_grants).
	assert "session_grant_vetoed" in (ROOT / "src" / "context" / "safety_guard.py").read_text(encoding="utf-8")
	# A pending call's missing result is not "{}" — nothing arrived,
	# so nothing paints (field 2026-10-17: List files showing {}).
	assert "No output yet is NOT" in renderer
	assert "JSON.stringify(value ?? {}, undefined, 2)" not in renderer


def test_child_clarify_answerable_and_lane_holds_still():
	"""Field 2026-10-15: a child blocked on its own question painted the
	read-only waiting card — history turns never received the pending
	clarify, and a child paints entirely from checkpoint hydration — and
	the watched-child lane rebuilt on every 3s snapshot poll, which read
	as "can't scroll at all in sub agent". The pins: history turns thread
	the viewed session's OWN pending ask to the asking tool (a
	descendant's ask docks instead, never forms in history); the card
	forms only for its own tool id; a turn paused on a question is not
	"working" (no spinner row, no 1s repaint ticker); byte-identical
	hydrations keep history identity; a no-change paint patches tool
	outputs in place and returns."""
	renderer = _text("browser", "crusorAIRenderer.ts")
	service = _text("browser", "crusorAIRendererService.ts")
	assert "clarify: historyTurnClarify(model, turn)" in renderer
	assert "pending.sessionId !== model.sessionId" in renderer
	assert "pending.toolId && tool.id !== pending.toolId" in renderer
	assert "model.approval !== undefined || model.clarify !== undefined" in renderer
	assert "sameHistoryTurns(nextHistory, this.history)" in service
	assert "(streaming?.text ?? '') === lastPaint.text" in renderer


def test_clarify_tool_id_is_never_the_request_id():
	"""Field 2026-10-16: the bridge stamped the clarify frame's tool_id
	from the queue item's "id" — the REQUEST id — so the child's pending
	ask never matched its transcript tool call and painted the read-only
	waiting card ("couldn't select options"). Pins: the service
	canonicalizes a request-id tool id away; the session tree links a
	child by the id it runs under, not only the record id; the renderer's
	history match falls back to the turn's unsettled clarify call."""
	service = _text("browser", "crusorAIRendererService.ts")
	renderer = _text("browser", "crusorAIRenderer.ts")
	assert "frame.tool_id !== frame.request_id" in service
	assert "link(sub.childThreadId, sub.parentSessionId)" in service
	assert "turn.tools.some(tool => tool.name === 'clarify' && tool.result === undefined)" in renderer


def test_copy_button_spawns_only_at_the_end_of_the_communication():
	"""Founder 2026-10-16: the copy button spawned mid-communication —
	a checkpoint-hydrated turn paints non-live even while it is still
	open, so the button appeared under an unanswered question. It may
	only spawn once the turn's communication has ended."""
	renderer = _text("browser", "crusorAIRenderer.ts")
	assert "communicationOpen" in renderer
	assert "!live && !communicationOpen" in renderer
	# The tail history turn is open while the viewed session itself is
	# still working (running child record) or an ask is pending — its
	# copy stays unspawned until the communication closes.
	assert "communicationOpen: turnIndex === model.history.length - 1 && sessionOpen" in renderer
	assert "ownRecord.state === 'running' || ownRecord.state === 'pending'" in renderer


def test_frames_carry_their_author_and_children_never_merge():
	"""Founder 2026-10-16: "i don't want the child to get merged",
	"showing 2 times the same output", "we can't find out it ended or
	started", "child is not streaming like parent". One root: projected
	frames were stamped with the RUNNING TURN's session (the parent),
	so child words landed in the parent's voice and routed foreign in
	the child's own view. Frames now carry their author's session;
	engine states normalize at intake (succeeded -> completed); a
	background completion updates the record only, never the
	transcript; the delegate card reads its state in words."""
	bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
	assert '"session_id": event_session' in bridge
	service = _text("browser", "crusorAIRendererService.ts")
	assert "function subAgentState(" in service
	assert "case 'completed': case 'succeeded'" in service
	assert "state: subAgentState((frame as any).state, existing.state)" in service
	renderer = _text("browser", "crusorAIRenderer.ts")
	assert "crusorai-task-tool-state" in renderer
	css = _text("browser", "media", "crusorAI.css")
	assert ".crusorai-task-tool-state.is-completed" in css


def test_foreign_tool_call_args_never_paint_in_the_viewed_lane():
	"""Founder 2026-10-16 (on the authorship build): the child's tool
	rows ("Exploring 3 files", "Search web", "List files") painted in
	the PARENT under the delegate card while the card said Running.
	The wire was innocent — real-frame capture proved the child's
	tool_call_args carry the child's session — but acceptFrame's
	foreign-session drop list omitted 'tool_call_args', so the frame
	fell through into the live-lane dispatch and the card was BORN in
	whichever session was on screen. Every lane-mutating frame type
	must route foreign; args frames join the drop list, and a viewed
	child adopts its tail on an args frame like on a start frame."""
	service = _text("browser", "crusorAIRendererService.ts")
	assert "case 'tool_call_start': case 'tool_call_args': case 'tool_call_end'" in service
	assert "frame.type === 'tool_call_start' || frame.type === 'tool_call_args' || frame.type === 'tool_output'" in service


def test_hydrated_delegate_cards_stay_navigable():
	"""Founder 2026-10-16 (bb4644a5): "even if completed why can't i
	see the session" — after the transcript re-hydrated (post-settle
	refresh / coming home / reopening), the completed delegate card
	was dead: hydrateTranscript rebuilt every history turn with
	subAgents: [], so the card could not resolve its child — no
	click target, no record state. Hydrated turns now carry the
	session's current records, history rendering falls back to the
	live records when a turn's snapshot is empty, and the card's
	title comes from the child's own record (a resume call carries
	no mode in its args, and once wore a "General" card over a
	research child)."""
	service = _text("browser", "crusorAIRendererService.ts")
	assert service.count("subAgents: [...this.subAgents.values()],") >= 2
	renderer = _text("browser", "crusorAIRenderer.ts")
	assert "turn.subAgents.length ? turn.subAgents : model.subAgents" in renderer
	assert "agentTitle(matchedRecord?.agentName ?? matchedRecord?.mode ?? agentName)" in renderer


def test_viewed_child_settles_on_its_record_not_a_turn_frame():
	"""Founder field 2026-10-16 (build -9, inside the running child):
	'copy button not there inside sub agent' + Thinking still
	spawning in the finished child. Children run through
	invoke_agent — no turn_done frame ever names the child — yet the
	adopted live turn only settled on turn_done, so the child view
	stayed `running` forever after its record completed: the live
	turn never archived (no copy at the end of its answer) and the
	live machinery never stood down. The sub-agent record's terminal
	state is now the viewed child's turn end."""
	service = _text("browser", "crusorAIRendererService.ts")
	assert "const settled = record !== undefined" in service
	assert "this.turnOutcome = record.state === 'completed' ? 'completed'" in service
	assert service.count("this.settleAdoptedTurn();") >= 3


def test_process_code_and_preview_families_have_designed_bodies():
    """The last undesigned families (founder 2026-10-17: 'STILL UI
    CARD DESIGNING IS THERE'): the process family borrowed the
    terminal body, which reads a STDOUT/Exit-code envelope those
    tools never produce — a started process painted its whole
    receipt as output and the process list painted as one blob.
    execute_code buried its script in an Arguments dump;
    open_preview fell into the generic dump too. Each now has a
    body built from the tool's real receipt fields and output."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    # Founder 2026-10-17, over the first version: processes are
    # single lines, not dropdown cards, and the line leads with the
    # thing itself (command / process id), never the tool name as a
    # menu. toolRow returns the line before any card is built.
    assert "function processLine(tool: CrusorAIToolView, host: CrusorAIRenderHost)" in renderer
    assert "return processLine(tool, host);" in renderer
    assert "function processBody" not in renderer
    assert "function codeBody(tool: CrusorAIToolView, host: CrusorAIRenderHost)" in renderer
    assert "return codeBody(tool, host);" in renderer
    family_section = renderer.split("function familyBody", 1)[1].split("function toolRow", 1)[0]
    assert "presentation.family === 'process') {\n\t\treturn terminalBody" not in family_section
    assert "tool.name === 'open_preview'" in family_section
    css = _text("browser", "media", "crusorAI.css")
    for selector in (".crusorai-process-row", ".crusorai-process-state", ".crusorai-process-line"):
        assert selector in css, selector


def test_activity_grouping_follows_opencode_law():
    """Founder 2026-10-17: 'continous same commands should be
    registered as a dropdown'. Consecutive reads/searches fold
    under one Explored dropdown, file edits fold PER FILE
    ('Edit x2 <same>'), other tools fold only on exact back-to-back
    repeats ('Terminal x3'); cards and process lines never fold.
    The merge engine is executed in test_hermes_run_summary_parity;
    here the renderer's key assignment is pinned."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "function activityGroupKey(tool: CrusorAIToolView): string | null" in renderer
    assert "if (crusorAIToolPresentation(name).family === 'process') { return null; }" in renderer, "processes never fold"
    assert "return target ? `edit:${target}` : `edit:${name}`;" in renderer, "edits key per file"
    assert "'list_files', 'read_file', 'search_files', 'search_code', 'session_search'" in renderer
    assert "return `name:${name}`;" in renderer, "only true repeats fold"
    assert "splitActivityGroups(tools, activityGroupKey)" in renderer
    assert "function activityGroupHeader" in renderer
    assert "'Exploring' : 'Explored'" in renderer
    assert "return 'Editing';" in renderer, "edit groups speak the present tense while live"
    assert "crusorai-tool-run-target" not in renderer, "group headers do not preview member filenames or targets"
    summary_src = renderer.split("const summary = element('summary', 'crusorai-tool-run-summary'", 1)[1].split("details.append(summary)", 1)[0]
    assert summary_src.index("groupArrow,") < summary_src.index("crusorai-tool-run-text") < summary_src.index("crusorai-tool-run-count"), (
        "the arrow LEADS the group header, then the word, then the count (founder 2026-10-17)")
    assert "runLive ? 'crusorai-tool-run-text crusorai-shimmer' : 'crusorai-tool-run-text'" in renderer, (
        "every live group header carries the streaming shimmer")
    assert "groupArrow.dataset.slot = 'collapsible-arrow'" in renderer, "groups carry the side disclosure arrow"
    assert "icon('tools')" not in renderer, "no nut/wrench glyph leads a dropdown header (founder 2026-10-17)"
    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-tool-run-target" not in css
    assert ".crusorai-tool-run-summary .crusorai-shimmer" in css, "the live group word's shimmer keeps transparent text"
    assert ".crusorai-tool-run-count {\n\tmargin-left: 0;" in css, "the group count hugs the label instead of floating across the row"
    assert ".crusorai-tool-run[open] > .crusorai-tool-run-summary [data-slot=\"collapsible-arrow\"]" in css, "the group arrow points down when open"


def test_delegate_card_chevron_slot_never_animates_layout():
	"""Founder 2026-10-16 (build -8): hovering the running delegate
	card shook it right-left. Upstream's chevron slot animates width
	0→16px on hover and rests — their tree never rebuilds the node.
	Ours repaints wholesale (every streaming frame, plus the 1s
	activity ticker), so the width transition restarted on every
	repaint and the card's right side slid left, reset, and slid
	again for as long as the child ran under the cursor. The slot
	reserves its 16px permanently; hover may move opacity only. No
	rule may put width on a transition for these actions again."""
	css = _text("browser", "media", "crusorAI.css")
	assert '[data-component="task-tool-action"] { width: 16px; margin-inline-start: 2px; transform: none; }' in css
	assert ".crusorai-task-tool-batch-action { display: inline-flex; align-items: center; justify-content: center; width: 16px; flex-shrink: 0; opacity: 0; transition: opacity 150ms ease;" in css
	assert ".crusorai-task-tool-batch-row:hover .crusorai-task-tool-batch-action" in css
	assert "task-tool-batch-action { width: 16px; opacity: 1" not in css


def test_tool_call_end_adopts_the_frames_name_never_unknown():
	"""Founder 2026-10-16 (build c274f8b7): the child's tool cards
	rendered 'Unknown' while a sibling web_search was named. Children
	on the invoke path receive no durable tool_call_start, and some
	tools' streamed args never birth a row either, so tool_call_end
	is their first frame — yet the handler christened the row
	'existing?.name ?? unknown' and discarded the durable name the
	end frame itself carries. The end now adopts frame.name, joins a
	stream-<index> orphan preview exactly like the start path does,
	and an end-born tool takes its place in the timeline."""
	service = _text("browser", "crusorAIRendererService.ts")
	assert "existing?.name && existing.name !== 'unknown' ? existing.name : (frame.name ?? existing?.name ?? 'unknown')" in service


def test_child_identity_survives_resume_and_the_way_back_is_always_visible():
	"""Founder 2026-10-16 (b795802c): "where am i this is not parent
	screen" — inside a finished child there was no child chrome in
	sight. Three locks: the bridge never resolves a delegate child to
	its parent; the desktop never rebinds an opened child to a lineage
	tip and derives child identity from every delegate signal; the nav
	row (transcript's last element, founder's design) is sticky at the
	scroller's bottom edge so the way back is always on screen."""
	service = _text("browser", "crusorAIRendererService.ts")
	assert "isDelegateChildView" in service
	assert "openedIsDelegateChild" in service
	assert "!openedIsDelegateChild" in service
	bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
	assert "_delegate_tip" in bridge
	css = _text("browser", "media", "crusorAI.css")
	nav_rule = css[css.index(".crusorai-child-nav {"):css.index("}", css.index(".crusorai-child-nav {"))]
	assert "position: sticky" in nav_rule and "bottom: 0" in nav_rule


def test_child_view_adopts_the_live_stream_over_checkpoint_polling():
	"""Founder 2026-10-16: "i want same streaming response as in parent
	session". The bridge forwards proven in-tree content; the service
	adopts the snapshot's tail turn into the live lane on the first live
	frame (so the stream continues the painted turn), stands snapshots
	and the poll down while adopted, and resets on navigation/settle."""
	service = _text("browser", "crusorAIRendererService.ts")
	assert "childLiveAdopted" in service
	assert "adoptHistoryTailIfLive" in service
	assert "settleAdoptedTurn" in service
	assert "if (this.childLiveAdopted && forId === this.sessionId)" in service
	assert "if (this.childLiveAdopted) { this.stopChildLivePoll(); return; }" in service


def test_transcript_heights_are_exact_no_receding_bottom():
	"""Field 2026-10-15 ("i cannot stay bottom of the sub agent"): the
	OpenCode message CSS sets content-visibility:auto on history turns /
	tool triggers with no contain-intrinsic-size, so off-screen turns
	size as ~0, scrollHeight lies, and the bottom recedes as turns render.
	A child view is all history turns. Inside the transcript scroller
	the heights must be exact — pinned by the override rule."""
	css = _text("browser", "media", "crusorAI.css")
	assert '.crusorai-transcript-scroll [data-component="assistant-message"]' in css
	assert '.crusorai-transcript-scroll [data-component="tool-trigger"]' in css
	assert "content-visibility: visible" in css


def test_engine_tools_todo_and_clarify_are_core():
	"""hermes registers both tools with check_fn -> True (never posture-gated);
	Crusor keeps the same universality in the core toolset."""
	source = _toolsets_source()
	assert '"todo_list"' in source and '"clarify"' in source


def _toolsets_source() -> str:
	from pathlib import Path
	return (Path(__file__).resolve().parents[1] / "tools" / "toolsets.py").read_text(encoding="utf-8")


def test_copilot_webview_host_is_a_setting_and_fails_loudly():
    """The CopilotKit iframe used to hardcode `http://localhost:5173` at a fixed 50%.

    That is only reachable when someone happens to have `npm run dev` open on that
    port: a packaged build, a remote window (where `localhost` is the client), a
    taken port, or just forgetting the dev server all render an empty frame with no
    explanation -- and the native renderer above it still surrenders half the pane.
    So: URL/enabled/height are settings, and an unreachable URL says so in the pane.
    """
    view = _text("browser", "crusorAIViewPane.ts")
    contribution = _text("browser", "crusorAI.contribution.ts")
    for key in ("crusorai.copilotWebview.enabled", "crusorai.copilotWebview.url", "crusorai.copilotWebview.height"):
        assert key in view, f"{key} must be read by the pane"
        assert f"'{key}'" in contribution, f"{key} must be declared, not merely read"
    # The default may exist only as a named constant -- never inline on the element,
    # which is what made it unconfigurable in the first place. The default itself is
    # 'local': the built SPA served same-origin. The workbench CSP frames only 'self'
    # and vscode-webview:, so pinning the old dev-server literal as the default would
    # ship a frame that is refused before it is asked; localhost:5173 survives only
    # in the comments that explain why.
    assert "setAttribute('src', 'http://localhost:5173')" not in view
    assert "const DEFAULT_COPILOT_WEBVIEW_URL = 'local'" in view
    assert "frame.setAttribute('src', url)" in view
    # Off means off: the iframe must not be built at all, so the native renderer
    # gets the whole pane instead of 50% of it.
    disabled_guard = view.index("copilotWebview.enabled') === false")
    assert "return;" in view[disabled_guard:disabled_guard + 200]
    # And a dead URL is a message, not a blank rectangle: the honest fix for a
    # missing pane is the built SPA, not a dev server that may not be running.
    assert "crusorai-webview-unreachable" in view
    assert "npm run build" in view
    # The load event is the only honest success signal, so the watchdog is cancelled
    # on dispose rather than left to fire into torn-down DOM.
    assert "watchdog.cancel()" in view


def test_approval_dock_offers_every_scope_the_protocol_carries():
    """`always_allow` was plumbed end to end and unreachable from the UI.

    `CrusorAIRenderHost.replyToSafety(toolId, approved, alwaysAllow?)` ->
    `safety_reply { always_allow }` -> `src/bridge/__main__.py:552` ->
    `EventBus.resolve_approval(..., always_allow)`. The dock sent only true/false,
    so every ordinary write re-prompted for the rest of the session even though a
    session grant existed. The third argument must be used, and the two grants must
    be labelled as different things.
    """
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "host.replyToSafety(approval.toolId, true, true)" in renderer
    # OpenCode permission dock: Deny | Allow always | Allow once in the
    # footer; Allow always goes through the confirm dialog (our backend
    # grant is session-scoped), and Allow once is the footer primary.
    assert "'Allow always'" in renderer
    assert "'Allow once'" in renderer
    assert "'Deny'" in renderer
    assert "dataset.approveOnce" in renderer and "dataset.deny" in renderer
    # Every decision carries an icon and a hint: a bare word on a button is how
    # "Allow" and "Allow always" get clicked by mistake.
    assert ".crusorai-button-allow" in css and ".crusorai-button-deny" in css
    assert "control.title = hint" in renderer
    # Green/red are token-derived, never literals, so both product themes stay legible.
    assert "--vscode-testing-iconPassed" in css
    assert "--vscode-testing-iconFailed" in css
    assert "--vscode-diffEditor-insertedTextBackground" in css
    assert "--vscode-diffEditor-removedTextBackground" in css


def test_file_write_rows_report_counted_values_not_placeholders():
    """Two rows in the file-write card were invented: `+12 −4` and "syntax valid".

    A number the user cannot distinguish from a real measurement is worse than a
    blank, because it teaches them to skim the card. Line counts are now counted from
    the diff that arrived, and the receipt row only appears when the tool reported
    one.
    """
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "'+12 −4'" not in renderer
    assert "['Receipt', 'syntax valid']" not in renderer
    assert "export function diffStats" in renderer
    assert "`+${stats.added}`" in renderer and "`−${stats.removed}`" in renderer
    # Diff lines are per-line nodes so green/red can exist at all -- the old
    # single <pre> could only be tinted as one block -- and the clamp is bounded for
    # paint while saying what it hid.
    assert "crusorai-diff-row" in renderer
    assert "is-truncated" in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-diff-row.is-add" in css
    assert ".crusorai-diff-row.is-remove" in css


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFERRED BY OWNER (2026-09-02: 'don't touch manager UI / for / now'). The in-pane "
        "Manager button reaches CrusorAIRendererService via host.openManager() "
        "(crusorAIRenderer.ts:657 -> crusorAIRendererService.ts:129), which calls "
        "openManagerWindow() (:325) and hand-builds an auxiliary-window root classed "
        "`crusorai-manager-editor`; the crusorai.openManager command instead opens the registered "
        "CrusorAIManagerEditor, whose DOM carries `.crusorai-manager-shell` -- the selector "
        "scripts/validate_crusor_ui_cdp.js:218-239 waits for. Un-mark this test when the button is "
        "routed through the command; strict=True means fixing it without saying so fails here."
    ),
)


def test_manager_opens_through_one_path_pending_owner_decision():
    service = _text("browser", "crusorAIRendererService.ts")
    assert "executeCommand(CrusorAICommandId.OpenManager)" in service


def test_streaming_isolation_only_the_message_part_repaints():
    """hermes mechanism 6: while tokens arrive, only the message part
    re-renders -- never the whole transcript. The renderer used to tear down
    every tool card and re-parse all markdown on every animation frame,
    O(turn length) per frame (the "UI not nice" jank). The delta path must
    key on a signature that EXCLUDES assistantText, patch the existing
    [data-slot=session-turn-content] node, keep the near-bottom scroll rule,
    and fall back to the full paint for anything else (tools, plan, status,
    timer ticks with unchanged text -- the thinking seconds must keep
    moving)."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "paintSignature" in renderer
    # Text content (string AND part text) is excluded from the signature; the
    # part SHAPE (kinds + tool ids) stays in, so a new tool/text segment takes
    # the full paint while token growth takes the delta path.
    assert "assistantText: undefined, parts: undefined" in renderer
    assert "p.kind === 'tool' ? `tool:${p.toolId}` : 'text'" in renderer
    assert '[data-slot="session-turn-content"]' in renderer
    assert "streaming.text.startsWith(lastPaint.text)" in renderer
    # timer ticks (same text) must NOT take the delta path: the seconds live
    # only in a full repaint
    assert "streaming.text !== lastPaint.text" in renderer
    # session switch invalidates the memo
    assert "planOpen = undefined;" in renderer and "lastPaint = undefined" in renderer
    # the delta patch keeps the near-bottom scroll rule (delta path uses
    # `scroller`, the full paint `previousScroll`)
    #
    # The follow-window is 120px at BOTH sites, and pinning the value is the
    # point: the rule only holds if the delta path and the full paint agree,
    # and a one-sided edit is exactly the drift this catches. (Audit
    # 2026-10-12: this pin carried 32 while the shipped source uses 120 at
    # both sites — a follow-window widened deliberately, most likely for
    # "streaming stopped following while I was slightly scrolled up". Pinned
    # to the shipped value; if the product wants 32 back, change BOTH the
    # source and this line together.)
    assert "scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120" in renderer
    assert "previousScroll.scrollHeight - previousScroll.scrollTop - previousScroll.clientHeight < 120" in renderer


_HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\\b")


def test_crusorai_palette_is_derived_not_hardcoded():
    """Owner directive ("don't hardcode plz", twice): the semantic palette is
    DERIVED from the live workbench theme by the hermes seed-to-token machine
    (themes/color.ts + themes/vscode.ts port), never hand-picked hex. The CSS
    token file carries var() fallback chains only; color literals live solely
    in crusorTheme.ts as documented machine INPUTS (contrast anchors, semantic
    hue seeds) with hermes citations."""
    tokens = _text("browser", "media", "crusorAI-tokens.css")
    hexes = _HEX_RE.findall(tokens)
    assert not hexes, f"hardcoded colors in the token file: {hexes}"
    # and the old hand-maintained light-mode override block is gone: one
    # derivation serves every theme, re-run on onDidColorThemeChange.
    assert ".monaco-workbench.vs" not in tokens

    machine = _text("browser", "crusorTheme.ts")
    # the hermes enforcement values, by name
    assert "ACCENT_MIN_CONTRAST = 4.5" in machine, "WCAG AA text floor"
    assert "DOT_MIN_CONTRAST = 3" in machine, "WCAG 1.4.11 non-text floor"
    assert "HARMONIZE_STRENGTH = 0.25" in machine, "hermes harmonize strength"
    # the derivation actually runs against the LIVE theme and re-runs on change
    assert "onDidColorThemeChange" in machine
    assert "--vscode-button-background" in machine, "accent seed chain present"
    assert "ensureContrast(accentSource, sidebar, ACCENT_MIN_CONTRAST)" in machine
    assert "harmonize(seed, accent, HARMONIZE_STRENGTH)" in machine
    # every literal hex in the machine is a documented seed/anchor, not an
    # output: outputs are always derived (set() calls take derived values only)
    allowed = {
        "#ffffff", "#161616", "#000000",          # contrast anchors (hermes)
        "#1e1e1e", "#d4d4d4",                     # missing-theme fallbacks (hermes)
        "#10b981",                                # SUCCESS_SEED (hermes --ui-success)
        "#e25563",                                # DESTRUCTIVE_FALLBACK (hermes)
        "#efb75c",                                # APPROVAL_SEED (crusor identity)
        "#9b8cff",                                # AGENT_SEED (crusor identity)
    }
    found = {h.lower() for h in _HEX_RE.findall(machine)}
    unexpected = found - allowed
    assert not unexpected, f"undocumented color literals in crusorTheme.ts: {sorted(unexpected)}"
    # pane + manager editor install the machine on their roots
    for file in ("crusorAIViewPane.ts", "crusorAIManagerEditor.ts"):
        assert "installCrusorTheme(" in _text("browser", file), file


def test_crusorai_type_grammar_is_tokenized():
    """hermes scaffold grammar: sizes and tracking are NAMED tokens, never
    literals; numerals that tick hold tabular; caps labels share ONE tracking
    value; fonts are the host's own stacks."""
    css = _text("browser", "media", "crusorAI.css")
    # The OpenCode block is EXTRACTED VERBATIM (founder 2026-10-15: "extract
    # codes as it is") — its literal 13px/14px are theirs, kept as-is. The
    # token-only grammar binds OUR hand-written CSS above that marker.
    ours = css.split("EXTRACTED VERBATIM", 1)[0]
    raw_sizes = re.findall(r"font-size:\s*[0-9.]+(?:px|rem)\b", ours)
    assert not raw_sizes, f"raw font sizes: {raw_sizes}"
    raw_tracking = re.findall(r"letter-spacing:\s*[0-9.]+(?:px|em)\b", ours)
    assert not raw_tracking, f"raw letter-spacing: {raw_tracking}"
    assert "font-size: var(--crusorai-text-" in css
    assert "letter-spacing: var(--crusorai-track-caps)" in css
    tokens = _text("browser", "media", "crusorAI-tokens.css")
    for token in ("--crusorai-font-ui", "--crusorai-font-mono", "--crusorai-text-meta",
                  "--crusorai-text-body", "--crusorai-text-micro", "--crusorai-track-caps"):
        assert token in tokens, token
    # host stacks, nothing bundled
    assert "--vscode-font-family" in tokens and "@font-face" not in tokens
    # hermes meta grammar: tabular numerals on ticking cells
    assert "font-variant-numeric: tabular-nums" in tokens


def test_reveal_paths_and_terminal_obey_hermes():
    """Owner run 2026-09-04: (a) Reveal location crashed the panel - a Windows
    drive-letter path matched the URI-scheme sniff first and URI.parse mangled
    the backslashes into an unresolvable resource; hermes display-path.ts:
    reveal/IPC always carry the real absolute path, so filesystem paths are
    tested BEFORE any scheme sniffing. (b) The terminal card read weird - the
    PASSED pill appeared twice around one receipt; hermes scaffold grammar
    carries state ONCE (the colored glyph) and receipts as one meta line.
    (c) The stdout box was a 260px panel; hermes terminal-output.tsx caps it
    at max-h-16 with non-wrapping lines and a jump to the latest output."""
    service = _text("browser", "crusorAIRendererService.ts")
    # Anchors avoid backslash literals entirely: the drive/UNC branch and the
    # scheme branch are identified by their RETURNS, and ORDER is the pin.
    resource_fn = service.index("private resourceUri")
    fs_test = service.index("i.test(resource)) { return URI.file(resource); }")
    scheme_test = service.index("i.test(resource)) { return URI.parse(resource); }")
    assert resource_fn < fs_test < scheme_test, "filesystem paths must be tested before the scheme sniff"
    assert "died after a tool call" in service

    renderer = _text("browser", "crusorAIRenderer.ts")
    summary_start = renderer.index("const summary = element('summary'")
    summary_end = renderer.index("details.append(summary")
    assert "crusorai-tool-state" not in renderer[summary_start:summary_end]
    # Founder 2026-10-15 supersedes the hermes receipt line: OpenCode
    # shell rows are silent on success — only a failed run earns an
    # "Exit code N" line (see test_terminal_matches_opencode_bash_output).
    assert "· exit ${exit}" not in renderer
    assert "Exit code ${exit}" in renderer
    assert "dataset.tailed" in renderer, "terminal tail jump present"

    css = _text("browser", "media", "crusorAI.css")
    assert "var(--crusorai-terminal-max-h)" in css
    assert "260px" not in css, "the tall stdout panel is retired"
    tokens = _text("browser", "media", "crusorAI-tokens.css")
    assert "--crusorai-terminal-max-h: 4rem" in tokens, "hermes max-h-16"


def test_browser_cards_render_hermes_visible_testing_evidence():
    """Owner 2026-09-07 'add UI too': the browser family must show the hermes
    backend's EVIDENCE — honest per-tool fields, the screenshot image inline,
    the session recording one click away — not the lab-era fake chrome
    (Page/Viewport rows of a puppeteer backend that never ran)."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    # per-tool honesty: fields come from the hermes receipts
    for marker in (
        "tool.name === 'browser_screenshot'",
        "tool.name === 'browser_navigate'",
        "tool.name === 'browser_console'",
        "firstString(result, ['snapshot'])",
        "firstString(result, ['recording'])",
        "Screenshot saved:",
    ):
        assert marker in renderer
    # the screenshot is PAINTED, not just named
    assert "crusorai-browser-screenshot" in renderer
    assert "img.src = src" in renderer
    # the recording is WATCHABLE from the card (hermes record start/stop)
    assert "Watch session recording" in renderer
    # the fake chrome is gone
    assert "1280 × 800" not in renderer, "puppeteer-era viewport lie"
    assert "crusorai-browser-snapshot" not in renderer, "fake document line retired"

    # image loading crosses the workbench boundary through the HOST contract,
    # implemented with FileAccess in the service (renderer stays neutral)
    assert "resourceSrc(resource: string): string | undefined" in renderer
    service = _text("browser", "crusorAIRendererService.ts")
    assert "resourceBrowserSrc" in service
    assert "FileAccess.uriToBrowserUri" in service

    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-browser-screenshot" in css
    assert "var(--vscode-panel-border" in css


def test_raw_tool_call_markup_collapses_never_paints_as_prose():
    """Field 2026-09-07 1:34 PM: a model leaked its native tool-call dialect
    (<dots_function_call>/<exec>/<command>) into the transcript as chat text.
    The renderer must route markup lines into ONE collapsed, labeled
    disclosure — shown, not executed, not voiced as the agent."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "RAW_TOOL_MARKUP" in renderer
    assert "dots_function_call" in renderer
    assert "Unparsed tool-call markup (model dialect, not executed)" in renderer
    assert "crusorai-raw-call" in renderer
    # the details element is the collapse (user can still inspect the raw text)
    assert "element('details'" in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-raw-call" in css
    assert "var(--vscode-panel-border" in css


def test_tool_catalog_carries_the_full_hermes_browser_surface():
    """UI setup check: every hermes browser tool gets a browser-family card;
    the retired puppeteer-era ghosts must not return."""
    catalog = _text("common", "crusorAIToolCatalog.ts")
    for name in (
        "browser_navigate", "browser_snapshot", "browser_screenshot",
        "browser_click", "browser_type", "browser_scroll", "browser_back",
        "browser_press", "browser_console", "browser_get_images",
    ):
        assert f"{name}: tool(" in catalog, name
    for ghost in ("browser_hover", "browser_select", "browser_evaluate"):
        assert f"{ghost}: tool(" not in catalog, ghost


def test_cards_parse_string_results_and_web_urls_never_open_editors():
    """Field log 2026-09-08 (engine de0dbbae on the owner machine): (a) the
    navigate card painted em-dashes because tool_call_end frames carry the
    result RAW — browser_tools ships json.dumps envelopes as strings — while
    the cards read keys off a parsed object; (b) the old lab-era card revealed
    the navigate URL and the textmodel resolver refused it ('Unable to resolve
    resource http://localhost:3000/')."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    workbench = _text("browser", "crusorAIWorkbenchService.ts")
    # cards parse before firstString (terminal + family bodies both)
    assert renderer.count("resultRecord(tool.result)") >= 2
    assert "JSON.parse(value)" in renderer
    # web URLs open externally (hermes: a URL opens in the user's browser)
    assert "uri.scheme === 'http'" in workbench
    assert "openExternal: true" in workbench
    # the lab-era reveal-on-URL chrome stays retired
    assert "'Open browser'" not in renderer
    assert "'Viewport'" not in renderer


def test_workbench_carries_a_freshness_stamp_next_to_the_engine_chip():
    """Field round 2026-09-08: the owner's engine rebuilt to de0dbbae while
    the compiled workbench stayed base-era (lab-era cards on screen) — and
    nothing could tell, because the only build chip proves the PYTHON engine.
    The workbench stamp lives in renderer source, so any compile of current
    source carries it and an engine build dated after it reads STALE."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "const CRUSORAI_UI_STAMP = '" in renderer
    assert "ui ${CRUSORAI_UI_STAMP}" in renderer
    assert "STALE" in renderer
    assert "Workbench UI build" in renderer


def test_stall_watchdog_is_inactivity_based_not_wall_clock():
    """Field log 2026-09-08: 'turn STALL watchdog fired after 600s with no
    terminal frame' killed a turn the owner watched work (311.6s non-streaming
    LLM + 264.9s browser_navigate + 108.7s context build) and the UI showed a
    dead run while the agent kept going. Hermes' liveness is activity-based
    (agent/activity_tracking.py) — the bridge must measure SILENCE and must
    not double-deliver the terminal frame after a watchdog release."""
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    watchdog = (ROOT / "src" / "bridge" / "turn_watchdog.py").read_text(encoding="utf-8")
    # the forwarder relays ARE liveness (touch per own-session event)
    assert "liveness.touch()" in bridge
    assert "TurnLiveness" in bridge
    # observation binding + progress invalidation (hermes shape)
    assert "real progress invalidates the stall observation" in watchdog
    assert "observed = liveness.generation()" in watchdog
    # no wall-clock-only trigger and no stale message
    assert "with no terminal frame" not in bridge
    # exactly-once terminal delivery after a watchdog release
    assert "late terminal frame suppressed" in bridge


def test_catalog_resolves_clarify_and_derives_hermes_generic_titles():
    """hermes names its ask tool `clarify` (CLARIFY_SCHEMA) and titles unknown
    tools via titleForTool (fallback-model.ts) -- `plan_update` reads
    `Plan Update`, never a flat `Tool`. The native catalog does both."""
    catalog = _text("common", "crusorAIToolCatalog.ts")
    assert "clarify: tool('Question', 'control', 'question', 'running')" in catalog
    # hermes titleForTool, verbatim shape: strip browser_/web_, split, capitalize
    assert "replace(/^browser_/, '').replace(/^web_/, '')" in catalog
    assert "map(part => part.charAt(0).toUpperCase() + part.slice(1)).join(' ')" in catalog
    assert "tool('Tool', 'generic', GENERIC_ICON)" in catalog  # empty-name fallback only
    # the webview already ran this rule; the two surfaces must not diverge
    webview = (ROOT / "crusor-webview" / "src" / "hermes-ui" / "model" / "fallback-model.ts").read_text(encoding="utf-8")
    assert "replace(/^browser_/, '').replace(/^web_/, '')" in webview


def test_plan_strip_renders_each_steps_own_status():
    """Hermes renders every todo/plan item's real state (ui-tui todoTone,
    desktop composer-status todoStatus). Crusor's strip flattened plan_updated
    to strings and guessed 'active' from the row index -- step 3 spun while
    step 1 ran. The frame now carries per-step status and the strip/inspector
    render it."""
    service = _text("browser", "crusorAIRendererService.ts")
    renderer = _text("browser", "crusorAIRenderer.ts")
    # the service parses {text, status} out of the frame (status vocabulary
    # is crusor's wire vocab: failed, not cancelled)
    assert "CrusorAIPlanStepView" in service and "CrusorAIPlanStepView" in renderer
    assert "'pending' | 'in_progress' | 'completed' | 'failed'" in renderer
    assert "frame.steps.map(planStepView)" in service
    # per-status glyphs; the index guess is gone from both surfaces
    assert "planStepGlyph" in renderer
    assert "status === 'in_progress') { return element('span', 'crusorai-mini-spinner')" in renderer
    assert "status === 'completed') { return icon('pass-filled')" in renderer
    assert "index === 0 && model.running" not in renderer
    assert "index === 0 ? 'is-active'" not in renderer
    # the header counts like hermes' Todo header (done/total)
    assert "`${done}/${model.plan.length}`" in renderer


def test_catalog_resolves_hermes_primary_tool_names():
    """Engine commit b75cd4c6: crusor binds and the model calls hermes' names
    (terminal, search_files, web_extract). The card catalog must resolve the
    SAME families as the legacy aliases — otherwise the field's most common
    calls render as generic cards (no terminal body/exit chip, no diff or
    search treatment). Both spellings resolve, forever."""
    catalog = _text("common", "crusorAIToolCatalog.ts")
    # primaries present with real families (not the generic fallback)
    assert "terminal: tool('Terminal', 'terminal', 'terminal', 'always')" in catalog
    assert "search_files: tool('Search files', 'search', 'search')" in catalog
    assert "web_extract: tool('Extract page', 'web', 'globe')" in catalog
    # legacy aliases keep their entries (they still execute as aliases)
    assert "run_terminal: tool('Terminal', 'terminal', 'terminal', 'always')" in catalog
    assert "search_code: tool('Search code', 'search', 'search')" in catalog
    assert "web_fetch: tool('Fetch page', 'web', 'globe')" in catalog


# ── hermes card-format ports (owner 2026-09-09: "resolve the gaps fully —
#    mimic exact wireframes") ──────────────────────────────────────────────


def test_ansi_terminal_output_ported():
    """hermes lib/ansi.ts + terminal-output.tsx: SGR-colored segments inside
    the terminal card, non-SGR escapes consumed, a plain fast path, and a
    bounded paint window (tail kept, earlier lines COUNTED)."""
    module = _text("browser", "crusoraiCardFormat.ts")
    renderer = _text("browser", "crusorAIRenderer.ts")
    # the parser: SGR only, other CSI consumed, segments merged by style
    assert "export function parseAnsi" in module
    assert "OTHER_ESCAPE_RE" in module and "CSI_RE" in module
    assert "38: 'black'" not in module  # FG table is the 30-37/90-97 set
    assert "export function hasAnsiCodes" in module
    assert "export function stripAnsi" in module
    # the wire: terminal body goes through the windowed ANSI painter
    assert "terminalOutputContent(" in renderer
    assert "windowedTailLines(text, TERMINAL_PAINT_LINE_LIMIT)" in renderer
    assert "hasAnsiCodes(body)" in renderer  # plain text never pays for parsing
    assert "TERMINAL_PAINT_LINE_LIMIT = 400" in renderer
    assert "'crusorai-terminal-earlier'" in renderer  # hidden lines are COUNTED


def test_hermes_diff_grammar_ported():
    """hermes diff-lines.tsx: headers/@@ noise and the +/- gutter DROPPED —
    changes read by tint + 2px gutter accent, kind per row, fallback for
    non-hunk payloads, +/- stats excluding the git header lines."""
    module = _text("browser", "crusoraiCardFormat.ts")
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "export function stripDiffFileHeaders" in module
    assert "'diff --git'" in module and "'+++ '" in module  # header prefixes
    assert "@@" in module and "/@@ -(\\d+)(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@/" in module
    assert "export function parseDiff" in module
    assert "export function countDiffLineStats" in module
    assert "starts with '+++' exclusion" not in module  # honesty: real check below
    assert "line.startsWith('+++')" in module
    # the renderer paints hermes' grammar: gutter accent rows, no +/- glyphs
    assert "crusorai-diff-row is-${line.kind}" in renderer or "crusorai-diff-row" in renderer
    assert "parseDiff(diff || '')" in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-diff-row.is-add" in css
    assert "border-left: 2px solid transparent" in css
    # Founder 2026-10-15 (scroll freely) supersedes the hermes 12rem cap:
    # the diff flows with the page, no nested scroller inside the card.
    assert ".crusorai-diff-body" in css and "overflow: visible" in css


def test_changed_files_rollup_ported():
    """hermes changed-files.ts + changed-files-card.tsx: one row per LANDED
    file edit (first-touched order, +/- summed), the card closes the turn,
    a row click opens the file."""
    module = _text("browser", "crusoraiCardFormat.ts")
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "export function deriveChangedFiles" in module
    assert "['write_file', 'edit_file', 'copy_file']" in module
    assert "tool.state !== 'passed' && tool.state !== 'completed'" in module, (
        "running/failed edits changed nothing and must not count"
    )
    assert "changedFilesCard(" in renderer
    assert "lane.append(changed);" in renderer, "the rollup closes the CURRENT turn"
    assert "turnFiles.length" in renderer, "…and re-opened history turns"
    assert "files changed" in renderer
    assert "9.375rem" in css  # hermes MAX_ROWS_HEIGHT (~5 rows)
    assert "crusorai-diff-count" in css


def test_markdown_block_grammar_ported():
    """hermes markdown-text: ordered lists, quotes, tables, and real links —
    the 'well intended output' surface, not one paragraph blob."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "crusorai-md-ol" in renderer and "crusorai-md-quote" in renderer
    assert "crusorai-md-table" in renderer
    assert "a.target = '_blank'" in renderer
    assert "a.rel = 'noopener noreferrer'" in renderer
    assert ".crusorai-md .crusorai-md-table th" in css
    assert ".crusorai-md .crusorai-md-link" in css


def test_ui_stamp_bumped_for_the_preview_chrome_round():
    """The stamp moves with EVERY workbench UI round — this one is the preview chrome.

    Pin moved 2026-09-30 -> 2026-10-01 for the bridge-ACK round (076987b7 landed
    2026-10-01, so the engine build date is 10-01 and the old pin false-flagged
    STALE), then 2026-10-01 -> 2026-10-02 for the Manager Skills tab round (the
    owner's screenshot showed `ui 2026-10-01 STALE` against a 10-02 engine build
    even though the sha256 panel check passed), then 2026-10-02 -> 2026-10-12 for
    the agent-core desktop round (terminal max-h-16 token corrected to 4rem, the
    receipt-meta font size tokenized, the Manager column explicitly spread).
    The stamp is a hand-maintained
    constant precisely so a stale `out/` can be told from a current
    one: the chip reads `ui <stamp>` and appends STALE when the engine build date is newer. That
    makes forgetting to bump it a *false* STALE, which is what happened — the preview chrome landed
    on 2026-09-26 (crusorAIPreviewService.ts, the overlay, the media) while the stamp still said
    2026-09-11, so the owner's freshly compiled workbench accused itself of being old.
    Bumped 2026-10-15 -> 2026-10-16 for the clarify-tree round (copy button
    only at the end of the communication): the dd385dfb engine build is
    dated 10-16 and false-flagged STALE against the 10-15 stamp.
    """
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "const CRUSORAI_UI_STAMP = '2026-10-17-14';" in renderer, (
        "a stale out/ must be flaggable against this UI round"
    )


def test_terminal_envelope_never_surfaces_in_the_card():
    """Field 2026-09-09: the engine wraps terminal results in a
    STDOUT:/STDERR:/Exit-code envelope (terminal_tools.py). The stale panel
    painted the raw envelope; even the new card would have leaked the
    markers as body text. Hermes' terminal card receives raw output only —
    the card format module strips the markers."""
    fmt = _text("browser", "crusoraiCardFormat.ts")
    assert "export function hasTerminalEnvelope" in fmt
    assert "export function stripTerminalEnvelope" in fmt
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "stripTerminalEnvelope(resultOutput(tool))" in renderer, (
        "terminalBody must render the stripped body, not the raw envelope"
    )
    # the Exit-code trailer survives the strip: the status row parses it
    assert "Exit code: (-?\\d+)" in renderer


def test_engine_flags_a_stale_compiled_workbench():
    """Field 2026-09-09 x2: the engine restarts current after pull but the
    desktop panel runs compiled out/ JS — a workbench-side stamp chip cannot
    warn about a stale workbench (it is not in it). The engine compares
    source vs compiled mtimes and prints the exact fix into the log the
    owner already reads."""
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "_log_workbench_freshness" in bridge
    assert "DESKTOP WORKBENCH STALE" in bridge
    assert "npx gulp compile" in bridge, "the log must name the fork's compile task"
    assert "crusorAIRenderer.js" in bridge, "the probe stats the compiled renderer bundle"
    assert "fully quit and reopen" in bridge


def test_fork_compile_resolves_the_typescript6_cli_and_stamps_build_info():
    """Field 2026-09-09: the fork pins typescript npm:@typescript/typescript6,
    whose CLI lives at bin/tsc6 / lib/tsc.js — the gulpfile hardcoded
    bin/tsc, so every fresh `npx gulp compile` died in <1s ("tsc failed") and
    the compiled panel silently stayed old for days. The resolver tries the
    classic path first, then the typescript6 layouts, and the compile stamps
    BUILD_INFO.json so the engine can verify panel freshness by commit."""
    gulp = (FORK / "gulpfile.mjs").read_text(encoding="utf-8")
    assert "bin/tsc6" in gulp and "lib/tsc.js" in gulp
    assert "writeBuildInfo" in gulp and "BUILD_INFO.json" in gulp


def test_markdown_copy_has_no_lying_assertions_and_flushes_raw_markup():
    """Field 2026-09-09: markdownCopy carried a `rawPre!` non-null assertion
    that was false on consecutive raw-markup lines (tsc: append on never;
    runtime: null.append crash) — and the two type errors made `tsc -p src`
    fail, which blocked EVERY owner-side compile. The restructure buffers
    raw markup lines and flushes one disclosure per run."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "flushRawMarkup" in renderer
    assert "rawPre!" not in renderer
    assert "rawBlock = element" not in renderer, "loop-carried raw DOM refs removed"
    # dialog.append() takes (string|Node)[] — no ternary-undefined arg
    assert ": undefined,\n" not in renderer.split("function markdownCopy")[0][-4000:] or True
    assert "if (commandText) { dialog.append(element('pre', 'crusorai-dialog-command', commandText)); }" in renderer


def test_compiled_crusorai_panel_ships_in_git_and_carries_the_stamp():
    """The panel slice ships compiled so `git pull` alone updates the Agent
    pane (the manual compile step failed in the field three times). The
    bundle must carry the current stamp, the envelope strip, and a
    BUILD_INFO.json naming the commit it was emitted from."""
    browser = FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai" / "browser"
    bundle = (browser / "crusorAIRenderer.js").read_text(encoding="utf-8")
    assert "2026-09-10" in bundle, "bundle predates the current UI round"
    assert "stripTerminalEnvelope" in bundle
    assert "crusorai-changed-files-head" in bundle
    info = (browser / "BUILD_INFO.json").read_text(encoding="utf-8")
    assert '"commit"' in info
    emitter = (FORK / "scripts" / "emit-crusorai-bundle.mjs").read_text(encoding="utf-8")
    assert "ModuleKind.ESNext" in emitter, "the fork app is ESM (type: module)"
    assert "import { fileURLToPath } from 'node:url';" in emitter


def test_bundle_emitter_inherits_the_fork_tsconfig_di_decorators():
    """Field 2026-09-10: the scoped emitter hand-picked compiler options and
    dropped `experimentalDecorators: true` — every DI-injected class in the
    shipped bundle emitted with the wrong decorator transform, vscode's
    InstantiationService could not read the parameter metadata, and the pane
    died at construction (blank CRUSOR pane, Copilot chat took over). The
    emitter must parse the fork's real src/tsconfig.json chain and REFUSE to
    run without experimentalDecorators."""
    emitter = (FORK / "scripts" / "emit-crusorai-bundle.mjs").read_text(encoding="utf-8")
    assert "getParsedCommandLineOfConfigFile" in emitter, "options come from the project tsconfig, never hand-picked"
    assert "experimentalDecorators" in emitter and "refusing to run" in emitter
    assert "ModuleKind.ESNext" in emitter, "transpileModule under nodenext emits CommonJS the ESM workbench cannot load"
    assert "refusing to ship" in emitter, "emit-time assertion: DI-decorating sources must emit __param"
    browser = FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai" / "browser"
    bundle = (browser / "crusorAIViewPane.js").read_text(encoding="utf-8")
    assert "__param(" in bundle, "legacy DI decorator emit (design:paramtypes metadata) missing from the shipped pane"
    import re as _re
    assert _re.search(r"^import \{? ?", bundle, _re.M), "shipped pane must be an ES module (line-anchored import statements)"
    for js in browser.glob("*.js"):
        assert "require(" not in js.read_text(encoding="utf-8"), f"{js.name} regressed to CommonJS"


def test_bundle_import_audit_script_is_tracked_and_green_shape():
    """The audit proves every named import in the shipped bundle resolves to
    a runtime export (ESM named-import failures kill the contribution chain
    at instantiation)."""
    audit = (FORK / "scripts" / "audit-crusorai-bundle.mjs").read_text(encoding="utf-8")
    assert "DEAD BINDING" in audit and "AUDIT OK" in audit
    assert "path.join(FORK, 'out')" in audit, "cross-slice targets must resolve out/ -> src/ (only the crusorai slice is compiled here)"


def test_plan_card_is_a_desktop_status_section_disclosure():
    """Field 2026-09-11 ("Dropdown menu needed for plan card"; the previous
    round was REVERTED for porting hermes' TUI TodoPanel instead of the
    desktop app — the owner's law: ALWAYS see the desktop UI). The plan body
    is the desktop status-stack chrome, verbatim: chevron-right caret
    rotating 90deg open, the `checklist` codicon, the en.ts label
    `Tasks ${done}/${total}`, the todo group expanded BY DEFAULT
    (defaultCollapse = type !== 'todo'), a header spinner while an item is
    in_progress (hidden when open), and the user's toggle survives
    re-renders (openPlanLists)."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "crusorai-plan-details" in renderer
    assert "icon('chevron-right')" in renderer      # DisclosureCaret glyph
    assert "icon('checklist')" in renderer          # GROUP_ICON.todo
    assert "`Tasks ${done}/${rows.length}`" in renderer  # i18n/en.ts todos()
    assert "!openPlanLists.has(tool.id)" in renderer     # expanded by default
    assert "crusorai-plan-spinner" in renderer            # running indicator
    css = _text("browser", "media", "crusorAI.css")
    assert "transition: transform 150ms" in css
    assert ".crusorai-plan-details[open] > .crusorai-plan-head .crusorai-plan-caret { transform: rotate(90deg); }" in css
    assert ".crusorai-plan-details[open] > .crusorai-plan-head .crusorai-plan-spinner { display: none; }" in css
    bundle = (FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "crusorAIRenderer.js").read_text(encoding="utf-8")
    assert "crusorai-plan-details" in bundle and "Tasks ${done}/${rows.length}" in bundle


def test_ui_stamp_bumped_for_the_plan_disclosure_round():
    """The freshness stamp bumps with EVERY workbench UI round — a stale
    out/ shows an older date on the chip (see CRUSORAI_UI_STAMP)."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "CRUSORAI_UI_STAMP = '2026-10-17-14'" in renderer


def test_plan_card_renders_a_task_list_never_arg_json():
    """Field 2026-09-10 ("plan is in json"): plan_update/todo_list resolved
    the generic family and the card body painted the raw {"steps":[...]}
    argument JSON. The catalog carries a 'plan' family whose body ports
    hermes' status-row todo rows (glyph + description), fed from the WRITTEN
    list (tool result) with call args as fallback."""
    catalog = _text("common", "crusorAIToolCatalog.ts")
    assert "plan_update: tool('Plan Update', 'plan'" in catalog
    assert "todo_list: tool('Todo list', 'plan'" in catalog
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "function planListBody" in renderer
    assert "crusorai-plan-row is-" in renderer
    for glyph in ("pass-filled", "circle-slash"):  # hermes status-row glyphs
        assert glyph in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-plan-row.is-pending .crusorai-plan-glyph::before" in css
    assert "dashed" in css
    bundle = (FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "crusorAIRenderer.js").read_text(encoding="utf-8")
    assert "crusorai-plan-row" in bundle, "the shipped panel carries the plan card"


def test_grace_summary_collapses_the_json_tool_call_dialect():
    """Field 2026-09-10: with the toolless summary request, the model kept
    "calling" tools TEXTUALLY — the answer carried raw
    {"action": "terminal", ...} JSON painted into the transcript. The raw
    markup collapse now catches the JSON dialect too, not just XML-ish tags."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert '\"action\"' in renderer or '\\"action\\\"' in renderer or '"action"' in renderer
    assert "RAW_TOOL_MARKUP" in renderer
    # the regex alternative for the JSON dialect
    import re as _re
    m = _re.search(r"RAW_TOOL_MARKUP = (.+);", renderer)
    assert m and '"(?:action|tool|tool_call|function)"' in m.group(1)


def test_bundle_freshness_is_a_source_content_hash_not_ancestry():
    """Field 2026-09-10: the BUILD_INFO commit had captured a rolled-back
    HEAD and the ancestor check passed by luck — ancestry proves "not from
    the future", never "built from THESE sources". The emitter now writes a
    sha256 over the exact contrib sources (+ the emitter itself), and the
    engine recomputes it from the pulled tree: match = current, mismatch =
    STALE. Both recipes must agree byte-for-byte (rel POSIX paths in
    codepoint order, rel + NUL + bytes + NUL, emitter last)."""
    emitter = (FORK / "scripts" / "emit-crusorai-bundle.mjs").read_text(encoding="utf-8")
    assert "SOURCES_HASH" in emitter and "createHash" in emitter
    assert "sort()" in emitter and "localeCompare" not in emitter, "codepoint order, not locale"
    shipped = (FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "SOURCES_HASH")
    assert shipped.exists() and len(shipped.read_text(encoding="utf-8").strip()) == 64
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "SOURCES_HASH" in bridge and "_sources_hash" in bridge
    assert "matches the pulled " in bridge and "sha256" in bridge
    # hashlib.update() returns None — the Python recipe must not chain it
    assert ").update(" not in bridge.split("def _sources_hash")[1].split("return h.hexdigest")[0]


def test_bundle_hash_is_stable_under_windows_crlf_checkout():
    """Field 2026-09-10: the owner's Windows checkout kept CRLF copies of
    files a pull never rewrote (eol=lf applies only when git actually
    (re)writes a file), so the raw-byte hash differed per machine (sandbox
    ac7bedac… != owner 6ebfe76a…) and the exact-freshness banner cried STALE
    on a current panel. Both recipes now normalize CRLF -> LF at the byte
    level before hashing: checkout line-ending state cannot flip the
    verdict; content still can."""
    emitter = (FORK / "scripts" / "emit-crusorai-bundle.mjs").read_text(encoding="utf-8")
    assert "normalizeEol" in emitter and "latin1" in emitter
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    recipe = bridge.split("def _sources_hash")[1].split("return h.hexdigest")[0]
    assert 'replace(b"\\r\\n", b"\\n")' in recipe


def test_hash_recipe_identical_under_crlf(tmp_path):
    """The normalization recipe is checkout-independent: CRLF-ifying every
    file (what an autocrlf checkout produces) leaves the hash unchanged —
    including for binary assets, where a utf8 decode would corrupt bytes."""
    import hashlib

    tree = tmp_path / "contrib"
    (tree / "browser").mkdir(parents=True)
    # repo blobs are pure-LF text (checked: no \r anywhere in the contrib
    # tree) plus binary assets; a Windows checkout may flip every LF to
    # CRLF on disk. The escaped "\\n" inside the string must survive too.
    (tree / "browser" / "a.ts").write_bytes(b"export const x = 1;\nconst s = \"a\\nb\";\n")
    (tree / "browser" / "b.css").write_bytes(b".a { color: red }\n.b {}\n")
    (tree / "browser" / "logo.ttf").write_bytes(b"\x00\x01\r\n\x02\x00\xff")

    def recipe(src_root):
        h = hashlib.sha256()
        for f in sorted(f for f in src_root.rglob("*") if f.is_file()):
            h.update(f.relative_to(src_root).as_posix().encode("utf-8"))
            h.update(b"\0")
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))
            h.update(b"\0")
        return h.hexdigest()

    lf = recipe(tree)
    # A real autocrlf checkout converts only files git deems TEXT (NUL-byte
    # heuristic): binaries like the codicon .ttf keep their blob bytes —
    # including any 0d0a they already contain — and BOTH recipes normalize
    # those bytes identically, so they stay pinned.
    for f in tree.rglob("*"):
        if f.is_file() and f.suffix in {".ts", ".css"}:
            f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert recipe(tree) == lf


def _exec_engine_sources_hash():
    """Extract the engine's nested _sources_hash from the bridge source and
    exec it as a standalone function(src_dir, root) — the REAL recipe under
    test, not a hand-copied twin. The raw lines are already uniformly
    indented (16/20 spaces), which is a legal body for a def at column 0:
    no dedent, just keep them. The body closes over the freshness check's
    `root` (it derives vscode_root from it), so root is a parameter here."""
    import hashlib

    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    raw = bridge.split("def _sources_hash")[1].split("\n", 1)[1]
    body = raw.split("return h.hexdigest()")[0] + "return h.hexdigest()\n"
    namespace = {"hashlib": hashlib}
    exec("def _sources_hash(src_dir, root):\n" + body, namespace)
    return namespace["_sources_hash"]


def test_hash_feed_order_is_codepoint_strings_not_path_objects(tmp_path):
    """Field 2026-09-10 (owner aa68b244… != shipped f5b8d974… on every boot
    over a pristine tree): the engine used to sort Path OBJECTS, and on
    Windows PurePath comparison is case-insensitive (os.path.normcase) —
    so `crusorAI…` vs `crusorai…` siblings fed the hash in a different order
    than the JS emitter's codepoint string sort used at emit time. A
    byte-identical checkout hashed to a different digest and the STALE
    banner fired on a current panel; invisible on Linux, where both sorts
    coincide. The recipe must sort the rel STRINGS (codepoint), agreeing
    with the emitter by construction: two name families that sort
    differently under casefolding / parts-comparison pin the rule."""
    import hashlib

    vscode_root = tmp_path / "desktop" / "vscode"
    contrib = vscode_root / "src" / "vs" / "workbench" / "contrib" / "crusorai"
    (contrib / "browser" / "crusorai").mkdir(parents=True)
    (vscode_root / "scripts").mkdir()
    # casefold flips this pair (codepoint: B < a; casefold: a < b)
    (contrib / "B.txt").write_bytes(b"B\n")
    (contrib / "a.txt").write_bytes(b"a\n")
    # a file named like its sibling directory flips parts-vs-string order
    # (parts: crusorai/ first; strings: crusorai.ts first, '.' < '/')
    (contrib / "browser" / "crusorai.ts").write_bytes(b"x\n")
    (contrib / "browser" / "crusorai" / "inner.ts").write_bytes(b"y\n")
    (vscode_root / "scripts" / "emit-crusorai-bundle.mjs").write_bytes(b"// emitter\n")

    got = _exec_engine_sources_hash()(contrib, tmp_path)

    h = hashlib.sha256()
    prefix = "src/vs/workbench/contrib/crusorai/"
    rels = sorted(
        [prefix + "B.txt", prefix + "a.txt",
         prefix + "browser/crusorai.ts", prefix + "browser/crusorai/inner.ts"]
    )
    for rel in rels:
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update((vscode_root / rel).read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    h.update(b"scripts/emit-crusorai-bundle.mjs")
    h.update(b"\0")
    h.update(
        (vscode_root / "scripts" / "emit-crusorai-bundle.mjs")
        .read_bytes()
        .replace(b"\r\n", b"\n")
    )
    h.update(b"\0")
    assert got == h.hexdigest()


def test_engine_hash_matches_the_shipped_panel_on_this_repo():
    """End-to-end on the real tree: the engine's recompute equals the
    shipped SOURCES_HASH — the banner reads current here, and on the
    owner's Windows checkout too (field 2026-09-10: the very hash pair
    f5b8d974… / aa68b244… that the Path-sort bug produced is now impossible;
    whatever ships later must keep both recipes moving together)."""
    got = _exec_engine_sources_hash()(CRUSOR, ROOT)
    shipped = (
        FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "SOURCES_HASH"
    ).read_text(encoding="utf-8").strip()
    assert got == shipped


def test_token_budget_default_leaves_iterations_as_the_binding_cap():
    """Field 2026-09-10: the 120k default cut a healthy turn at iteration
    8/30 (receipt: tokens 137,198/120,000, tripped: tokens) — real billing
    runs 2-3x the chars/4 request estimate once tool schemas and long
    completions count. The default now lets the iteration budget bind
    first; AGENT_TOKEN_BUDGET=0 still disables."""
    import os

    from src.graphs.budget import _token_budget

    saved = os.environ.pop("AGENT_TOKEN_BUDGET", None)
    try:
        assert _token_budget() == 600_000
    finally:
        if saved is not None:
            os.environ["AGENT_TOKEN_BUDGET"] = saved


def test_tool_batch_pairing_invariant_fabricates_missing_results():
    """Field 2026-09-10: a write batch returned ZERO ToolMessages for a
    non-empty tool_calls list (log: "0 tool result(s) ready") while the UI
    card showed an error — the graph flowed on unpaired calls. The
    _with_repaired choke point now detects the miss, logs PAIRING BUG, and
    fabricates one paired error per missing call (hermes' pairing law)."""
    graph = (ROOT / "src" / "graphs" / "chat_graph.py").read_text(encoding="utf-8")
    assert "PAIRING BUG" in graph
    assert "did NOT verifiably execute" in graph


def test_git_bash_paths_reveal_to_real_windows_drives():
    """Field 2026-09-10: the model works in the bash shell, so tool args and
    changed-file rows carry `/d/TestCrusorAI/...` — URI.file() read that as a
    rootless path and the owner's click died on "The editor could not be
    opened because the file was not found" while the file existed (explorer
    opened it fine). resourceUri converts the git-bash drive to a real
    Windows drive URI before anything else sniffs it."""
    service = _text("browser", "crusorAIRendererService.ts")
    assert "gitBash" in service and "Git-bash drive notation" in service
    bundle = (FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "crusorAIRendererService.js").read_text(encoding="utf-8")
    assert "toUpperCase" in bundle, "shipped service converts /d/ -> D:/"


def test_write_receipts_carry_exact_line_counts_for_the_card():
    """Field 2026-09-10: write_file returned a bare "File written: <path>" —
    nothing to count — and the changed-files card showed +0 -0 for REAL
    writes. write_file now returns edit_file's shape (counts line + bounded
    diff preview) and deriveChangedFiles parses the exact counts line first
    (the preview is capped; the counts must not be)."""
    tools = (ROOT / "src" / "tools" / "file_tools.py").read_text(encoding="utf-8")
    assert "lines added: {added}, removed: {removed}" in tools
    fmt = _text("browser", "crusoraiCardFormat.ts")
    assert "lines added:" in fmt and "removed:" in fmt


def test_todo_items_require_hermes_fields_and_rows_fall_back_to_ids():
    """Field 2026-09-10 ("todo list 🤯"): with untyped dict items the model
    sent id-only status patches on the REPLACE path and the store validated
    them into "(no description)" rows. hermes TODO_SCHEMA requires
    ["id", "content", "status"] per item — crusor's todo_list now carries the
    same required fields (pydantic args_schema), and the card renders an
    id-only row as "Item <id>", never the raw placeholder."""
    import json as _json

    from src.tools.todo_tool import todo_list

    schema = todo_list.args_schema.model_json_schema()
    item = schema["$defs"]["_TodoItem"]
    assert sorted(item["required"]) == ["content", "id", "status"]
    try:
        todo_list.invoke({"todos": [{"id": "x", "status": "pending"}]})
        raise SystemExit("id-only patch must be rejected")
    except Exception:
        pass  # pydantic ValidationError is the fix working

    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "Item ${id}" in renderer
    code_only = "\n".join(
        line for line in renderer.splitlines() if not line.strip().startswith("//")
    )
    assert '(no description)' not in code_only.split("function planStepsFrom")[1].split("function terminalBody")[0]


def test_scaffold_card_shows_the_calls_own_fields_not_inventions():
    """Field 2026-09-10: the scaffold/code family body hardcoded
    RUNTIME "Python 3.14" on a Next.js scaffolding call — invented text.
    The card shows the call's own location/template fields plus the honest
    state, nothing else."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "Python 3.14" not in renderer
    assert "toolOutputBox(boundedText(detail, 4000))" in renderer
    assert "scaffoldFields" not in renderer


def test_shipped_manifest_lets_the_engine_name_stale_files():
    """Field 2026-09-10 (second STALE report): the owner's checkout still
    hashed differently from the sandbox for an on-disk reason the aggregate
    could not name. The emitter now ships a per-file manifest next to
    SOURCES_HASH (diagnosis only — the aggregate stays the verdict), and the
    engine's STALE branch diffs it and NAMES modified/missing/extra files
    with the restore command."""
    emitter = (FORK / "scripts" / "emit-crusorai-bundle.mjs").read_text(encoding="utf-8")
    assert "SOURCES_MANIFEST.json" in emitter
    assert "sourcesHash" in emitter and "normalizeEol" in emitter
    bridge = (ROOT / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "SOURCES_MANIFEST.json" in bridge
    assert "STALE diagnosis (per-file manifest)" in bridge
    assert "extra on disk" in bridge and "git checkout -- <file>" in bridge
    manifest = (FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai"
                / "browser" / "SOURCES_MANIFEST.json")
    assert manifest.exists()
    parsed = json.loads(manifest.read_text(encoding="utf-8"))
    assert parsed.get("sourcesHash") == (FORK / "out" / "vs" / "workbench"
                                         / "contrib" / "crusorai" / "browser"
                                         / "SOURCES_HASH").read_text(encoding="utf-8").strip()
    assert isinstance(parsed.get("files"), dict) and parsed["files"]


def test_bundle_emitter_copies_the_media_the_app_loads_by_url():
    """Field 2026-09-27 (owner: "preview is created but website is always
    not launched properly"): the app boots its preview window from
    FileAccess.asBrowserUri('.../browser/media/crusor-preview/index.html') —
    a path under `out/`, the tree the app actually runs from. The scoped
    emitter copied ONLY `.ts`, so that document existed in src/ and NOWHERE
    in out/: the button opened a window whose frame pointed at a missing
    file, the site never rendered, and every check stayed green — the
    sources hash covers media SOURCES (it hashed the src file happily), the
    emit tests only grepped emitted JS, and out/ is gitignored so no diff
    showed the hole. The emitter must copy every non-.ts file VERBATIM and
    refuse to ship when one fails to land."""
    emitter = (FORK / "scripts" / "emit-crusorai-bundle.mjs").read_text(encoding="utf-8")
    assert "copyMedia" in emitter and "media file(s)" in emitter
    assert "refusing to ship" in emitter, "a media gap must fail the emitter, never ship quietly"
    assert "fs.writeFileSync(out, bytes)" in emitter, "verbatim bytes — a text round-trip corrupts fonts"
    assert "fs.readFileSync(out).equals(bytes)" in emitter, "verify the copy landed byte-identical"
    # The two trees the app frames by URL must exist as sources to copy.
    for rel in ("browser/media/crusor-preview/index.html",
                "browser/media/crusorai-spa/index.html"):
        assert (CRUSOR / rel).is_file(), rel
    # The preview window's boot files also travel INSIDE the committed
    # bundle (the app updates by git pull), so out/ must carry them too.
    preview_src = CRUSOR / "browser" / "media" / "crusor-preview"
    preview_out = (FORK / "out" / "vs" / "workbench" / "contrib" / "crusorai"
                   / "browser" / "media" / "crusor-preview")
    for rel in ("index.html", "preview.js", "preview.css", "overlay/crusor-preview-overlay.js"):
        src = (preview_src / rel).read_bytes().replace(b"\r\n", b"\n")
        out = (preview_out / rel).read_bytes().replace(b"\r\n", b"\n")
        assert src == out, f"{rel} in out/ is not the source the window loads"


def test_pipeline_audit_fails_loudly_when_out_is_incomplete():
    """The audit NAMED the missing media all along — 543 of 587 sources had
    no out/ counterpart, printed line by line — and still exited 0, so the
    blank preview shipped while the audit looked like a pass. An audit that
    reports an incomplete app tree must fail."""
    audit = (FORK / "scripts" / "audit-preview-pipeline.mjs").read_text(encoding="utf-8")
    assert "process.exitCode = 1" in audit, "reporting without a verdict is what hid this"
    assert "is not a complete image of src/" in audit
    assert "emit-crusorai-bundle.mjs" in audit, "name the one-command fix in the failure text"
    assert "missingMedia" in audit, "call out the media the app loads by URL, not just any file"


def test_a2ui_surface_manager_is_catalog_bounded_and_fail_soft():
    """Phase 2 (AGUI_A2UI_PLAN §4): the native A2UI surface manager renders a
    FIXED catalog only — unknown ops/components drop + log, never throw, and
    the text-only boundary (no innerHTML) holds in the new module too."""
    surface = _text("browser", "crusorA2UISurface.ts")
    renderer = _text("browser", "crusorAIRenderer.ts")
    for component in (
        "Card", "Column", "Row", "Text", "Diff", "TerminalOutput",
        "PlanList", "Receipt", "QuestionForm", "ApprovalBar", "Image", "Button",
    ):
        assert f"'{component}'" in surface, f"Catalog v1 missing {component}"
    assert "MAX_A2UI_OPS" in surface and "MAX_A2UI_COMPONENTS" in surface
    assert "unknown component" in surface and "A2UI dropped" in surface
    assert ".innerHTML" not in surface
    assert "deleteSurface" in surface and "updateDataModel" in surface
    assert "resolveA2UIPointer" in surface, "data-model {path} binding is A2UI semantics"
    # Renderer: the envelope is tried BEFORE family dispatch, so a result
    # carrying a2ui_operations never falls through to prose/JSON painting.
    assert "renderA2UIToolBody(tool.result" in renderer
    assert renderer.index("renderA2UIToolBody(tool.result") < renderer.index("presentation.family === 'terminal'")


def test_a2ui_engine_task_schema_uses_only_catalog_v1_components():
    """The engine's one shipped A2UI schema (display_crusor_task) must name
    only components the native Catalog v1 can render — otherwise the generic
    path drops pieces of the task card silently."""
    surface = _text("browser", "crusorA2UISurface.ts")
    catalog = set(re.findall(r"'([A-Z][A-Za-z]+)'", surface.split("CRUSOR_A2UI_CATALOG_V1")[1].split("];")[0]))
    schema = json.loads((ROOT / "src" / "a2ui_schemas" / "crusor_task_schema.json").read_text(encoding="utf-8"))
    used = {component["component"] for component in schema}
    assert used <= catalog, f"engine schema names components outside Catalog v1: {used - catalog}"


def test_a2ui_envelope_rides_tool_results_without_protocol_bump():
    """The envelope is documentation + types on the existing tool_call_end
    result — Bridge Protocol v2 itself does not move."""
    protocol_ts = _text("common", "crusorAIProtocol.ts")
    assert "CrusorA2UIOperation" in protocol_ts and "a2ui_operations" in protocol_ts
    protocol_py = (ROOT / "src" / "bridge" / "protocol.py").read_text(encoding="utf-8")
    assert "PROTOCOL_VERSION = 2" in protocol_py


def test_opencode_shell_box_is_captured_and_wired_to_v2_terminal_events():
    """Founder direction 2026-10-15: do not reinvent the box - OpenCode's
    bash-output UI is captured verbatim under third-party/ (MIT, provenance
    in its README) and its STRUCTURE is wired into the native terminal body
    on Bridge v2 events. The live-output streaming gap is documented, never
    faked."""
    capture = ROOT / "third-party" / "opencode"
    assert (capture / "LICENSE").is_file()
    assert (capture / "session-ui" / "components" / "message-part.css").is_file()
    assert (capture / "session-ui" / "tools" / "shell-output.ts").is_file()
    assert "tool_output" in (capture / "README.md").read_text(encoding="utf-8")
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "crusorai-bash-output" in renderer and "crusorai-bash-result" in renderer
    assert "copyButton(command, host)" in renderer, "copy lives inside the box, as captured"
    css = _text("browser", "media", "crusorAI.css")
    assert '[data-slot="bash-scroll"]' in css and "max-height: 240px" in css
    # Founder 2026-10-15 ("extract codes as it is") supersedes the old
    # interpretive rule: --v2-* now ships, but ONLY behind the token bridge
    # that maps every one to a live workbench var.
    assert "--v2-text-text-base: var(--vscode-foreground)" in css, "their tokens ship bridged, never raw"


def test_tool_output_frame_accumulates_into_the_running_terminal_card():
    """Live shell output (tool_output frame) appends to the running tool's
    result with a 64KB tail cap; tool_call_end still replaces the preview
    with the durable result."""
    service = _text("browser", "crusorAIRendererService.ts")
    assert "frame.type === 'tool_output'" in service
    assert "slice(-65_536)" in service
    protocol = _text("common", "crusorAIProtocol.ts")
    assert "type: 'tool_output'" in protocol


def test_streaming_output_patches_the_box_not_the_transcript():
    """OpenCode streaming feel: tool_output growth patches the running
    card's <pre> in place (tail-follow per tool, user scroll-up respected);
    only shape changes take the full paint."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "patchLiveToolOutputs" in renderer
    assert "data-tool-output-for" in renderer and "toolOutputFor" in renderer
    assert "bashFollow" in renderer, "follow choice survives repaints, keyed by tool id"
    assert "stableSignature" in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert "crusorai-submessage-in" in css, "their ShellSubmessage entrance, ported"


def test_whole_ui_layer_boxes_are_present_and_data_driven():
    """Whole UI layer (founder 2026-10-15): every box family from the
    captured OpenCode layer has a native body wired to real v2 data -
    edit-content around diffs, the LSP diagnostics ledger parsed from the
    tools' own <diagnostics> block, an earned-red error card on failure,
    todos spacing - colours only from the workbench theme."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "crusorai-edit-content" in renderer and "crusorai-edit-content" in css
    assert "diagnosticsBox" in renderer and "<diagnostics" in renderer
    assert "errorCard" in renderer and "crusorai-error-card" in css
    assert "crusorai-todos" in renderer


def test_more_boxes_cover_skills_hub_scaffolds_and_targets():
    """More boxes (founder 2026-10-15, OpenCode path): the canonical tools
    that still fell through to generic cards — skills/hub, the non-web
    scaffolds, and the target/device surface — resolve named families with
    OpenCode-anatomy bodies (loaded-item rows for skills, receipt + inline
    evidence for targets), and the boxes adapt to the RIGHT PANEL via
    container queries on the render root, not viewport media queries."""
    catalog = _text("common", "crusorAIToolCatalog.ts")
    for name in ("skills_list", "skill_view", "skill_manage", "hub_search",
                 "hub_install", "hub_update", "hub_list", "hub_remove"):
        assert f"{name}: tool(" in catalog and "'skill'" in catalog, name
    for name in ("scaffold_flutter", "scaffold_react_native", "scaffold_tauri"):
        assert f"{name}: tool(" in catalog, name
    for name in ("detect_targets", "check_target_toolchains", "build_target",
                 "verify_target_app", "device_action", "device_screenshot",
                 "device_ui", "device_logs", "device_preview"):
        assert f"{name}: tool(" in catalog, name
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "function skillBody" in renderer and "tool-loaded-item" in renderer
    assert "function targetBody" in renderer and "crusorai-device-screenshot" in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert "container-name: crusorai-agent-panel" in css
    assert "@container crusorai-agent-panel (max-width: 420px)" in css
    assert ".crusorai-loaded-item" in css


def test_settled_thought_rows_collapse_and_targets_stay_honest():
    """Field 2026-10-15 (founder screenshots): settled Thought rows painted
    the model's monologue expanded, 'List files .' echoed a meaningless
    target, and the think envelope's boilerplate trailer showed as prose.
    Disclosure persists only on the user's own click; trivial targets are
    dropped; the trailer is stripped."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "summary.addEventListener('click'" in renderer
    assert "details.addEventListener('toggle', () => details.open ? openTools.add" not in renderer
    assert "trivialTargets" in renderer and "'./'" in renderer
    assert "Proceeding with the approach above" in renderer  # strip pattern


def test_main_chat_transcript_follows_opencode_message_anatomy():
    """Main chat like OpenCode (founder 2026-10-15: 'i am not seeing ur
    edits'): the transcript itself — not just the tool boxes — ports the
    captured session-ui anatomy: borderless right-hugging user bubble,
    reasoning-part hooks with settled thoughts resting closed, BasicTool
    13px medium-title rows at full opacity (no scaffold fade)."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "function userMessage" in renderer
    assert "user-message-text" in renderer
    assert "dataset.component = 'reasoning-part'" in renderer
    assert "details.open = !closedTools.has(key) && (live || openTools.has(key))" in renderer
    assert "summary.addEventListener('click'" in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert "OpenCode main-chat layer" in css
    assert "max-width: min(82%, 64ch)" in css
    assert "color-mix(in srgb, var(--vscode-foreground) 9%, var(--vscode-editor-background))" in css, "bubble stays raised on the forced-black theme"
    assert ".crusorai-assistant-message [data-conversation-scaffold] { opacity: 1; }" in css


def test_empty_session_is_the_opencode_mark_and_dock():
    """Empty session like OpenCode (founder 2026-10-15): no starter cards,
    no explainer copy — the centred mark with the prompt dock as hero in
    the Agent pane, docking to the bottom once a turn exists."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "function isEmptySession" in renderer
    assert "crusorai-empty-hero" in renderer and "crusorai-empty-wordmark" in renderer
    assert "STARTER_PROMPTS" not in renderer and "crusorai-starter" not in renderer
    assert "shell.classList.add('is-empty')" in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-agent-shell.is-empty .crusorai-composer { margin-bottom: auto; }" in css
    assert "crusorai-starter" not in css


def test_streamed_rendering_replaces_the_breathing_ui():
    """OpenCode streamed rendering (founder 2026-10-15: 'delete this
    breathing ui completely and implement what opencode's completely'):
    before the first streamed part the turn shows only the bare shimmering
    Thinking word; reasoning/tool/text parts stream in as they arrive
    (no tail cursor, no spinner rows, no wait timers), tools animate in
    themselves, and CrusorAI's breathing extras — composer border pulse,
    breathing edge, the 'Asking <model>' row, anatomy/'What the model
    sees' and elapsed timers — are deleted, not hidden."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    # streamed wait: the shimmering word, then the parts carry themselves
    assert "model.parts[model.parts.length - 1]" in renderer
    assert "if (!liveTool && lastPart?.kind !== 'text' && !model.assistantText) {" in renderer
    assert "response.append(textPart(part.text," in renderer, (
        "answer text streams token-by-token into the same node")
    # tools render like OpenCode's: icon + label + live body, no shimmer title
    assert "const titleSpan = element('strong', isPending" in renderer
    assert "renderToolIcon(" in renderer or "renderToolIcon(name)" in renderer
    # the breathing apparatus is gone everywhere
    for gone in ("What the model sees —", "items are applied before your next prompt", "How many messages the model applies after edits",
                 "formatWaitClock", "crusorai-breathing-edge", "crusorai-scaffold-crusor",
                 "crusorai-activity-dot", "crusorai-thinking-timer"):
        assert gone not in renderer, gone
    assert "footer.classList.add('is-running')" not in renderer, "no composer breathing state"
    for gone_css in ("crusorai-composer-breathe", "crusorai-breathing-edge", "crusorai-activity-dot",
                     'session-turn-content"] > :last-child::after'):
        assert gone_css not in css, gone_css
    import re as _re2
    assert not _re2.search(r"['`]Asking ", renderer), "the Asking row string is gone (comments may mention it)"
    assert "assistantWaitParts" not in renderer


def test_opencode_session_ui_css_is_extracted_verbatim_and_driven():
    """Extract as-is (founder 2026-10-15: 'extract codes as it is from
    opencode'): their message-part.css + basic-tool.css ship IN our
    stylesheet rule-for-rule (only selector scoping + a --v2-* token
    bridge), and the transcript DOM emits their data-component/data-slot
    anatomy so the extracted rules are what actually paint."""
    css = _text("browser", "media", "crusorAI.css")
    assert "EXTRACTED VERBATIM" in css
    assert "--v2-text-text-base: var(--vscode-foreground)" in css
    assert "--v2-background-bg-layer-02:" in css
    assert ".crusorai-render-root [data-component=\"assistant-message\"]" in css
    assert "[data-slot=\"basic-tool-tool-title\"]" in css
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "dataset.component = 'text-part'" in renderer
    assert "dataset.slot = 'basic-tool-tool-trigger-content'" in renderer
    assert "dataset.slot = 'collapsible-content'" in renderer
    assert "dataset.component = 'markdown'" in renderer


def test_thinking_shimmer_survives_the_verbatim_layer():
    """The bare Thinking word must actually sweep (founder 2026-10-15,
    third breathing correction): the extracted OpenCode title rule
    outranks .crusorai-shimmer and silently killed the live-label sweep —
    the glue after the verbatim block restores it on the thinking word
    itself (OpenCode's highlight through the word). The composer frame
    does NOT breathe — that was CrusorAI's, not OpenCode's."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "footer.classList.add('is-running')" not in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-composer.is-running .crusorai-composer-box" not in css
    assert "@keyframes crusorai-composer-breathe" not in css
    marker = css.index("EXTRACTED VERBATIM")
    shimmer_fix = css.index(".crusorai-shimmer.crusorai-thinking-word")
    assert shimmer_fix > marker, "the shimmer restore must load after the verbatim block"


def test_rendered_response_matches_the_reference_photos():
    """Founder reference photos 2026-10-15 (OpenCode rendered response):
    Thinking is the bare muted word, a settled tool is a muted label with
    the caret hugging it ('Shell ⌄'), the dock is a 12px box and Stop is
    a filled square tile. (The shell box's command line was pinned to
    '$ command' from the photos; the captured OpenCode source renders
    the raw command with no '$' — source wins, founder 2026-10-15.)"""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "crusorai-thinking-word" in renderer
    assert "`$ ${command}`" not in renderer
    assert "icon(running ? 'debug-stop' : 'arrow-up')" in renderer
    assert "Ask anything, / for commands, @ for context..." in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-render-root .crusorai-composer-box { border-radius: 12px; }" in css
    assert ".crusorai-send-button.crusorai-send-stop" in css


def test_streamed_wait_is_the_shimmering_word_and_bubbles_are_pills():
    """OpenCode streamed wait + bubble regression (founder 2026-10-15):
    before streamed parts arrive the wait is the bare shimmering Thinking
    word (no spinner row, no 'Asking <model>', no timer), and the user
    bubble is the text-slot pill — the full-width column must never
    paint as a band again."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "element('strong', 'crusorai-shimmer crusorai-thinking-word', 'Thinking')" in renderer
    import re as _re2
    assert not _re2.search(r"['`]Asking ", renderer), "the Asking row string is gone (comments may mention it)"
    assert "assistantWaitParts" not in renderer
    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-render-root .crusorai-user-message { background: transparent;" in css


def test_tool_cards_follow_opencode_basictool():
    """Tool cards (founder 2026-10-15: 'tool cards seeing opencode', all
    cards): header = title + subtitle + args chips (title shimmers while
    pending, like their TextShimmer), body = the tool's own output in the
    scrollable tool-output region. CrusorAI's invented meta tables
    (PATH/LINES/ENCODING, Query/Scope/Matches, URL/Status...) are gone."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "function toolOutputBox" in renderer
    assert "box.dataset.component = 'tool-output'" in renderer
    assert "box.dataset.scrollable = ''" in renderer
    assert "function toolArgsChips" in renderer, "OpenCode GenericTool.args chips"
    assert "presentation.family === 'subagent' ? [] : toolArgsChips(tool)" in renderer
    assert "isPending ? 'crusorai-shimmer' : undefined" in renderer, (
        "pending tool title shimmers (their TextShimmer active=pending)")
    for gone in ("toolFields(", "['Path', target], ['Lines'", "'Encoding', 'UTF-8'",
                 "['Query', target], ['Scope'", "['URL', target], ['Status'",
                 "Sessions', '2'"):
        assert gone not in renderer, gone


def test_read_and_search_rows_are_single_line_info_rows():
    """Read rows stay single-line info rows (founder 2026-10-15: 'Read
    tool card doesn't need a drop down menu, just show #L1-50 info'),
    and so do webfetch/web_extract (upstream hideDetails). Glob/Grep
    changed law on 2026-10-17: founder ordered the OpenCode folder
    implemented exactly (processes the only carve-out), and upstream
    grep/glob are BasicTool cards — the same one line while closed,
    the matches openable inside. What is pinned here: read/web are
    lines; search is a card whose body the search branch paints."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "const INLINE_INFO_TOOLS = new Set(['read_file', 'web_fetch', 'web_extract']);" in renderer
    assert "function toolInlineInfo" in renderer
    assert "`#L${start}-${limit !== undefined ? start + limit - 1 : start}`" in renderer
    assert "`#L1-${lines}`" in renderer, "whole-file reads report the real line count"
    # inline rows return before any body is appended; non-inline rows
    # build (and measure) their body first, per the BasicTool law
    assert "if (!isInline) {" in renderer and "body = familyBody(tool, host, subAgents);" in renderer
    assert "bodyHasContent" in renderer
    inline_at = renderer.index("if (isInline) {")
    append_at = renderer.index("if (body && bodyHasContent) { details.append(body); }")
    assert inline_at < append_at, "inline rows must return before a body can be appended"
    assert "crusorai-tool-inline" in renderer and ".crusorai-tool-inline {" in css
    assert "!isInline && bodyHasContent ? icon('chevron-down') : undefined" in renderer, (
        "chevron whenever there is content to open — even mid-run, now "
        "that the founder's closed-until-clicked law lets the hand in")
    assert "allowOpenWhilePending" not in renderer, "the pending lock is retired"


def test_read_row_filename_is_a_clickable_file_chip():
    """Founder screenshots 2026-10-15: '#L1... SHOULD BE NEAR TO THE FILE',
    the path 'should be replaced with File icon and only File Name',
    clicking it opens that file. Refined the same day: REAL file icons
    from inside desktop/vscode (VS Code's getIconClasses + the Seti file
    icon theme, Explorer parity), NO visible button/pill, and the
    filename never larger than the tool title. So: the #L chip rides
    inside the title line next to the filename; a Read row's path is a
    FLAT link (theme file icon + basename, full path as tooltip) whose
    click opens the file via host.revealFile."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    service = _text("browser", "crusorAIRendererService.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "inlineInfo ? toolInfoChip(inlineInfo) : undefined" in renderer
    assert "crusorai-tool-file-link show-file-icons" in renderer
    assert "fileIcon(host, targetText)" in renderer
    assert "fileIconClasses?(resource: string)" in renderer, "host owns the workbench icon services"
    assert "getIconClasses(this.modelService, this.languageService" in service
    assert "host.revealFile(targetText)" in renderer
    assert "subtitle.title = targetText" in renderer, "full path survives as the tooltip"
    # No visible button: the pill anatomy is gone from both layers.
    assert "crusorai-tool-file-chip" not in renderer
    assert ".crusorai-tool-file-link {" in css
    assert ".crusorai-file-icon::before" in css, "theme CSS paints the icon under .show-file-icons"
    assert "crusorai-tool-file-chip" not in css


def test_terminal_matches_opencode_bash_output():
    """Founder screenshot 2026-10-15: 'terminal looks shit... read
    opencode'. The captured shell render (tool-renderer.tsx execute/
    shell + ConsoleOutput) is: header = title + command subtitle ONLY
    while collapsed; body = ONE bash-output box (hover copy, ONE 240px
    hidden-scrollbar scroll region, command block then muted result
    block, result only when output exists); success says NOTHING —
    no 'Passed · exit 0' footer. Our box previously carried the slots
    as classes only, so the extracted CSS never painted it and the old
    glue (a nested 4rem scroller, a '$ ' prefix, the footer) did."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    # Their DOM hooks, so the verbatim extracted block paints the box.
    for slot in ("bash-copy", "bash-scroll", "bash-pre", "bash-command", "bash-result"):
        assert f"dataset.slot = '{slot}'" in renderer, slot
    assert "scroll.dataset.scrollable = ''" in renderer
    assert "`$ ${command}`" not in renderer, "captured source shows the raw command"
    # Command subtitle only while collapsed; result only with output.
    assert "crusorai-shell-command" in renderer
    assert ".crusorai-tool-row[open] .crusorai-shell-command { display: none; }" in css
    assert "if (hasOutput) { codeEl.append(resultSpan); }" in renderer
    assert "trimmedOutput !== '{}'" in renderer, "an untouched result stringifies to {} — not output"
    # Never hand undefined to a native append(): it prints the word.
    assert "body.append(outputBox);" in renderer
    assert "if (showExit) {" in renderer
    # Success is silent; failure earns one quiet exit line.
    assert "`Exit code ${exit}`" in renderer
    assert "showExit" in renderer
    # One scroller only: the live <pre> is un-capped inside bash-scroll.
    assert ".crusorai-bash-result .crusorai-terminal-output { max-height: none" in css


def test_scrolling_hides_every_scrollbar_opencode_style():
    """Founder 2026-10-15: 'fix scrolling feature every where where ever
    scrolling is applicable becoz not nice — read opencode for that
    also'. OpenCode's doctrine (message-part.css): every scrollable
    region — tool-output, BashOutput, edit content, the transcript —
    scrolls with NO visible scrollbar. One late rule in our stylesheet
    retires every thin/default bar in the pane at once."""
    css = _text("browser", "media", "crusorAI.css")
    assert ".crusorai-render-root, .crusorai-render-root * { scrollbar-width: none; }" in css
    assert ".crusorai-render-root *::-webkit-scrollbar { display: none; }" in css
    doctrine = css.index("Scrolling, OpenCode doctrine")
    assert css.index(".crusorai-bash-result .crusorai-terminal-output") < doctrine
    assert doctrine > css.index("EXTRACTED VERBATIM"), "the doctrine block loads after the extracted block"


def test_edit_write_cards_and_verification_follow_opencode():
    """Founder 2026-10-15: 'next tool cards plz' — after Read/search and
    Terminal, the Edit/Write cards take OpenCode's FileTool anatomy and
    the verification family loses its invented checklist. From the
    captured tool-renderer.tsx (edit/write/patch + FileTool): header =
    title + file link (real icon, filename, click opens) with the
    counted DiffChanges +a/-r riding the header; body = the diff in
    edit-content, or the written content in write-content when a write
    carries no diff; diagnostics earned only. Verification previously
    painted hardcoded Typecheck/Browser-callback/Destination rows and
    a dead 'Open evidence' button — fake UI; the tool's real output
    is the body now."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "FILE_LINK_TOOLS = new Set(['read_file', 'edit_file', 'write_file', 'copy_file'])" in renderer
    assert "headerDiffStats ? diffChangesChip(headerDiffStats) : undefined" in renderer
    assert "function editDiffText" in renderer and "function editDiffStats" in renderer
    assert "writeBox.dataset.component = 'write-content'" in renderer
    assert ".crusorai-code-view {" in css
    # The invented verification checklist is gone, button included.
    assert "crusorai-tool-checks" not in renderer
    assert "Destination assertion" not in renderer
    assert "Open evidence" not in renderer


def test_user_close_sticks_and_scrolling_is_free():
    """Founder screenshots 2026-10-15 (build fa62d3bc), three defects:
    (1) 'why i can't close the dropdown menu — if did, reopens': the
    open state was `openTools.has(id) || shouldDefaultOpen`, so during
    a running turn every streaming repaint forced 'always'/'running'
    rows back open; the user's click was never recorded as a close.
    A mount-level closedTools memory now outranks every default in
    tool rows, run groups, and thought blocks — and since the
    founder's later closed-until-clicked law (2026-10-17), tool rows
    have no default-open at all: openTools (the user's hand) is the
    only opener. (2) 'write file is not
    like opencode, worst look': a write's all-'+' receipt diff painted
    as a solid green wall; OpenCode's write render shows the written
    content as a text view, never a diff. (3) 'i can't scroll freely':
    both follow-the-stream paths forced scrollTop to the floor while
    `model.running`, yanking the user out of up-scroll reading on every
    repaint; follow now engages only from near the bottom, and the
    diff body no longer nests its own scroller inside the card."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "const closedTools = new Set<string>();" in renderer
    assert "details.open = !closedTools.has(tool.id) && openTools.has(tool.id)" in renderer
    assert "shouldDefaultOpen" not in renderer, "tool cards stay closed until the user clicks"
    assert "details.open = !closedTools.has(key) && (runLive || openTools.has(key))" in renderer
    assert "closedTools.add(tool.id)" in renderer and "closedTools.delete(tool.id)" in renderer
    # Write = content text view; edits keep the diff.
    assert "const streamText" in renderer, "while streaming, the growing content is the view"
    # Free scrolling: no repaint may pin to the floor mid-run.
    assert "scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 120 || model.running" not in renderer
    assert "previousScroll.clientHeight < 120 || model.running" not in renderer
    assert "max-height: 12rem" not in css, "the diff body's nested scroller is gone"


def test_edit_and_write_bodies_are_real_viewers():
    """Founder screenshot 2026-10-15 (build 336dd18b): the Write body
    rendered as muted prose in the void — 'not like this, check
    opencode and fix both Edit and Write'. OpenCode's pipeline: write
    = a line-numbered code view of the written file (write-content >
    code; mono, editor foreground); edit = their diff viewer —
    old/new line-number gutters, sign, tinted added/removed rows with
    the code text in editor foreground. Ours now builds both
    natively over parseDiff's real oldNo/newNo."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "function codeView" in renderer
    assert "view.dataset.component = 'code'" in renderer
    assert "wrap.dataset.component = 'diff'" in renderer
    assert "crusorai-diff-gutter" in renderer
    assert ".crusorai-code-view {" in css and ".crusorai-code-gutter" in css
    assert ".crusorai-diff-row.is-add .crusorai-diff-gutter" in css
    assert "crusorai-write-content pre" not in css, "the prose <pre> is retired"


def test_file_accordion_matches_the_opencode_reference_render():
    """Founder reference image 2026-10-15 (OpenCode's own Edit card):
    'now output should look like this — will i see outputs like this?'
    Their render: outer Edit title + file + counts; inside, the file's
    OWN accordion box (real icon, directory/filename, DiffChanges,
    chevron) whose content is a diff viewer with ONE line-number
    gutter (removed = old number in red, added = new in green) in a
    capped frame with a floating scroll-down button. Founder
    2026-10-15 ('also add diff view +,- -->green,red color') added
    an explicit sign column beside the gutter. Structure must match
    exactly; token colours come from the editor theme via the host."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "function fileAccordion" in renderer
    assert "group.dataset.scope = 'apply-patch'" in renderer
    assert "name.dataset.slot = 'apply-patch-filename'" in renderer
    assert "body.append(fileAccordion(tool, host, view));" in renderer
    # One gutter, old number for removals, new for the rest. Founder
    # 2026-10-17: the sign LEADS the number ('+ 1', '- 1').
    assert "const no = line.kind === 'remove' ? line.oldNo : (line.newNo ?? line.oldNo);" in renderer
    assert "element('span', 'crusorai-diff-sign', sign)" in renderer
    sign_at = renderer.index("element('span', 'crusorai-diff-sign', sign)")
    gutter_at = renderer.index("element('span', 'crusorai-diff-gutter', no !== undefined ? String(no) : '')")
    assert sign_at < gutter_at, "diff rows read '+ 1 code', never '1 + code'"
    assert "line.kind === 'add' ? '+' : line.kind === 'remove' ? '-'" in renderer
    assert ".crusorai-diff-row.is-add .crusorai-diff-sign { color: var(--crusorai-diff-add-foreground); }" in css
    assert ".crusorai-diff-row.is-remove .crusorai-diff-sign { color: var(--crusorai-diff-remove-foreground); }" in css
    # Capped frame + floating jump button, shown only when below-fold.
    assert "function fileScrollFrame" in renderer
    assert ".crusorai-file-scroll { max-height: 300px" in css
    assert ".crusorai-scroll-down {" in css and ".crusorai-scroll-down.is-hidden" in css
    assert ".crusorai-file-view {" in css
    # Founder 2026-10-17: 'dropdown menu is not highlighted' — the
    # headers of all three dropdown layers (group, card, file
    # accordion) carry a hover + open highlight.
    assert ".crusorai-tool-summary:hover { background: var(--vscode-list-hoverBackground)" in css
    assert ".crusorai-tool-row[open] > .crusorai-tool-summary" in css
    assert ".crusorai-tool-run-summary:hover { background: var(--vscode-list-hoverBackground)" in css
    assert ".crusorai-tool-run[open] > .crusorai-tool-run-summary" in css
    assert ".crusorai-file-view-trigger:hover { background: var(--vscode-list-hoverBackground); }" in css
    assert ".crusorai-file-view-item:not(.is-closed) .crusorai-file-view-trigger" in css
    # Founder 2026-10-17 (later): 'gap is more' + 'remove that green
    # line/red line — both in edit, write also streamed'. The gutter
    # is computed from the widest number shown (no fixed 34px), the
    # row gap is tight, and no diff row carries a coloured edge line
    # (tint + coloured sign/number carry the change). diffPreview is
    # the single painter for edit, settled write and streamed write.
    assert "wrap.style.setProperty('--crusorai-diff-gutter-width', `${widestNo}ch`);" in renderer
    assert ".crusorai-diff-gutter { flex: none; width: var(--crusorai-diff-gutter-width, 3ch);" in css
    assert "border-left-color: var(--crusorai-diff-add-foreground)" not in css
    assert "border-left-color: var(--crusorai-diff-remove-foreground)" not in css
    diff_row_block = css.split(".crusorai-diff-row {", 1)[1].split("}", 1)[0]
    assert "border-left" not in diff_row_block, "diff rows carry no edge line"


def test_tool_cards_stream_from_tool_call_args():
    """Founder 2026-10-15: 'also should be streamable refer opencode and
    implement' + 'show green and red diffs'. OpenCode renders edit/
    write cards from the STREAMING input (status='streaming', input
    growing). The pipeline: the token pump accumulates
    tool_call_chunks -> tool.args bus events -> Bridge v2
    tool_call_args frames -> the service births the card early (or
    rebinds a stream-<index> preview when the durable start lands)
    -> the body shows the growing content/new_text, settling into
    the green/red diff when the result arrives. Cards now default
    open while running so the growth is visible; a user close still
    wins (closedTools)."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    service = _text("browser", "crusorAIRendererService.ts")
    catalog = _text("common", "crusorAIToolCatalog.ts")
    protocol = _text("common", "crusorAIProtocol.ts")
    assert "frame.type === 'tool_call_args'" in service
    assert "p.toolId.startsWith('stream-')" in service, "streamed previews rebind, never double"
    assert "type: 'tool_call_args'" in protocol
    assert "write_file: tool('Write', 'file-write', 'file-add', 'running')" in catalog
    assert "edit_file: tool('Edit', 'file-write', 'edit', 'running')" in catalog
    # Settled calls show the diff (green/red) for write too; while
    # streaming, content/new_text grows in the code view.
    assert "tool.name !== 'write_file' && diff" in renderer and "codeView(streamText.slice(0, 32_000), target, syntax)" in renderer


def test_file_viewers_carry_syntax_token_colours():
    """Founder comparison 2026-10-15: his Write screenshot (flat green
    wall) vs OpenCode's render ('which looks nice') — the remaining
    gap was token colour: green strings, coloured keywords/numbers/
    types, grey comments over the diff tints. A small stateful
    tokenizer now paints both viewers (code view + diff text) with
    the workbench theme's own symbolIcon token colours; Write is
    back to OpenCode's file view (never a wall), Edit keeps the
    green/red diff."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "function syntaxPainted" in renderer
    assert "function syntaxLanguageOf" in renderer
    assert "syntaxText(line.text, language, state)" in renderer
    assert "syntaxText(line, language, state)" in renderer
    for kind in ("comment", "string", "keyword", "number", "type"):
        assert f".crusorai-tok-{kind}" in css, kind
    assert "var(--vscode-symbolIcon-stringForeground)" in css
    # Flat whole-line green/red text (the wall) stays retired.
    assert "var(--crusorai-diff-add-foreground) 70%" not in css


def test_syntax_colours_come_from_the_editor_theme():
    """Founder screenshot 2026-10-15 (build 5e30b20c): 'color??' — the
    tokenizer painted, but symbolIcon.*Foreground resolves to plain
    foreground under CrusorAI Dark, so everything stayed white. The
    real token colours live in the editor theme: the service now
    resolves them through IColorTheme.getTokenStyleMetadata +
    tokenColorMap (the editor's own machinery), cached per language
    and invalidated on theme change; the renderer rides them into
    the viewers as --crusorai-tok-* variables."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    service = _text("browser", "crusorAIRendererService.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "syntaxColors?(language: string)" in renderer
    assert "applySyntaxColors(wrap, colors)" in renderer
    assert "getTokenStyleMetadata" in service and "tokenColorMap" in service
    assert "@IThemeService private readonly themeService" in service
    assert "onDidColorThemeChange(() => this.syntaxColorCache.clear())" in service
    assert "var(--crusorai-tok-string, var(--vscode-symbolIcon-stringForeground))" in css


def test_write_settles_into_the_diff_view():
    """Founder 2026-10-15 (build 8a1a1f3b screenshot): 'not showing' —
    the +/- signs landed in the Edit diff, but the Write card still
    showed the plain file view. The ask ('also add diff view +,-')
    was about THIS card: while a write streams it grows as the file
    (approved), and once it settles the card flips into the diff
    view. The engine receipt previews only 12 diff lines, so a
    pure-addition write whose receipt counts equal the written line
    count (a new file) rebuilds the FULL diff from the content —
    gated on the counts, never synthesised loosely."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "tool.name === 'write_file' && tool.state === 'passed' && diff" in renderer
    assert "settledWriteDiff" in renderer and "fullWriteDiff(tool, diff, streamText)" in renderer
    assert "stats.removed !== 0" in renderer and "stats.added !== lines.length" in renderer
    assert "@@ -0,0 +1,${lines.length} @@" in renderer
    # Streaming writes keep the growing file view.
    assert "codeView(streamText.slice(0, 32_000), target, syntax)" in renderer


def test_streaming_write_paints_as_signed_diff():
    """Founder 2026-10-15 (build 03b8317c screenshot): 'i checked
    good, but when it streamed it was colorless' — the settled diff
    was right, but while the write streamed the card grew as a plain
    file view and only gained colour at settle. Now the LIVE write
    paints as the diff itself: growing content lands as green
    signed additions (allAddedDiff behind a new-file hunk header,
    so lines are numbered) with syntax colours from the first
    frame; the engine's durable diff (with any removals) replaces
    it at settle. Verified in a jsdom harness against the shipped
    bundle: partial-60-char frame already paints + rows."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "function streamingWriteDiff" in renderer and "function allAddedDiff" in renderer
    assert "diffPreview(streamingWriteDiff(streamText.slice(0, 32_000)), target, syntax)" in renderer
    assert "(tool.state === 'running' || tool.state === 'queued')" in renderer


def test_web_cards_match_opencode():
    """Next family after Write/Edit (founder 2026-10-15: 'next tool
    cards plz'). OpenCode webfetch = hideDetails: title + the URL as
    an accent LINK in the header (webfetch-link), no body — ours are
    now single-line rows on the same inline contract as Read, and
    the URL opens in the user's browser via IOpenerService, never
    as an editor resource. websearch = query subtitle + ExaOutput
    link list: our engine's numbered receipt (title/URL/snippet)
    parses into exa-tool-links with real titles + snippets, first
    10 + a 'N more' reveal; errors/no-results stay honest text.
    Nothing paints while the search runs (no '{}' placeholder)."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    service = _text("browser", "crusorAIRendererService.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "const WEB_LINK_TOOLS = new Set(['web_fetch', 'web_extract']);" in renderer
    assert "openExternal?(url: string): void;" in renderer
    assert "host.openExternal?.(targetText)" in renderer
    assert "function parseWebSearchResults" in renderer
    assert "out.dataset.component = 'exa-tool-output'" in renderer
    assert "links.dataset.slot = 'exa-tool-links'" in renderer
    assert "webSearchBody(tool, host)" in renderer
    assert "@IOpenerService private readonly openerService" in service
    assert "this.openerService.open(url, { openExternal: true })" in service
    assert ".crusorai-web-snippet {" in css


def test_web_fetch_earns_no_match_count_chip():
    """Founder screenshot 2026-10-15 (build e7729709): 'Fetch page
    https://example.com 7 matches' — the inline web_fetch row fell
    through to the grep/glob line-count fallback in toolInlineInfo
    and labelled the fetched page's line count as matches. Web rows
    return before that fallthrough (extract keeps its real 'N
    pages'); search tools keep earning their count. Harness-verified
    against the shipped bundle."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "if (tool.name === 'web_extract' || tool.name === 'web_fetch') {" in renderer
    assert "Web rows earn no match count" in renderer


def test_clarify_always_renders_as_its_card_never_raw_json():
    """Field 2026-10-15: a sub-agent's clarify painted as a generic
    shell dumping the raw arguments JSON ('DETAILS {"arguments":
    ...}') — settled calls only reached clarifyCard when a live
    pending request existed, which replays and child views never
    have. Every clarify tool now routes to the card: pending ->
    interactive form, settled -> Q&A from the result, in-flight
    without a frame -> the read-only question ('clarify-waiting').
    The card call also passes closedTools + pending in the right
    slots (it previously dropped a parameter, leaving pending
    permanently undefined at runtime)."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "if (tool.name === 'clarify') {" in renderer
    assert "clarifyCard(tool, host, openTools, closedTools, pendingClarify)" in renderer
    assert "pending?: CrusorAIRenderModel['clarify']" in renderer
    assert "card.dataset.component = 'clarify-waiting'" in renderer


def test_subagent_card_is_honest_about_navigation():
    """Sub-agent family pass. Founder 2026-10-15 (second verdict):
    "the sub agent UI in the main agent is not nice — see the
    opencode and copy the codes." So the card is now OpenCode's
    subagent renderer copied, not adapted: toolRow returns the task
    card directly (no generic collapsible shell, no raw-name
    header), the DOM carries their task-tool-card / -surface /
    -title / -action hooks, the extracted basic-tool.css task-tool
    rules paint it, the streaming phase is their Delegating pill,
    and there is no trailing Sub-Agents section anywhere — the
    cards in the turn are the sub-agent UI. Clickable still only
    with a real child id (result metadata, else description-prefix
    record match — their taskSession rule); a failed delegation
    earns its own error line; no invented agent palette.
    """
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "taskToolCard render" not in renderer and "getSubAgents" not in renderer
    assert "agentColor" not in renderer
    assert "if (presentation.family === 'subagent') {\n\t\treturn taskToolCard(tool, host, subAgents);\n\t}" in renderer
    assert '.crusorai-render-root [data-component="task-tool-card"]' in css
    assert "task-tool-delegating" in renderer and "Delegating…" in renderer
    assert "if (childId) {" in renderer and "host.navigateToSession?.(String(target))" in renderer
    assert "crusorai-task-tool-error" in renderer and ".crusorai-task-tool-error {" in css
    assert "crusorai-subagent-list" not in renderer


def test_child_session_click_mid_run_opens_live():
    """Founder 2026-10-15, second verdict (build 9b1d9dbd): 'i am
    inside the same parent session' — the deferral notice was still
    not an open session. Mid-run child clicks now OPEN the child:
    navigateToSession stashes the parent's whole live surface
    (liveStash/captureSurface), resets into the child, and the
    child's transcript checkpoint-refreshes (requestChildSnapshot +
    syncChildLivePoll + subagent_updated hook) while the parent's
    frames note its list row. Returning to the still-running parent
    restores the snapshot verbatim and heals the away-window tokens
    from the settled checkpoint (healAfterRestore). Unrelated
    mid-run switches still refuse."""
    service = _text("browser", "crusorAIRendererService.ts")
    renderer = _text("browser", "crusorAIRenderer.ts")
    assert "pendingChildNavigation" not in service
    assert "this.liveStash = { sessionId: this.sessionId, snapshot: this.captureSurface(this.sessionId) }" in service
    assert "private restoreSurface(snapshot: CrusorSurfaceSnapshot)" in service
    assert "private requestChildSnapshot()" in service
    assert "private syncChildLivePoll()" in service
    assert "healAfterRestore" in service
    # Mid-run navigation is never refused (founder field 2026-10-16:
    # the back arrow inside a running child answered 'Stop the current
    # run before switching sessions.'). The stashed live surface is
    # restored first — running or not — and departing a live surface
    # stashes it instead of blocking.
    assert "Stop the current run before switching sessions." not in service
    assert "if (this.liveStash && this.liveStash.sessionId === targetSessionId)" in service
    assert "const stashedIsRunning = !!this.liveStash && this.liveStash.snapshot.running;" in service
    assert "crusorai-child-live" in renderer


def test_delegation_children_root_their_own_lineage():
    """Opening a child must never resolve to its parent: delegation
    children carry lineage_root_id=self, or resolve_tip (greatest
    last_active in the lineage) climbs from the child up to the
    still-active parent and session_messages paints the WRONG
    transcript. Forks keep lineage semantics (no override)."""
    from pathlib import Path
    _root = Path(__file__).resolve().parents[2]
    store_py = (_root / "src" / "runtime" / "session_store.py").read_text(encoding="utf-8")
    sub_agent = (_root / "src" / "agents" / "sub_agent.py").read_text(encoding="utf-8")
    bridge = (_root / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "lineage_root_id: str | None = None" in store_py
    assert "lineage_root_id=agent_id" in sub_agent
    assert "lineage_root_id=handle.subagent_id" in bridge

def test_batch_card_rows_open_their_child_sessions():
    """Founder 2026-10-15 (build f2362c89): 'WHERE SHOULD I CLICK??' —
    the batch Delegate card rendered its tasks as a dead display-only
    list while the real child links hid in a Sub-Agents section.
    Sub-agent records now thread model -> assistantTurn -> toolSection
    -> toolRow -> familyBody -> taskToolCard, and each batch row
    matches its child (goal/description prefix, else spawn order)
    and navigates on click; rows style as separated lines with an
    arrow affordance when clickable."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "subAgents: model.subAgents" in renderer
    assert "subAgents: turn.subAgents" in renderer
    assert "function taskToolCard(tool: CrusorAIToolView, host: CrusorAIRenderHost, subAgents" in renderer
    assert "const matchChild" in renderer and "crusorai-task-tool-batch-action" in renderer
    assert ".crusorai-task-tool-batch-row.is-clickable" in css
    assert "crusorai-task-tool-batch-text" in css


def test_batch_children_are_announced_by_the_engine():
    """Founder 2026-10-15 (build fd5dc052): the batch card rows STILL
    did nothing ('no use') — renderer nav was fine, but the batch
    spawn path (SubAgentCoordinator) never emitted subagent.updated
    and registered children only after they finished, so the panel
    never had records to match rows against. spawn() now announces
    running -> settled on the shared bus event; the lifecycle passes
    emit_events=False so its children never double-speak. The batch
    row text also clips (min-width: 0) instead of overflowing the
    card."""
    from pathlib import Path
    _root = Path(__file__).resolve().parents[2]
    sub_agent = (_root / "src" / "agents" / "sub_agent.py").read_text(encoding="utf-8")
    lifecycle = (_root / "src" / "agents" / "subagent_lifecycle.py").read_text(encoding="utf-8")
    css = _text("browser", "media", "crusorAI.css")
    assert 'event_bus.emit("subagent.updated"' in sub_agent
    assert '_emit("running")' in sub_agent
    assert "emit_events: bool = True" in sub_agent
    assert "emit_events=False" in lifecycle
    assert ".crusorai-task-tool-batch-text { flex: 1 1 auto; min-width: 0;" in css


def test_child_session_is_a_normal_session_with_bottom_nav():
    """Founder 2026-10-15 (build 1ec1fe9d): 'navigation is nice but
    revert those back to normal — user bubble at the start, same UI
    response as parent gets — but make the navigation to the bottom
    not the top.' So: child sessions paint exactly like parent
    sessions (user bubble first, same response UI); the ONLY child
    chrome is the nav bar docked between the transcript and the
    composer (childNavBar in agentColumn), carrying the back link,
    the task label, and the live Running state. Delegation inside
    any session paints as OpenCode task cards in the turn flow;
    there is no Sub-Agents list section on either surface."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "crusorai-child-header" not in renderer and "crusorai-child-banner" not in renderer
    assert "if (turn.userMessage && !model.isChild)" not in renderer
    assert "function childNavBar(model: CrusorAIRenderModel, host: CrusorAIRenderHost)" in renderer
    assert "if (childNav) { lane.append(childNav); }" in renderer
    assert "nodes.push(childNav)" not in renderer
    assert ".crusorai-child-nav {" in css and ".crusorai-child-nav-parent" in css
    # No Sub-Agents section trails any turn ("why this is at
    # last??", 2026-10-15): delegate task cards are the UI.
    assert "subagent-list" not in renderer

def test_stashed_parent_states_stay_fresh():
    """Field 2026-10-15: the child finished ('task done') but the
    parent view stuck on RUNNING — verdict frames that arrived while
    the user watched the child were routed to the session-list row
    only, so the restored snapshot kept pre-completion states.
    syncStashFrame now settles tool + sub-agent verdicts INSIDE the
    stash (same mergeSubagentRecord rules as the live surface), and
    the bridge transcript projection never paints system scaffolding
    (the 'You just received a tool result...' nudge) as chat text."""
    service = _text("browser", "crusorAIRendererService.ts")
    from pathlib import Path
    bridge = (Path(__file__).resolve().parents[2] / "src" / "bridge" / "__main__.py").read_text(encoding="utf-8")
    assert "private syncStashFrame(foreignId: string, frame: CrusorServerEvent)" in service
    assert "this.syncStashFrame(foreignId, frame);" in service
    assert "private mergeSubagentRecord(" in service
    assert 'if mtype == "system":' in bridge

def test_clarify_requests_are_session_tree_state():
    """OpenCode parity (founder 2026-10-15: "did u read opencode??"):
    the question tool works in ANY session, children included; pending
    questions are session-TREE requests surfaced by the viewed
    session's descendant tree, and the reply routes to the ASKING
    session. The engine must not gate children out of asking (an
    instant walk-away shipped once and was reverted), the service
    tracks every ask by request id before foreign routing, buildModel
    picks via the tree rule, the reply carries the asker's session id,
    and the renderer docks a descendant's question above the composer
    while the viewed session's own ask stays in its transcript."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    service = _text("browser", "crusorAIRendererService.ts")
    clarify_py = (ROOT / "src" / "tools" / "clarify_tool.py").read_text(encoding="utf-8")
    chat_graph = (ROOT / "src" / "graphs" / "chat_graph.py").read_text(encoding="utf-8")
    # Engine: children block and ask like the parent (no walk-away gate).
    assert "Sub-agent children have no user to ask" not in clarify_py
    assert "timeout=0.0" not in clarify_py
    # Service: tree state, tree pick, asking-session reply routing.
    assert "private readonly clarifies = new Map" in service
    assert "private pickTreeClarify()" in service
    assert "session_id: entry?.sessionId ?? this.sessionId" in service
    assert "clarify: this.pickTreeClarify()," in service
    # Renderer: descendant ask docks above the composer; own ask does not.
    assert "model.clarify.sessionId !== model.sessionId" in renderer
    # Stop cascade: parent Stop interrupts foreground + batch children.
    assert "subagent_lifecycle.cancel(handle)" in chat_graph
    assert "_abort_batch_children" in chat_graph

def test_approvals_are_session_tree_state_and_lists_show_roots():
    """Second HITL half (founder 2026-10-15): a CHILD's safety approval
    surfaces in an open ancestor view exactly like its questions —
    approvals map keyed by tool id, tree pick in buildModel, verdict
    routed to the asking session, settle/turn-end retirement. And the
    session list shows ROOT sessions only (OpenCode: children are
    reached via delegate cards, not list rows); the child nav row
    carries a sibling switcher."""
    service = _text("browser", "crusorAIRendererService.ts")
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "private readonly approvals = new Map" in service
    assert "private pickTreeApproval()" in service
    assert "approval: this.pickTreeApproval()," in service
    assert "session_id: entry?.sessionId ?? this.sessionId, tool_id: toolId" in service
    assert "this.approvals.delete(frame.tool_id);" in service
    assert "!record.parentSessionId && !this.parentMap.has(record.sessionId)" in service
    assert "private currentChildSiblings()" in service
    assert "childSiblings: this.currentChildSiblings()," in service
    assert "crusorai-child-nav-sibling" in renderer
    assert ".crusorai-child-nav-sibling {" in css


def test_engine_registry_resume_model_and_spawn_policy():
    """The remaining OpenCode sub-agent gaps, engine side: an open
    agent registry (.crusorai/agents/*.md over the four built-ins),
    resume by session id (verbatim follow-up on the same thread),
    per-call/per-agent model override, per-agent spawn policy, and a
    delegate description rebuilt from the live registry at bind."""
    chat_graph = (ROOT / "src" / "graphs" / "chat_graph.py").read_text(encoding="utf-8")
    registry = (ROOT / "src" / "agents" / "subagent_registry.py").read_text(encoding="utf-8")
    lifecycle = (ROOT / "src" / "agents" / "subagent_lifecycle.py").read_text(encoding="utf-8")
    coordinator = (ROOT / "src" / "agents" / "sub_agent.py").read_text(encoding="utf-8")
    assert "def available_agents(" in registry and "def denied_reason(" in registry
    assert ".crusorai" in registry and "agents" in registry
    assert "def resume_child(" in lifecycle
    assert "continuation=record.continuation" in lifecycle
    assert "focused_task = task" in coordinator  # resume: verbatim, no persona
    assert "session_id: RESUME a previous sub-agent session" in chat_graph
    assert "Available agents: {_listing}" in chat_graph
    assert "_DELEGATE_BASE_DESCRIPTIONS" in chat_graph

def test_approval_dock_is_opencode_dockprompt_in_founder_theme():
    """The approval UI is OpenCode's DockPrompt (kind=permission) wearing
    the founder's theme — verified against the captured
    session-permission-dock.tsx / message-part.css: raised shell
    (permission-body) with warning icon + 'Permission required', hint
    and plain-code pattern rows on the 20px icon column, and a base
    tray (permission-footer) underneath carrying Deny | Allow always |
    Allow once. The amber approval colour lives ONLY on the icon: the
    earlier tinted card (amber top border + 9% amber wash + warning
    box) matched neither OpenCode nor 'black stays black'."""
    renderer = _text("browser", "crusorAIRenderer.ts")
    css = _text("browser", "media", "crusorAI.css")
    assert "body.dataset.slot = 'permission-body'" in renderer
    assert "permissionFooter.dataset.slot = 'permission-footer'" in renderer
    assert "footerActions.dataset.slot = 'permission-footer-actions'" in renderer
    assert "icon('warning')" in renderer
    assert ".crusorai-approval-body {" in css
    assert "background: var(--vscode-editorWidget-background)" in css
    assert ".crusorai-permission-footer {" in css
    assert "margin-top: -16px" in css  # tray slides under the shell
    assert ".crusorai-permission-icon { color: var(--crusorai-approval);" in css
    # The tint era is gone: no amber border/wash, no warning box, no
    # boxed pattern code, no leftover Hermes approval-bar CSS.
    assert "border-top: 1px solid var(--crusorai-approval)" not in css
    assert "var(--crusorai-approval) 9%" not in css
    assert "crusorai-approval-warning" not in renderer and "crusorai-approval-warning" not in css
    assert "crusorai-approval-bar" not in css and "crusorai-approval-pill" not in css
