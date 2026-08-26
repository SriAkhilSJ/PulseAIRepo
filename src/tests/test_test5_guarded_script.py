"""Static safety contracts for the Windows Test-5 watchdog wrapper."""
from pathlib import Path


SCRIPT = (Path(__file__).parents[2] / "scripts" / "run_test5_guarded.ps1").read_text(
    encoding="utf-8"
)


def test_guarded_run_disables_unused_autonomous_memory():
    assert '$env:PULSEAI_DISABLE_LONG_TERM_MEMORY = "1"' in SCRIPT


def test_probe_uses_configured_custom_endpoint_and_model():
    assert 'values.get("CUSTOM_BASE_URL", "")' in SCRIPT
    assert 'values.get("LLM_MODEL", "")' in SCRIPT
    assert 'base_url.rstrip("/") + "/chat/completions"' in SCRIPT
    assert '"https://api.sarvam.ai/v1/chat/completions"' not in SCRIPT
    assert '"model": "sarvam-105b-conversations"' not in SCRIPT


def test_explicit_skip_probe_avoids_the_extra_provider_request():
    assert "[switch]$SkipProbe" in SCRIPT
    assert "if (-not $SkipProbe)" in SCRIPT
    assert "SKIPPED by explicit one-turn authorization" in SCRIPT


def test_watchdog_writes_durable_outcome_before_exit():
    assert "function Write-WatchdogOutcome" in SCRIPT
    assert '-Result "watchdog-hard-cap"' in SCRIPT
    assert '-Result "watchdog-stalled"' in SCRIPT
    for field in (
        "watchdog_kill", "watchdog_idle_seconds", "files_delivered",
        "delivered_bytes", "llm_request_frames",
    ):
        assert field in SCRIPT


def test_each_watchdog_line_has_request_and_delivery_counts():
    assert "idle={2:n0}s llm={3} files={4} bytes={5}" in SCRIPT
