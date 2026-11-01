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


# ── Defects 3 and 4: optional extras were hard prerequisites ───────────────
# `src/llm/factory.py` imported the Google and Groq SDKs at module scope, and
# `src/tools/web_tools.py` imported `ddgs` at module scope. Result: chat_graph,
# the tool layer and the graph itself could not be imported without every
# provider SDK AND a web-search package installed -- on a deployment that only
# ever uses one provider. This subprocess hides those three packages and
# demands that the core still imports.
_HIDE_EXTRAS = """
import sys
BLOCK = {"langchain_google_genai", "langchain_groq", "ddgs"}


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCK:
            raise ImportError(f"simulated missing extra: {name}")
        return None


sys.meta_path.insert(0, Blocker())
import src.graphs.chat_graph as cg          # the core graph
import src.tools.web_tools as wt            # the tool that needs ddgs
assert (
    "not installed" in wt.web_search.invoke({"query": "x"})
), "web_search must degrade with an actionable message, not raise"
print("core imported without extras")
"""


def test_core_imports_without_optional_provider_sdks():
    import os

    env = {k: v for k, v in os.environ.items() if not k.endswith("API_KEY")}
    env["PYTHONPATH"] = str(ROOT)
    out = subprocess.run(
        [sys.executable, "-c", _HIDE_EXTRAS],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert out.returncode == 0, (out.stdout + out.stderr)[-900:]


def test_provider_sdk_error_names_the_install_command():
    """Selecting a provider whose SDK is absent must say which pip package fixes it."""
    sys.path.insert(0, str(ROOT))
    from src.llm.factory import _provider_sdk

    with pytest.raises(ImportError) as exc:
        _provider_sdk("groq", "definitely_not_installed_sdk", "Nope", "langchain-groq")
    assert "langchain-groq" in str(exc.value)


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
