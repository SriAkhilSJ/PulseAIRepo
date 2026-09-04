"""The fork's tail activity row, glyphs and thinking row must be Hermes', not Hermes-adjacent.

Split deliberately:

* the row's *math* (signature, narrating-tool suppression, elapsed formatting) is EXECUTED here
  -- esbuild bundles the fork module and the webview module and node runs both over identical
  fixtures, because that logic is behaviour and a grep only proves someone wrote a word;
* the *constants* and the *icon path data* are compared as literals, because a compile-time
  constant has no behaviour to run and a copied SVG path is only equal byte-for-byte or not at all;
* the wiring is asserted structurally, since a row that exists but is never mounted paints nothing.

A skipped test here is a host gap to report (no node, no esbuild, no pinned Hermes checkout), never
a pass.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BROWSER = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "pulseai" / "browser"
COMMON = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "pulseai" / "common"
HERMES_UI = ROOT / "pulse-webview" / "src" / "hermes-ui"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node_loader import esbuild_or_skip  # noqa: E402  (src/tests is not a package; pytest prepends it)

FORK_ACTIVITY = BROWSER / "pulseAIActivity.ts"
FORK_ICONS = BROWSER / "pulseAIIcons.ts"
FORK_RENDERER = BROWSER / "pulseAIRenderer.ts"
FORK_CATALOG = COMMON / "pulseAIToolCatalog.ts"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="the row's maths are executed here, so this needs node (and an esbuild that executes)",
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


def _bundle(source: Path, workdir: Path) -> Path:
    out = workdir / f"{source.stem}.mjs"
    proc = subprocess.run(
        [str(esbuild_or_skip(ROOT / "pulse-webview")), str(source), "--bundle", "--format=esm", f"--outfile={out}",
         "--log-level=warning", "--platform=node"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=180,
    )
    if proc.returncode != 0:
        pytest.fail(f"esbuild could not bundle {source.name}: {proc.stderr.strip()[:500]}")
    return out


def _run(node_script: Path, workdir: Path, payload: object) -> object:
    cases = workdir / "fixtures.json"
    cases.write_text(json.dumps(payload), encoding="utf-8")
    return _node_json(["node", str(node_script), str(cases)], workdir)


# Same fixture list feeds BOTH surfaces: text lengths, part counts and settled-call counts are the
# three things the signature is made of, so these cover each moving independently.
PART_FIXTURES: list[list[dict[str, object]]] = [
    [],
    [{"type": "text", "text": ""}],
    [{"type": "text", "text": "hi"}],
    [{"type": "reasoning", "text": "let me look"}, {"type": "text", "text": "hi"}],
    [{"type": "tool-call", "toolName": "read_file", "result": None}],
    [{"type": "tool-call", "toolName": "read_file", "result": {"ok": True}}],
    [{"type": "tool-call", "toolName": "think", "result": None}],
    [{"type": "tool-call", "toolName": "think", "result": "planning"},
     {"type": "tool-call", "toolName": "search_code", "result": None}],
    [{"type": "tool-call", "toolName": "run_terminal", "result": {"exit": 0}},
     {"type": "tool-call", "toolName": "run_terminal", "result": {"exit": 1}},
     {"type": "text", "text": "two runs"}],
]
# `result: None` (i.e. the key present but null) is a settled call upstream reads as `!== undefined`
# only when absent; the fork maps a settled tool state to a present value, so the fixture set has to
# contain the absent case explicitly, which `del` in the runner cannot express -- hence two shapes.
UNSETTLED = [{"type": "tool-call", "toolName": "write_file"}]

SIGNED_RUNNER = """
import { activitySignature, toolNarratesWait, TURN_QUIET_S } from '%s';
import { activitySignature as webSignature, toolNarratesWait as webNarrates, TURN_QUIET_S as webQuiet } from '%s';
import { readFileSync } from 'node:fs';

const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const strip = parts => parts.map(part => {
  const copy = { ...part };
  // JSON cannot carry "absent", so the fixture uses a marker the surfaces never see.
  if (copy.result === '__absent__') { delete copy.result; }
  return copy;
});

process.stdout.write(JSON.stringify(cases.map(parts => {
  const forkInput = strip(parts);
  const webInput = strip(parts);
  return {
    fork: [activitySignature(forkInput), toolNarratesWait(forkInput) ? 1 : 0],
    web: [webSignature(webInput), webNarrates(webInput) ? 1 : 0],
    quiet: [TURN_QUIET_S, webQuiet],
  };
})));
"""


def test_signature_and_suppression_are_the_same_function_on_both_surfaces(tmp_path):
    fork = _bundle(FORK_ACTIVITY, tmp_path)
    web = _bundle(HERMES_UI / "model" / "turn-activity.ts", tmp_path)
    script = tmp_path / "signed.mjs"
    script.write_text(SIGNED_RUNNER % (f"./{fork.name}", f"./{web.name}"), encoding="utf-8")

    results = _run(script, tmp_path, [*[p for p in PART_FIXTURES], UNSETTLED])
    for index, result in enumerate(results):
        assert result["fork"] == result["web"], f"fixture {index}: {PART_FIXTURES[index] if index < len(PART_FIXTURES) else UNSETTLED} -> {result}"
        assert result["quiet"][0] == result["quiet"][1] == 2, f"fixture {index}: quiet threshold drifted: {result['quiet']}"


ELAPSED_RUNNER = """
import { formatElapsed as forkFormat, elapsedSeconds as forkElapsed } from '%s';
import { formatElapsed as webFormat } from '%s';

import { readFileSync } from 'node:fs';
const seconds = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const results = seconds.map(s => [forkFormat(s), webFormat(s)]);
// [now, origin, expected whole seconds] -- the third row is a clock that went backwards,
// which the fork must clamp to zero rather than print as a negative age.
const origins = [[4500, 0, 4], [0, 0, 0], [1000, 4500, 0]];
for (const [now, origin, want] of origins) {
  results.push([forkElapsed(now, origin), want, webFormat(want)]);
}
results.push([forkElapsed(0, undefined), 0, webFormat(0)]);
process.stdout.write(JSON.stringify(results));
"""


def test_elapsed_formatting_and_origin_math_agree(tmp_path):
    fork = _bundle(FORK_ACTIVITY, tmp_path)
    web = _bundle(HERMES_UI / "model" / "activity-timer.ts", tmp_path)
    script = tmp_path / "elapsed.mjs"
    script.write_text(ELAPSED_RUNNER % (f"./{fork.name}", f"./{web.name}"), encoding="utf-8")

    seconds = [0, 1, 2, 59, 60, 61, 119, 600]
    results = _run(script, tmp_path, seconds)
    for index, (value, format_seconds) in enumerate(zip(seconds, results[:len(seconds)])):
        assert format_seconds[0] == format_seconds[1], f"{format(value)}s formats differently: {format_seconds}"
    assert results[:len(seconds)][0][0] == "0s", "a turn that just started must read 0s, not blank"
    assert len(results) == len(seconds) + 4, f"expected {len(seconds)} formats + 3 origins + the no-origin row, got {len(results)}"
    for row in results[len(seconds):len(seconds) + 3]:
        assert row[0] == row[1], f"elapsedSeconds(now, origin) disagreeing with the fixture: {row}"
        assert row[2] == f"{row[1]}s" if row[1] < 60 else row[2] == f"{row[1] // 60}:{row[1] % 60:02d}", row
    assert results[-1][0] == 0, "no origin must read zero, never a negative or the epoch"
    assert results[-1][1] == 0


def test_reveal_delay_and_compaction_label_are_the_webviews_constants():
    """Compile-time constants have no behaviour to execute, so compare them literally.

    `DRAFTING_REVEAL_MS` is what stops a fast tool from flashing a label; `COMPACTION_LABEL` is
    the one hint that outranks a draft. Both must be the *same numbers and words* the webview
    renders with, or the two surfaces disagree about when a row appears at all.
    """
    fork = FORK_ACTIVITY.read_text(encoding="utf-8")
    status = (HERMES_UI / "components" / "status-line.tsx").read_text(encoding="utf-8")
    fork_reveal = int(re.search(r"export const DRAFTING_REVEAL_MS = (\d+)", fork).group(1))
    web_reveal = int(re.search(r"export const DRAFTING_REVEAL_MS = (\d+)", status).group(1))
    assert fork_reveal == web_reveal == 200, f"reveal delay drifted: fork {fork_reveal}, web {web_reveal}"
    for source, label in ((fork, "fork"), (status, "web")):
        assert "Summarizing thread" in source, f"{label} lost the compaction label"


UPSTREAM_ICON_TABLE = Path("apps/desktop/src/components/ui/tool-icon.tsx")


def _path_table(text: str, var_name: str) -> dict[str, str]:
    block = text.split(f"{var_name}", 1)[1]
    block = block[block.index("{") + 1:block.index("\n}")]
    # Tolerant of either house style: upstream indents with two spaces and sometimes breaks the
    # value onto its own line, the fork uses one tab. Path data never contains a quote.
    entries = re.findall(r"'?([a-z][a-z-]*)'?:\s*'([^']+)'", block)
    return dict(entries)


def test_solid_glyphs_are_upstreams_path_data_verbatim():
    """A copied icon is only faithful byte-for-byte; a redrawn one is a different icon.

    Upstream inlines Phosphor "fill" paths because Codicons are an outline *font* -- a filled look
    cannot be derived from it -- so the fork either carries those exact paths or it is rendering a
    different glyph at a different weight.
    """
    ref = Path(os.environ.get("HERMES_REF") or "/home/user/.hermes-ref")
    upstream = ref / UPSTREAM_ICON_TABLE
    if not upstream.is_file():
        pytest.skip(f"no pinned hermes-agent checkout at {ref} (set $HERMES_REF) -- the icon table has nothing to compare against")
    assert _path_table(upstream.read_text(encoding="utf-8"), "const TOOL_ICON_PATHS") == \
        _path_table(FORK_ICONS.read_text(encoding="utf-8"), "TOOL_ICON_PATHS"), \
        "fork icon path data diverged from hermes-agent's table"


def _webview_tool_meta() -> dict[str, str]:
    text = (HERMES_UI / "model" / "fallback-model.ts").read_text(encoding="utf-8")
    meta = dict(re.findall(r"^\s{2}([a-z_0-9]+):\s*\{\s*icon:\s*'([a-z-]+)'", text, flags=re.M))
    # browser_* is assigned by the loop below TOOL_META in the same file; mirror its rule.
    for action in ("click", "evaluate", "hover", "navigate", "screenshot", "select", "snapshot", "type"):
        meta[f"browser_{action}"] = "file-media" if action == "screenshot" else "globe"
    return meta


def _fork_catalog_icons() -> dict[str, str]:
    text = FORK_CATALOG.read_text(encoding="utf-8")
    return dict(re.findall(r"^\t([a-z_0-9]+): tool\('[^']+', '[a-z-]+', '([a-z-]+)'", text, flags=re.M))


def test_fork_glyph_names_are_the_ones_the_webview_resolves():
    """Same tool, same glyph key -- so the solid/fallback decision is shared, not re-guessed."""
    fork, web = _fork_catalog_icons(), _webview_tool_meta()
    assert fork, "no entries parsed: the catalog's shape changed and this pin needs updating too"
    mismatched = {name: (icon, web.get(name)) for name, icon in fork.items() if web.get(name) and web[name] != icon}
    assert not mismatched, f"fork shows a different glyph than the webview: {mismatched}"
    assert "tools" in _path_table(FORK_ICONS.read_text(encoding="utf-8"), "TOOL_ICON_PATHS"), "the generic glyph must be solid"


def test_both_surfaces_mount_the_same_column_and_teardown_the_timers():
    renderer = FORK_RENDERER.read_text(encoding="utf-8")
    assert "function createActivityState" in renderer and "function agentColumn" in renderer
    assert renderer.count("...agentColumn(model, host, openTools, activity, planOpen, setPlanOpen)") == 2, \
        "both the pane and the Manager chat box must come from one column"
    assert "activity.row(model)" in renderer
    assert "activity.sync(model)" in renderer and "activity.dispose()" in renderer, \
        "a ticking row that outlives its mount keeps repainting a dead surface"
    assert "transcript(model, host, openTools)," not in renderer, \
        "the Manager used to bolt the transcript on by itself; the column owns it now"
    for glyph in ("icon('brain')", "renderToolIcon(name)"):
        assert glyph in renderer
    css = (BROWSER / "media" / "pulseAI.css").read_text(encoding="utf-8")
    for rule in (".pulseai-scaffold-pulse", "@keyframes pulseai-breathe", "@keyframes pulseai-sweep",
                 ".pulseai-disclosure-caret", ".pulseai-thought-body"):
        assert rule in css, f"{rule} is not in the stylesheet -- the row would mount unstyled"


MODE_RUNNER = """
import { activityRowMode } from '%s';
import { readFileSync } from 'node:fs';

const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = cases.map(c => activityRowMode({
  parts: c.parts,
  working: c.working,
  awaitingInput: c.awaitingInput,
  toolNarrating: c.toolNarrating,
  hint: c.hint,
  // JSON has no `undefined`; a null here must not read as "a quiet spell started".
  quietSince: c.quietSince ?? undefined,
}));
process.stdout.write(JSON.stringify(out));
"""

# (label, parts, working, awaitingInput, toolNarrating, hint, quietSince, expected)
MODE_CASES = [
    ("turn start, nothing streamed yet", [], True, False, False, "", None, "aui_response-loading"),
    ("same, but the user is being asked", [], True, True, False, "", None, None),
    ("not working at all", [], False, False, False, "", None, None),
    ("streaming text, no name, no quiet spell", [{"type": "text", "text": "hi"}], True, False, False, "", None, None),
    ("streaming text named by a drafting tool", [{"type": "text", "text": "hi"}], True, False, False, "Exploring src/a.py", None, "aui_turn-activity"),
    ("unnamed wait past the quiet threshold", [{"type": "text", "text": "hi"}], True, False, False, "", 1_700_000_000_000, "aui_turn-activity"),
    ("a tool row is narrating the wait already", [{"type": "tool-call", "toolName": "run_terminal"}], True, False, True, "Running tests", 1_700_000_000_000, None),
    ("quiet spell, nothing narrating it", [{"type": "tool-call", "toolName": "run_terminal", "result": {}}], True, False, False, "", 1_700_000_000_000, "aui_turn-activity"),
]


def test_row_visibility_follows_upstreams_two_component_rule(tmp_path):
    """`ResponseLoadingIndicator` fires unconditionally pre-first-token; `TurnActivityIndicator`
    waits for a name or a quiet spell; both are off when a tool row is already speaking or the
    turn is paused on a question. Executed, not eyeballed: this is the truth table for the fork's
    own decision function, derived from status.tsx's two render branches.
    """
    fork = _bundle(FORK_ACTIVITY, tmp_path)
    script = tmp_path / "mode.mjs"
    script.write_text(MODE_RUNNER % f"./{fork.name}", encoding="utf-8")

    payload = [{"parts": parts, "working": w, "awaitingInput": a, "toolNarrating": t, "hint": h, "quietSince": q}
               for _, parts, w, a, t, h, q, _ in MODE_CASES]
    results = _run(script, tmp_path, payload)
    for (label, *_expected), got in zip(MODE_CASES, results):
        assert got == _expected[-1], f"{label}: expected {_expected[-1]!r}, got {got!r}"


MEASURE_RUNNER = """
import { elapsedFor, closeMeasurement, measuredDuration } from '%s';

const k = 'thought:s1';
const armed = elapsedFor(k, 1000);
const mid = elapsedFor(k, 5000);
const closed = closeMeasurement(k, 9000);
const afterUnmount = measuredDuration(k);
const reclosed = closeMeasurement(k, 99000);
const neverWatched = measuredDuration('thought:other');
const reopened = elapsedFor(k, 100000);
process.stdout.write(JSON.stringify([armed, mid, closed, afterUnmount, reclosed, neverWatched === undefined, reopened]));
"""


def test_thought_duration_survives_the_repaint_that_measured_it(tmp_path):
    """`Thought for 12s` is only possible if the number lives outside the row: the transcript
    repaints wholesale on every frame, so a duration kept in the widget would reset on each
    repaint and vanish entirely once its row scrolled away. Same registry semantics as upstream's
    `useMeasuredDuration`, without React.
    """
    fork = _bundle(FORK_ACTIVITY, tmp_path)
    script = tmp_path / "measure.mjs"
    script.write_text(MEASURE_RUNNER % f"./{fork.name}", encoding="utf-8")
    armed, mid, closed, remembered, reclosed, unknown, reopened = _run(script, tmp_path, [])
    assert (armed, mid) == (0, 4), f"watching must accumulate from the first sight, got {armed}, {mid}"
    assert closed == 8, f"closing at 9000 from an origin at 1000 must read 8s, got {closed}"
    assert remembered == 8, "the number has to outlive the row that measured it"
    assert reclosed == 8, "closing twice must not restart or inflate the measurement"
    assert unknown, "an unwatched turn has no duration; the row shows no trailing meta rather than a guess"
    assert reopened == 0, "a new thought re-arms rather than inheriting the old count"
    renderer = FORK_RENDERER.read_text(encoding="utf-8")
    assert "activity.thoughtSeconds(model)" in renderer and "liveThoughtSeconds" in renderer
def test_no_progress_line_is_invented_when_there_is_nothing_to_report():
    """Both narrating layers used to claim workspace work that had not happened.

    The renderer fell back to a sentence about inspecting the workspace whenever the assistant had no
    text yet, and the bridge emitted a "preparing context" reasoning frame before the graph ran. On a
    run that failed at the provider, that produced two confident progress lines above "Run failed" --
    the exact shape of progress theatre, and the owner spotted it in a screenshot. Progress copy is only
    allowed to come from a model field or a real event.
    """
    root = Path(__file__).resolve().parents[2]
    inspecting = "Inspecting " + "workspace context"
    preparing = "Preparing " + "workspace context"
    renderer = (root / "desktop/vscode/src/vs/workbench/contrib/pulseai/browser/pulseAIRenderer.ts").read_text(encoding="utf-8")
    bridge = (root / "src/bridge/__main__.py").read_text(encoding="utf-8")
    assert inspecting not in renderer, "assistant copy must not be invented when assistantText is empty"
    assert preparing not in bridge, "the pre-graph liveness frame must not narrate a step that has not run"
    copy_call = re.search(r"element\('div', 'pulseai-assistant-copy[^)]*\)", renderer)
    assert copy_call, "the assistant copy element must still exist -- the fix is to gate it, not delete it (01e09f92 merged the markdown root into this class; the pin follows the call shape)"
    assert "||" not in copy_call.group(0), f"the copy line must render only real text: {copy_call.group(0)}"
    # hermes message-parts port (owner report #4): the guard moved into the
    # turn painter — empty text segments never paint, and the legacy
    # single-block fallback stays emptiness-gated.
    assert "if (!part.text) { return; }" in renderer, "empty text segments never paint"
    assert "if (spec.assistantText && lastTextIndex < 0)" in renderer, "the copy element needs an emptiness guard to survive removal of the fallback"
