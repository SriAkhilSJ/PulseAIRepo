"""Connect vs read, dead hosts vs slow hosts -- the distinction the owner's endpoint needed.

Hermes separates "nothing is there" from "something is thinking" (agent/model_metadata.py @ 8cab422) and Pulse
did not: one flat 2.5s budget meant a 5.1s / 503 KB / 1,572-model catalog on localhost was indistinguishable from
a dead host, and the engine concluded the provider published no window. Also ported: probing `localhost` on a
Windows dual-stack machine pays a ~2s IPv6 connect timeout before falling back to IPv4 -- which is exactly the
owner's `http://localhost:20128/v1`.

These run without httpx or a network: a fake httpx module is injected, because the code paths under test are the
exception handlers themselves.
"""
from __future__ import annotations

import sys
import types

import pytest

from src.context import model_budgets as mb


class ConnectTimeout(Exception):
    pass


class ReadTimeout(Exception):
    pass


class _FakeTimeout:
    def __init__(self, read, connect=None, **kwargs):
        self.read = read
        self.connect = connect


@pytest.fixture(autouse=True)
def fake_httpx(monkeypatch):
    calls: list[tuple[str, object]] = []
    state = {"raise": None, "json": {"data": []}, "status": 200, "calls": calls}

    def get(url, headers=None, timeout=None):
        calls.append((url, timeout))
        if state["raise"]:
            raise state["raise"]()
        return types.SimpleNamespace(status_code=state["status"], json=lambda: state["json"])

    mod = types.ModuleType("httpx")
    mod.Timeout = lambda read, connect=None, **kw: _FakeTimeout(read, connect)
    mod.get = get
    mod.ConnectTimeout = ConnectTimeout
    mod.ConnectError = ConnectionError
    mod.ReadTimeout = ReadTimeout
    monkeypatch.setitem(sys.modules, "httpx", mod)
    mb._blackholed.clear()
    mb._failures.clear()
    return state


def test_connect_and_read_budgets_are_separate_numbers(fake_httpx):
    mb._http_get_json("http://127.0.0.1:20128/v1/models", timeout=12.0, connect_timeout=5.0)
    (url, timeout), = fake_httpx["calls"]
    assert isinstance(timeout, _FakeTimeout), "a flat number is the bug, not the fix"
    assert (timeout.read, timeout.connect) == (12.0, 5.0)


def test_a_connect_timeout_blackholes_the_host_but_a_read_timeout_does_not(fake_httpx):
    base = "http://localhost:20128/v1"

    fake_httpx["raise"] = ConnectTimeout
    assert mb._http_get_json(f"{base}/models", base_url=base) is None
    assert mb._is_blackholed(base), "a host that never answered must not be paid again on every probe"

    mb._blackholed.clear()
    fake_httpx["raise"] = ReadTimeout
    assert mb._http_get_json(f"{base}/models", base_url=base) is None
    assert not mb._is_blackholed(base), (
        "a read timeout means the server accepted the connection -- blackholing it hides a HEALTHY endpoint"
    )


def test_blackhole_is_keyed_on_host_and_port_not_on_path(fake_httpx):
    fake_httpx["raise"] = ConnectTimeout
    mb._http_get_json("http://localhost:20128/v1/models", base_url="http://localhost:20128/v1")
    assert mb._is_blackholed("http://localhost:20128"), "same server, different probe path, one verdict"
    assert not mb._is_blackholed("http://localhost:20129"), "a different port is a different server"


def test_the_localhost_ipv4_penalty_is_skipped(fake_httpx):
    mb._http_get_json("http://localhost:20128/v1/models")
    (url, _timeout), = fake_httpx["calls"]
    assert url == "http://127.0.0.1:20128/v1/models", url


def test_a_localhost_mentioned_only_in_the_query_is_left_alone(fake_httpx):
    weird = "https://router.example/v1/models?upstream=http://localhost:11434"
    mb._http_get_json(weird)
    (url, _timeout), = fake_httpx["calls"]
    assert url == weird, "only the URL's own host may be rewritten"


def test_the_catalog_skips_a_blackholed_endpoint_without_touching_the_network(fake_httpx):
    base = "http://localhost:20128/v1"
    mb._note_blackhole(base)
    fake_httpx["calls"].clear()
    assert mb._endpoint_catalog(base) == []
    assert fake_httpx["calls"] == [], "the whole point of the blackhole cache: no probe is issued at all"


def test_a_failed_verdict_is_forgotten_in_minutes_not_hours(monkeypatch):
    monkeypatch.setattr(mb, "_endpoint_catalog", lambda base: [])
    monkeypatch.setattr(mb, "_endpoint_auth_headers", lambda: {})
    import src.config.settings as settings
    monkeypatch.setattr(settings, "CUSTOM_BASE_URL", "http://localhost:20128/v1", raising=False)
    monkeypatch.delenv("LLM_CONTEXT_WINDOW", raising=False)
    monkeypatch.setattr(mb, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(mb, "_write_cache", lambda *a, **k: None)

    asked: list[str] = []
    monkeypatch.setattr(mb, "_endpoint_catalog", lambda base: asked.append(base) or [])
    mb.resolve_context_window("brand-new-abc", provider="custom", endpoint_probe=True)
    assert len(asked) == 1
    mb.resolve_context_window("brand-new-abc", provider="custom", endpoint_probe=True)
    assert len(asked) == 1, "a failure just recorded must not be re-asked on every construction"

    key = "custom:brand-new-abc"
    mb._failures[key] = mb._now() - (mb._FAILURE_TTL_S + 1)
    mb.resolve_context_window("brand-new-abc", provider="custom", endpoint_probe=True)
    assert len(asked) == 2, "and it must expire: the server may simply have been starting up"
