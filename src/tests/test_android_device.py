"""android_device: the agent's only path to a real phone.

Tested against a stub `agent-device` on PATH, so the logic under test — the
allowlist, the read-only/mutating labelling, the refusal of anything that could
become a shell command, the real exit code — is exercised without Node, without
a device and without the network.

The property worth stating: this tool could have been a one-line
`subprocess.run(cmd, shell=True)`. It is not, and these tests are what stop it
from quietly becoming one.
"""
from __future__ import annotations

import ast
import inspect
import json
import os
import stat
from pathlib import Path

import pytest

from src.tools import android_device as mod
from src.tools.android_device import android_device, classify

_STUB = """
# Only real agent-device command names appear here; the tool's allowlist would
# refuse anything else, so a stub could not exercise these paths otherwise.
case "$1" in
  snapshot)   echo '@e1 text:"Save"'; echo '@e2 button:"Submit"' ;;
  click)      echo 'clicked'; echo 'diff: +@e9 text:"Saved"' ;;
  open)       echo 'opened'; echo '@e1 text:"Hello"' ;;
  devices)    printf 'emulator-5554\tdevice\n' ;;
  shutdown)   echo 'device shut down' ;;
  install)    echo 'installed' ;;
  device)     echo "device $2" ;;
  session)    echo "session $2" ;;
  find)       echo 'error: element not found' >&2; exit 3 ;;
  scroll)     sleep 30 ;;
  artifacts)  head -c 40000 /dev/zero | tr '\0' 'x' ;;
  get)        shift; echo "GOT: $*" ;;
  *)          echo "unknown $*" ;;
esac
exit 0
"""

@pytest.fixture
def stubbin(tmp_path_factory):
    d = tmp_path_factory.mktemp("adbin")
    script = d / "agent-device"
    script.write_text("#!/bin/sh\n" + _STUB, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return d


@pytest.fixture
def use_stub(stubbin, monkeypatch):
    monkeypatch.setenv("PATH", f"{stubbin}{os.pathsep}{os.environ.get('PATH', '')}")
    return stubbin


@pytest.fixture
def ws(tmp_path):
    return tmp_path / "project"


@pytest.fixture
def cfg(ws):
    ws.mkdir()
    return {"configurable": {"workspace": str(ws)}}


def _run(cfg, sub, arguments=None, **kw):
    return android_device.invoke(
        {"subcommand": sub, "arguments": arguments or [], **kw}, config=cfg
    )


def _log(ws) -> list[dict]:
    """Invocations recorded so far. Empty when nothing ran — which is itself
    the interesting assertion for the refusal tests."""
    path = Path(ws) / ".crusorai" / "android-evidence" / "device-log.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sub,args,expected", [
    ("snapshot", [], "read-only"),
    ("devices", [], "read-only"),
    ("screenshot", [], "read-only"),
    ("logs", [], "read-only"),
    ("click", ["@e3"], "mutating"),
    ("fill", ["@e2", "hi"], "mutating"),
    ("open", ["com.x"], "mutating"),
    ("device", ["status"], "read-only"),
    ("device", ["release"], "mutating"),
    ("session", ["list"], "read-only"),
    ("session", ["end"], "mutating"),
    ("shutdown", [], "consequential"),
    ("takeover", [], "consequential"),
    ("reinstall", [], "consequential"),
    ("boot", [], "consequential"),
])
def test_classification(sub, args, expected):
    assert classify(sub, args) == expected


def test_every_known_command_gets_a_label():
    """An unlabelled command would silently default to the weakest claim."""
    for cmd in mod._KNOWN_COMMANDS:
        assert classify(cmd, []) in {"read-only", "mutating", "consequential"}, cmd


def test_the_allowlist_matches_the_upstream_registry():
    """Pinned against packages/command-registry/src/registry.ts. If agent-device
    adds a command, this fails and someone makes a deliberate decision."""
    # 73 as of 2026-10-10. Verified by diffing against the registry rather
    # than counted by eye: `comm` on the two sorted sets came back empty both
    # ways, so this list is neither invented nor incomplete.
    assert len(mod._KNOWN_COMMANDS) == 73
    assert {"snapshot", "click", "open", "replay", "scroll"} <= mod._KNOWN_COMMANDS
    assert "mcp" in mod._KNOWN_COMMANDS, "registry command missing from the allowlist"


# ---------------------------------------------------------------------------
# refusals — this is the part that must not regress
# ---------------------------------------------------------------------------

def test_unknown_subcommand_is_refused_not_passed_through(use_stub, cfg):
    """The whole point of the allowlist: this is not a command runner."""
    out = _run(cfg, "rm")
    assert out.startswith("❌ REFUSED"), out
    assert "general command runner" in out
    assert _log(cfg["configurable"]["workspace"]) == [], (
        "a refused command must not reach the device or the receipt"
    )


@pytest.mark.parametrize("bad", ["@e1; rm -rf /", "a && b", "x | tee /tmp/p",
                                 "$(whoami)", "`id`", "a > /etc/passwd", "$HOME"])
def test_shell_metacharacters_are_rejected(use_stub, cfg, bad):
    out = _run(cfg, "click", [bad])
    assert out.startswith("❌ REFUSED"), f"{bad!r} was not refused: {out}"


def test_mcp_subcommand_is_refused_because_it_would_hang(use_stub, cfg):
    out = _run(cfg, "mcp")
    assert out.startswith("❌ REFUSED")
    assert "long-lived server" in out


def test_no_call_is_made_through_a_shell():
    """Rule 1, enforced by AST rather than by grepping prose — the module
    docstring deliberately contains the phrase `shell=True` when explaining
    what it does NOT do, so a string scan gives the wrong answer here."""
    tree = ast.parse(inspect.getsource(mod))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert calls, "no calls parsed — the check is vacuous"
    for node in calls:
        for kw in node.keywords:
            if kw.arg == "shell":
                assert isinstance(kw.value, ast.Constant) and kw.value.value is False, (
                    "a call passes shell=; that reopens the injection surface"
                )
    src = inspect.getsource(mod)
    assert "os.system" not in src and "os.popen" not in src


# ---------------------------------------------------------------------------
# honest reporting
# ---------------------------------------------------------------------------

def test_missing_binary_is_unavailable_not_failed(tmp_path, monkeypatch, cfg):
    monkeypatch.setenv("PATH", str(tmp_path))  # nothing on PATH
    out = _run(cfg, "snapshot")
    assert out.startswith("⛔ UNAVAILABLE"), out
    assert "not the agent's" in out or "Do not install it yourself" in out
    assert "Do not report a UI result" in out


def test_nonzero_exit_reports_failure_with_the_stderr(use_stub, cfg):
    """A stub that exits 3 must not be smoothed into a pass."""
    out = _run(cfg, "find")
    assert out.startswith("❌ FAILED"), out
    assert "exit=3" in out
    assert "element not found" in out


def test_exit_code_comes_from_the_process(use_stub, cfg):
    _run(cfg, "find")
    entry = _log(cfg["configurable"]["workspace"])[-1]
    assert entry["exit"] == 3, "the receipt lost the real exit code"


def test_timeout_is_distinguished_from_failure(use_stub, cfg):
    out = _run(cfg, "scroll", timeout=1)
    assert out.startswith("⏱️ TIMEOUT"), out
    assert "Nothing here proves success or failure" in out
    assert _log(cfg["configurable"]["workspace"])[-1]["status"] == "timeout"


# ---------------------------------------------------------------------------
# usefulness
# ---------------------------------------------------------------------------

def test_snapshot_output_reaches_the_model_with_refs(use_stub, cfg):
    out = _run(cfg, "snapshot")
    assert "@e1" in out and '@e2 button:"Submit"' in out
    assert "read-only" in out


def test_platform_is_appended_once(use_stub, cfg):
    # the header line echoes the resolved argv, which is what we assert on —
    # the stub also echoes its own args in the body, so counting the whole
    # output would double-count and prove nothing
    header = _run(cfg, "snapshot").splitlines()[0]
    assert "--platform android" in header

    dup = _run(cfg, "get", ["--platform", "ios"])
    dup_header = dup.splitlines()[0]
    assert dup_header.count("--platform") == 1, dup_header
    assert "--platform android" not in dup, (
        "an explicit --platform must not be overwritten or duplicated"
    )


def test_platform_can_be_omitted(use_stub, cfg):
    assert "--platform" not in _run(cfg, "get", ["foo"], platform="")


def test_large_output_is_truncated_for_the_model_but_saved_in_full(use_stub, cfg):
    out = _run(cfg, "artifacts")
    assert "more chars saved to" in out
    ws = Path(cfg["configurable"]["workspace"])
    saved = sorted((ws / ".crusorai" / "android-evidence").glob("device-*/artifacts.log"))
    assert saved, "the full output was not preserved"
    assert saved[-1].stat().st_size > mod._MAX_OUTPUT_CHARS


def test_every_invocation_is_logged_with_its_label(use_stub, cfg):
    ws = Path(cfg["configurable"]["workspace"])
    _run(cfg, "snapshot")
    _run(cfg, "click", ["@e1"])
    _run(cfg, "shutdown")
    entries = _log(ws)
    assert [e["kind"] for e in entries] == ["read-only", "mutating", "consequential"]
    assert all(e["exit"] == 0 for e in entries)
    assert all(Path(e["artifact"]).is_file() for e in entries)


def test_interactive_loop_produces_a_readable_trail(use_stub, cfg):
    """open -> click -> snapshot is the actual shape of a UI test."""
    ws = Path(cfg["configurable"]["workspace"])
    assert "@e1" in _run(cfg, "open", ["com.akhil.notes", "--foreground"])
    assert "Saved" in _run(cfg, "click", ["@e2", "--settle"])
    assert "@e1" in _run(cfg, "snapshot")
    assert [e["cmd"][0] for e in _log(ws)] == ["open", "click", "snapshot"]
