from __future__ import annotations

import json
from pathlib import Path

from benchmarks.colibri_agent_core import kaggle_runner

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "benchmarks" / "colibri_agent_core"


def test_model_selection_manifest_pins_colibri_and_high_context_model():
    manifest = json.loads((PACKAGE / "model_manifest.json").read_text(encoding="utf-8"))
    selected = manifest["selected"]

    assert manifest["schema"] == "pulseai-colibri-model-selection/v1"
    assert selected["catalog_id"] == "qwen36-35b"
    assert selected["api_model_id"] == "qwen3.6-colibri"
    assert selected["colibri_commit"] == "e0db083cdc9e563e0766cc6fc661ef23c32298e0"
    assert selected["engine_max_context_tokens"] == 262144
    assert selected["initial_test_context_tokens"] == 65536
    assert selected["native_tool_calls"] is True
    assert selected["cuda_tier"] is True
    assert selected["disk_gb_decimal"] < 30


def test_mcp_runbook_rejects_the_candidate_broken_quota_command():
    runbook = (PACKAGE / "README.md").read_text(encoding="utf-8")

    assert '"kaggle==1.8.4"' in runbook
    assert "nonexistent `kaggle quota` command" in runbook
    assert "`mcp_kaggle_list_my_kernels`" in runbook
    assert "Treat GPU quota as **unknown**" in runbook
    assert "`mcp_kaggle_get_quota` — require positive GPU quota" not in runbook


def test_agent_response_receipt_requires_sentinel_and_grounded_defect(tmp_path):
    frames = tmp_path / "frames.jsonl"
    rows = [
        {"type": "tool_call_start", "name": "read_file"},
        {
            "type": "token",
            "text": "project.py uses values[:-1], which excludes the last value. ",
        },
        {"type": "token", "text": "PULSEAI_AGENT_CORE_DONE"},
        {"type": "turn_done", "completed": True},
    ]
    frames.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    receipt = kaggle_runner._agent_response_receipt(frames)

    assert receipt["terminal_type"] == "turn_done"
    assert receipt["completion_sentinel_present"] is True
    assert receipt["defect_identified"] is True
    assert receipt["response_utf8_bytes"] > 0
    assert receipt["response_body_persisted_in_receipt"] is False
    assert "values" not in json.dumps(receipt)


def test_kaggle_runner_dry_run_is_network_and_gpu_inert(tmp_path):
    output = tmp_path / "results"
    runtime = tmp_path / "runtime"
    code = kaggle_runner.main(
        [
            "--dry-run",
            "--allow-non-kaggle",
            "--run-id",
            "dry-run-test",
            "--runtime-root",
            str(runtime),
            "--output-root",
            str(output),
        ]
    )

    assert code == 0
    receipt_path = output / "dry-run-test" / "run_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["status"] == "dry_run"
    assert receipt["dry_run"] is True
    assert {phase["name"] for phase in receipt["phases"]} == {"configuration"}
    assert receipt["phases"][0]["name"] == "configuration"
    assert receipt["phases"][0]["status"] == "passed"
    assert receipt["credentials"]["kaggle_persisted"] is False
    assert receipt["paths"]["model_persisted_in_results"] is False
    assert not (runtime / "dry-run-test" / "models").exists()
    archive = output / "dry-run-test.tar.gz"
    assert archive.is_file()
    assert Path(str(archive) + ".sha256").is_file()


def test_kaggle_runner_dry_run_records_invalid_context(tmp_path):
    output = tmp_path / "results"
    code = kaggle_runner.main(
        [
            "--dry-run",
            "--allow-non-kaggle",
            "--run-id",
            "invalid-context",
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--output-root",
            str(output),
            "--context-window",
            "262145",
        ]
    )

    assert code == 1
    receipt = json.loads(
        (output / "invalid-context" / "run_receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["status"] == "failed"
    assert receipt["phases"][0]["status"] == "failed"
    assert "outside 8192..262144" in receipt["phases"][0]["error"]
    assert "No Kaggle GPU" in receipt["claim"]


def test_kaggle_notebook_and_metadata_request_private_gpu_internet_kernel():
    notebook = json.loads(
        (PACKAGE / "kaggle" / "colibri_agent_core.ipynb").read_text(encoding="utf-8")
    )
    metadata = json.loads(
        (PACKAGE / "kaggle" / "kernel-metadata.template.json").read_text(
            encoding="utf-8"
        )
    )
    source = "".join(
        line for cell in notebook["cells"] for line in cell.get("source", [])
    )

    assert notebook["nbformat"] == 4
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), f"notebook-cell-{index}", "exec")
    assert "benchmarks.colibri_agent_core.kaggle_runner" in source
    assert "arena/a7c2c868-pulseairepo" in source
    assert "/kaggle/temp" in source
    assert "/kaggle/working/colibri-agent-core-results" in source
    assert metadata["code_file"] == "colibri_agent_core.ipynb"
    assert metadata["is_private"] is True
    assert metadata["enable_gpu"] is True
    assert metadata["enable_tpu"] is False
    assert metadata["enable_internet"] is True
