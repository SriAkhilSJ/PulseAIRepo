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
    assert len(pipelines) >= 14, sorted(pipelines)
    for expect in (
        "context", "compaction", "model call", "failure recovery", "tools",
        "loop control", "finalize",
        # Field 2026-11-01: "healthy" was scoped to correctness and never to
        # cost. The economics pipeline is the correction — a checkup that can
        # call a body healthy while it burns the account is not a checkup.
        "economics",
    ):
        assert any(expect in p for p in pipelines), f"no coverage for {expect}"
    assert len(cu.checks) >= 55, len(cu.checks)


def test_blueprint_is_a_flow_with_the_system_message_as_its_own_node():
    """Field 2026-11-01: the blueprint had to become an n8n-style workflow, and
    the SYSTEM MESSAGE had to be a node in it — not an implicit 430-token
    footnote. It is the largest constant in the loop: the autonomous variant is
    430 tokens, but the desktop default composes 24,606 chars across 17
    sections, re-sent on every cycle. If the drawing ever loses either number,
    this fails.
    """
    import xml.etree.ElementTree as ET

    sys.path.insert(0, str(ROOT))
    from scripts.agent_core_blueprint import measure, render_flow

    m = measure()
    svg = render_flow(m)
    root = ET.fromstring(svg)
    text = " ".join(t.text or "" for t in root.iter() if t.tag.endswith("text"))

    # the node exists, and both measured variants are on it
    assert "SYSTEM MESSAGE" in text
    assert "autonomous" in text and "desktop default" in text
    assert f"{m['persona_default_tokens']:,}" in text, m["persona_default_tokens"]
    assert f"{m['persona_default_chars']:,}" in text

    # it is a workflow: a loop container, ports and a terminal node
    assert "AGENT LOOP" in text
    assert "Terminal frame" in text
    assert svg.count("<circle") > 20, "nodes must expose ports like a flow editor"
    assert svg.count("<path") >= 8, "a workflow needs edges"

    # the two variants must actually differ by an order of magnitude
    assert m["persona_default_tokens"] > m["persona_tokens"] * 10


def test_blueprint_draws_every_pipeline_with_a_metric():
    """Field 2026-11-01: the blueprint is a generated artifact, not a picture.

    It must (a) be valid SVG, (b) carry all 14 pipelines, (c) put a number in
    every stage — a stage with no metric is a stage nobody measured — and
    (d) re-derive the tool-schema cost from the repo at render time, so the
    diagram cannot drift away from the code it describes.
    """
    import xml.etree.ElementTree as ET

    sys.path.insert(0, str(ROOT))
    from scripts.agent_core_blueprint import measure, render, stages

    m = measure()
    svg = render(m)
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")

    text = " ".join(t.text or "" for t in root.iter() if t.tag.endswith("text"))
    st = stages(m)
    assert len(st) == 14, len(st)
    for s in st:
        assert s["name"] in text, s["name"]
        assert any(ch.isdigit() for ch in s["metric"]), f"{s['name']} has no measured number"
        assert s["best"], f"{s['name']} has no best-in-class reference"
        assert s["gap"], f"{s['name']} has no stated gap"

    # the schema cost must be measured, not typed in
    assert m["schema_tokens"] > 1000, m
    assert str(f"{m['schema_tokens']:,}") in text, "tool-schema cost missing from the drawing"


def test_reference_blueprints_cover_the_five_repos_with_sourced_numbers():
    """Field 2026-11-01: the comparison had to be measured, not asserted.

    Each of the five harnesses was downloaded from codeload.github.com and read.
    This pins three things: every repo is present, every one carries a token
    number for its system message, and ours is included in the same table so the
    comparison cannot quietly drop the unflattering column.
    """
    import xml.etree.ElementTree as ET

    sys.path.insert(0, str(ROOT))
    from scripts.ref_blueprints import OURS, REFS, render

    svg = render()
    root = ET.fromstring(svg)
    text = " ".join(t.text or "" for t in root.iter() if t.tag.endswith("text"))

    names = [r["name"] for r in REFS]
    assert names == ["Aider", "OpenCode", "Codex CLI", "Void", "openclaude"], names
    for r in REFS:
        assert r["name"] in text, r["name"]
        assert isinstance(r["system"], int) and r["system"] > 0, r
        assert r["verdict"] and r["steal"], r["name"]
        assert r["source"], f"{r['name']} must name the files its numbers came from"
    assert "CrusorAI (ours)" in text, "the table must include our own column"
    assert f"{OURS['system']:,}" in text

    # the finding: nobody else carries our fixed preamble
    assert all(r["system"] < OURS["system"] for r in REFS[:4]), (
        "Aider/OpenCode/Codex/Void must all keep a smaller system message than ours; "
        "if this fails, either we got slimmer (good — update the doc) or the data was edited"
    )
