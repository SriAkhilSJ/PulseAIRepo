from __future__ import annotations

import hashlib
import json
import tarfile
import textwrap
from pathlib import Path

import pytest

from benchmarks.colibri_agent_core import github_kaggle_mcp as orchestrator

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "kaggle-colibri-agent-core.yml"


def _write_result_archive(root: Path, *, status: str = "passed") -> tuple[Path, Path]:
    source = root / "source" / "run-test"
    source.mkdir(parents=True)
    required = ["gpu_execution_proof", "colibri_endpoint_probe", "agent_core_turn"]
    receipt = {
        "status": status,
        "run_id": "run-test",
        "fatal_error": None if status == "passed" else "expected failure",
        "required_phases": required,
        "phase_statuses": {name: "passed" for name in required},
        "claims": {name: True for name in orchestrator.SUCCESS_CLAIMS},
        "gpu_execution": {"verified": True},
        "pulseai": {"commit": "a" * 40, "worktree_clean": True},
        "credentials": {
            "kaggle_persisted": False,
            "huggingface_token_persisted": False,
            "local_api_key_persisted": False,
        },
        "paths": {"model_persisted_in_results": False},
    }
    (source / "run_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    (source / "colibri_endpoint_probe.json").write_text(
        json.dumps({"status": "passed"}), encoding="utf-8"
    )
    archive = root / "run-test.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname=source.name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sidecar = Path(str(archive) + ".sha256")
    sidecar.write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    return archive, sidecar


def test_kernel_status_classification():
    assert (
        orchestrator.classify_kernel_status(
            {"output": 'owner/kernel has status "running"'}
        )
        == "pending"
    )
    assert (
        orchestrator.classify_kernel_status(
            {"output": 'owner/kernel has status "complete"'}
        )
        == "succeeded"
    )
    assert (
        orchestrator.classify_kernel_status(
            {"output": 'owner/kernel has status "error"'}
        )
        == "failed"
    )
    assert (
        orchestrator.classify_kernel_status(
            {"output": 'owner/kernel has status "cancel_acknowledged"'}
        )
        == "failed"
    )
    assert (
        orchestrator.classify_kernel_status(
            {"output": 'owner/kernel has status "new_script"'}
        )
        == "pending"
    )
    assert orchestrator.classify_kernel_status({"output": "surprising"}) == "unknown"


def test_result_archive_validation_and_bounded_selected_evidence(tmp_path):
    archive, sidecar = _write_result_archive(tmp_path)
    output = tmp_path / "output"
    output.mkdir()

    result = orchestrator.validate_result_archive(archive, sidecar, output)

    assert result["run_id"] == "run-test"
    assert result["pulseai_commit"] == "a" * 40
    assert result["claims"] == {
        name: True for name in sorted(orchestrator.SUCCESS_CLAIMS)
    }
    assert result["credentials_persisted"] is False
    assert not (output / "validated").exists()
    assert (output / "selected-evidence" / "run_receipt.json").is_file()
    assert (output / "selected-evidence" / "colibri_endpoint_probe.json").is_file()


def test_result_archive_rejects_traversal(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    payload = tmp_path / "payload"
    payload.write_text("escape", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(payload, arcname="../escape")

    with pytest.raises(RuntimeError, match="escaping path"):
        orchestrator._safe_tar_members(archive)


def test_result_archive_rejects_failed_runner(tmp_path):
    archive, sidecar = _write_result_archive(tmp_path, status="failed")
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(RuntimeError, match="did not pass"):
        orchestrator.validate_result_archive(archive, sidecar, output)


def test_branch_workflow_never_exposes_secrets_to_prs_or_repository():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" not in workflow
    assert "arena/a7c2c868-pulseairepo" in workflow
    assert "contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "KAGGLE_USERNAME: sriakhilsj" in workflow
    assert "secrets.KAGGLE_USERNAME" not in workflow
    assert "secrets.KAGGLE_API_TOKEN" in workflow
    assert "[kaggle-colibri]" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert "--expected-pulseai-commit ${{ github.sha }}" in workflow
    assert "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09" in workflow
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in workflow
    assert (
        "actions/upload-artifact@330a01c490aca151604b8cf639adc76d48f6c5d4" in workflow
    )
    assert "Publish redacted orchestration failure" in workflow
    assert "Redacted Kaggle orchestration failure" in workflow
    assert "get_quota" not in workflow
    assert "kernel_logs" not in workflow


def test_mock_mcp_orchestration_never_persists_credentials(tmp_path, monkeypatch):
    archive, sidecar = _write_result_archive(tmp_path / "fixture")
    fake_server = tmp_path / "fake_kaggle_mcp.py"
    fake_server.write_text(
        textwrap.dedent(
            """
            import json, os, shutil, sys

            TOOLS = [
                "list_my_kernels", "push_notebook", "kernel_status",
                "kernel_files", "kernel_output",
            ]

            def send(request_id, payload):
                print(json.dumps({
                    "jsonrpc": "2.0", "id": request_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
                }), flush=True)

            for line in sys.stdin:
                request = json.loads(line)
                if "id" not in request:
                    continue
                method = request["method"]
                if method == "initialize":
                    print(json.dumps({
                        "jsonrpc": "2.0", "id": request["id"],
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "kaggle-mcp", "version": "3.1.0"},
                        },
                    }), flush=True)
                elif method == "tools/list":
                    print(json.dumps({
                        "jsonrpc": "2.0", "id": request["id"],
                        "result": {"tools": [
                            {"name": name, "inputSchema": {"type": "object"}}
                            for name in TOOLS
                        ]},
                    }), flush=True)
                elif method == "tools/call":
                    params = request["params"]
                    name = params["name"]
                    args = params.get("arguments", {})
                    if name == "list_my_kernels":
                        payload = {"output": "authenticated"}
                    elif name == "push_notebook":
                        payload = {
                            "status": "pushed", "kernel_ref": "private/kernel",
                            "private": True, "gpu": True,
                        }
                    elif name == "kernel_status":
                        payload = {"output": "kernel has status complete"}
                    elif name == "kernel_files":
                        payload = {"output": "two files"}
                    elif name == "kernel_output":
                        output = args["output_dir"]
                        os.makedirs(output, exist_ok=True)
                        archive = os.environ["FAKE_ARCHIVE"]
                        sidecar = os.environ["FAKE_SIDECAR"]
                        shutil.copy2(archive, output)
                        shutil.copy2(sidecar, output)
                        payload = {
                            "files": [
                                {"path": os.path.basename(archive), "size_bytes": os.path.getsize(archive)},
                                {"path": os.path.basename(sidecar), "size_bytes": os.path.getsize(sidecar)},
                            ]
                        }
                    send(request["id"], payload)
            """
        ),
        encoding="utf-8",
    )
    notebook = tmp_path / "notebook.ipynb"
    notebook.write_text("{}", encoding="utf-8")
    output = tmp_path / "results"
    username = "private-user"
    token = "K" + "GAT_" + "synthetic-never-persist"
    monkeypatch.setenv("KAGGLE_USERNAME", username)
    monkeypatch.setenv("KAGGLE_API_TOKEN", token)
    monkeypatch.setenv("FAKE_ARCHIVE", str(archive))
    monkeypatch.setenv("FAKE_SIDECAR", str(sidecar))

    result = orchestrator.main(
        [
            "--mcp-script",
            str(fake_server),
            "--notebook",
            str(notebook),
            "--output-dir",
            str(output),
            "--kernel-name",
            "test-kernel",
            "--expected-pulseai-commit",
            "a" * 40,
            "--poll-seconds",
            "1",
            "--max-wait-seconds",
            "1",
        ]
    )

    assert result == 0
    receipt = json.loads(
        (output / "orchestration_receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["status"] == "passed"
    assert receipt["credentials"] == {
        "present": True,
        "persisted": False,
        "values_logged": False,
    }
    for path in output.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert token.encode() not in data
            assert username.encode() not in data
