"""Voice pipeline: speech-to-text and text-to-speech for Pulse (Floor 5).

hermes ships ~8,000 lines of voice (tts_tool 4,827 + transcription 3,419 +
wake words + streaming). Pulse gets the right-sized core for an IDE call:

  * ``transcribe(audio_bytes, filename)`` — audio in, text out. Provider:
    Groq ``whisper-large-v3-turbo`` (fast, cheap, key Pulse already has).
  * ``speak(text)`` — text in, audio bytes (wav) out. Provider: Groq
    ``playai-tts`` (voice ``Fritz-PlayAI``), OpenAI-compatible endpoints
    also honored via ``PULSEAI_TTS_BASE_URL``.

Fail-closed by contract: no key, no provider, or any transport failure
returns a structured error dict — a voice hiccup must never kill a turn
(the D17 crash-net idiom). The HTTP transport is injectable so the whole
pipeline is contract-testable with zero network.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Configuration — ENV-DRIVEN, NEVER HARDCODED (the repo's "getters, never
# captured values" rule: these are read PER CALL so a settings change or
# provider swap mid-session is always honored; nothing here is baked in at
# import time). Defaults exist only as fallbacks; every one is overridable.
# ---------------------------------------------------------------------------

def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def stt_url() -> str:
    """Speech-to-text endpoint (OpenAI-compatible /audio/transcriptions)."""
    return _env("PULSEAI_STT_URL", "https://api.groq.com/openai/v1/audio/transcriptions")


def stt_model() -> str:
    return _env("PULSEAI_STT_MODEL", "whisper-large-v3-turbo")


def tts_url() -> str:
    """Text-to-speech endpoint (OpenAI-compatible /audio/speech)."""
    return _env("PULSEAI_TTS_URL", "https://api.groq.com/openai/v1/audio/speech")


def tts_model() -> str:
    return _env("PULSEAI_TTS_MODEL", "playai-tts")


def tts_voice() -> str:
    return _env("PULSEAI_TTS_VOICE", "Fritz-PlayAI")


def max_transcribe_bytes() -> int:
    return int(_env("PULSEAI_VOICE_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))


def max_speak_chars() -> int:
    return int(_env("PULSEAI_VOICE_MAX_SPEAK_CHARS", "10000"))


def _api_key() -> str:
    """Credential resolution, most-specific first: per-feature keys, then the
    voice key, then the provider key the app already carries. No key is ever
    hardcoded; everything comes from the environment the deployment owns."""
    return (
        os.environ.get("PULSEAI_STT_API_KEY")
        or os.environ.get("PULSEAI_TTS_API_KEY")
        or os.environ.get("PULSEAI_VOICE_API_KEY")
        or os.environ.get("GROQ_API_KEY")
        or os.environ.get("PULSEAI_API_KEY")
        or ""
    )


@dataclass
class VoiceResult:
    ok: bool
    text: str = ""
    audio: bytes = b""
    error: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "text": self.text, "error": self.error}


def transcribe(
    audio: bytes,
    filename: str = "audio.webm",
    *,
    transport: Callable[..., Any] | None = None,
    api_key: str | None = None,
) -> VoiceResult:
    """Audio bytes -> transcript text. ``transport`` is httpx.post-shaped
    (url, data, files, headers) and injectable for tests."""
    if not audio:
        return VoiceResult(ok=False, error="no audio received")
    limit = max_transcribe_bytes()
    if len(audio) > limit:
        return VoiceResult(ok=False, error=f"audio too large ({limit} byte limit)")
    key = api_key if api_key is not None else _api_key()
    if not key:
        return VoiceResult(ok=False, error="no voice API key configured (GROQ_API_KEY)")
    post = transport or _default_transport
    try:
        resp = post(
            stt_url(),
            data={"model": stt_model(), "response_format": "json"},
            files={"file": (filename, audio)},
            headers={"Authorization": f"Bearer {key}"},
        )
        body = resp.json() if hasattr(resp, "json") else json_loads(resp)
        text = str(body.get("text") or "").strip()
        if not text:
            return VoiceResult(ok=False, error="transcription came back empty")
        return VoiceResult(ok=True, text=text)
    except Exception as exc:
        return VoiceResult(ok=False, error=f"transcription failed: {type(exc).__name__}: {exc}")


def speak(
    text: str,
    *,
    transport: Callable[..., Any] | None = None,
    api_key: str | None = None,
) -> VoiceResult:
    """Text -> audio bytes (wav). Same fail-closed contract."""
    text = (text or "").strip()
    if not text:
        return VoiceResult(ok=False, error="nothing to speak")
    if len(text) > max_speak_chars():
        text = text[:max_speak_chars()]
    key = api_key if api_key is not None else _api_key()
    if not key:
        return VoiceResult(ok=False, error="no voice API key configured (GROQ_API_KEY)")
    post = transport or _default_transport
    base = _env("PULSEAI_TTS_BASE_URL") or tts_url()
    try:
        resp = post(
            base,
            json={"model": tts_model(), "voice": tts_voice(), "input": text, "response_format": "wav"},
            headers={"Authorization": f"Bearer {key}"},
        )
        audio = resp.content if hasattr(resp, "content") else resp
        if not audio:
            return VoiceResult(ok=False, error="tts came back empty")
        return VoiceResult(ok=True, audio=audio)
    except Exception as exc:
        return VoiceResult(ok=False, error=f"tts failed: {type(exc).__name__}: {exc}")


def _default_transport(url: str, **kwargs: Any) -> Any:
    """httpx, imported lazily — the voice feature must not tax startup."""
    import httpx

    return httpx.post(url, timeout=60.0, **kwargs)


def json_loads(obj: Any) -> dict:
    import json

    return json.loads(obj) if isinstance(obj, (str, bytes)) else dict(obj)
