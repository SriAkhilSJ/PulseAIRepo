"""Field 2026-11-01 — the body checkup must stay green, and must stay honest.

Companion to ``scripts/agent_core_checkup.py``. These tests pin the two defects
the checkup actually found, and they pin the *shape* of the checkup so a later
edit cannot quietly turn a FAIL into a pass by deleting the probe.

Nothing here needs a network or an API key.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _classify(message: str):
    from src.llm.error_classifier import classify_api_error

    return classify_api_error(RuntimeError(message), provider="custom", model="z-ai/glm-5.3-flash")


# ── Defect 1: canonical auth bodies were retried as transient ──────────────
# The message fallback exists for wrapped exceptions whose status_code did not
# survive a shim. Only 2 of these 7 matched before the fix; the other 5 came
# back `unknown, retryable=True`, so the agent burned the retry ladder on a
# dead credential and never rotated.
CANONICAL_AUTH_BODIES = [
    ("openai", "Incorrect API key provided: sk-proj-abc123"),
    ("anthropic", "invalid x-api-key"),
    ("gemini", "API key not valid. Please pass a valid API key."),
    ("groq", "Invalid API Key"),
    ("openrouter", "No auth credentials found"),
    ("custom", "Authentication failed: missing bearer token"),
    ("gateway", "Error code: 401 - Incorrect API key provided"),
]


@pytest.mark.parametrize("vendor,body", CANONICAL_AUTH_BODIES)
def test_auth_body_is_terminal_and_rotates(vendor, body):
    c = _classify(body)
    assert c.reason.value == "auth", f"{vendor}: classified {c.reason.value}"
    assert c.retryable is False, f"{vendor}: a dead key must not be retried"
    assert c.should_rotate_credential is True, f"{vendor}: nothing else can recover"


@pytest.mark.parametrize(
    "body",
    [
        "rate limit exceeded, retry in 1s",
        "Error code: 500 - internal server error",
        "connection reset by peer",
    ],
)
def test_transient_bodies_stay_retryable(body):
    """The auth fix must not swallow real transient failures."""
    assert _classify(body).retryable is True


def test_billing_bodies_stay_terminal():
    c = _classify("Error code: 402 - Balance ₹0.00. Top up from ₹10 at https://velona.in/wallet")
    assert c.reason.value == "billing"
    assert c.retryable is False


# ── Defect 2: a core module needed credentials just to be imported ─────────
def test_basic_graph_imports_without_credentials():
    """Import-time client construction made `import src.graphs.*` fail keyless.

    Health checks, test collection and any tool walking the package died with a
    provider credential error. The client is built lazily now.
    """
    import os

    env = {k: v for k, v in os.environ.items() if not k.endswith("API_KEY")}
    env["PYTHONPATH"] = str(ROOT)
    out = subprocess.run(
        [sys.executable, "-c", "import src.graphs.basic_graph as g; print(g.graph is not None)"],
        cwd=str(ROOT),
        env={**env, "LLM_PROVIDER": "", "LLM_MODEL": ""},
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert out.returncode == 0, out.stderr[-600:]
    assert "True" in out.stdout


# ── The checkup itself ─────────────────────────────────────────────────────
def test_body_checkup_reports_zero_failures():
    """52+ probes across every pipeline, keyless. Any FAIL is a body-part that
    is not doing its job; a WARN is allowed and must stay visible."""
    out = subprocess.run(
        [sys.executable, str(ROOT / "scripts/agent_core_checkup.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=900,
    )
    tail = out.stdout[-2500:] + out.stderr[-1500:]
    assert "0 fail" in out.stdout, tail
    assert out.returncode == 0, tail


def test_body_checkup_covers_every_pipeline():
    """Thirteen pipeline sections, or the 'checkup' is just a spot check."""
    sys.path.insert(0, str(ROOT))
    from scripts.agent_core_checkup import run_all

    cu = run_all()
    pipelines = {c.pipeline for c in cu.checks}
    assert len(pipelines) >= 12, sorted(pipelines)
    for expect in ("context", "compaction", "model call", "failure recovery", "tools", "loop control", "finalize"):
        assert any(expect in p for p in pipelines), f"no coverage for {expect}"
    assert len(cu.checks) >= 45, len(cu.checks)
