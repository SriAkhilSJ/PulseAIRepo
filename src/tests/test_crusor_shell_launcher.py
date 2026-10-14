"""The macOS/Linux source launcher delegates paths and options without shell splitting."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")


@pytest.mark.skipif(os.name == "nt" or BASH is None, reason="crusor.sh is the POSIX launcher")
def test_crusor_sh_preserves_workspace_and_extra_arguments(monkeypatch, tmp_path):
    launcher = tmp_path / "fake Code OSS" / "code.sh"
    launcher.parent.mkdir()
    launcher.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\0' \"$@\" > \"$CRUSORAI_TEST_CAPTURE\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    captured = tmp_path / "argv.bin"
    monkeypatch.setenv("CRUSORAI_CODE_LAUNCHER", str(launcher))
    monkeypatch.setenv("CRUSORAI_TEST_CAPTURE", str(captured))

    result = subprocess.run(
        [BASH, str(REPO_ROOT / "crusor.sh"), "folder with spaces", "--new-window", "--wait"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert captured.read_bytes().split(b"\0")[:-1] == [
        b"folder with spaces", b"--new-window", b"--wait",
    ]


@pytest.mark.skipif(os.name == "nt" or BASH is None, reason="crusor.sh is the POSIX launcher")
def test_crusor_sh_gives_actionable_error_when_code_oss_launcher_is_missing(monkeypatch, tmp_path):
    missing = tmp_path / "missing code.sh"
    monkeypatch.setenv("CRUSORAI_CODE_LAUNCHER", str(missing))

    result = subprocess.run(
        [BASH, str(REPO_ROOT / "crusor.sh")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Build the desktop checkout first" in result.stderr
