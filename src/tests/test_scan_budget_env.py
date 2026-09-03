"""Zero-hardcoding contract for the bounded-scan ceilings (owner-report fix).

The desktop fork (40k+ files) hit the baked-in 1,000-entry ceiling and the
receipt read like a product limit. Every scan knob is now an env getter read
PER CONSTRUCTION -- PULSEAI_SCAN_* -- with clamps, and an explicit argument
always wins over the environment.
"""
from __future__ import annotations

import os

import pytest

from src.context.bounded_scan import ContextBudget, ScanLimits, default_scan_limits

_KNOBS = {
    "PULSEAI_SCAN_MAX_SECONDS": "10",
    "PULSEAI_SCAN_MAX_FILES": "2000",
    "PULSEAI_SCAN_MAX_BYTES": str(32 * 1024 * 1024),
    "PULSEAI_SCAN_MAX_FILE_BYTES": str(2 * 1024 * 1024),
    "PULSEAI_SCAN_MAX_ENTRIES": "2500",
    "PULSEAI_SCAN_MAX_VISITED": "2600",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in _KNOBS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_env_unset():
    limits = default_scan_limits()
    assert limits.max_elapsed == 5.0
    assert limits.max_files == 1000
    assert limits.max_bytes == 16 * 1024 * 1024
    assert limits.max_file_bytes == 1024 * 1024
    assert limits.max_considered == 1000
    assert limits.max_visited == 1000


def test_env_values_flow_per_construction(monkeypatch):
    for name, value in _KNOBS.items():
        monkeypatch.setenv(name, value)
    first = ContextBudget()
    second = ContextBudget()
    assert first.max_elapsed == 10.0
    assert first.max_files == 2000
    assert first.max_bytes == 32 * 1024 * 1024
    assert first.max_file_bytes == 2 * 1024 * 1024
    assert first.max_considered == 2500
    assert first.max_visited == 2600
    # per-call getter: raising the env between constructions moves the ceiling
    monkeypatch.setenv("PULSEAI_SCAN_MAX_FILES", "3000")
    assert second.max_files == 2000
    assert ContextBudget().max_files == 3000


def test_env_change_between_constructions_is_honored(monkeypatch):
    monkeypatch.setenv("PULSEAI_SCAN_MAX_ENTRIES", "500")
    assert ContextBudget().max_considered == 500
    monkeypatch.setenv("PULSEAI_SCAN_MAX_ENTRIES", "5000")
    assert ContextBudget().max_considered == 5000


def test_clamps_reject_absurd_values(monkeypatch):
    monkeypatch.setenv("PULSEAI_SCAN_MAX_FILES", "0")  # below lo=1
    monkeypatch.setenv("PULSEAI_SCAN_MAX_SECONDS", "9999")  # above hi=120
    monkeypatch.setenv("PULSEAI_SCAN_MAX_BYTES", "1")  # below 64 KiB
    limits = default_scan_limits()
    assert limits.max_files == 1
    assert limits.max_elapsed == 120.0
    assert limits.max_bytes == 65_536


def test_garbage_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("PULSEAI_SCAN_MAX_FILES", "not-a-number")
    monkeypatch.setenv("PULSEAI_SCAN_MAX_SECONDS", "")
    limits = default_scan_limits()
    assert limits.max_files == 1000
    assert limits.max_elapsed == 5.0


def test_explicit_arguments_win_over_env(monkeypatch):
    monkeypatch.setenv("PULSEAI_SCAN_MAX_FILES", "2000")
    budget = ContextBudget(max_files=7)
    assert budget.max_files == 7
    limits = ScanLimits(max_files=9)
    assert limits.max_files == 9


def test_share_slices_derive_from_env_sized_pool(monkeypatch):
    monkeypatch.setenv("PULSEAI_SCAN_MAX_FILES", "2000")
    pool = ContextBudget()
    a, b = pool.share(2), pool.share(2)
    assert a.to_limits().max_files == 1000
    assert b.to_limits().max_files == 1000


def test_unbounded_still_unbounded(monkeypatch):
    monkeypatch.setenv("PULSEAI_SCAN_MAX_SECONDS", "10")
    monkeypatch.setenv("PULSEAI_SCAN_MAX_FILES", "50")
    budget = ContextBudget.unbounded()
    # explicit sentinel arguments must beat the env: 0 = no deadline, 0 bytes
    # cap = unlimited, 2**31 = uncountable, and ONLY this path may embed.
    assert budget.max_elapsed == 0
    assert budget.max_files == 2**31
    assert budget.max_bytes == 0
    assert budget.allow_embedding_compute is True
