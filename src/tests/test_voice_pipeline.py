"""Contracts: the voice pipeline (Floor 5) — injected transport, zero network."""
import json

from src.voice.pipeline import VoiceResult, speak, transcribe


class FakeResp:
    def __init__(self, payload=None, content=b""):
        self._payload = payload
        self.content = content
    def json(self):
        return self._payload


def test_transcribe_roundtrip():
    calls = {}
    def transport(url, **kw):
        calls["url"], calls["files"] = url, kw["files"]
        return FakeResp({"text": "  fix the login bug  "})
    r = transcribe(b"AUDIO", "clip.webm", transport=transport, api_key="k")
    assert r.ok and r.text == "fix the login bug"
    assert calls["url"].endswith("/audio/transcriptions")
    assert calls["files"]["file"][0] == "clip.webm"


def test_transcribe_fail_closed():
    assert not transcribe(b"").ok
    assert not transcribe(b"A", api_key="").ok
    big = b"x" * (26 * 1024 * 1024)
    assert "too large" in transcribe(big, api_key="k").error
    r = transcribe(b"A", transport=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")), api_key="k")
    assert not r.ok and "transcription failed" in r.error
    assert r.as_dict()["ok"] is False


def test_speak_roundtrip_and_fail_closed():
    def transport(url, **kw):
        assert kw["json"]["voice"] == "Fritz-PlayAI"
        return FakeResp(content=b"WAVD")
    r = speak("hello", transport=transport, api_key="k")
    assert r.ok and r.audio == b"WAVD"
    assert not speak("", api_key="k").ok
    assert not speak("hello", api_key="").ok
    def boom(url, **kw): raise OSError("net down")
    assert "tts failed" in speak("hi", transport=boom, api_key="k").error
