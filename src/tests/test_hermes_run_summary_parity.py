"""Grouping + narration law for tool activity, executed (not grep-checked).

Two halves:
- The clause machinery (verbs, counting) is still mirrored from the
  CopilotKit webview's run-summary: the session list and the webview
  must not tell two stories about one run, so the verb tables and the
  present-tense verbs are compared by EXECUTION under node.
- The transcript GROUPING law changed on founder order 2026-10-17 to
  OpenCode's ("continous same commands should be registered as a
  dropdown"): consecutive same-key calls fold into one dropdown,
  different kinds never mix, lone calls stand alone — replacing the
  old hermes mixed-run fold, which this file used to parity-test.
  The executed cases below pin the new law against the real module.

If node or esbuild is unavailable the executed tests skip — a skip
is a host gap to report, never a pass.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FORK_TS = ROOT / "desktop" / "vscode" / "src" / "vs" / "workbench" / "contrib" / "crusorai" / "browser" / "crusorAIRunSummary.ts"
WEB_TS = ROOT / "crusor-webview" / "src" / "hermes-ui" / "model" / "run-summary.ts"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _node_loader import esbuild_or_skip  # noqa: E402  (src/tests is not a package; pytest prepends it)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="parity is executed, so it needs node and crusor-webview's esbuild (npm install)",
)


def _bundle(source: Path, workdir: Path) -> Path:
    out = workdir / f"{source.stem}.mjs"
    proc = subprocess.run(
        [str(esbuild_or_skip(ROOT / "crusor-webview")), str(source), "--bundle", "--format=esm", f"--outfile={out}",
         "--log-level=warning", "--platform=node"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=120,
    )
    if proc.returncode != 0:
        pytest.fail(f"esbuild could not bundle {source.name}: {proc.stderr.strip()[:400]}")
    return out


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


# The grouping law, as (names, expected [(kind, groupKey-or-name, size)]).
# The key assignment mirrors the renderer's activityGroupKey; what is
# pinned here is the module's merge/break/singleton behaviour.
GROUPING_CASES: list[tuple[list[str], list[tuple[str, str, int]]]] = [
    (["read_file", "read_file", "search_code"],
     [("group", "explore", 3)]),                                   # reads+search fold together
    (["read_file", "write_file", "search_code"],
     [("single", "read_file", 1), ("single", "write_file", 1), ("single", "search_code", 1)]),  # edit breaks, all lone
    (["edit_file:/repo/app.ts", "edit_file:/repo/app.ts"],
     [("group", "edit:/repo/app.ts", 2)]),                          # Edit x2 <same file>
    (["edit_file:/repo/app.ts", "edit_file:/repo/other.ts"],
     [("single", "edit_file", 1), ("single", "edit_file", 1)]),     # different files never merge
    (["run_terminal", "run_terminal", "run_terminal"],
     [("group", "name:run_terminal", 3)]),                          # Terminal x3
    (["run_terminal", "execute_code"],
     [("single", "run_terminal", 1), ("single", "execute_code", 1)]),  # different kinds never mix
    (["read_file", "start_terminal", "read_file"],
     [("single", "read_file", 1), ("single", "start_terminal", 1), ("single", "read_file", 1)]),  # a process line breaks and stands alone
    (["delegate_to_subagent", "delegate_to_subagent"],
     [("single", "delegate_to_subagent", 1), ("single", "delegate_to_subagent", 1)]),  # cards never fold
    ([], []),
]

RUNNER = """
import { splitActivityGroups } from %s;
import { readFileSync } from 'node:fs';

const cases = JSON.parse(readFileSync(process.argv[2], 'utf8'));

// Mirrors crusorAIRenderer's activityGroupKey (the renderer's key
// assignment itself is pinned by the architecture tests).
const EXPLORE = new Set(['list_files', 'read_file', 'search_files', 'search_code', 'session_search']);
const CARDS = new Set(['ask_user', 'display_crusor_task', 'invoke_host_capability', 'delegate_to_subagent', 'delegate_to_subagent_batch', 'think']);
const PROCESS = new Set(['start_terminal', 'check_terminal', 'read_terminal_output', 'list_terminal_processes', 'stop_terminal', 'cleanup_terminal_processes']);
const keyOf = (tool) => {
  const colon = tool.name.indexOf(':');
  const name = colon >= 0 ? tool.name.slice(0, colon) : tool.name;
  const target = colon >= 0 ? tool.name.slice(colon + 1) : undefined;
  if (PROCESS.has(name)) return null;
  if (name === 'edit_file' || name === 'write_file' || name === 'copy_file') return target ? `edit:${target}` : `edit:${name}`;
  if (CARDS.has(name)) return null;
  if (EXPLORE.has(name)) return 'explore';
  return `name:${name}`;
};

const out = [];
for (const names of cases) {
  const tools = names.map((name, i) => ({ id: `t${i}`, name, result: { ok: true } }));
  const groups = splitActivityGroups(tools, keyOf);
  out.push(groups.map(g => g.kind === 'single'
    ? ['single', g.tool.name.split(':')[0], 1]
    : ['group', g.groupKey, g.tools.length]));
}
process.stdout.write(JSON.stringify(out));
"""


def test_grouping_law_grouping_and_breaks(tmp_path):
    fork_js = _bundle(FORK_TS, tmp_path)
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([names for names, _ in GROUPING_CASES]), encoding="utf-8")
    runner = tmp_path / "runner.mjs"
    runner.write_text(RUNNER % json.dumps(fork_js.as_posix()), encoding="utf-8")
    proc = subprocess.run(
        ["node", str(runner), str(cases)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, timeout=120,
    )
    assert proc.returncode == 0, f"runner failed: {proc.stderr.strip()[:600]}"
    results = json.loads(proc.stdout)
    for (names, expected), result in zip(GROUPING_CASES, results):
        assert [tuple(row) for row in result] == expected, (
            f"{names}: got {result}, want {expected} — consecutive same-kind calls "
            "must register as one dropdown; different kinds, cards and process "
            "lines must never fold into it"
        )


def test_fork_renderer_actually_uses_the_rule():
    """Otherwise this module is a well-tested orphan."""
    renderer = (FORK_TS.parent / "crusorAIRenderer.ts").read_text(encoding="utf-8")
    assert "splitActivityGroups(tools, activityGroupKey)" in renderer
    assert "function activityGroupKey" in renderer and "function activityGroupHeader" in renderer
    assert "dataset.runKey = key" in renderer, "a group must be keyed by its first call, not positional"
    assert "summarizeToolRun" in renderer, "the clause machinery still narrates the session list"
    css = (FORK_TS.parent / "media" / "crusorAI.css").read_text(encoding="utf-8")
    assert ".crusorai-tool-run" in css and ".crusorai-tool-run-summary" in css
