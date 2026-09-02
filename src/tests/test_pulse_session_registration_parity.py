"""Pulse's Agent Manager speaks the fork's session contract -- and nothing else's branding.

The registration decision (docs/PULSE_COPILOT_REGISTRATION_REVIEW.md) is that the manager is not a
second UI to hand-build but a *session provider*: one session type whose scheme is the type id, one
status vocabulary shared with chat, one store that both the workbench list and our own rows project.
That contract is behaviour, so it is EXECUTED here -- esbuild bundles the projection module and node
runs it over fixtures -- rather than grepped:

* every branch of the lifecycle mapping (approval outranks running, idle is no status at all);
* the elapsed/attention rules the rows print;
* `changes` being absent rather than zero when nothing was counted;
* the session URI round-tripping to the id the engine named.

The rest is structural, because a registration that does not compile is not a registration: the
pin list at the bottom is exactly the code that would silently unlink us from the fork's list.

A skipped test here is a host gap to report (no node, no esbuild), never a pass.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PULSE = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "pulseai"
COMMON = PULSE / "common"
BROWSER = PULSE / "browser"
ESBUILD = ROOT / "pulse-webview" / "node_modules" / ".bin" / "esbuild"

PROJECTION = COMMON / "pulseAISessionProjection.ts"
STORE = COMMON / "pulseAISessionStore.ts"
CONTROLLER = BROWSER / "pulseAISessionController.ts"
CONTRIBUTION = BROWSER / "pulseAI.contribution.ts"
SERVICE = BROWSER / "pulseAIRendererService.ts"
RENDERER = BROWSER / "pulseAIRenderer.ts"
VIEW_PANE = BROWSER / "pulseAIViewPane.ts"
CSS = BROWSER / "media" / "pulseAI.css"
CHAT_URI = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "chat" / "common" / "model" / "chatUri.ts"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not ESBUILD.exists(),
    reason="the mapping table is executed here, so this needs node and pulse-webview's esbuild (npm install)",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _bundle(source: Path, workdir: Path) -> Path:
    out = workdir / f"{source.stem}.mjs"
    proc = subprocess.run(
        [str(ESBUILD), str(source), "--bundle", "--format=esm", f"--outfile={out}",
         "--log-level=warning", "--platform=node"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=180,
    )
    if proc.returncode != 0:
        pytest.fail(f"esbuild could not bundle {source.name}: {proc.stderr.strip()[:700]}")
    return out


RUNNER = """
import { readFileSync } from 'node:fs';
import {
  PULSE_CHAT_SESSION_TYPE, pulseSessionUri, pulseSessionIdFromUri, isPulseSessionUri,
  pulseSessionStatusName, pulseSessionLabel, pulseSessionElapsedSeconds, pulseSessionElapsedLabel,
  pulseSessionNeedsAttention, pulseSessionRows,
} from '%s';

const input = JSON.parse(readFileSync(process.argv[2], 'utf8'));

const status = input.status.map(c => [
  pulseSessionStatusName({ running: c.running, turnOutcome: c.turnOutcome, hasApproval: c.hasApproval }) ?? null,
  // A fresh session must not be reported as completed: the fork reads completed-and-unread as
  // "look at me", so `idle` has to have no status at all.
  pulseSessionNeedsAttention({ statusName: pulseSessionStatusName({ running: c.running, turnOutcome: c.turnOutcome, hasApproval: c.hasApproval }) }) ? 1 : 0,
]);

const labels = input.labels.map(c => pulseSessionLabel(c.message, c.sessionId));

const elapsed = input.elapsed.map(c => [
  pulseSessionElapsedSeconds(c.now, c.origin) ?? null,
  pulseSessionElapsedLabel(c.seconds, c.status),
]);

const rows = input.rows.map(group => {
  const [facts, activeId, now, read] = group;
  const readMap = read ? new Map(Object.entries(read)) : undefined;
  return pulseSessionRows(facts, activeId, now, readMap).map(row => ({
    label: row.label,
    status: row.statusName ?? null,
    state: row.elapsedLabel,
    detail: row.description,
    attention: row.needsAttention ? 1 : 0,
    active: row.isActive ? 1 : 0,
    hasChanges: 'changes' in row ? 1 : 0,
    changes: row.changes ?? null,
    created: row.timing.created,
    started: row.timing.lastRequestStarted ?? null,
    ended: row.timing.lastRequestEnded ?? null,
    uri: row.resource.toString(),
    type: row.resource.scheme,
    idRoundTrip: pulseSessionIdFromUri(pulseSessionUri(facts[0].sessionId)) === facts[0].sessionId ? 1 : 0,
  }));
});

const uriIds = input.uriIds.map(id => {
  const uri = pulseSessionUri(id);
  return [uri.scheme, PULSE_CHAT_SESSION_TYPE, isPulseSessionUri(uri) ? 1 : 0, pulseSessionIdFromUri(uri)];
});

process.stdout.write(JSON.stringify({ status, labels, elapsed, rows, uriIds, type: PULSE_CHAT_SESSION_TYPE }));
"""

# (running, turnOutcome, approval) -> expected lifecycle name, plus whether it counts as attention.
STATUS_CASES = [
    {"running": False, "turnOutcome": "idle", "hasApproval": False},
    {"running": True, "turnOutcome": "running", "hasApproval": False},
    {"running": True, "turnOutcome": "running", "hasApproval": True},
    {"running": False, "turnOutcome": "completed", "hasApproval": False},
    {"running": False, "turnOutcome": "cancelled", "hasApproval": False},
    {"running": False, "turnOutcome": "failed", "hasApproval": False},
    {"running": True, "turnOutcome": "completed", "hasApproval": True},
    {"running": False, "turnOutcome": "idle", "hasApproval": True},
]
EXPECTED_STATUS = [
    [None, 0],
    ["inProgress", 0],
    ["needsInput", 0],
    ["completed", 1],
    ["completed", 1],
    ["failed", 0],
    ["needsInput", 0],
    ["needsInput", 0],
]

FACTS = [
    {
        "sessionId": "s-2",
        "label": "Add retry to the fetcher",
        "workspaceLabel": "pulse-desktop",
        "statusName": "completed",
        "firstSeenAt": 1_000,
        "turnStartedAt": 4_000,
        "turnEndedAt": 9_000,
        "changes": {"files": 3, "insertions": 40, "deletions": 5},
    },
    {
        "sessionId": "s-1",
        "label": "Read the engine",
        "workspaceLabel": "pulse-desktop",
        "statusName": "inProgress",
        "firstSeenAt": 2_000,
        "turnStartedAt": 5_000,
    },
]


def _exec(fixtures: dict, tmp_path: Path) -> dict:
    bundle = _bundle(PROJECTION, tmp_path)
    script = tmp_path / "projection.mjs"
    script.write_text(RUNNER % f"./{bundle.name}", encoding="utf-8")
    cases = tmp_path / "fixtures.json"
    cases.write_text(json.dumps(fixtures), encoding="utf-8")
    proc = subprocess.run(
        ["node", str(script), str(cases)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=180, cwd=str(tmp_path),
    )
    if proc.returncode != 0:
        pytest.fail(f"runner failed: {proc.stderr.strip()[:900]}")
    return json.loads(proc.stdout)


def test_lifecycle_names_are_the_forks_vocabulary(tmp_path):
    """`needsInput` outranks `inProgress`, and an untouched session has no status to show."""
    out = _exec({"status": STATUS_CASES, "labels": [], "elapsed": [], "rows": [], "uriIds": []}, tmp_path)
    assert out["status"] == EXPECTED_STATUS


def test_row_label_is_the_users_own_words(tmp_path):
    cases = [
        {"sessionId": "s"},
        {"sessionId": None},
        {"sessionId": "s", "message": "   fix\n\tthe retry   "},
        {"sessionId": "s", "message": "x" * 200},
    ]
    out = _exec({"status": [], "labels": cases, "elapsed": [], "rows": [], "uriIds": []}, tmp_path)
    assert out["labels"][0] == "Pulse session"
    assert out["labels"][1] == "New Pulse session"
    assert out["labels"][2] == "fix the retry"
    assert len(out["labels"][3]) == 90 and out["labels"][3].endswith("\u2026")


def test_elapsed_and_attention_follow_the_lists_own_rules(tmp_path):
    cases = [
        {"now": 10_000, "origin": 5_000, "seconds": None, "status": "inProgress"},
        {"now": 10_000, "origin": 5_000, "seconds": None, "status": "needsInput"},
        {"now": 10_000, "origin": 9_500, "seconds": None, "status": "completed"},
        {"now": 10_000, "origin": None, "seconds": None, "status": "completed"},
        {"now": 10_000, "origin": 20_000, "seconds": None, "status": "completed"},
        {"now": 0, "origin": 0, "seconds": 600, "status": "completed"},
    ]
    out = _exec({"status": [], "labels": [], "elapsed": cases, "rows": [], "uriIds": []}, tmp_path)
    # Whole seconds since the origin; a clock that ran backwards or has no origin is no duration.
    assert [row[0] for row in out["elapsed"]] == [5, 5, 0, None, None, 0]
    # Under a minute reads as "now"; in-progress and needs-input name themselves instead.
    assert [row[1] for row in out["elapsed"]] == ["Working\u2026", "Needs input", "now", "now", "now", "10m"]


def test_rows_are_a_projection_of_the_store(tmp_path):
    group = [[FACTS[1], FACTS[0]], "s-1", 10_000, None]
    out = _exec({"status": [], "labels": [], "elapsed": [], "rows": [group], "uriIds": []}, tmp_path)
    rows = out["rows"][0]
    # Most recent activity first, decided once for both surfaces: the finished run ended at 9s,
    # which is later than the in-flight turn that started at 5s, so it leads while still running.
    assert [row["label"] for row in rows] == ["Add retry to the fetcher", "Read the engine"]
    assert rows[1]["active"] == 1 and rows[1]["status"] == "inProgress"
    assert rows[1]["state"] == "Working\u2026" and rows[0]["state"] == "now"
    # A finished, never-opened row is attention; an in-flight one is not.
    assert [row["attention"] for row in rows] == [1, 0]
    # The gap is reported as a gap: no diff counted, no number shown.
    assert rows[1]["hasChanges"] == 0 and rows[1]["changes"] is None
    assert rows[0]["hasChanges"] == 1 and rows[0]["changes"] == {"files": 3, "insertions": 40, "deletions": 5}
    assert rows[1]["started"] == 5_000 and rows[0]["started"] == 4_000
    # `created` is a first sighting, so the earlier note has to survive the later one.
    assert rows[0]["created"] == 1_000 and rows[1]["created"] == 2_000
    assert all(row["type"] == "pulseai" for row in rows)
    assert all(row["idRoundTrip"] == 1 for row in rows)


def test_session_uri_scheme_is_the_session_type(tmp_path):
    """`getChatSessionType()` returns `resource.scheme` for contributed types: one identity, not two."""
    ids = ["s-1", "session/with slash", "100%_odd", "\u00fcnicode"]
    out = _exec({"status": [], "labels": [], "elapsed": [], "rows": [], "uriIds": ids}, tmp_path)
    assert out["type"] == "pulseai"
    for scheme, expected_type, recognised, round_trip in out["uriIds"]:
        assert scheme == expected_type == "pulseai"
        assert recognised == 1
        assert round_trip in ids, (scheme, round_trip)
    resolver = _text(CHAT_URI)
    assert "return resource.scheme;" in resolver


def test_one_store_two_skins():
    """The manager and the workbench list read the same store; neither keeps a copy."""
    store = _text(STORE)
    controller = _text(CONTROLLER)
    service = _text(SERVICE)
    renderer = _text(RENDERER)

    assert "registerChatSessionItemController(this.chatSessionType, this)" in controller
    assert "class PulseAISessionController extends Disposable implements IChatSessionItemController" in controller
    assert "WorkbenchPhase.AfterRestored" in controller
    # Read state stays the host's: implementing setChatSessionItemRead would move it in-memory.
    assert re.search(r"^\s*setChatSessionItemRead\(", controller, re.M) is None, "read state must stay the host's"
    # The engine pushes; a refresh that re-queried would be theatre.
    assert "async refresh(" in controller

    assert "createDecorator<IPulseAISessionStore>" in store
    assert "MAX_TRACKED_SESSIONS" in store
    assert "const merged: PulseAISessionFacts" in store  # firstSeenAt survives a re-render

    assert "this.sessionStore.note(facts)" in service
    assert "this.sessionStore.markRead(this.sessionId, true)" in service
    assert "sessions: this.sessionRows()," in service
    assert "readonly sessions?: readonly PulseAISessionRow[];" in renderer
    # No second source of rows, and no second narration formatter.
    assert "model.sessions" in renderer
    assert "summarizeToolRun(model.tools, model.running, tool => compactTarget(displayTarget(tool)) ?? tool.name)" in renderer
    assert "registerSingleton(IPulseAISessionStore, PulseAISessionStore" in _text(CONTRIBUTION)
    assert "import './pulseAISessionController.js'" in _text(CONTRIBUTION)


def test_the_manager_is_not_branded_like_anyone_elses_product():
    """Fork craft on the inside, Pulse on the outside: no Copilot chrome in our surfaces."""
    for path in (RENDERER, VIEW_PANE, CSS, SERVICE, CONTROLLER, CONTRIBUTION):
        text = _text(path)
        assert "pulseai-copilot" not in text, f"{path.name} still names a class after Copilot"
        # A comment may name the thing it hides; a label, a class and an icon may not.
        for branded in ("'CopilotKit'", '"CopilotKit"', "'@copilot'", "'GitHub Copilot'"):
            assert branded not in text, f"{path.name} ships {branded} as chrome"
    view = _text(VIEW_PANE)
    assert "webviewTab.textContent = 'Webview';" in view
    # Hiding Copilot's own chrome is the intended behaviour and must survive the sweep.
    css = _text(CSS)
    assert ".codicon-copilot" in css
    assert "activity-workbench-view-extension-copilot-chat" in css
    # Inventing a diff count is the failure mode this whole layer exists to prevent.
    assert "+12" not in _text(RENDERER)


def test_no_ui_text_reuses_the_forks_copilot_wording():
    """Upstream's list says 'Agents'; ours says what it is, so nothing reads as a Copilot clone."""
    renderer = _text(RENDERER)
    start = renderer.index("function renderManager(")
    head = renderer[start:renderer.index("\n}\n", start)]
    for word in ("'Agents'", "'GitHub Copilot'", "'@workspace'", "chat-agent"):
        assert word not in head, f"manager chrome echoes {word!r}"
    # Ours, in our words: a live-evidence inspector and a control plane, not a Copilot clone.
    assert "Run inspector" in renderer and "LIVE EVIDENCE" in renderer and "CONTROL PLANE" in renderer
