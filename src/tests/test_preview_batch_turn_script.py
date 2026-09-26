"""CrusorAI — ``scripts/preview_batch_turn.py`` (the preview batch harness).

This script is how a preview fix batch gets tested against a real agent without the IDE, so the
things worth pinning are the ones that made its first live run hard to trust:

* **its output must appear as it happens.** Piped, Python block-buffers stdout, and a slow run then
  looks like a hang: the first live run was reported as "600s with zero log output", which hid a turn
  that was actually progressing. The fix runs at import, so this test asserts it on import;
* **its `--diff` must never lie.** It shelled out to `git diff --stat`, which exits 128 outside a
  repository, and because only the exception was caught the run reported "no changes" while the agent
  had in fact edited the CSS. The evidence now comes from the filesystem, so the test drives
  add/modify/delete directly;
* **its demo batch must match the fixture.** The batch hardcodes the classes, text and attributes of
  ``preview-lab/demo-app``; if the fixture drifts, the prompt sends fingerprints that are not in the
  page and the agent has nothing to grep for — a silent, confusing failure.

Importing the module is safe: everything runs under ``main()``.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "preview_batch_turn.py"
FIXTURE = REPO_ROOT / "preview-lab" / "demo-app"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("preview_batch_turn", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------- output must not be buffered

def test_importing_the_harness_enables_line_buffering() -> None:
    """The real assertion is about a *pipe*, so it runs in a child process with piped stdout.

    In-process, pytest replaces stdout with its own object and the question is not answered. A child
    whose stdout is a pipe has ``line_buffering == False`` unless something changes it, which is
    exactly the state the first live run was in.
    """
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('h', r'{SCRIPT}')\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(mod)\n"
        "print('LINE_BUFFERING', sys.stdout.line_buffering)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], cwd=str(REPO_ROOT), capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert "LINE_BUFFERING True" in done.stdout, (
        f"stdout is buffered when piped — a slow run would print nothing until it exits: {done.stdout!r}"
    )


# --------------------------------------------------------------- the diff must be honest

def test_describe_changes_detects_modified_added_and_removed(harness) -> None:
    before = {"styles.css": b"a\nb\n", "keep.txt": b"same\n"}
    after = {"styles.css": b"a\nB\nc\n", "keep.txt": b"same\n", "new.txt": b"hello\n"}
    report = harness.describe_changes(before, after)
    assert "M styles.css" in report
    assert "+2 -1" in report, report          # b -> B, plus the new c line
    assert "A new.txt" in report
    assert "keep.txt" not in report, "an unchanged file must not be reported as changed"


def test_describe_changes_reports_a_deletion(harness) -> None:
    report = harness.describe_changes({"gone.txt": b"x\n"}, {})
    assert "D gone.txt" in report


def test_describe_changes_says_so_honestly_when_nothing_changed(harness) -> None:
    report = harness.describe_changes({"a.css": b"x\n"}, {"a.css": b"x\n"})
    assert report.startswith("no file changed"), report
    assert "1 file(s) compared" in report, "…and it must say what it actually looked at"


def test_snapshot_reads_content_and_skips_dependency_noise(harness, tmp_path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.css").write_text("body{}\n", encoding="utf-8")
    for noise in ("node_modules", ".git", "__pycache__", ".venv"):
        (tmp_path / noise).mkdir()
        (tmp_path / noise / "junk.js").write_text("junk", encoding="utf-8")

    files = harness.snapshot(tmp_path)
    assert set(files) == {"src/app.css"}, files
    assert files["src/app.css"] == b"body{}\n"


def test_git_diff_stat_is_none_outside_a_repository(harness, tmp_path) -> None:
    """The bug: git exits 128 with empty stdout here, and the old code called that "no changes"."""
    assert harness.git_diff_stat(tmp_path) is None


def test_git_diff_stat_reports_inside_a_repository(harness, tmp_path) -> None:
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git is not installed")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "file.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path, check=True,
    )
    (tmp_path / "file.txt").write_text("one\ntwo\n", encoding="utf-8")
    stat = harness.git_diff_stat(tmp_path)
    assert stat is not None and "file.txt" in stat, stat


# --------------------------------------------------------------- the demo batch must fit the fixture

def test_demo_batch_fingerprints_exist_in_the_fixture(harness) -> None:
    """Every fingerprint the demo prompt sends must be greppable in the page it describes.

    Drift here is invisible and expensive: the model gets a class name that is not in the file, its
    searches come back empty, and the failure looks like a prompt-engineering problem instead of a
    stale fixture.
    """
    markup = " ".join(
        path.read_text(encoding="utf-8")
        for path in (FIXTURE / "index.html", FIXTURE / "styles.css", FIXTURE / "app.js")
    )
    fixes = harness.demo_batch()["fixes"]
    assert fixes, "the demo batch is empty"

    for fix in fixes:
        element = fix["element"]
        for css_class in element["classes"]:
            assert css_class in markup, f"{fix['id']}: class {css_class!r} is not in the fixture"
        text = str(element.get("text") or "")[:24]
        if text:
            assert text in markup, f"{fix['id']}: text {text!r} is not in the fixture"
        for attr in element["fingerprint"].get("attrs") or []:
            assert attr["value"] in markup, f"{fix['id']}: {attr['value']!r} is not in the fixture"

    # The selector shown to the model should at least name elements the fixture has.
    selectors = [fix["element"]["selector"] for fix in fixes]
    assert any("btn-primary" in selector for selector in selectors)
    assert any("hero-title" in selector for selector in selectors)


def test_demo_batch_is_a_complete_batch_for_the_frame_builder(harness) -> None:
    """It must be usable as-is: the window's batch shape, with the fields the prompt reads."""
    batch = harness.demo_batch()
    for key in ("sessionId", "target", "targetLabel", "kind", "viewport", "fixes"):
        assert key in batch, key
    for fix in batch["fixes"]:
        assert fix["instruction"].strip()
        assert fix["element"]["rect"]["width"] > 0
        assert fix["element"]["viewport"]["width"] > 0


def test_demo_mode_never_points_at_the_repository(harness) -> None:
    """`--demo` copies the fixture to a temp dir; the repo must not be the editing target."""
    assert FIXTURE.is_dir()
    assert harness.FIXTURE == FIXTURE
    # The copy is made with tempfile.mkdtemp, so assert the mechanism the script relies on.
    import tempfile

    made = Path(tempfile.mkdtemp(prefix="crusor-preview-agent-test-"))
    try:
        assert made != FIXTURE
        assert os.path.commonpath([str(made), str(FIXTURE)]) != str(FIXTURE)
    finally:
        made.rmdir()
