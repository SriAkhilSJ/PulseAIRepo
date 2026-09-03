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

STT_MODEL = "whisper-large-v3-turbo"
STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
TTS_MODEL = "playai-tts"
TTS_VOICE = "Fritz-PlayAI"
TTS_URL = "https://api.groq.com/openai/v1/audio/speech"
MAX_TRANSCRIBE_BYTES = 25 * 1024 * 1024  # provider hard limit
MAX_SPEAK_CHARS = 10_000


@dataclass
class VoiceResult:
    ok: bool
    text: str = ""
    audio: bytes = b""
    error: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "text": self.text, "error": self.error}


def _api_key() -> str:
    return (
        os.environ.get("GROQ_API_KEY")
        or os.environ.get("PULSEAI_VOICE_API_KEY")
        or ""
    )


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
    if len(audio) > MAX_TRANSCRIBE_BYTES:
        return VoiceResult(ok=False, error="audio too large (25MB provider limit)")
    key = api_key if api_key is not None else _api_key()
    if not key:
        return VoiceResult(ok=False, error="no voice API key configured (GROQ_API_KEY)")
    post = transport or _default_transport
    try:
        resp = post(
            STT_URL,
            data={"model": STT_MODEL, "response_format": "json"},
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
    if len(text) > MAX_SPEAK_CHARS:
        text = text[:MAX_SPEAK_CHARS]
    key = api_key if api_key is not None else _api_key()
    if not key:
        return VoiceResult(ok=False, error="no voice API key configured (GROQ_API_KEY)")
    post = transport or _default_transport
    base = os.environ.get("PULSEAI_TTS_BASE_URL", TTS_URL)
    try:
        resp = post(
            base,
            json={"model": TTS_MODEL, "voice": TTS_VOICE, "input": text, "response_format": "wav"},
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
