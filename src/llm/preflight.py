"""Cheap provider readiness probe for credit-sensitive live benchmarks."""
from __future__ import annotations

import os
import time
from typing import Any


def provider_preflight(timeout: float = 20.0) -> dict[str, Any]:
    """Send one tiny OpenAI-compatible request and return a redacted receipt.

    This is deliberately outside the agent graph: if the endpoint is queued,
    depleted, or unhealthy, no workspace setup or benchmark turn should start.
    Credentials are never included in the result.
    """
    provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if provider != "custom":
        return {
            "ok": False, "provider": provider or "unset", "latency_ms": 0,
            "error": "preflight currently supports the custom OpenAI-compatible provider",
        }
    base = os.environ.get("CUSTOM_BASE_URL", "").rstrip("/")
    key = os.environ.get("CUSTOM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")
    if not base or not key or not model:
        return {
            "ok": False, "provider": "custom", "latency_ms": 0,
            "error": "provider URL, model, or API key is missing",
        }

    import httpx

    started = time.monotonic()
    try:
        response = httpx.post(
            base + "/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply only READY"}],
                "max_tokens": 2,
                "temperature": 0,
            },
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
        )
        latency = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            return {
                "ok": False, "provider": "custom", "model": model,
                "latency_ms": latency, "status_code": response.status_code,
                "error": "provider returned a non-success status",
            }
        payload = response.json()
        choices = payload.get("choices") if isinstance(payload, dict) else None
        content = ""
        if choices and isinstance(choices, list):
            content = str(((choices[0] or {}).get("message") or {}).get("content") or "")
        return {
            "ok": bool(content.strip()), "provider": "custom", "model": model,
            "latency_ms": latency, "status_code": response.status_code,
            "response_received": bool(content.strip()),
        }
    except Exception as exc:
        return {
            "ok": False, "provider": "custom", "model": model,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": type(exc).__name__,
        }
