from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-core-velona.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_push_tag_gated_and_read_only():
    text = _workflow_text()
    parsed = yaml.safe_load(text)

    assert isinstance(parsed, dict)
    assert "pull_request:" not in text
    assert "workflow_dispatch:" not in text
    assert "contents: read" in text
    assert "[agent-core-velona]" in text
    assert "persist-credentials: false" in text


def test_workflow_uses_secret_reference_and_never_a_literal_key():
    text = _workflow_text()

    assert "secrets.CUSTOM_API_KEY" in text
    assert "CUSTOM_API_KEY: ${{ secrets.CUSTOM_API_KEY }}" in text
    assert "api_key_persisted" in text
    assert "Scan bounded receipts before upload" in text
    assert "velona-live-results/*.json" in text
    assert "frames.jsonl" not in text


def test_workflow_pins_requested_main_and_live_1m_aux_selection():
    text = _workflow_text()

    assert "CUSTOM_BASE_URL: https://velona.in/v1" in text
    assert "LLM_MODEL: z-ai/glm-5.3-flash" in text
    assert "--minimum-context 1000000" in text
    assert "--verify-chat" in text
    assert "--max-chat-candidates 20" in text
    assert "scripts/select_velona_aux.py" in text
    assert 'AUX_LLM_PROVIDER: custom' in text


def test_genuine_turn_has_credit_and_time_bounds():
    text = _workflow_text()

    assert "scripts/run_bridge_turn.py" in text
    assert "--timeout-s 600" in text
    assert "--max-llm-calls 8" in text
    assert "--max-input-tokens 80000" in text
    assert "--max-no-delivery-calls 4" in text
    assert "proof_file_exact" in text
    assert "llm_request_observed" in text
    assert "--junitxml=velona-routing-tests.xml" in text
    assert "scripts/ci_report_pytest.py velona-routing-tests.xml" in text
    assert "id: aux_factory" in text
    assert "title=Velona AUX factory" in text
    assert "title=Velona Agent Core receipt" in text
    assert "def load_receipt(path):" in text
    assert '"proof_file_exact": bool(expected) and proof == expected' in text
