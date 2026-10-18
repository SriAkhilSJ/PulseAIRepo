"""Behaviour contracts for the scaffold receipt parser.

The scaffold tools answer with prose receipts whose leading glyph is
the verdict (scaffold_tools.py / target_scaffold.py). The card shows
the receipt's own words — never the glyph, the raw tool name, or the
engine's instructions TO the agent. The parser is a pure function in
crusoraiCardFormat.ts; this runs its EMITTED bundle under node (the
same file the workbench loads) over the engines' real strings.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_MODULE = (
    _REPO
    / "desktop/vscode/out/vs/workbench/contrib/crusorai/browser/crusoraiCardFormat.js"
)

_SCRIPT = """
const { parseScaffoldReceipt } = await import(process.argv[1]);
const cases = [
  "✅ scaffold_nextjs completed at the workspace root. Installed base dependencies plus: ['three']. The `_provided` directory was preserved. Continue with the named copy_file deliverables.",
  "⛔ scaffold_nextjs create step failed (exit 1):\\nnpm ERR! boom",
  "⚠️ scaffold_flutter created the project at the correct root, but `flutter pub get` failed (exit 1). Fix the install before finishing:\\nSome pub output",
  "ℹ️ scaffold_tauri skipped: src-tauri already exists at the workspace root. Inspect the existing project and continue there.",
  "✅ scaffold_flutter completed at the workspace root for platforms android,ios (org com.example). The `_provided` directory was preserved. Next: build and prove it with `verify_target_app` instead of only compiling.",
  "⛔ scaffold_react_native refused unknown template 'weird'. Choose from ['blank', 'tabs'].",
  "plain text, not a receipt",
  "",
];
console.log(JSON.stringify(cases.map((c) => parseScaffoldReceipt(c) ?? null)));
"""


@pytest.fixture(scope="module")
def receipts() -> list:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to run the emitted parser")
    assert _MODULE.is_file(), "emitted crusoraiCardFormat.js must be committed"
    proc = subprocess.run(
        [node, "--input-type=module", "-e", _SCRIPT, _MODULE.as_uri()],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_completed_nextjs_headline_drops_envelope_and_trailer(receipts):
    receipt = receipts[0]
    assert receipt["tone"] == "completed"
    assert receipt["headline"].startswith("completed at the workspace root.")
    assert "scaffold_nextjs" not in receipt["headline"]
    assert "copy_file deliverables" not in receipt["headline"]
    assert "Installed base dependencies plus: ['three']" in receipt["headline"]
    assert "tail" not in receipt


def test_failed_receipt_splits_headline_from_command_output(receipts):
    receipt = receipts[1]
    assert receipt["tone"] == "failed"
    assert receipt["headline"] == "create step failed (exit 1)"
    assert receipt["tail"] == "npm ERR! boom"


def test_partial_receipt_keeps_the_fix_sentence_in_the_headline(receipts):
    receipt = receipts[2]
    assert receipt["tone"] == "partial"
    assert receipt["headline"].endswith("Fix the install before finishing")
    assert receipt["tail"] == "Some pub output"


def test_skipped_receipt_keeps_the_users_advice(receipts):
    receipt = receipts[3]
    assert receipt["tone"] == "skipped"
    assert "Inspect the existing project and continue there." in receipt["headline"]


def test_completed_flutter_trailer_is_stripped(receipts):
    receipt = receipts[4]
    assert receipt["tone"] == "completed"
    assert "verify_target_app" not in receipt["headline"]
    assert "platforms android,ios (org com.example)" in receipt["headline"]


def test_refusal_without_output_has_no_tail(receipts):
    receipt = receipts[5]
    assert receipt["tone"] == "failed"
    assert receipt["headline"].startswith("refused unknown template")
    assert "tail" not in receipt


def test_non_receipts_do_not_parse(receipts):
    assert receipts[6] is None
    assert receipts[7] is None
