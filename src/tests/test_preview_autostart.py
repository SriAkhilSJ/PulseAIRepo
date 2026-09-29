"""Crusor Preview — the engine starts the proxy, so launching the desktop app is enough.

The field report this answers: running the Windows launcher popped up *two* windows next to each
other — the desktop app and a minimized Python console for the preview proxy. The fix is not to hide
the terminal but to remove the need for it: the engine already receives the opened folder on every
session frame, and a proxy is a stdlib program in the same repo, so the engine starts it itself,
windowless, on first sighting of the workspace.

What is pinned here:

* a healthy proxy for the **same** workspace is adopted, never duplicated — two proxies for one
  folder would fight over the same endpoint file, and the IDE would frame whichever won;
* a healthy proxy for a **different** folder is *not* adopted (a proxy confines file targets to one
  workspace, so the workspace is part of the proxy's identity);
* a **dead registration** is not adopted — the file outlives the process that wrote it, and the IDE
  would otherwise frame nothing;
* the spawn is windowless (``CREATE_NO_WINDOW`` / ``windowsHide``), detached, run from the engine
  root, and pointed at the opened folder — the entire feature is "no second window, right folder";
* a busy 8931 falls back to a free port, because the endpoint file carries the real port;
* nothing ever raises: a preview that cannot start must not touch an agent turn;
* ``CRUSORAI_PREVIEW_AUTOSTART=0`` restores the manual flow;
* and the bridge hook is off the frame path (a daemon thread), because a cold start is seconds.

The last test spawns the **real** proxy against a real workspace (stdlib only, same code path as the
field) and asserts the endpoint it publishes answers on ``/crusor-preview/health``.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from src.preview.autostart import (
	ENGINE_ROOT,
	AUTOSTART_ENV,
	PreviewAutostart,
	ensure_stdio,
	find_serving_endpoint,
	normalize_workspace,
)
from src.preview.endpoint import read_endpoint, write_endpoint
from src.preview.server import PreviewServer


class FakeProcess:
	"""Stands in for the spawned child; only the parts the autostart touches."""

	def __init__(self, pid: int = 4242, exit_code: int | None = None) -> None:
		self.pid = pid
		self.exit_code = exit_code
		self.terminated = False

	def poll(self) -> int | None:
		return self.exit_code

	def terminate(self) -> None:
		self.terminated = True

	def wait(self, timeout: float | None = None) -> int | None:
		return self.exit_code


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
	"""Pin the runtime home (endpoints must never land in the real ~/.crusorai) and switch
	autostart back ON — conftest.py turns it off for the whole suite so no other test spawns a
	proxy by surprise."""
	runtime = tmp_path / "crusorai-home"
	monkeypatch.setenv("CRUSORAI_HOME", str(runtime))
	monkeypatch.setenv(AUTOSTART_ENV, "1")
	return runtime


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
	folder = tmp_path / "opened-project"
	folder.mkdir()
	return folder


def dead_origin() -> str:
	"""A loopback origin with nothing listening: bind, learn the port, close."""
	sock = socket.socket()
	sock.bind(("127.0.0.1", 0))
	port = int(sock.getsockname()[1])
	sock.close()
	return f"http://127.0.0.1:{port}"


# -- adopting what is already there -------------------------------------------------------------


def test_healthy_proxy_for_the_same_workspace_is_adopted(home: Path, workspace: Path) -> None:
	server = PreviewServer(workspace, port=0, secret="s").start()
	try:
		write_endpoint("ide", origin=server.origin, workspace=str(workspace.resolve()), secret="s")
		calls: list[object] = []
		service = PreviewAutostart(popen=lambda *a, **k: calls.append(a) or FakeProcess())

		handle = service.ensure(workspace)

		assert handle is not None
		assert handle.reused is True and handle.started is False
		assert handle.origin == server.origin
		assert calls == [], "a healthy proxy must be adopted, not duplicated"
	finally:
		server.stop()


def test_healthy_proxy_for_another_workspace_is_not_adopted(
	home: Path, workspace: Path, tmp_path: Path
) -> None:
	other = tmp_path / "a-different-project"
	other.mkdir()
	server = PreviewServer(other, port=0, secret="s").start()
	try:
		write_endpoint("ide", origin=server.origin, workspace=str(other.resolve()), secret="s")
		assert find_serving_endpoint(workspace) is None
		assert find_serving_endpoint(other) is not None
	finally:
		server.stop()


def test_dead_registration_is_not_adopted(home: Path, workspace: Path) -> None:
	"""The file survives the process, so liveness — not the presence of a file — decides reuse."""
	write_endpoint("ide", origin=dead_origin(), workspace=str(workspace.resolve()), secret="s")
	assert find_serving_endpoint(workspace) is None


def test_a_dead_newer_registration_does_not_hide_a_live_older_one(home: Path, workspace: Path) -> None:
	"""Killed proxies leave their file behind; the live one must still be found."""
	live = PreviewServer(workspace, port=0, secret="s").start()
	try:
		write_endpoint("older", origin=live.origin, workspace=str(workspace.resolve()), secret="s")
		time.sleep(0.02)
		write_endpoint("newer", origin=dead_origin(), workspace=str(workspace.resolve()), secret="s")
		found = find_serving_endpoint(workspace)
		assert found is not None and found["origin"] == live.origin
	finally:
		live.stop()


def test_a_registration_without_a_workspace_is_not_adopted(home: Path, workspace: Path) -> None:
	"""No workspace recorded → it cannot be proven to be this folder's proxy."""
	server = PreviewServer(workspace, port=0, secret="s").start()
	try:
		write_endpoint("ide", origin=server.origin, secret="s")  # workspace defaults to ""
		assert find_serving_endpoint(workspace) is None
	finally:
		server.stop()


def test_workspace_comparison_folds_case_only_where_the_platform_does(workspace: Path) -> None:
	"""The IDE compares with normcase; reuse has to agree or `D:\\Proj` and `d:\\proj` diverge."""
	assert normalize_workspace(str(workspace)) == os.path.normcase(str(workspace.resolve()))
	if os.name == "nt":
		assert normalize_workspace(str(workspace).upper()) == normalize_workspace(str(workspace))
	else:
		# POSIX is case-sensitive: folding here would adopt a different project's proxy.
		assert normalize_workspace(str(workspace).upper()) != normalize_workspace(str(workspace))


def test_workspace_comparison_resolves_relative_paths(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.chdir(workspace)
	assert normalize_workspace(".") == normalize_workspace(workspace)


# -- starting one -------------------------------------------------------------------------------


def test_a_spawned_proxy_is_recorded_and_not_started_twice(
	home: Path, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""The fake child publishes a *real* endpoint, so everything after the spawn runs for real."""
	server = PreviewServer(workspace, port=0, secret="s").start()
	calls: list[tuple[list[str], dict]] = []

	def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
		calls.append((command, kwargs))
		write_endpoint("ide", origin=server.origin, workspace=str(workspace.resolve()), secret="s")
		return FakeProcess(pid=999)

	try:
		service = PreviewAutostart(popen=fake_popen)
		handle = service.ensure(workspace)
		again = service.ensure(workspace)
	finally:
		server.stop()

	assert handle is not None and handle.started is True
	assert handle.origin == server.origin and handle.pid == 999
	assert again is handle, "a second call must return what the first one found, without respawning"
	assert len(calls) == 1

	command, kwargs = calls[0]
	assert command[:2] == [sys.executable, "-u"], "unbuffered: the log is a file, not a console"
	assert command[2:4] == ["-m", "src.preview.server"]
	assert "--workspace" in command and str(workspace) in command
	assert "--endpoint-session" in command and "ide" in command
	assert kwargs["cwd"] == str(ENGINE_ROOT), "the proxy CLI must resolve from the engine root"
	assert kwargs["stdin"] is subprocess.DEVNULL
	if os.name == "nt":
		assert kwargs["windowsHide"] is True, "no window next to the desktop app"
		assert kwargs["creationflags"] & 0x08000000  # CREATE_NO_WINDOW
	else:
		assert kwargs["start_new_session"] is True, "the preview must outlive the launching terminal"


def test_a_busy_port_falls_back_to_a_free_one(
	home: Path, workspace: Path
) -> None:
	"""8931 is the documented port, not a requirement: the endpoint file carries the real one."""
	server = PreviewServer(workspace, port=0, secret="s").start()
	attempts: list[str] = []

	def flaky_popen(command: list[str], **kwargs: object) -> FakeProcess:
		port = command[command.index("--port") + 1]
		attempts.append(port)
		if port != "0":
			return FakeProcess(exit_code=1)  # "Address already in use" and gone
		write_endpoint("ide", origin=server.origin, workspace=str(workspace.resolve()), secret="s")
		return FakeProcess(pid=1000)

	try:
		handle = PreviewAutostart(popen=flaky_popen).ensure(workspace)
	finally:
		server.stop()

	assert attempts == ["8931", "0"]
	assert handle is not None and handle.pid == 1000


def test_a_failed_spawn_is_swallowed_and_throttled(
	home: Path, workspace: Path
) -> None:
	def exploding_popen(command: list[str], **kwargs: object) -> FakeProcess:
		raise OSError("no interpreter here")

	service = PreviewAutostart(popen=exploding_popen)
	assert service.ensure(workspace) is None  # no exception escapes
	calls = 0

	def counting_popen(command: list[str], **kwargs: object) -> FakeProcess:
		nonlocal calls
		calls += 1
		raise OSError("still no interpreter here")

	service = PreviewAutostart(popen=counting_popen)
	assert service.ensure(workspace) is None
	assert service.ensure(workspace) is None
	assert calls == 1, "a failed attempt is remembered for the cooldown, not retried every frame"

	service.forget(workspace)
	assert service.ensure(workspace) is None
	assert calls == 2, "forget() is the way back for a caller that knows the world changed"


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", " False "])
def test_the_switch_disables_autostart(home: Path, workspace: Path, value: str) -> None:
	calls: list[str] = []
	service = PreviewAutostart(
		environ={AUTOSTART_ENV: value},
		popen=lambda command, **kwargs: calls.append(command) or FakeProcess(),
	)
	assert service.enabled() is False
	assert service.ensure(workspace) is None
	assert calls == []


def test_the_switch_defaults_to_on(home: Path, workspace: Path) -> None:
	assert PreviewAutostart(environ={}).enabled() is True
	assert PreviewAutostart(environ={AUTOSTART_ENV: "1"}).enabled() is True


def test_a_missing_workspace_starts_nothing(home: Path) -> None:
	"""`Path("").resolve()` is the engine root — never let a blank workspace become a proxy target."""
	calls: list[object] = []
	service = PreviewAutostart(popen=lambda *a, **k: calls.append(a) or FakeProcess())
	assert service.ensure("") is None
	assert service.ensure("   ") is None
	assert service.ensure(None) is None
	assert calls == []


# -- windowless output --------------------------------------------------------------------------


def test_a_windowless_process_binds_its_output_to_the_proxy_log(
	home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""pythonw.exe (the whole reason no second window appears) has no stdio at all."""
	saved_out, saved_err = sys.stdout, sys.stderr
	monkeypatch.setattr(sys, "stdout", None)
	monkeypatch.setattr(sys, "stderr", None)
	try:
		path = ensure_stdio("ide")
		assert path is not None
		assert sys.stdout is sys.stderr, "both streams must land in the same file"
		print("proxy line the user can read later")
		sys.stdout.flush()
	finally:
		stream = sys.stdout
		sys.stdout, sys.stderr = saved_out, saved_err
		if stream is not None and stream is not saved_out:
			stream.close()

	assert path is not None and path.exists()
	content = path.read_text(encoding="utf-8")
	assert "proxy line the user can read later" in content
	assert str(path.parent) == str(home / "preview")


def test_stdio_is_left_alone_when_there_is_one(home: Path) -> None:
	assert ensure_stdio("ide") is None


# -- the bridge hook ----------------------------------------------------------------------------


def test_the_bridge_hook_runs_off_the_frame_path(
	home: Path, workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
	"""The hook must return immediately: the caller is the frame loop."""
	from src.bridge import __main__ as bridge

	monkeypatch.setenv(AUTOSTART_ENV, "1")  # conftest turns the feature off suite-wide

	finished = threading.Event()
	seen: list[str] = []

	def slow_ensure(ensure, target: str):
		time.sleep(0.2)  # a cold start is seconds in the field; even this must not block the caller
		seen.append(target)
		finished.set()

	monkeypatch.setattr(bridge, "_ensure_preview_proxy", slow_ensure)
	server = bridge.BridgeServer.__new__(bridge.BridgeServer)
	server._preview_hooked = set()

	start = time.monotonic()
	server._start_preview_proxy(str(workspace))
	elapsed = time.monotonic() - start

	assert elapsed < 0.15, "the frame loop must not wait on a proxy start"
	server._start_preview_proxy(str(workspace))  # second sighting: no second thread
	assert finished.wait(timeout=5)
	assert seen == [str(workspace)]


def test_the_bridge_thread_body_swallows_errors(capsys: pytest.CaptureFixture[str]) -> None:
	from src.bridge.__main__ import _ensure_preview_proxy

	_ensure_preview_proxy(lambda target: (_ for _ in ()).throw(RuntimeError("boom")), "D:/x")
	_ensure_preview_proxy(lambda target: None, "D:/x")
	# Neither call may raise, and both must say something a user can act on.
	assert "boom" in capsys.readouterr().err


# -- the real thing -----------------------------------------------------------------------------


def test_the_real_proxy_is_spawned_hidden_and_serves_the_workspace(
	home: Path, workspace: Path
) -> None:
	"""End to end with the real interpreter: what the field gets on a cold start."""
	service = PreviewAutostart(port=0, wait_seconds=30.0)
	handle = service.ensure(workspace)
	try:
		assert handle is not None, "the real proxy did not come up"
		assert handle.started is True and handle.process is not None
		assert handle.log_path is not None and Path(handle.log_path).exists()

		with urllib.request.urlopen(f"{handle.origin}/crusor-preview/health", timeout=5) as response:
			assert response.status == 200

		published = read_endpoint("ide")
		assert published is not None
		assert normalize_workspace(published["workspace"]) == normalize_workspace(workspace)
		assert published["secret"], "the window needs the registration secret from this file"
	finally:
		if handle is not None and handle.process is not None:
			handle.process.terminate()
			try:
				handle.process.wait(timeout=10)
			except Exception:  # pragma: no cover - already gone
				pass
