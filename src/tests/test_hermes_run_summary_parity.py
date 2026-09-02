"""The right panel and the CopilotKit surface must not tell two stories about one run.

Both implementations are *executed* here (esbuild-transpiled, run under node) rather than
grep-compared: grouping, ordering and clause shape are behaviour, and a regex only proves
someone wrote a word. If node or esbuild is unavailable the test skips -- a skip is a host
gap to report, never a pass.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORK_TS = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "pulseai" / "browser" / "pulseAIRunSummary.ts"
WEB_TS = ROOT / "pulse-webview" / "src" / "hermes-ui" / "model" / "run-summary.ts"
ESBUILD = ROOT / "pulse-webview" / "node_modules" / ".bin" / "esbuild"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not ESBUILD.exists(),
    reason="parity is executed, so it needs node and pulse-webview's esbuild (npm install)",
)


def _bundle(source: Path, workdir: Path) -> Path:
    out = workdir / f"{source.stem}.mjs"
    proc = subprocess.run(
        [str(ESBUILD), str(source), "--bundle", "--format=esm", f"--outfile={out}",
         "--log-level=warning", "--platform=node"],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120,
    )
    if proc.returncode != 0:
        pytest.fail(f"esbuild could not bundle {source.name}: {proc.stderr.strip()[:400]}")
    return out


# Tool sequences that pin the rule, not the wording: (names, which index is still pending)
SEQUENCES: list[tuple[list[str], int | None]] = [
    (["read_file", "read_file", "search_code"], None),          # one run
    (["read_file", "write_file", "search_code"], None),         # card splits it in half
    (["run_terminal", "run_terminal", "run_terminal"], None),   # counting beats naming
    (["run_terminal", "run_terminal", "run_terminal"], 2),      # ...unless it is live
    (["think", "read_file"], None),
    (["write_file"], None),
    (["ask_user", "read_file"], None),
    ([], None),
]

RUNNER = """
import { splitRunGroups, summarizeToolRun, toolPresentVerb } from %s;
import { summarizeToolRun as webSummarize, toolPresentVerb as webVerb } from %s;
import { readFileSync } from 'node:fs';

const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const basename = value => {
  if (!value) { return undefined; }
  const text = String(value);
  const cut = Math.max(text.lastIndexOf('/'), text.lastIndexOf('\\\\'));
  return cut >= 0 ? text.slice(cut + 1) : text;
};

const out = [];
for (const item of cases) {
  const names = item.names;
  // Same payload both surfaces, in each one's own shape.
  const forkTools = names.map((name, i) => ({
    id: `t${i}`, name,
    state: item.pending === i ? 'running' : 'passed',
    arguments: { path: 'src/deep/dir/thing.ts', command: 'pytest -q', query: 'auth' },
    result: item.pending === i ? undefined : { ok: true },
  }));
  const webTools = names.map((name, i) => ({
    toolCallId: `t${i}`, toolName: name,
    args: { path: 'src/deep/dir/thing.ts', command: 'pytest -q', query: 'auth' },
    result: item.pending === i ? undefined : { ok: true },
  }));

  const groups = splitRunGroups(forkTools);
  const forkRuns = groups.filter(g => g.kind === 'run')
    .map(g => ({
      key: g.tools[0].id,
      start: g.start,
      size: g.tools.length,
      summary: summarizeToolRun(g.tools, item.pending !== null && g.tools.some(t => t.state === 'running'), t => basename(t.arguments?.path ?? t.arguments?.command ?? t.arguments?.query)),
    }));
  const webRuns = [];
  let index = 0;
  for (const g of groups) {
    const size = g.kind === 'run' ? g.tools.length : 1;
    if (g.kind === 'run') {
      webRuns.push({
        key: forkTools[g.start].id,
        start: g.start,
        size,
        summary: webSummarize(webTools.slice(g.start, g.end + 1), item.pending !== null && forkTools.slice(g.start, g.end + 1).some(t => t.state === 'running')),
      });
    }
    index += size;
  }

  out.push({
    kinds: groups.map(g => g.kind),
    fork: forkRuns,
    web: webRuns,
    verbs: names.map(n => [toolPresentVerb(n), webVerb(n)]),
  });
}
process.stdout.write(JSON.stringify(out));
"""

COPY_RE = re.compile(
    r"^\s*(delegate|edit|explore|other|run):\s*\{\s*noun:\s*\['([^']+)',\s*'([^']+)'\],\s*past:\s*'([^']+)',\s*present:\s*'([^']+)'",
    re.MULTILINE,
)


def _copy_table(path: Path) -> dict[str, tuple[str, str, str, str]]:
    found = {}
    for match in COPY_RE.finditer(path.read_text(encoding="utf-8")):
        found[match.group(1)] = match.group(2, 3, 4, 5)
    return found


def test_both_surfaces_share_one_verb_table():
    """Copy drift is the quiet failure: same run, two different grey lines."""
    fork = _copy_table(FORK_TS)
    web = _copy_table(WEB_TS)
    assert fork, "no category copy parsed from the fork module"
    assert web, "no category copy parsed from the webview module"
    assert set(fork) == set(web), f"categories diverge: {sorted(set(fork) ^ set(web))}"
    for category, copy in web.items():
        assert fork[category] == copy, (
            f"{category}: fork {fork[category]} vs webview {copy} — verbs must match exactly"
        )


def test_grouping_and_clauses_agree_between_surfaces(tmp_path):
    fork_js = _bundle(FORK_TS, tmp_path)
    web_js = _bundle(WEB_TS, tmp_path)
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([
        {"names": names, "pending": pending} for names, pending in SEQUENCES
    ]), encoding="utf-8")
    runner = tmp_path / "runner.mjs"
    runner.write_text(
        RUNNER % (json.dumps(fork_js.as_posix()), json.dumps(web_js.as_posix())),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(runner), str(cases)],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120,
    )
    assert proc.returncode == 0, f"runner failed: {proc.stderr.strip()[:600]}"
    results = json.loads(proc.stdout)

    for (names, pending), result in zip(SEQUENCES, results):
        assert result["fork"] == result["web"], (
            f"{names} (pending={pending}): fork runs {result['fork']} vs webview {result['web']}"
        )
        for verb in result["verbs"]:
            assert verb[0] == verb[1], f"present-tense verb differs for a tool in {names}: {verb}"


def test_a_card_breaks_a_run_and_a_run_is_keyed_by_its_first_call(tmp_path):
    """The two rules most likely to be 'improved' away, pinned directly."""
    fork_js = _bundle(FORK_TS, tmp_path)
    probe = tmp_path / "probe.mjs"
    probe.write_text(
        "import { splitRunGroups } from %s;\n"
        "const t = (id, name) => ({ id, name, result: {} });\n"
        "const groups = splitRunGroups([\n"
        "  t('a', 'read_file'), t('b', 'run_terminal'), t('c', 'write_file'),\n"
        "  t('d', 'search_code'), t('e', 'read_file'),\n"
        "]);\n"
        "process.stdout.write(JSON.stringify(groups.map(g => ({ kind: g.kind, key: g.kind === 'run' ? g.tools[0].id : g.tool.id, size: g.kind === 'run' ? g.tools.length : 1 }))));\n"
        % json.dumps(fork_js.as_posix()),
        encoding="utf-8",
    )
    proc = subprocess.run(
        ["node", str(probe)], capture_output=True, text=True,
        stdin=subprocess.DEVNULL, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[:400]
    assert json.loads(proc.stdout) == [
        {"kind": "run", "key": "a", "size": 2},
        {"kind": "card", "key": "c", "size": 1},
        {"kind": "run", "key": "d", "size": 2},
    ], "read+run must fold, the edit must stay a card in place, then a NEW run keyed by its own first call"


def test_fork_renderer_actually_uses_the_rule():
    """Otherwise this module is a well-tested orphan."""
    renderer = (FORK_TS.parent / "pulseAIRenderer.ts").read_text(encoding="utf-8")
    assert "splitRunGroups" in renderer and "summarizeToolRun" in renderer
    assert "for (const tool of model.tools) { tools.append(toolRow(tool, host, openTools)); }" not in renderer
    assert "dataset.runKey = key" in renderer, "a run must be keyed, not positional"
    css = (FORK_TS.parent / "media" / "pulseAI.css").read_text(encoding="utf-8")
    assert ".pulseai-tool-run" in css and ".pulseai-tool-run-summary" in css
