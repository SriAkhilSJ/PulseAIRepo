"""The key checker must never lie about a key it has not tested.

These pin the parts that decide whether a report is trustworthy: redaction,
shape rules, key collection, and the "unknown is not offered" rule.
"""

from __future__ import annotations

import importlib.util
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_velona_keys", REPO_ROOT / "scripts" / "check_velona_keys.py"
)
checker = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(checker)


def test_a_key_is_never_printed():
    key = "key_live_ABCDEFGHIJKLMNOPQRSTUVWX1234"
    shown = checker.mask(key)
    assert key not in shown
    assert shown == f"len={len(key)} …1234"
    assert shown.endswith(key[-4:]) and len(shown) < 20


def test_shape_rejects_the_classic_failures():
    ok, _ = checker.check_shape("key_live_" + "a" * 32)
    assert ok
    assert not checker.check_shape("  key_live_" + "a" * 32)[0]   # copied newline
    assert not checker.check_shape("key_live_ab cd" + "a" * 30)[0]  # inner space
    assert not checker.check_shape("sk-proj-" + "a" * 32)[0]       # wrong vendor
    assert not checker.check_shape("key_live_abc")[0]             # truncated


def test_keys_are_collected_trimmed_and_deduplicated(monkeypatch):
    monkeypatch.setenv("CUSTOM_API_KEYS", "key_live_aaa1, key_live_bbb2")
    monkeypatch.setenv("CUSTOM_API_KEY", " key_live_bbb2 ")  # duplicate, untrimmed
    monkeypatch.delenv("CRUSORAI_CHEAP_API_KEY", raising=False)
    keys = checker.collect_keys()
    assert [k for _s, k in keys] == ["key_live_aaa1", "key_live_bbb2"]
    assert all(k == k.strip() for _s, k in keys)


def test_named_keys_are_supported(monkeypatch):
    monkeypatch.setenv("CUSTOM_API_KEYS", "main:key_live_aaa1,cheap:key_live_bbb2")
    monkeypatch.delenv("CUSTOM_API_KEY", raising=False)
    monkeypatch.delenv("CRUSORAI_CHEAP_API_KEY", raising=False)
    assert [k for _s, k in checker.collect_keys()] == ["key_live_aaa1", "key_live_bbb2"]


def test_the_three_models_under_test_are_the_pinned_ones():
    assert [m for m, _role in checker.MODELS] == [
        "z-ai/glm-5.3-flash",
        "deepseek/deepseek-v4.1-flash",
        "qwen/qwen3.7-flash",
    ]


def test_an_unreadable_catalog_never_reports_a_model_as_offered():
    """An empty catalog means unknown, and unknown must not be printed as a tick."""
    source = (REPO_ROOT / "scripts" / "check_velona_keys.py").read_text(encoding="utf-8")
    assert "(m in ids if ids else None)" in source
