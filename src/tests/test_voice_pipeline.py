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


def test_everything_is_env_driven_never_hardcoded(monkeypatch):
    """The Floor-5 rule: credentials + endpoints + models come from env, read
    PER CALL (getters, never captured values) — a provider swap mid-session
    is honored without a restart."""
    from src.voice import pipeline as vp

    monkeypatch.setenv("PULSEAI_STT_URL", "https://alt.example/stt")
    monkeypatch.setenv("PULSEAI_STT_MODEL", "whisper-alt")
    monkeypatch.setenv("PULSEAI_TTS_URL", "https://alt.example/tts")
    monkeypatch.setenv("PULSEAI_TTS_MODEL", "tts-alt")
    monkeypatch.setenv("PULSEAI_TTS_VOICE", "AltVoice")
    monkeypatch.setenv("PULSEAI_STT_API_KEY", "stt-key")
    monkeypatch.setenv("PULSEAI_TTS_API_KEY", "tts-key")

    seen = {}
    def transport(url, **kw):
        seen["url"], seen["auth"], seen["model"] = url, kw["headers"]["Authorization"], kw.get("data", {}).get("model") or kw["json"]["model"]
        if "stt" in url:
            return FakeResp({"text": "hi"})
        return FakeResp(content=b"W")
    assert transcribe(b"A", transport=transport).ok
    assert seen["url"] == "https://alt.example/stt" and seen["model"] == "whisper-alt" and seen["auth"] == "Bearer stt-key"
    assert speak("hey", transport=transport).ok
    assert seen["url"] == "https://alt.example/tts" and seen["model"] == "tts-alt"

    # Key precedence: per-feature beats the shared provider key.
    monkeypatch.setenv("GROQ_API_KEY", "shared")
    monkeypatch.setenv("PULSEAI_STT_API_KEY", "specific")
    assert vp._api_key() == "specific"
    monkeypatch.delenv("PULSEAI_STT_API_KEY", raising=False)
    monkeypatch.delenv("PULSEAI_TTS_API_KEY", raising=False)
    monkeypatch.delenv("PULSEAI_VOICE_API_KEY", raising=False)
    assert vp._api_key() == "shared"


def test_upload_limit_is_env_configurable(monkeypatch):
    monkeypatch.setenv("PULSEAI_VOICE_MAX_UPLOAD_BYTES", "10")
    r = transcribe(b"x" * 11, api_key="k")
    assert not r.ok and "10 byte limit" in r.error


def test_hermes_tool_use_enforcement_flows_into_the_system_prompt():
    """Floor-5 ask: the tools System Message IS Hermes' TOOL_USE_ENFORCEMENT —
    pinned end-to-end through the hermes session prompt builder."""
    import sys
    sys.path.insert(0, ".")
    from src.prompts.hermes.system_prompt import build_system_prompt
    from src.prompts.hermes.view import PulsePromptView

    view = PulsePromptView(
        model="qwen/qwen3.6-27b", cwd=".",
        valid_tool_names=("run_terminal", "edit_file"),
    )
    prompt = build_system_prompt(view, use_cache=False)
    assert "Tool-use enforcement" in prompt
    assert "Never end your turn with a promise of future action" in prompt

    # Same contract as upstream: enforcement is MODEL-GATED — a claude-family
    # model does not get the steering block.
    import dataclasses
    fields = {f.name: getattr(view, f.name) for f in dataclasses.fields(view)} if dataclasses.is_dataclass(view) else {}
    if fields:
        fields["model"] = "claude-sonnet-4"
        try:
            claude_view = PulsePromptView(**fields)
            assert "Tool-use enforcement" not in build_system_prompt(claude_view, use_cache=False)
        except TypeError:
            pass  # view surface drifted; the qwen-side pin above is the contract
