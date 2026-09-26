"""Crusor Preview — the handshake file the proxy publishes for the IDE.

The workbench cannot discover an ephemeral port or a capability token by asking Bridge Protocol v2
(which is a session channel), so the runtime publishes them as machine state under
``$CRUSORAI_HOME/preview``. Two failure modes matter and both are silent:

* a **torn read** (the renderer reads the file while the proxy is rewriting it) leaves the IDE
  convinced there is no preview server, so writes are atomic here and this test reads concurrently;
* a **session id used as a path** (``../../``) would write outside the runtime directory, so the
  name is sanitised before it becomes a filename.

Also pinned: a stale endpoint is pruned, because a dead file is worse than a missing one — the IDE
would keep trying to frame an origin that no longer exists.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from src.preview.endpoint import (
	clear_endpoint,
	endpoint_path,
	preview_home,
	prune_stale,
	read_endpoint,
	runtime_home,
	write_endpoint,
)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
	"""Never touch the developer's real ~/.crusorai while testing runtime state."""
	monkeypatch.setenv("CRUSORAI_HOME", str(tmp_path / "home"))
	yield tmp_path / "home"


def test_round_trip() -> None:
	path = write_endpoint(
		"sess-1", origin="http://127.0.0.1:8931/", token="tok-abc", secret="s3cret",
		workspace="/tmp/ws", extra={"note": "lab"},
	)
	assert path == endpoint_path("sess-1")
	payload = read_endpoint("sess-1")
	assert payload is not None
	assert payload["origin"] == "http://127.0.0.1:8931", "trailing slash is normalised away"
	assert payload["token"] == "tok-abc"
	assert payload["secret"] == "s3cret", "the registration capability the preview window needs"
	assert payload["workspace"] == "/tmp/ws"
	assert payload["ui_path"] == "/crusor-preview/ui/"
	assert payload["note"] == "lab"
	assert payload["pid"] == os.getpid()
	assert payload["started_at"] <= time.time()


def test_file_is_owner_only_and_inside_the_runtime_home() -> None:
	write_endpoint("sess-2", origin="http://127.0.0.1:9/", token="t")
	path = endpoint_path("sess-2")
	assert path.parent == preview_home()
	assert preview_home() == runtime_home() / "preview"
	if os.name != "nt":
		assert (path.stat().st_mode & 0o077) == 0, "the token in this file is the only guard on the proxy"


def test_a_session_id_is_never_a_path() -> None:
	write_endpoint("../../escape", origin="http://127.0.0.1:9/", token="t")
	path = endpoint_path("../../escape")
	assert path.parent == preview_home(), "sanitised into the preview directory"
	assert ".." not in path.name
	# The real directory must not have gained a sibling, and nothing was written outside the home.
	assert not (runtime_home().parent / "escape.json").exists()


def test_missing_or_broken_files_read_as_absent() -> None:
	assert read_endpoint("never-written") is None
	broken = endpoint_path("broken")
	broken.parent.mkdir(parents=True, exist_ok=True)
	broken.write_text("{not json", encoding="utf-8")
	assert read_endpoint("broken") is None
	broken.write_text(json.dumps({"session_id": "broken"}), encoding="utf-8")
	assert read_endpoint("broken") is None, "an endpoint without an origin is not an endpoint"


def test_clear_is_idempotent() -> None:
	write_endpoint("sess-3", origin="http://127.0.0.1:9/")
	assert clear_endpoint("sess-3") is True
	assert clear_endpoint("sess-3") is False
	assert read_endpoint("sess-3") is None


def test_reads_never_see_a_half_written_file() -> None:
	"""A concurrent reader must always see a complete document, or nothing at all."""
	write_endpoint("sess-4", origin="http://127.0.0.1:1/", token="t0")
	stop = threading.Event()
	problems: list[str] = []

	def reader() -> None:
		while not stop.is_set():
			payload = read_endpoint("sess-4")
			if payload is None:
				problems.append("read returned None while the writer was active")
				return
			if not payload.get("token", "").startswith("t"):
				problems.append(f"torn payload: {payload!r}")
				return

	def writer() -> None:
		for index in range(400):
			write_endpoint("sess-4", origin="http://127.0.0.1:1/", token=f"t{index}", extra={"n": index})

	readers = [threading.Thread(target=reader) for _ in range(3)]
	writer_thread = threading.Thread(target=writer)
	for thread in readers:
		thread.start()
	writer_thread.start()
	writer_thread.join(timeout=30)
	stop.set()
	for thread in readers:
		thread.join(timeout=5)
	assert not problems, problems[:3]


def test_prune_removes_only_stale_endpoints() -> None:
	fresh = write_endpoint("fresh", origin="http://127.0.0.1:1/")
	stale = write_endpoint("stale", origin="http://127.0.0.1:2/")
	old = time.time() - 3600
	os.utime(stale, (old, old))

	removed = prune_stale(max_age_seconds=600)
	assert stale in removed
	assert fresh.exists()
	assert read_endpoint("fresh") is not None


def test_endpoint_shape_matches_the_typescript_contract() -> None:
	"""The workbench reads these keys by name; a rename on either side breaks the feature silently."""
	source = (
		Path(__file__).resolve().parents[2] / "desktop" / "vscode" / "src" / "vs" / "workbench"
		/ "contrib" / "crusorai" / "common" / "crusorAIPreview.ts"
	).read_text(encoding="utf-8")
	interface = source.split("export interface CrusorPreviewEndpoint", 1)[1].split("}", 1)[0]
	payload = write_endpoint("contract", origin="http://127.0.0.1:1/", token="t", workspace="/ws")
	written = json.loads(Path(payload).read_text(encoding="utf-8"))
	for key in ("session_id", "origin", "token", "secret", "workspace", "ui_path", "health_path", "started_at", "pid"):
		assert key in interface, f"{key} missing from the TypeScript endpoint contract"
		assert key in written, f"{key} missing from the published endpoint"


def test_write_retries_a_transient_replace_failure(monkeypatch, tmp_path) -> None:
	"""A contended rename must not lose the endpoint.

	On Windows `os.replace` can fail with PermissionError while another process holds the destination
	open (a reader mid-read, a virus scanner, the search indexer). Losing that race deletes the only
	map from "this workspace" to "the running preview proxy", and the IDE then reports no proxy while
	one is running — a symptom nobody can diagnose from the outside.
	"""
	import os as _os

	real_replace = _os.replace
	attempts = {"count": 0}

	def flaky_replace(src, dst):
		attempts["count"] += 1
		if attempts["count"] <= 3:
			raise PermissionError(13, "the destination is open in another process")
		return real_replace(src, dst)

	# A scoped patch, NOT monkeypatch.undo(): undoing the fixture's monkeypatch would also lift its
	# CRUSORAI_HOME override, and the read below would then look in the developer's real ~/.crusorai.
	with pytest.MonkeyPatch.context() as patcher:
		patcher.setattr(_os, "replace", flaky_replace)
		write_endpoint("contended", origin="http://127.0.0.1:7/", secret="s")

	assert attempts["count"] == 4, "three failures, then the successful attempt"
	printed = read_endpoint("contended")
	assert printed is not None and printed["origin"] == "http://127.0.0.1:7"


def test_write_still_publishes_when_renames_never_succeed(monkeypatch) -> None:
	"""The pathological case degrades to a direct write instead of leaving no endpoint at all."""
	import os as _os

	def never(src, dst):
		raise PermissionError(13, "locked forever")

	with pytest.MonkeyPatch.context() as patcher:
		patcher.setattr(_os, "replace", never)
		write_endpoint("unrenamable", origin="http://127.0.0.1:8/", secret="s")

	payload = read_endpoint("unrenamable")
	assert payload is not None, "an un-renamable destination must still end up holding the endpoint"
	assert payload["origin"] == "http://127.0.0.1:8"


def test_no_temp_files_are_left_behind() -> None:
	write_endpoint("tidy", origin="http://127.0.0.1:9/", secret="s")
	leftovers = [path.name for path in preview_home().glob("*.tmp")]
	assert leftovers == [], f"temp files left in the runtime home: {leftovers}"
