import os

from src.llm.preflight import provider_preflight


def test_preflight_refuses_missing_config(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    result = provider_preflight()
    assert result["ok"] is False
    assert "missing" in result["error"]
    assert "key" not in result


def test_preflight_success_is_redacted(monkeypatch):
    import httpx

    class Response:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "READY"}}]}

    captured = {}
    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_API_KEY", "secret-value")
    monkeypatch.setenv("CUSTOM_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("LLM_MODEL", "model")
    monkeypatch.setattr(httpx, "post", fake_post)
    result = provider_preflight()
    assert result["ok"] is True
    assert result["response_received"] is True
    assert "secret-value" not in repr(result)
    assert captured["json"]["max_tokens"] == 2


def test_preflight_timeout_is_fail_closed_and_redacted(monkeypatch):
    import httpx

    monkeypatch.setenv("LLM_PROVIDER", "custom")
    monkeypatch.setenv("CUSTOM_API_KEY", "secret-value")
    monkeypatch.setenv("CUSTOM_BASE_URL", "https://provider.example/v1")
    monkeypatch.setenv("LLM_MODEL", "model")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ReadTimeout("slow")))
    result = provider_preflight(timeout=0.1)
    assert result["ok"] is False
    assert result["error"] == "ReadTimeout"
    assert "secret-value" not in repr(result)
