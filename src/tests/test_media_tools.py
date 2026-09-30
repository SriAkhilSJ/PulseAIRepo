"""Tests for media_tools — image/video sourcing for UI work.

Pins the capability that closes the "changed the product but never got the
product photo" gap:
  - media_search merges Openverse + Wikimedia (keyless) and Pexels (optional
    PEXELS_API_KEY), dedupes by URL, tolerates a failing source, and NEVER
    raises (D17: error strings go back to the model).
  - media_download validates scheme/content-type/size, confines to
    workspace-relative paths, sniffs the real type when the server lies,
    removes partial files on abort, and retries ONCE on HTTP 429 before
    failing fast with a "do not loop" message.
  - the tools are bound into the research toolset.
All network is mocked — no live HTTP in the suite.
"""

import pytest

from src.tools.media_tools import (
    _MAX_IMAGE_BYTES,
    _sanitize_dest,
    media_download,
    media_search,
)
from src.tools.toolsets import resolve_runtime_tool_names


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class _FakeResp:
    def __init__(self, payload=None):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Boom:
    """Callable that raises — stands in for an unreachable source."""

    def __init__(self, error: Exception):
        self._error = error

    def __call__(self, params=None):
        raise self._error


OPENVERSE_PAYLOAD = {
    "results": [
        {
            "title": "Amber perfume bottle",
            "url": "https://example.org/amber.jpg",
            "width": 1600, "height": 1000,
            "license": "by", "license_version": "4.0",
            "provider": "flickr",
            "foreign_landing_url": "https://example.org/page/amber",
        },
        {
            "title": "duplicate url is deduped",
            "url": "https://example.org/amber.jpg",
            "width": 1, "height": 1, "license": "cc0",
            "provider": "rawpixel", "foreign_landing_url": "",
        },
    ]
}

WIKIMEDIA_PAYLOAD = {
    "query": {
        "pages": {
            "10": {
                "title": "File:Perfume webm loop.webm",
                "imageinfo": [{
                    "url": "https://upload.example/loop.webm",
                    "mime": "video/webm", "width": 640, "height": 480,
                    "descriptionurl": "https://commons.example/loop",
                    "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}},
                }],
            },
            "11": {
                "title": "File:Perfume photo.jpg",
                "imageinfo": [{
                    "url": "https://upload.example/photo.jpg",
                    "mime": "image/jpeg", "width": 4000, "height": 3000,
                    "descriptionurl": "https://commons.example/photo",
                    "extmetadata": {},
                }],
            },
        }
    }
}

PEXELS_PAYLOAD = {
    "photos": [{
        "alt": "studio shot", "src": {"large": "https://pexels.example/l.jpg"},
        "width": 2000, "height": 1200, "url": "https://pexels.example/p",
    }],
    "videos": [{
        "url": "https://pexels.example/v", "duration": 12,
        "video_files": [
            {"link": "https://pexels.example/v4k.mp4", "file_type": "video/mp4", "width": 3840},
            {"link": "https://pexels.example/v640.mp4", "file_type": "video/mp4", "width": 640},
        ],
    }],
}


def _patch_get(monkeypatch, route: dict):
    """route: substring of URL -> callable(params)->_FakeResp (or raising)."""
    def fake_get(url, params=None, headers=None, timeout=None):
        for frag, fn in route.items():
            if frag in url:
                return fn(params or {})
        raise RuntimeError(f"unrouted URL in test: {url}")
    monkeypatch.setattr("src.tools.media_tools.httpx.get", fake_get)


# ---------------------------------------------------------------------------
# media_search
# ---------------------------------------------------------------------------

def test_search_arg_validation():
    assert "must not be empty" in media_search.invoke({"query": "  "})
    assert "media_type" in media_search.invoke({"query": "perfume", "media_type": "wav"})


def test_search_merges_sources_dedupes_and_formats(monkeypatch):
    _patch_get(monkeypatch, {
        "api.openverse.org": lambda p: _FakeResp(OPENVERSE_PAYLOAD),
        "commons.wikimedia.org": lambda p: _FakeResp(WIKIMEDIA_PAYLOAD),
        "api.pexels.com": _Boom(RuntimeError("no key route")),
    })
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    out = media_search.invoke({"query": "perfume bottle", "media_type": "all"})
    assert "Amber perfume bottle" in out
    assert "https://example.org/amber.jpg" in out
    assert "CC by 4.0" in out
    # dedupe: amber.jpg listed once though two openverse rows carry it
    assert out.count("https://example.org/amber.jpg") == 1
    # wikimedia video survived the "all" filter with license from extmetadata
    assert "loop.webm" in out and "CC BY-SA 4.0" in out
    assert "media_download" in out  # the next-step nudge


def test_search_tolerates_a_failing_source(monkeypatch):
    _patch_get(monkeypatch, {
        "api.openverse.org": _Boom(RuntimeError("boom")),
        "commons.wikimedia.org": lambda p: _FakeResp(WIKIMEDIA_PAYLOAD),
        "api.pexels.com": _Boom(RuntimeError("no key route")),
    })
    out = media_search.invoke({"query": "perfume", "media_type": "image"})
    assert "photo.jpg" in out  # wikimedia results still returned
    assert "openverse" in out  # the failure is surfaced, not swallowed


def test_search_all_sources_failing_returns_error_string(monkeypatch):
    def _raise(url, params=None, headers=None, timeout=None):
        raise RuntimeError("network down")
    monkeypatch.setattr("src.tools.media_tools.httpx.get", _raise)
    out = media_search.invoke({"query": "perfume", "media_type": "image"})
    assert out.startswith("No media found")
    assert "network down" in out


def test_search_pexels_needs_key_then_used_when_set(monkeypatch):
    route = {"api.pexels.com": lambda p: _FakeResp(PEXELS_PAYLOAD)}
    _patch_get(monkeypatch, route)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    out = media_search.invoke({"query": "perfume", "media_type": "all"})
    assert "pexels.example" not in out  # no key: pexels contributes nothing

    monkeypatch.setenv("PEXELS_API_KEY", "test-key-123")
    out = media_search.invoke({"query": "perfume", "media_type": "all"})
    assert "studio shot" in out and "pexels.example/l.jpg" in out
    # video file picked is the SMALL mp4, not the 4K
    assert "v640.mp4" in out and "v4k.mp4" not in out
    assert "Authorization" not in out  # key never leaks into model context


def test_search_wikimedia_video_query_uses_filetype_video(monkeypatch):
    captured = {}

    def commons(params):
        captured["gsrsearch"] = params.get("gsrsearch")
        return _FakeResp({"query": {"pages": {}}})

    _patch_get(monkeypatch, {"commons.wikimedia.org": commons})
    media_search.invoke({"query": "ocean waves", "media_type": "video"})
    assert "filetype:video" in (captured["gsrsearch"] or "")


# ---------------------------------------------------------------------------
# media_download — path + content-type + size discipline
# ---------------------------------------------------------------------------

def test_sanitize_dest_rejects_traversal_and_absolute():
    err1 = _sanitize_dest("../escape.png", "image/png")[1]
    err2 = _sanitize_dest("/etc/passwd", "image/png")[1]
    err3 = _sanitize_dest("", "image/png")[1]
    assert err1 and "workspace-relative" in err1
    assert err2 and "workspace-relative" in err2
    assert err3 and "empty" in err3


def test_sanitize_dest_infers_extension():
    path, err = _sanitize_dest("assets/perfume", "image/jpeg")
    assert err is None
    assert path.as_posix() == "assets/perfume.jpg"


def test_download_rejects_non_http_and_non_media(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = media_download.invoke({"url": "ftp://x/a.jpg", "filename": "a.jpg"})
    assert "only http/https" in out
    monkeypatch.setattr(
        "src.tools.media_tools.httpx.stream",
        lambda *a, **k: _FakeStreamOk([b"<html>hi</html>"], {"content-type": "text/html"}),
    )
    out = media_download.invoke({"url": "https://x/page.html", "filename": "a.jpg"})
    assert "not media" in out  # content-type text/html
    assert not (tmp_path / "a.jpg").exists()


def test_download_size_cap_from_content_length(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    class FakeStream:
        status_code = 200
        headers = {"content-type": "video/mp4", "content-length": str(100 * 1024 * 1024)}
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def raise_for_status(self):
            return None
        def iter_bytes(self, n):
            return iter(())

    monkeypatch.setattr(
        "src.tools.media_tools.httpx.stream",
        lambda *a, **k: FakeStream(),
    )
    out = media_download.invoke({"url": "https://x/big.mp4", "filename": "assets/big.mp4"})
    assert "too large" in out
    assert not (tmp_path / "assets").exists()


class _FakeStreamOk:
    status_code = 200

    def __init__(self, chunks, headers):
        self._chunks = chunks
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self, n):
        return iter(self._chunks)


def test_download_happy_path_sniffs_wrong_extension(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 500
    monkeypatch.setattr(
        "src.tools.media_tools.httpx.stream",
        lambda *a, **k: _FakeStreamOk([png], {"content-type": "image/jpeg"}),
    )
    out = media_download.invoke({
        "url": "https://x/photo", "filename": "assets/perfume.jpg",
    })
    # server claimed image/jpeg; magic bytes said PNG — the extension is fixed
    assert "saved: assets/perfume.png" in out
    assert (tmp_path / "assets" / "perfume.png").read_bytes() == png
    assert "never hotlink" in out


def test_download_stream_over_cap_aborts_and_cleans(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    big_chunk = b"\xff\xd8\xff" + b"0" * (_MAX_IMAGE_BYTES // 2)
    monkeypatch.setattr(
        "src.tools.media_tools.httpx.stream",
        lambda *a, **k: _FakeStreamOk(
            [big_chunk, big_chunk, big_chunk], {"content-type": "image/jpeg"}
        ),
    )
    out = media_download.invoke({"url": "https://x/huge.jpg", "filename": "assets/huge.jpg"})
    assert "cap" in out and "removed" in out
    assert not (tmp_path / "assets" / "huge.jpg").exists()


def test_download_empty_body_cleans_up(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.tools.media_tools.httpx.stream",
        lambda *a, **k: _FakeStreamOk([], {"content-type": "image/png"}),
    )
    out = media_download.invoke({"url": "https://x/empty.png", "filename": "assets/e.png"})
    assert "empty response" in out
    assert not (tmp_path / "assets" / "e.png").exists()


# ---------------------------------------------------------------------------
# media_download — HTTP 429 rate-limit: one bounded retry, then fail fast
# ---------------------------------------------------------------------------

class _FakeStream429:
    status_code = 429
    headers = {"retry-after": "3"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):  # never reached: status is checked first
        return None


def test_download_429_retries_once_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    slept: list[float] = []
    monkeypatch.setattr("src.tools.media_tools._pause", slept.append)
    calls = {"n": 0}

    def stream(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeStream429()
        return _FakeStreamOk([b"\xff\xd8\xff" + b"0" * 100], {"content-type": "image/jpeg"})

    monkeypatch.setattr("src.tools.media_tools.httpx.stream", stream)
    out = media_download.invoke({"url": "https://x/a.jpg", "filename": "assets/a.jpg"})
    assert "saved: assets/a.jpg" in out  # second attempt wins
    assert calls["n"] == 2
    assert slept == [3.0]  # Retry-After honored


def test_download_429_twice_gives_up_with_actionable_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    slept: list[float] = []
    monkeypatch.setattr("src.tools.media_tools._pause", slept.append)
    calls = {"n": 0}

    def stream(*a, **k):
        calls["n"] += 1
        return _FakeStream429()

    monkeypatch.setattr("src.tools.media_tools.httpx.stream", stream)
    out = media_download.invoke({"url": "https://x/loop.webm", "filename": "assets/loop.webm"})
    assert "rate-limited" in out and "429" in out
    assert "do not loop" in out.lower()  # tells the model to stop hammering
    assert calls["n"] == 2  # exactly one retry, no runaway
    assert slept == [3.0]
    assert not (tmp_path / "assets").exists()


# ---------------------------------------------------------------------------
# toolset binding — media rides the research capability gate
# ---------------------------------------------------------------------------

def test_media_tools_in_research_toolset():
    from src.agents.runtime_profile import CAP_RESEARCH, RuntimeProfile
    profile = RuntimeProfile(name="test-profile", capabilities=(CAP_RESEARCH,))
    names = resolve_runtime_tool_names(profile)
    assert "media_search" in names and "media_download" in names
