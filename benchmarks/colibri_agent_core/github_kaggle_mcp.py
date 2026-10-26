#!/usr/bin/env python3
"""Run the private Kaggle Colibri notebook through the pinned Kaggle MCP.

This module is intended for the branch-scoped GitHub Actions bridge. Credentials are
read from the process environment, passed only to the MCP subprocess, and never written
into receipts. The downloaded Kaggle archive is hash-checked and its bounded receipts
are validated before the workflow can pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from src.tools.mcp_client import MCPStdioClient

SCHEMA = "pulseai-kaggle-mcp-orchestration/v1"
MCP_COMMIT = "bb8c9539a0efe966000fb59d15be12aef2912df2"
REQUIRED_TOOLS = {
    "list_my_kernels",
    "push_notebook",
    "kernel_status",
    "kernel_files",
    "kernel_output",
}
SUCCESS_CLAIMS = {
    "kaggle_gpu_run_verified",
    "colibri_endpoint_passed",
    "agent_core_turn_completed",
    "runtime_evidence_integrity_valid",
}
_FAILURE_STATUS_WORDS = {
    "error",
    "failed",
    "failure",
    "cancel",
    "cancelled",
    "canceled",
    "cancel_requested",
    "cancel_acknowledged",
}
_PENDING_STATUS_WORDS = {"queued", "pending", "running", "starting", "new_script"}
_SUCCESS_STATUS_WORDS = {"complete", "completed", "success", "succeeded"}
_TOKEN_PATTERN = re.compile(r"\bKGAT_[A-Za-z0-9_-]+\b")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _redact(text: str, secrets: tuple[str, ...]) -> str:
    result = _TOKEN_PATTERN.sub("[REDACTED]", str(text))
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result[:2000]


def _response_receipt(text: str) -> dict[str, Any]:
    encoded = text.encode("utf-8", errors="replace")
    return {
        "utf8_bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "body_persisted": False,
    }


def _tool_payload(text: str) -> dict[str, Any]:
    error_prefix = "mcp tool error:"
    if text.lstrip().lower().startswith(error_prefix):
        detail = text.split(":", 1)[1].strip() if ":" in text else "tool failed"
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict):
                detail = str(parsed.get("error") or "tool failed")
        except json.JSONDecodeError:
            pass
        raise RuntimeError(detail)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("MCP tool returned non-JSON output") from exc
    if not isinstance(payload, dict):
        raise TypeError("MCP tool returned a non-object payload")
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload


def classify_kernel_status(payload: dict[str, Any]) -> str:
    """Map Kaggle CLI status output to pending/succeeded/failed/unknown."""

    text = json.dumps(payload, sort_keys=True).lower()
    quoted = re.search(r"status(?:\\?\"|\s|:|=)+[\\\"']*([a-z_]+)", text)
    words: set[str] = set(re.findall(r"[a-z]+", text))
    if quoted:
        words.add(quoted.group(1))
    if words & _FAILURE_STATUS_WORDS:
        return "failed"
    if words & _SUCCESS_STATUS_WORDS:
        return "succeeded"
    if words & _PENDING_STATUS_WORDS:
        return "pending"
    return "unknown"


def _safe_tar_members(
    archive: Path,
    *,
    max_members: int = 5000,
    max_unpacked_bytes: int = 512 * 1024 * 1024,
) -> list[tarfile.TarInfo]:
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
    if not members or len(members) > max_members:
        raise RuntimeError(f"archive member count outside 1..{max_members}")
    total = 0
    for member in members:
        normalized = PurePosixPath(member.name.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise RuntimeError("archive contains an escaping path")
        if member.issym() or member.islnk() or member.isdev():
            raise RuntimeError("archive contains a link or device entry")
        if member.isfile():
            total += member.size
    if total > max_unpacked_bytes:
        raise RuntimeError("archive exceeds the unpacked-size limit")
    return members


def _find_single(root: Path, name: str) -> Path:
    matches = [path for path in root.rglob(name) if path.is_file()]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {name}, found {len(matches)}")
    return matches[0]


def validate_result_archive(archive: Path, sidecar: Path, output_dir: Path) -> dict:
    """Verify archive integrity and the runner's success/evidence contract."""

    digest = _sha256_file(archive)
    sidecar_fields = sidecar.read_text(encoding="ascii", errors="strict").split()
    if len(sidecar_fields) < 2 or sidecar_fields[0].lower() != digest:
        raise RuntimeError("Kaggle result archive SHA-256 mismatch")
    if Path(sidecar_fields[-1]).name != archive.name:
        raise RuntimeError("archive sidecar names a different file")

    members = _safe_tar_members(archive)
    extracted = output_dir / "validated"
    if extracted.exists():
        shutil.rmtree(extracted)
    extracted.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(extracted, members=members)

    receipt_path = _find_single(extracted, "run_receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("status") != "passed":
        raise RuntimeError(
            "Kaggle runner did not pass: " + str(receipt.get("fatal_error") or "failed")
        )
    phases = receipt.get("phase_statuses") or {}
    required = set(receipt.get("required_phases") or [])
    if not required or any(phases.get(name) != "passed" for name in required):
        raise RuntimeError("one or more required Kaggle runner phases did not pass")
    claims = receipt.get("claims") or {}
    if any(claims.get(name) is not True for name in SUCCESS_CLAIMS):
        raise RuntimeError("one or more required Kaggle runner claims is unproven")
    if (receipt.get("gpu_execution") or {}).get("verified") is not True:
        raise RuntimeError("GPU execution receipt is not verified")
    credentials = receipt.get("credentials") or {}
    if any(value is not False for value in credentials.values()):
        raise RuntimeError("runner receipt reports persisted credentials")
    if (receipt.get("paths") or {}).get("model_persisted_in_results") is not False:
        raise RuntimeError("runner receipt reports model weights in results")
    pulseai_commit = str((receipt.get("pulseai") or {}).get("commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", pulseai_commit):
        raise RuntimeError("runner receipt has no immutable PulseAI commit")

    probe_path = _find_single(extracted, "colibri_endpoint_probe.json")
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    if probe.get("status") != "passed":
        raise RuntimeError("Colibri endpoint probe did not pass")

    selected = output_dir / "selected-evidence"
    selected.mkdir(exist_ok=True)
    shutil.copy2(receipt_path, selected / "run_receipt.json")
    shutil.copy2(probe_path, selected / "colibri_endpoint_probe.json")
    summary = {
        "archive_sha256": digest,
        "archive_bytes": archive.stat().st_size,
        "run_id": receipt.get("run_id"),
        "pulseai_commit": pulseai_commit,
        "required_phases": sorted(required),
        "claims": {name: claims.get(name) for name in sorted(SUCCESS_CLAIMS)},
        "probe_status": probe.get("status"),
        "credentials_persisted": any(credentials.values()),
        "model_persisted_in_results": (receipt.get("paths") or {}).get(
            "model_persisted_in_results"
        ),
    }
    shutil.rmtree(extracted)
    return summary


class KaggleMCPOrchestrator:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.output_dir = args.output_dir.resolve()
        self.receipt_path = self.output_dir / "orchestration_receipt.json"
        self.username = os.environ.get("KAGGLE_USERNAME", "").strip()
        self.token = (
            os.environ.get("KAGGLE_API_TOKEN") or os.environ.get("KAGGLE_KEY") or ""
        ).strip()
        self.secrets = (self.username, self.token)
        self.client: MCPStdioClient | None = None
        self.kernel_ref: str | None = None
        self.receipt: dict[str, Any] = {
            "schema": SCHEMA,
            "status": "running",
            "started_at": _utc_now(),
            "finished_at": None,
            "mcp": {
                "expected_commit": MCP_COMMIT,
                "tool_count": None,
                "required_tools_present": False,
            },
            "request": {
                "private": True,
                "gpu": True,
                "tpu": False,
                "internet": True,
                "notebook_sha256": None,
                "expected_pulseai_commit": args.expected_pulseai_commit or None,
            },
            "kernel": {
                "reference_sha256": None,
                "reference_persisted": False,
                "terminal_status": None,
                "poll_count": 0,
            },
            "credentials": {
                "present": False,
                "persisted": False,
                "values_logged": False,
            },
            "phases": [],
        }

    def _write(self) -> None:
        _atomic_json(self.receipt_path, self.receipt)

    def _phase(
        self,
        name: str,
        status: str,
        evidence: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "name": name,
            "status": status,
            "finished_at": _utc_now(),
            "evidence": evidence or {},
        }
        if error:
            entry["error"] = _redact(error, self.secrets)
        self.receipt["phases"].append(entry)
        self._write()
        print(f"[{status.upper()}] {name}", flush=True)

    def _call(self, name: str, arguments: dict[str, Any] | None = None) -> tuple:
        if self.client is None:
            raise RuntimeError("MCP client is not initialized")
        text = self.client.call_tool(name, arguments or {})
        response = _response_receipt(text)
        return _tool_payload(text), response

    def _validate_configuration(self) -> None:
        if not self.username or not self.token:
            raise RuntimeError(
                "KAGGLE_USERNAME and KAGGLE_API_TOKEN repository secrets are required"
            )
        if not self.args.notebook.is_file():
            raise RuntimeError(f"notebook not found: {self.args.notebook}")
        if not self.args.mcp_script.is_file():
            raise RuntimeError(f"MCP script not found: {self.args.mcp_script}")
        if self.args.expected_pulseai_commit and not re.fullmatch(
            r"[0-9a-f]{40}", self.args.expected_pulseai_commit
        ):
            raise RuntimeError("expected PulseAI commit must be a full lowercase SHA")
        self.receipt["credentials"]["present"] = True
        self.receipt["request"]["notebook_sha256"] = _sha256_file(self.args.notebook)
        self._phase(
            "configuration",
            "passed",
            {
                "credentials_present": True,
                "credential_values_persisted": False,
                "notebook_sha256": self.receipt["request"]["notebook_sha256"],
            },
        )

    def _initialize(self) -> None:
        env = {
            "KAGGLE_USERNAME": self.username,
            "KAGGLE_KEY": self.token,
            "KAGGLE_API_TOKEN": self.token,
            "KAGGLE_NO_PROGRESS": "1",
        }
        self.client = MCPStdioClient(
            "kaggle",
            [sys.executable, str(self.args.mcp_script), "--stdio"],
            env,
        )
        info = self.client.initialize()
        tools = self.client.list_tools()
        names = {str(tool.get("name")) for tool in tools}
        missing = sorted(REQUIRED_TOOLS - names)
        if missing:
            raise RuntimeError("required MCP tools missing: " + ", ".join(missing))
        self.receipt["mcp"].update(
            {
                "server_name": (info.get("serverInfo") or {}).get("name"),
                "server_version": (info.get("serverInfo") or {}).get("version"),
                "protocol_version": info.get("protocolVersion"),
                "tool_count": len(tools),
                "required_tools_present": True,
            }
        )
        self._phase(
            "mcp_discovery",
            "passed",
            {
                "server_name": self.receipt["mcp"]["server_name"],
                "server_version": self.receipt["mcp"]["server_version"],
                "protocol_version": self.receipt["mcp"]["protocol_version"],
                "tool_count": len(tools),
            },
        )

    def _authenticated_preflight(self) -> None:
        _, response = self._call("list_my_kernels", {"limit": 1, "page": 1})
        self._phase(
            "authenticated_kaggle_preflight",
            "passed",
            {"response": response, "quota_claimed": False},
        )

    def _push(self) -> None:
        payload, response = self._call(
            "push_notebook",
            {
                "path": str(self.args.notebook.resolve()),
                "name": self.args.kernel_name,
                "gpu": True,
                "tpu": False,
                "internet": True,
                "private": True,
            },
        )
        if payload.get("status") != "pushed" or not payload.get("kernel_ref"):
            raise RuntimeError("MCP did not return a pushed kernel reference")
        self.kernel_ref = str(payload["kernel_ref"])
        reference_digest = hashlib.sha256(self.kernel_ref.encode()).hexdigest()
        self.receipt["kernel"]["reference_sha256"] = reference_digest
        self._phase(
            "private_gpu_kernel_push",
            "passed",
            {
                "response": response,
                "kernel_reference_sha256": reference_digest,
                "kernel_reference_persisted": False,
                "private": payload.get("private") is True,
                "gpu_requested": payload.get("gpu") is True,
            },
        )

    def _poll(self) -> str:
        assert self.kernel_ref is not None
        deadline = time.monotonic() + self.args.max_wait_seconds
        count = 0
        transient_errors = 0
        last_state = "unknown"
        last_response: dict[str, Any] = {}
        while time.monotonic() < deadline:
            count += 1
            try:
                payload, last_response = self._call(
                    "kernel_status", {"ref": self.kernel_ref}
                )
                state = classify_kernel_status(payload)
                transient_errors = 0
            except Exception as exc:
                transient_errors += 1
                state = "transient_error"
                last_response = {
                    "error_sha256": hashlib.sha256(
                        _redact(str(exc), self.secrets).encode()
                    ).hexdigest()
                }
                if transient_errors >= self.args.max_status_errors:
                    raise RuntimeError("Kaggle status failed repeatedly") from exc
            if state != last_state or count == 1 or count % 10 == 0:
                print(f"[KAGGLE] status={state} poll={count}", flush=True)
            last_state = state
            self.receipt["kernel"].update(
                {"terminal_status": state, "poll_count": count}
            )
            self._write()
            if state in {"succeeded", "failed"}:
                self._phase(
                    "kernel_terminal_status",
                    "passed" if state == "succeeded" else "failed",
                    {"state": state, "poll_count": count, "response": last_response},
                )
                return state
            time.sleep(self.args.poll_seconds)
        raise RuntimeError("timed out waiting for the Kaggle kernel")

    def _download(self) -> dict:
        assert self.kernel_ref is not None
        _, listing_response = self._call(
            "kernel_files", {"ref": self.kernel_ref, "page_size": 50}
        )
        download_dir = self.output_dir / "downloaded"
        payload, output_response = self._call(
            "kernel_output",
            {"ref": self.kernel_ref, "output_dir": str(download_dir)},
        )
        files = payload.get("files") or []
        safe_files = [
            {
                "path": str(item.get("path"))[:300],
                "size_bytes": int(item.get("size_bytes") or 0),
            }
            for item in files
            if isinstance(item, dict)
        ]
        self._phase(
            "kernel_output_download",
            "passed",
            {
                "listing_response": listing_response,
                "download_response": output_response,
                "file_count": len(safe_files),
                "files": safe_files[:100],
            },
        )
        return payload

    def _validate_download(self) -> dict:
        download_dir = self.output_dir / "downloaded"
        archives = sorted(download_dir.rglob("*.tar.gz"))
        pairs = [
            (archive, Path(str(archive) + ".sha256"))
            for archive in archives
            if Path(str(archive) + ".sha256").is_file()
        ]
        if len(pairs) != 1:
            raise RuntimeError(
                f"expected one result archive/sidecar pair, found {len(pairs)}"
            )
        validation = validate_result_archive(*pairs[0], self.output_dir)
        expected = self.args.expected_pulseai_commit
        if expected and validation.get("pulseai_commit") != expected:
            raise RuntimeError("Kaggle notebook tested a different PulseAI commit")
        self._phase("result_evidence_validation", "passed", validation)
        return validation

    def run(self) -> int:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write()
        try:
            self._validate_configuration()
            self._initialize()
            self._authenticated_preflight()
            self._push()
            terminal = self._poll()
            download_error: Exception | None = None
            try:
                self._download()
            except Exception as exc:  # noqa: BLE001 - preserve terminal failure receipt
                download_error = exc
                self._phase(
                    "kernel_output_download",
                    "failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            if download_error is not None:
                raise download_error
            validation = self._validate_download()
            if terminal != "succeeded":
                raise RuntimeError("Kaggle kernel reached a failure state")
            self.receipt.update(
                {
                    "status": "passed",
                    "finished_at": _utc_now(),
                    "validation": validation,
                }
            )
            self._write()
            return 0
        except Exception as exc:  # noqa: BLE001 - always emit a bounded receipt
            message = _redact(f"{type(exc).__name__}: {exc}", self.secrets)
            self.receipt.update(
                {"status": "failed", "finished_at": _utc_now(), "fatal_error": message}
            )
            self._write()
            print(f"[FAILED] {message}", file=sys.stderr, flush=True)
            return 1
        finally:
            if self.client is not None:
                self.client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-script", type=Path, required=True)
    parser.add_argument(
        "--notebook",
        type=Path,
        default=Path("benchmarks/colibri_agent_core/kaggle/colibri_agent_core.ipynb"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--kernel-name", required=True)
    parser.add_argument("--expected-pulseai-commit", default="")
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--max-wait-seconds", type=int, default=19_800)
    parser.add_argument("--max-status-errors", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.poll_seconds < 1:
        raise SystemExit("--poll-seconds must be positive")
    if args.max_wait_seconds < args.poll_seconds:
        raise SystemExit("--max-wait-seconds must be >= --poll-seconds")
    if args.max_status_errors < 1:
        raise SystemExit("--max-status-errors must be positive")
    return KaggleMCPOrchestrator(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
