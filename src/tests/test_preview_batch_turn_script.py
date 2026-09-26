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
import queue
import subprocess
import sys
import time
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
    """snapshot() is byte-exact, and its output must not depend on the platform's text mode.

    Written with ``write_bytes`` on purpose: ``write_text`` translates ``\n`` to ``\r\n`` on Windows,
    which made the old assertion red on the owner's machine while green here — a test that asserted
    the platform instead of the code. The bytes are the contract; a CRLF file must come back CRLF.
    """
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.css").write_bytes(b"body{}\n")
    (tmp_path / "src" / "legacy.css").write_bytes(b"a{}\r\nb{}\r\n")
    for noise in ("node_modules", ".git", "__pycache__", ".venv"):
        (tmp_path / noise).mkdir()
        (tmp_path / noise / "junk.js").write_text("junk", encoding="utf-8")

    files = harness.snapshot(tmp_path)
    assert set(files) == {"src/app.css", "src/legacy.css"}, files
    assert files["src/app.css"] == b"body{}\n"
    assert files["src/legacy.css"] == b"a{}\r\nb{}\r\n", "snapshot must not normalize line endings"


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
        assert made.resolve() != FIXTURE.resolve()
        # Deliberately NOT os.path.commonpath: on Windows TEMP is on C: and this checkout on D:, and
        # commonpath RAISES ValueError across drives — the test failed there for that reason alone.
        # is_relative_to answers the same question and returns False instead of raising.
        assert made.is_relative_to(Path(tempfile.gettempdir()).resolve())
        assert not made.is_relative_to(FIXTURE.resolve()), "the copy must not land inside the repo"
    finally:
        made.rmdir()


# --------------------------------------------------------------- teardown must reach grandchildren

def test_kill_process_tree_reaches_a_grandchild(harness) -> None:
    """`http.server &` style: the engine starts a process, and killing the engine must take it too.

    A direct-child kill leaves the backgrounded command running — on a real `--workspace` run that is
    a listening server left behind after the harness exits (a field report from run 6). The POSIX
    branch (process group) is asserted fully here; the Windows branch uses `taskkill /T /F`, the same
    technique as `src/context/git_context.py`, and cannot be executed in this sandbox — it is covered
    by the "did not use the direct-child fallback" assertion only.
    """
    if os.name == "nt":
        pytest.skip("process-group semantics are POSIX; the Windows branch uses taskkill /T (unverified here)")

    # A parent that starts a grandchild and waits, printing the grandchild's pid.
    script = (
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        "print(child.pid, flush=True)\n"
        "time.sleep(300)\n"
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    try:
        grandchild_pid = int(parent.stdout.readline().strip())

        def alive(pid: int) -> bool:
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                return False
            return True

        assert alive(grandchild_pid), "the grandchild did not start"

        how = harness.kill_process_tree(parent)
        assert "whole tree" in how, f"fell back to a direct-child kill: {how}"

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and alive(grandchild_pid):
            time.sleep(0.05)
        assert not alive(grandchild_pid), "the grandchild outlived the tree kill — a stray server"
    finally:
        try:
            parent.kill()
        except Exception:
            pass


def test_kill_process_tree_is_safe_on_an_exited_process(harness) -> None:
    done = subprocess.run([sys.executable, "-c", "pass"], timeout=60)
    class _Fake:
        pid = 999_999
        def poll(self):
            return 0 if done.returncode == 0 else None
    assert harness.kill_process_tree(_Fake()) == "already exited"


# ─────────────────────────────────────── the parent's own stdout must survive the run
def _child(body: str) -> str:
    """Source for a child that loads the real harness by path, then runs `body`."""
    return (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('preview_batch_turn', {str(SCRIPT)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        + body
    )


def test_the_parent_survives_a_cp1252_console() -> None:
    """A Windows console is cp1252 when redirected, and this script prints what cp1252 lacks.

    `render()` emits `[tool done] name → result`, and the model's own text carries `…` and curly
    quotes. Printing one of those raised `UnicodeEncodeError` and killed a live run. Encoded in the
    child's own code page: stdout AND stderr must both come back as valid UTF-8 with the arrow
    intact, and stderr must still be line-buffered (the reconfigure must not drop that).
    """
    if sys.version_info < (3, 7):  # pragma: no cover - reconfigure is 3.7+
        pytest.skip("TextIOWrapper.reconfigure needs 3.7")
    child = subprocess.run(
        [sys.executable, "-c", _child(
            "module.enable_unbuffered_output()  # idempotent; import already ran it\n"
            "print('  [tool done] read_file → 42 lines')\n"
            "print('  [tool done] →', file=sys.stderr)\n"
            "print('line_buffering:', sys.stdout.line_buffering, file=sys.stderr)\n"
        )],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
    )
    assert child.returncode == 0, (
        "the parent died encoding its own output:\n" + child.stderr.decode("utf-8", "replace")
    )
    # Both streams are UTF-8 now, so decoding them as such is the assertion, not a hope.
    assert "→ 42 lines" in child.stdout.decode("utf-8")
    assert "→" in child.stderr.decode("utf-8"), "stderr was not reconfigured with stdout"
    assert b"line_buffering: True" in child.stderr, "reconfigure dropped line buffering"


def test_each_run_is_a_fresh_session() -> None:
    """The engine keys durable history by session id, so a fixed one makes run N resume run N-1.

    Two separate invocations (different processes) must never share an id. This is the hunk that
    stopped the model answering "I already did that in the previous turn" with zero tool calls.
    """
    ids = []
    for _ in range(2):
        child = subprocess.run(
            [sys.executable, "-c", _child("print(module.batch_session_id())\n")],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
        )
        assert child.returncode == 0, child.stderr.decode("utf-8", "replace")
        ids.append(child.stdout.decode().strip())
    assert ids[0] != ids[1], f"two invocations shared a session id: {ids[0]!r}"
    assert all(i.startswith("preview-batch-turn-") for i in ids), ids
    assert all(i != "preview-batch-turn" for i in ids), "the old fixed id came back"


def test_the_harness_never_uses_the_demos_own_session_field(harness) -> None:
    """`demo_batch()` carries a `sessionId` for payload shape; the frame must not adopt it."""
    from src.preview.prompt import build_prompt_frame

    frame = build_prompt_frame(
        harness.demo_batch(), session_id="fresh-123", workspace="/ws", mode="agent"
    )
    assert frame["session_id"] == "fresh-123"


class _ScriptedBridge:
    """The smallest thing `run_turn` needs: a workspace, a send sink, and a frame queue."""

    workspace = "/ws"

    def __init__(self, frames: list[dict]) -> None:
        self._frames = list(frames)
        self.sent: list[dict] = []

    def send(self, frame: dict) -> None:
        self.sent.append(frame)

    def read(self, timeout: float | None = None) -> dict | None:
        # The real Bridge raises queue.Empty when nothing arrives before the timeout and returns None
        # only when the engine closes its stream; mirroring that is what makes the quiet-engine
        # (heartbeat -> timeout report) path reachable here.
        if not self._frames:
            raise queue.Empty
        return self._frames.pop(0)


def _run_scripted(harness, frames: list[dict]) -> tuple[dict, list[str]]:
    return harness.run_turn(
        _ScriptedBridge(frames), {"type": "prompt", "text": "x"}, "sid-1", 5.0, show_tools=True
    )


def test_a_resumed_session_is_never_silent(harness, capsys) -> None:
    """The engine reports `prior_checkpoints`; a non-zero count must be shouted about.

    This is the guard, not the fix: the id is fresh, so a non-zero count means the engine answered a
    conversation this run did not start, and every conclusion drawn from the run is suspect.
    """
    terminal, _ = _run_scripted(harness, [
        {"type": "session_info", "session_id": "sid-1", "prior_checkpoints": 3},
        {"type": "turn_started"},
        {"type": "turn_done"},
    ])
    out = capsys.readouterr().out
    assert "SESSION NOT FRESH" in out and "3 prior checkpoint" in out, out
    assert terminal.get("type") == "turn_done"


def test_a_fresh_session_says_nothing_extra(harness, capsys) -> None:
    _run_scripted(harness, [
        {"type": "session_info", "session_id": "sid-1", "prior_checkpoints": 0},
        {"type": "turn_started"},
        {"type": "turn_done"},
    ])
    assert "SESSION NOT FRESH" not in capsys.readouterr().out


# ─────────────────────────────────────────── the diff must stay honest on a Windows checkout
def test_eol_only_changes_are_named_not_shown_as_a_rewrite(harness) -> None:
    """A CRLF workspace + an LF edit must not read as "every line changed".

    This is the Windows case, reproduced here by writing the bytes directly: the checkout hands the
    file CRLF, the agent's edit lands LF, and a byte-comparing report would print the whole file as
    removed-and-re-added — burying the one line that actually changed. The report names it instead.
    """
    before = {"styles.css": b".btn {\r\n  color: red;\r\n}\r\n"}
    after = {"styles.css": b".btn {\n  color: red;\n}\n"}
    report = harness.describe_changes(before, after)
    assert "line endings only" in report, report
    assert "-.btn" not in report and "+.btn" not in report, "no fake line-by-line rewrite"


def test_a_real_edit_next_to_an_eol_difference_is_still_shown(harness) -> None:
    """The narrowness that makes the rule safe: a genuine change must never hide behind it."""
    before = {"styles.css": b".btn {\r\n  color: red;\r\n}\r\n"}
    after = {"styles.css": b".btn {\n  color: blue;\n}\n"}
    report = harness.describe_changes(before, after)
    assert "line endings only" not in report, "a real edit must not be dismissed as EOL noise"
    # splitlines() strips the EOL characters, so the changed line is the ONLY one counted — the
    # CRLF->LF difference contributes nothing and the reader sees exactly what changed.
    assert "+1 -1" in report, report
    assert "color: blue" in report and "color: red" in report


def test_the_run_prints_its_turn_budget(harness) -> None:
    """Run 8 was reported as "the 300s budget" while the default is 900s.

    Whatever the cause — an explicit `--timeout`, or an assumption — the run should never leave the
    reader guessing which cap they are hitting, so the budget is printed up front.
    """
    assert harness.DEFAULT_TIMEOUT_S == 900.0, "the documented default is 900s"
    source = SCRIPT.read_text(encoding="utf-8")
    assert "turn budget:" in source
    assert "--timeout" in source


def test_the_timeout_report_says_how_much_work_had_happened(harness, capsys) -> None:
    """A timeout must distinguish "stuck" from "still working" — that is the difference between a bug
    and a budget, and it decides whether the next run should raise `--timeout`."""
    frames = [{"type": "turn_started"}] + [{"type": "tool_call_start", "name": "read_file"}] * 3
    harness.run_turn(_ScriptedBridge(frames), {"type": "prompt", "text": "x"}, "sid", 0.3, show_tools=False)
    out = capsys.readouterr().out
    assert "Timed out after 0s" in out, out
    assert "3 tool call(s)" in out, out
    assert "--timeout" in out, "the report must name the flag that raises the budget"
