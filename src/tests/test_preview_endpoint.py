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
import sys
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
	"""A concurrent reader must always see a complete document, or nothing at all.

	Two platform facts shape this test, and the second one cost a Windows run to learn:

	* POSIX renames never disturb a reader, so on Linux this only ever caught a writer that was
	  non-atomic by construction;
	* on Windows a *tight-loop reader* is part of the problem: it holds the destination open, and
	  Windows refuses to replace a destination somebody holds open (``os.replace`` ->
	  ``PermissionError``, which is why the writer retries). Reading while a replace is in flight can
	  also fail outright, and ``read_endpoint`` reports that as ``None`` — so a transient ``None`` is
	  one of the two outcomes this test's contract allows ("a complete document, or nothing at all"),
	  not a defect. Asserting that ``None`` never happens made this test a Linux-only test.

	So the readers pace themselves (they do not hold the file open in a loop), a ``None`` read is
	tolerated and counted, and the strength moves to the reads that *did* succeed: each one must be a
	document that belongs to exactly one write. ``token`` and ``n`` are written together, so a payload
	where they disagree is torn even though it parses as JSON — that is the failure the atomic write
	exists to prevent, and it fails here on any platform.

	The writer's own failures are collected rather than left to die in a thread: ``write_endpoint``
	can raise when even its fallback fails, and a silently dead writer would look exactly like a
	passing test.

	What the count assertion can and cannot do, stated plainly because the first version of this test
	passed against a deliberately non-atomic writer: a torn document mostly surfaces as an
	*unreadable* file, and a measured tear rate of 20% still left 240 of 300 reads complete — so
	"some reads worked" proves nothing. On POSIX it does not have to prove anything by counting:
	``os.replace`` is atomic and never disturbs a reader holding the old file, so a single unreadable
	read *is* the regression, and that is asserted exactly. Windows is where a paced reader can be
	refused the file while a replace is in flight — a transient "nothing at all", not a tear — so there
	the count is merely bounded. The writer's mechanism is pinned deterministically, on either
	platform, by the two monkeypatched tests above.
	"""
	origin = "http://127.0.0.1:1"
	write_endpoint("sess-4", origin=f"{origin}/", token="t0", extra={"n": 0})

	# The readers only read *while the writer is running* — that is the only interesting window — so
	# the write count decides how much of the test is real. At ~200us a write this is ~0.5s of
	# contention, i.e. ~100 reads per reader at the 5ms pacing below; far more on Windows, where the
	# same loop is slowed by exactly the replace failures this test exists for.
	writes = 3000
	pacing_seconds = 0.005
	attempts_each = 20_000  # a cap, not a target: the writer finishing is what ends a reader
	writer_done = threading.Event()
	counters = [{"ok": 0, "none": 0} for _ in range(3)]
	problems: list[str] = []
	writer_errors: list[BaseException] = []

	def reader(counter: dict[str, int]) -> None:
		for _ in range(attempts_each):
			if writer_done.is_set():
				return
			payload = read_endpoint("sess-4")
			if payload is None:
				# Allowed: nothing at all. Counted, and bounded by the assertion below.
				counter["none"] += 1
			else:
				token = str(payload.get("token", ""))
				index = token[1:] if token.startswith("t") else ""
				if not index.isdigit():
					problems.append(f"torn payload: {payload!r}")
					return
				if payload.get("n") != int(index):
					problems.append(
						f"mixed write: token={token!r} belongs to a different document than "
						f"n={payload.get('n')!r} — the reader saw two writes in one file"
					)
					return
				if payload.get("origin") != origin:
					problems.append(f"unexpected origin: {payload.get('origin')!r}")
					return
				counter["ok"] += 1
			time.sleep(pacing_seconds)

	def writer() -> None:
		try:
			for index in range(writes):
				write_endpoint("sess-4", origin=f"{origin}/", token=f"t{index}", extra={"n": index})
		except BaseException as exc:  # noqa: BLE001 - reported, never swallowed
			writer_errors.append(exc)
		finally:
			writer_done.set()

	threads = [threading.Thread(target=reader, args=(counter,)) for counter in counters]
	writer_thread = threading.Thread(target=writer)
	for thread in threads:
		thread.start()
	writer_thread.start()
	writer_thread.join(timeout=60)
	for thread in threads:
		thread.join(timeout=30)

	assert not writer_thread.is_alive(), (
		f"the writer never finished {writes} publishes in 60s — the publish retry is not converging"
	)
	assert not writer_errors, writer_errors[:1]
	assert not problems, problems[:3]
	complete = sum(counter["ok"] for counter in counters)
	unreadable = sum(counter["none"] for counter in counters)
	attempts = complete + unreadable

	if sys.platform != "win32":
		# See the docstring: on POSIX an atomic replace cannot hide the file from a reader, so one
		# unreadable read means the publish stopped being atomic. This is what fails on a regressed
		# `_publish` (measured: 25 unreadable reads out of 122 with the atomic rename removed).
		assert unreadable == 0, (
			f"{unreadable} unreadable read(s) out of {attempts} on {sys.platform}, where os.replace is "
			"atomic — the endpoint is being rewritten in place rather than renamed into position"
		)
	assert complete >= 100, (
		f"only {complete} complete reads out of {attempts} attempts "
		f"({unreadable} returns of None) — the endpoint was effectively unreadable"
	)


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
