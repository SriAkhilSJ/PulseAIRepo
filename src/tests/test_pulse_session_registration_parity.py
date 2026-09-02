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

The loader is chosen at runtime: esbuild when its binary is native to the host, otherwise
`typescript/bin/tsc`, which is plain JS and so survives a node_modules tree installed on another
platform. Both routes feed the SAME fixtures -- a host gap never turns into a pass, and a fallback
never runs a weaker check.

The rest is structural, because a registration that does not compile is not a registration: the
pin list at the bottom is exactly the code that would silently unlink us from the fork's list.

A skipped test here is a host gap to report (no node, and no tsc fallback either), never a pass.
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
SRC = ROOT / "desktop" / "vscode" / "src"
# tsc is a JS entrypoint, so it runs on any host with node -- including a Windows checkout whose
# node_modules was installed on Linux, where .bin/esbuild is a POSIX shim that cannot execute.
TSC_CANDIDATES = (
    ROOT / "pulse-webview" / "node_modules" / "typescript" / "bin" / "tsc",
    ROOT / "desktop" / "vscode" / "node_modules" / "typescript" / "bin" / "tsc",
)

PROJECTION = COMMON / "pulseAISessionProjection.ts"
STORE = COMMON / "pulseAISessionStore.ts"
CONTROLLER = BROWSER / "pulseAISessionController.ts"
CONTRIBUTION = BROWSER / "pulseAI.contribution.ts"
SERVICE = BROWSER / "pulseAIRendererService.ts"
RENDERER = BROWSER / "pulseAIRenderer.ts"
VIEW_PANE = BROWSER / "pulseAIViewPane.ts"
CSS = BROWSER / "media" / "pulseAI.css"
CHAT_URI = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "chat" / "common" / "model" / "chatUri.ts"

# node is the hard requirement: the table is EXECUTED, not grepped. Either bundler works -- esbuild
# when its binary is native to this host, tsc when it is not -- and the lane runs the same fixtures.
pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="the mapping table is executed in node here; without node this is a host gap to report, never a pass",
)


def _node_json(command: list[str], cwd: Path, timeout: int = 180) -> object:
    """Run node and decode its output as UTF-8 *explicitly*.

    `text=True` decodes with the ambient locale, and a Windows console is cp1252 -- so every
    non-ASCII character in a result (the ellipsis in 'Working…', the minus sign in '+4 −1') arrives as
    mojibake and an honest comparison fails. Reported from the owner's laptop at gate B: 4 parity
    tests red, the projection itself innocent. Never let a subprocess inherit the console's opinion
    about bytes.
    """
    proc = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL,
                          timeout=timeout, cwd=str(cwd))
    if proc.returncode != 0:
        pytest.fail(f"runner failed: {proc.stderr.decode('utf-8', 'replace').strip()[:900]}")
    return json.loads(proc.stdout.decode("utf-8"))


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _esbuild_usable() -> bool:
    if not ESBUILD.exists():
        return False
    try:
        probe = subprocess.run([str(ESBUILD), "--version"], capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", stdin=subprocess.DEVNULL, timeout=60)
    except OSError:
        return False          # e.g. WinError 193: the shim is a POSIX script, not an executable
    return probe.returncode == 0


def _transpile(source: Path, workdir: Path) -> Path:
    """Fallback that needs no native binary: tsc emits the whole import closure as ESM."""
    tsc = next((path for path in TSC_CANDIDATES if path.exists()), None)
    if tsc is None:
        raise RuntimeError("neither a runnable esbuild nor a typescript package to transpile with (npm install)")
    out_dir = workdir / "ts-out"
    proc = subprocess.run(
        ["node", str(tsc), str(source), "--rootDir", str(SRC), "--outDir", str(out_dir),
         "--target", "es2022", "--module", "esnext", "--moduleResolution", "bundler",
         "--skipLibCheck"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=600,
    )
    # tsc reports type errors in the files it transpiles (base/ has none of the repo's @types here)
    # and still emits; the emitted file is the contract, so the exit code is not consulted.
    emitted = out_dir / source.relative_to(SRC).with_suffix(".js")
    if not emitted.exists():
        pytest.fail(f"tsc emitted nothing for {source.name}: {(proc.stdout + proc.stderr).strip()[:600]}")
    (out_dir / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    return emitted


def _load(source: Path, workdir: Path) -> str:
    """Return an ESM specifier node can import, relative to `workdir`: esbuild's single-file bundle
    when its binary is native to this host, otherwise tsc's emitted tree -- whose modules sit at
    their source-relative depth, so the specifier is a path and not a bare filename."""
    if _esbuild_usable():
        out = workdir / f"{source.stem}.mjs"
        proc = subprocess.run(
            [str(ESBUILD), str(source), "--bundle", "--format=esm", f"--outfile={out}",
             "--log-level=warning", "--platform=node"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL, timeout=180,
        )
        if proc.returncode == 0 and out.exists():
            return f"./{out.name}"
        print(f"esbuild unusable ({proc.stderr.strip()[:200]}); falling back to tsc")
    try:
        return f"./{_transpile(source, workdir).relative_to(workdir).as_posix()}"
    except RuntimeError as error:
        pytest.skip(f"no usable loader on this host: {error}")


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
    spec = _load(PROJECTION, tmp_path)
    script = tmp_path / "projection.mjs"
    script.write_text(RUNNER % spec, encoding="utf-8")
    cases = tmp_path / "fixtures.json"
    cases.write_text(json.dumps(fixtures), encoding="utf-8")
    return _node_json(["node", str(script), str(cases)], tmp_path)


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


def test_no_lane_asks_the_console_how_to_read_utf8():
    """Both Windows rounds died in this file's harness, once per encoding assumption.

    A `subprocess.run(..., text=True)` with no explicit `encoding` decodes node's UTF-8 through the
    ambient locale: cp1252 in one report, cp1253 in another (the ellipsis came back as 'ΓÇª'), and a
    truncation test failed on length 92 vs 90 rather than on behaviour. Pinned at source level so it
    fails on ANY host, including one whose locale happens to be UTF-8 and would hide it.
    """
    offenders = []
    for path in (Path(__file__), Path(__file__).with_name("test_hermes_activity_parity.py")):
        text = path.read_text(encoding="utf-8")
        for call in re.findall(r"subprocess\.run\((?:.|\n)*?\)\n", text):
            if "text=True" in call and 'encoding="utf-8"' not in call:
                offenders.append(f"{path.name}: {call.strip().splitlines()[0][:60]}")
    assert not offenders, offenders
    assert "def _node_json(" in text, "the parity lanes must decode bytes as UTF-8 explicitly"


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
