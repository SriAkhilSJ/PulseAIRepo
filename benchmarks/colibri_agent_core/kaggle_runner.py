#!/usr/bin/env python3
"""Run Colibri and a bounded PulseAI Agent Core turn inside one Kaggle kernel.

Nothing in this module authenticates to Kaggle or uploads a kernel. The Kaggle
MCP/CLI owns that boundary. Once Kaggle executes the checked-in notebook, this
runner owns reproducibility, resource gates, local inference, Agent Core
execution, evidence validation, and the small downloadable result bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmarks.colibri_agent_core import SCHEMA_VERSION

DEFAULT_MANIFEST = PACKAGE_ROOT / "model_manifest.json"
_GB = 1_000_000_000
_LOCAL_API_KEY = "pulseai-colibri-kaggle-local"
_GPU_MARKERS = (
    "[gpu] MoE experts -> CUDA VRAM tier",
    "[qtier] CUDA VRAM expert tier active:",
)
_PARTIAL_RESIDENCY_MARKER = "the tier copies each expert it takes as it passes"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _safe_tail(path: Path, limit: int = 12000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", "replace")


def _tree_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _agent_response_receipt(frames_path: Path) -> dict[str, Any]:
    """Evaluate the bounded diagnosis without copying model prose into the receipt."""
    chunks: list[str] = []
    terminal: dict[str, Any] | None = None
    for line in frames_path.read_text(encoding="utf-8").splitlines():
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            continue
        if frame.get("type") == "token" and isinstance(frame.get("text"), str):
            chunks.append(frame["text"])
        if frame.get("type") in {"turn_done", "turn_failed"}:
            terminal = frame
    text = "".join(chunks)
    if not text and isinstance((terminal or {}).get("message"), str):
        text = str(terminal["message"])
    lowered = text.lower()
    exact_slice = "values[:-1]" in lowered.replace(" ", "")
    describes_omission = "last" in lowered and any(
        word in lowered for word in ("omit", "exclud", "drop", "skip")
    )
    return {
        "terminal_type": (terminal or {}).get("type"),
        "response_utf8_bytes": len(text.encode("utf-8")),
        "response_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "completion_sentinel_present": "PULSEAI_AGENT_CORE_DONE" in text,
        "defect_identified": exact_slice or describes_omission,
        "response_body_persisted_in_receipt": False,
    }


def _parse_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        match = re.match(r"([^:]+):\s+(\d+)\s+kB", line)
        if match:
            values[match.group(1)] = int(match.group(2)) * 1024
    return values


def _cuda_activity_from_log(text: str) -> dict[str, Any]:
    hit_counts = [
        int(value)
        for value in re.findall(r"\[qtier\]\s+dev\s+\d+:\s+hits\s+(\d+)\s+\|", text)
    ]
    group_rows = [
        (int(calls), int(experts), float(kernel_ms))
        for calls, experts, kernel_ms in re.findall(
            r"\[qtier\] group_stats:\s+(\d+) calls,\s+(\d+) experts\s+\|"
            r"[^\n]*?kernel\s+([0-9.]+) ms",
            text,
        )
    ]
    return {
        "device_hit_reports": len(hit_counts),
        "max_device_hits": max(hit_counts, default=0),
        "group_stat_reports": len(group_rows),
        "max_group_calls": max((row[0] for row in group_rows), default=0),
        "max_group_experts": max((row[1] for row in group_rows), default=0),
        "max_kernel_ms": max((row[2] for row in group_rows), default=0.0),
    }


def _nvidia_memory_used_mib(text: str) -> float:
    total = 0.0
    parsed = 0
    for line in text.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 4:
            continue
        try:
            total += float(fields[-2])
        except ValueError:
            continue
        parsed += 1
    return total if parsed else 0.0


def _redacted_command(argv: list[str]) -> list[str]:
    safe: list[str] = []
    redact_next = False
    for value in argv:
        if redact_next:
            safe.append("[REDACTED]")
            redact_next = False
        elif value in {"--api-key", "--token", "--key"}:
            safe.append(value)
            redact_next = True
        else:
            safe.append(value.replace(_LOCAL_API_KEY, "[REDACTED]"))
    return safe


def _bound_log(path: Path, max_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "available": False}
    size = path.stat().st_size
    digest = _sha256_file(path)
    if size > max_bytes:
        data = path.read_bytes()
        half = max_bytes // 2
        marker = (
            f"\n\n[log bounded by Kaggle runner; original_bytes={size}; "
            f"original_sha256={digest}]\n\n"
        ).encode()
        path.write_bytes(data[:half] + marker + data[-half:])
    return {
        "path": str(path),
        "available": True,
        "original_bytes": size,
        "original_sha256": digest,
        "persisted_bytes": path.stat().st_size,
    }


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.manifest_path = args.model_manifest.resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        selected = self.manifest["selected"]
        self.colibri_commit = str(selected["colibri_commit"])
        patch = selected["colibri_upstream_patch"]
        self.colibri_patch_ref = str(patch["fetch_ref"])
        self.colibri_patch_commit = str(patch["commit"])
        self.colibri_patch_parent = str(patch["parent"])
        self.colibri_patched_tree = str(patch["applied_tree"])
        self.model_repo = str(selected["model_repository"])
        self.model_id = str(selected["api_model_id"])
        self.experts_per_layer = int(selected["experts_per_layer"])
        self.effective_cache_slots_per_layer: int | None = None
        self.run_id = args.run_id or (
            datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
        )
        self.output_parent = args.output_root.expanduser().resolve()
        self.run_dir = self.output_parent / self.run_id
        self.runtime_parent = args.runtime_root.expanduser().resolve()
        self.runtime_dir = self.runtime_parent / self.run_id
        self.colibri_dir = self.runtime_dir / "colibri"
        self.model_dir = self.runtime_dir / "models" / "qwen36-35b-i4-gs64"
        self.logs_dir = self.run_dir / "logs"
        self.receipt_path = self.run_dir / "run_receipt.json"
        self.server: subprocess.Popen[str] | None = None
        self.server_log_handle: Any = None
        self.server_log_path = self.logs_dir / "colibri_server.log"
        self.phases: list[dict[str, Any]] = []
        self.receipt: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "kind": "kaggle_colibri_agent_core_run",
            "run_id": self.run_id,
            "started_at": _utc_now(),
            "status": "running",
            "model_selection_manifest": str(self.manifest_path),
            "model": {
                "catalog_id": selected["catalog_id"],
                "name": selected["name"],
                "api_model_id": self.model_id,
                "repository": self.model_repo,
                "experts_per_layer": self.experts_per_layer,
                "context_window": args.context_window,
                "architectural_ceiling": selected["engine_max_context_tokens"],
            },
            "colibri": {
                "repository": selected["colibri_repository"],
                "commit": self.colibri_commit,
                "base_commit": self.colibri_commit,
                "upstream_patch_commit": self.colibri_patch_commit,
                "expected_patched_tree": self.colibri_patched_tree,
            },
            "pulseai": {},
            "paths": {
                "run_directory": str(self.run_dir),
                "runtime_directory": str(self.runtime_dir),
                "model_persisted_in_results": False,
            },
            "credentials": {
                "kaggle_persisted": False,
                "huggingface_token_persisted": False,
                "local_api_key_persisted": False,
            },
            "phases": self.phases,
        }

    def _write_receipt(self) -> None:
        _atomic_json(self.receipt_path, self.receipt)

    def _phase(
        self,
        name: str,
        status: str,
        *,
        evidence: dict[str, Any] | None = None,
        error: str | None = None,
        started: float | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "name": name,
            "status": status,
            "finished_at": _utc_now(),
            "evidence": evidence or {},
        }
        if started is not None:
            entry["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if error:
            entry["error"] = error[:2000]
        self.phases.append(entry)
        self._write_receipt()
        print(f"[{status.upper()}] {name}", flush=True)

    def _prepare_paths(self) -> None:
        if self.run_dir.exists():
            raise RuntimeError(f"result directory already exists: {self.run_dir}")
        if self.runtime_dir.exists():
            raise RuntimeError(f"runtime directory already exists: {self.runtime_dir}")
        self.logs_dir.mkdir(parents=True)
        self.runtime_dir.mkdir(parents=True)
        shutil.copy2(self.manifest_path, self.run_dir / "model_manifest.json")
        self._write_receipt()

    def _run_logged(
        self,
        name: str,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 1800,
        check: bool = True,
    ) -> dict[str, Any]:
        log_path = self.logs_dir / f"{name}.log"
        started = time.monotonic()
        print(f"[RUN] {' '.join(_redacted_command(argv))}", flush=True)
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                argv,
                cwd=str(cwd) if cwd else None,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
            deadline = time.monotonic() + timeout
            selector = selectors.DefaultSelector()
            try:
                assert process.stdout is not None
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    if time.monotonic() > deadline:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                        raise TimeoutError(f"{name} exceeded {timeout}s")
                    events = selector.select(timeout=0.5)
                    for key, _ in events:
                        line = key.fileobj.readline()
                        if line:
                            log.write(line)
                            log.flush()
                            print(line.rstrip()[:2000], flush=True)
                    if process.poll() is not None:
                        # Drain the final buffered output after process exit.
                        remainder = process.stdout.read()
                        if remainder:
                            log.write(remainder)
                            log.flush()
                            for line in remainder.splitlines():
                                print(line[:2000], flush=True)
                        break
                code = int(process.wait())
            finally:
                selector.close()
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
        result = {
            "command": _redacted_command(argv),
            "exit_code": code,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "log": _bound_log(log_path),
        }
        if check and code != 0:
            raise RuntimeError(f"{name} exited {code}: {_safe_tail(log_path)}")
        return result

    def _run_capture(
        self,
        name: str,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 300,
        check: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
        started = time.monotonic()
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        log_path = self.logs_dir / f"{name}.log"
        log_path.write_text(
            "--- stdout ---\n"
            + completed.stdout
            + "\n--- stderr ---\n"
            + completed.stderr,
            encoding="utf-8",
        )
        result = {
            "command": _redacted_command(argv),
            "exit_code": completed.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "log": _bound_log(log_path),
        }
        if check and completed.returncode != 0:
            raise RuntimeError(
                f"{name} exited {completed.returncode}: {_safe_tail(log_path)}"
            )
        return completed, result

    def _validate_configuration(self) -> dict[str, Any]:
        selected = self.manifest.get("selected") or {}
        if self.manifest.get("schema") != "pulseai-colibri-model-selection/v1":
            raise ValueError("unknown model selection manifest schema")
        maximum = int(selected.get("engine_max_context_tokens") or 0)
        initial = int(selected.get("initial_test_context_tokens") or 0)
        if self.args.context_window < 8192 or self.args.context_window > maximum:
            raise ValueError(
                f"context {self.args.context_window} is outside 8192..{maximum}"
            )
        if self.args.long_context_tokens < 0:
            raise ValueError("long-context probe token count cannot be negative")
        if self.args.long_context_tokens >= self.args.context_window:
            raise ValueError(
                "long-context probe must stay below the configured context"
            )
        if not 0 <= self.args.cache_cap <= self.experts_per_layer:
            raise ValueError(
                "cache cap must be 0 (machine-plan auto) or between 1 and "
                f"{self.experts_per_layer}, got {self.args.cache_cap}"
            )
        if selected.get("cuda_partial_residency") is not True:
            raise ValueError("manifest does not enable audited CUDA partial residency")
        pinned_shas = {
            "colibri base commit": self.colibri_commit,
            "Colibri patch commit": self.colibri_patch_commit,
            "Colibri patch parent": self.colibri_patch_parent,
            "Colibri patched tree": self.colibri_patched_tree,
        }
        for label, value in pinned_shas.items():
            if not re.fullmatch(r"[0-9a-f]{40}", value):
                raise ValueError(f"{label} is not an immutable full Git object id")
        if not self.colibri_patch_ref.startswith("refs/pull/"):
            raise ValueError("Colibri patch fetch ref must be a pinned pull-request ref")
        if not 1024 <= self.args.port <= 65535:
            raise ValueError("port must be between 1024 and 65535")
        if self.args.context_window != initial:
            print(
                f"[NOTE] manifest starts at {initial}, this run requested "
                f"{self.args.context_window}",
                flush=True,
            )
        return {
            "manifest_sha256": _sha256_file(self.manifest_path),
            "context_window": self.args.context_window,
            "long_context_tokens_approx": self.args.long_context_tokens,
            "cache_cap": self.args.cache_cap,
            "cache_policy": (
                "machine_plan" if self.args.cache_cap == 0 else "explicit_at_or_below_plan"
            ),
            "experts_per_layer": self.experts_per_layer,
            "colibri_base_commit": self.colibri_commit,
            "colibri_patch_commit": self.colibri_patch_commit,
            "colibri_patched_tree": self.colibri_patched_tree,
            "model_repository": self.model_repo,
        }

    def _preflight(self) -> dict[str, Any]:
        if not self.args.allow_non_kaggle and not Path("/kaggle").is_dir():
            raise RuntimeError(
                "not running in Kaggle; use --allow-non-kaggle only for a controlled lab"
            )
        mem = _parse_meminfo()
        disk = shutil.disk_usage(self.runtime_parent)
        total_gb = mem.get("MemTotal", 0) / _GB
        available_gb = mem.get("MemAvailable", 0) / _GB
        free_disk_gb = disk.free / _GB
        minimum_disk = float(self.manifest["selected"]["disk_gb_decimal"]) + 12.0
        if total_gb < self.args.min_ram_gb:
            raise RuntimeError(
                f"host has {total_gb:.1f} GB RAM; requires {self.args.min_ram_gb:.1f} GB"
            )
        if available_gb < self.args.min_available_ram_gb:
            raise RuntimeError(
                f"host has {available_gb:.1f} GB available RAM; requires "
                f"{self.args.min_available_ram_gb:.1f} GB"
            )
        if free_disk_gb < minimum_disk:
            raise RuntimeError(
                f"runtime filesystem has {free_disk_gb:.1f} GB free; requires {minimum_disk:.1f} GB"
            )
        gpu, gpu_receipt = self._run_capture(
            "nvidia_smi_preflight",
            [
                "nvidia-smi",
                "--query-gpu=name,uuid,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            check=True,
        )
        if not gpu.stdout.strip():
            raise RuntimeError("nvidia-smi returned no GPU")
        nvcc, nvcc_receipt = self._run_capture(
            "nvcc_version", ["nvcc", "--version"], check=True
        )
        return {
            "kaggle_directory_present": Path("/kaggle").is_dir(),
            "ram_total_gb": round(total_gb, 2),
            "ram_available_gb": round(available_gb, 2),
            "disk_free_gb": round(free_disk_gb, 2),
            "disk_gate_gb": round(minimum_disk, 2),
            "gpu_inventory": [line for line in gpu.stdout.splitlines() if line.strip()],
            "nvidia_smi": gpu_receipt,
            "nvcc_version_sha256": hashlib.sha256(nvcc.stdout.encode()).hexdigest(),
            "nvcc": nvcc_receipt,
        }

    def _pulseai_identity(self) -> dict[str, Any]:
        completed, _ = self._run_capture(
            "pulseai_identity",
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
        )
        sha = completed.stdout.strip()
        status, _ = self._run_capture(
            "pulseai_status",
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            check=True,
        )
        self.receipt["pulseai"] = {
            "repository": "https://github.com/SriAkhilSJ/PulseAIRepo.git",
            "commit": sha,
            "worktree_clean": not bool(status.stdout.strip()),
        }
        return self.receipt["pulseai"]

    def _clone_colibri(self) -> dict[str, Any]:
        clone = self._run_logged(
            "colibri_clone",
            [
                "git",
                "clone",
                "--no-tags",
                "--filter=blob:none",
                str(self.manifest["selected"]["colibri_repository"]),
                str(self.colibri_dir),
            ],
            timeout=600,
        )
        checkout = self._run_logged(
            "colibri_checkout",
            ["git", "checkout", "--detach", self.colibri_commit],
            cwd=self.colibri_dir,
            timeout=300,
        )
        resolved, _ = self._run_capture(
            "colibri_identity",
            ["git", "rev-parse", "HEAD"],
            cwd=self.colibri_dir,
        )
        if resolved.stdout.strip() != self.colibri_commit:
            raise RuntimeError("Colibri checkout does not match the pinned base commit")

        patch_fetch = self._run_logged(
            "colibri_patch_fetch",
            [
                "git",
                "fetch",
                "--no-tags",
                "origin",
                self.colibri_patch_ref,
            ],
            cwd=self.colibri_dir,
            timeout=600,
        )
        fetched, fetched_receipt = self._run_capture(
            "colibri_patch_identity",
            ["git", "rev-parse", "FETCH_HEAD^{commit}"],
            cwd=self.colibri_dir,
        )
        if fetched.stdout.strip() != self.colibri_patch_commit:
            raise RuntimeError("Colibri pull-request ref moved away from the pinned patch")
        parent, parent_receipt = self._run_capture(
            "colibri_patch_parent",
            ["git", "rev-parse", f"{self.colibri_patch_commit}^"],
            cwd=self.colibri_dir,
        )
        if parent.stdout.strip() != self.colibri_patch_parent:
            raise RuntimeError("Colibri patch parent does not match the audited object")
        patch_apply = self._run_logged(
            "colibri_patch_apply",
            ["git", "cherry-pick", "--no-commit", self.colibri_patch_commit],
            cwd=self.colibri_dir,
            timeout=600,
        )
        _, diff_check = self._run_capture(
            "colibri_patch_diff_check",
            ["git", "diff", "--cached", "--check"],
            cwd=self.colibri_dir,
        )
        tree, tree_receipt = self._run_capture(
            "colibri_patched_tree",
            ["git", "write-tree"],
            cwd=self.colibri_dir,
        )
        if tree.stdout.strip() != self.colibri_patched_tree:
            raise RuntimeError(
                "Colibri base plus upstream patch does not match the audited Git tree"
            )
        unstaged, unstaged_receipt = self._run_capture(
            "colibri_unstaged_check",
            ["git", "diff", "--quiet"],
            cwd=self.colibri_dir,
            check=False,
        )
        untracked, untracked_receipt = self._run_capture(
            "colibri_untracked_check",
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=self.colibri_dir,
        )
        if unstaged.returncode != 0 or untracked.stdout.strip():
            raise RuntimeError("Colibri patched checkout has unexpected unstaged files")
        changed, changed_receipt = self._run_capture(
            "colibri_patch_paths",
            ["git", "diff", "--cached", "--name-only"],
            cwd=self.colibri_dir,
        )
        changed_paths = [line for line in changed.stdout.splitlines() if line]
        if not changed_paths:
            raise RuntimeError("Colibri upstream patch changed no files")
        return {
            "resolved_base_commit": resolved.stdout.strip(),
            "resolved_patch_commit": fetched.stdout.strip(),
            "resolved_patch_parent": parent.stdout.strip(),
            "resolved_patched_tree": tree.stdout.strip(),
            "patched_path_count": len(changed_paths),
            "clone": clone,
            "checkout": checkout,
            "patch_fetch": patch_fetch,
            "patch_identity": fetched_receipt,
            "patch_parent": parent_receipt,
            "patch_apply": patch_apply,
            "diff_check": diff_check,
            "tree_check": tree_receipt,
            "unstaged_check": unstaged_receipt,
            "untracked_check": untracked_receipt,
            "changed_paths": changed_receipt,
        }

    def _install_dependencies(self) -> dict[str, Any]:
        return self._run_logged(
            "pulseai_install",
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-e",
                str(REPO_ROOT),
                "huggingface_hub>=0.27,<2",
                "pytest>=8",
            ],
            cwd=REPO_ROOT,
            timeout=2400,
        )

    def _build_colibri(self) -> dict[str, Any]:
        partial_test_build = self._run_logged(
            "colibri_partial_tier_test_build",
            ["make", "-C", "c", "tests/test_qwen36_tier_stream", "-j2"],
            cwd=self.colibri_dir,
            timeout=600,
        )
        partial_test = self._run_logged(
            "colibri_partial_tier_test",
            [str(self.colibri_dir / "c" / "tests" / "test_qwen36_tier_stream")],
            cwd=self.colibri_dir,
            timeout=300,
        )
        result = self._run_logged(
            "colibri_cuda_build",
            ["make", "-C", "c", "qwen36", "CUDA=1", "-j2"],
            cwd=self.colibri_dir,
            timeout=2400,
        )
        binary = self.colibri_dir / "c" / "qwen36"
        if not binary.is_file():
            raise RuntimeError("CUDA build produced no c/qwen36 binary")
        linked, linkage = self._run_capture(
            "colibri_cuda_linkage", ["ldd", str(binary)], check=True
        )
        if "libcudart" not in linked.stdout:
            raise RuntimeError("qwen36 binary is not linked to libcudart")
        result["binary"] = str(binary)
        result["binary_sha256"] = _sha256_file(binary)
        result["libcudart_linked"] = True
        result["partial_residency_unit_test"] = {
            "build": partial_test_build,
            "run": partial_test,
            "passed": True,
        }
        result["linkage"] = linkage
        return result

    def _download_model(self) -> dict[str, Any]:
        started = time.monotonic()
        from huggingface_hub import HfApi, snapshot_download

        token = os.getenv("HF_TOKEN") or None
        info = HfApi(token=token).model_info(self.model_repo, revision="main")
        revision = str(info.sha)
        self.model_dir.parent.mkdir(parents=True, exist_ok=True)
        resolved_path = snapshot_download(
            repo_id=self.model_repo,
            revision=revision,
            local_dir=self.model_dir,
            token=token,
            max_workers=4,
        )
        files = [path for path in self.model_dir.rglob("*") if path.is_file()]
        total = sum(path.stat().st_size for path in files)
        if total < 10 * _GB:
            raise RuntimeError(
                f"downloaded checkpoint is unexpectedly small: {total / _GB:.2f} GB"
            )
        receipt = {
            "repository": self.model_repo,
            "resolved_revision": revision,
            "resolved_path": str(resolved_path),
            "files": len(files),
            "bytes": total,
            "gb_decimal": round(total / _GB, 3),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "hf_token_present": bool(token),
            "hf_token_persisted": False,
        }
        _atomic_json(self.run_dir / "model_download_receipt.json", receipt)
        return receipt

    def _resource_plan(self) -> dict[str, Any]:
        plan_argv = [
            sys.executable,
            "c/coli",
            "plan",
            "--model",
            str(self.model_dir),
            "--ctx",
            str(self.args.context_window),
            "--gpu",
            "auto",
            "--vram",
            "0",
            "--auto-tier",
            "--json",
        ]
        completed, command = self._run_capture(
            "colibri_resource_plan",
            plan_argv,
            cwd=self.colibri_dir,
            timeout=900,
        )
        try:
            plan = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Colibri resource plan did not emit JSON") from exc
        if (plan.get("model") or {}).get("family_id") != "qwen36":
            raise RuntimeError("Colibri resource plan resolved the wrong model family")
        tiers = plan.get("tiers") or {}
        ram = tiers.get("ram") or {}
        vram = tiers.get("vram") or {}
        planned_cap = int(ram.get("cache_slots_per_layer") or 0)
        if not 1 <= planned_cap <= self.experts_per_layer:
            raise RuntimeError(
                "resource plan returned an invalid Qwen3.6 RAM cache: "
                f"{planned_cap} slots per layer for {self.experts_per_layer} experts"
            )
        if self.args.cache_cap > planned_cap:
            raise RuntimeError(
                "explicit cache cap exceeds the machine-local safe plan: "
                f"requested {self.args.cache_cap}, planned {planned_cap}"
            )
        if not vram.get("devices") or int(vram.get("budget_bytes") or 0) <= 0:
            raise RuntimeError("resource plan has no executable CUDA VRAM tier")
        effective_cap = self.args.cache_cap or planned_cap
        self.effective_cache_slots_per_layer = effective_cap
        partial = effective_cap < self.experts_per_layer
        _atomic_json(self.run_dir / "colibri_resource_plan.json", plan)
        return {
            "command": command,
            "plan_path": str(self.run_dir / "colibri_resource_plan.json"),
            "plan_sha256": _sha256_file(self.run_dir / "colibri_resource_plan.json"),
            "ram_cache_slots_per_layer": planned_cap,
            "effective_cache_slots_per_layer": effective_cap,
            "experts_per_layer": self.experts_per_layer,
            "cache_policy": (
                "machine_plan" if self.args.cache_cap == 0 else "explicit_at_or_below_plan"
            ),
            "cuda_partial_residency_expected": partial,
            "cuda_residency_gate_passed": True,
            "ram_expert_cache_bytes": ram.get("expert_cache_bytes"),
            "ram_warm_expert_bytes": ram.get("warm_expert_bytes"),
            "ram_sequence_state_bytes": ram.get("sequence_state_bytes"),
            "vram_budget_bytes": vram.get("budget_bytes"),
            "vram_devices": vram.get("devices"),
            "warnings": plan.get("warnings") or [],
        }

    def _server_command(self) -> list[str]:
        command = [
            sys.executable,
            "c/coli",
            "serve",
            "--model",
            str(self.model_dir),
            "--ctx",
            str(self.args.context_window),
            "--gpu",
            "auto",
            "--vram",
            "0",
            "--auto-tier",
        ]
        runtime_cap = self.args.cache_cap or self.effective_cache_slots_per_layer
        if runtime_cap:
            command.extend(["--cap", str(runtime_cap)])
        command.extend(
            [
                "--ngen",
                "2048",
                "--max-queue",
                "0",
                "--queue-timeout",
                "60",
                "--kv-slots",
                "1",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.args.port),
                "--model-id",
                self.model_id,
                "--api-key",
                _LOCAL_API_KEY,
            ]
        )
        return command

    def _required_gpu_markers(self) -> tuple[str, ...]:
        markers = list(_GPU_MARKERS)
        if (
            self.effective_cache_slots_per_layer is not None
            and self.effective_cache_slots_per_layer < self.experts_per_layer
        ):
            markers.append(_PARTIAL_RESIDENCY_MARKER)
        return tuple(markers)

    def _start_server(self) -> dict[str, Any]:
        if self.effective_cache_slots_per_layer is None:
            raise RuntimeError("Colibri server cannot start before its resource plan")
        command = self._server_command()
        log_offset = (
            self.server_log_path.stat().st_size if self.server_log_path.is_file() else 0
        )
        restarting = log_offset > 0
        self.server_log_handle = self.server_log_path.open("a", encoding="utf-8")
        if restarting:
            self.server_log_handle.write(f"\n[runner] server restart at {_utc_now()}\n")
            self.server_log_handle.flush()
        self.server = subprocess.Popen(
            command,
            cwd=str(self.colibri_dir),
            stdout=self.server_log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        started = time.monotonic()
        deadline = started + self.args.server_start_timeout
        url = f"http://127.0.0.1:{self.args.port}/health"
        last_error = "not attempted"
        while time.monotonic() < deadline:
            if self.server.poll() is not None:
                raise RuntimeError(
                    f"Colibri server exited {self.server.returncode}: "
                    f"{_safe_tail(self.server_log_path)}"
                )
            try:
                request = urllib.request.Request(
                    url,
                    headers={"Authorization": f"Bearer {_LOCAL_API_KEY}"},
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    if response.status == 200:
                        body = json.loads(response.read())
                        self.server_log_handle.flush()
                        server_log = self.server_log_path.read_bytes()[
                            log_offset:
                        ].decode("utf-8", errors="replace")
                        required_markers = self._required_gpu_markers()
                        markers = {
                            marker: marker in server_log for marker in required_markers
                        }
                        if not all(markers.values()):
                            missing = [
                                marker
                                for marker, present in markers.items()
                                if not present
                            ]
                            raise RuntimeError(
                                "Colibri became healthy without its required CUDA tier "
                                f"markers {missing}: {_safe_tail(self.server_log_path)}"
                            )
                        gpu, gpu_receipt = self._run_capture(
                            "nvidia_smi_server_ready",
                            [
                                "nvidia-smi",
                                "--query-gpu=name,uuid,memory.used,utilization.gpu",
                                "--format=csv,noheader,nounits",
                            ],
                            check=True,
                        )
                        return {
                            "command": _redacted_command(command),
                            "pid": self.server.pid,
                            "restarted": restarting,
                            "ready_seconds": round(time.monotonic() - started, 3),
                            "health_sha256": hashlib.sha256(
                                json.dumps(body, sort_keys=True).encode()
                            ).hexdigest(),
                            "endpoint": f"http://127.0.0.1:{self.args.port}/v1",
                            "effective_cache_slots_per_layer": (
                                self.effective_cache_slots_per_layer
                            ),
                            "cuda_partial_residency": (
                                self.effective_cache_slots_per_layer is not None
                                and self.effective_cache_slots_per_layer
                                < self.experts_per_layer
                            ),
                            "cuda_markers": markers,
                            "nvidia_smi": gpu_receipt,
                            "gpu_state": [
                                line for line in gpu.stdout.splitlines() if line.strip()
                            ],
                            "log": str(self.server_log_path),
                        }
            except (OSError, ValueError, urllib.error.URLError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if int(time.monotonic() - started) % 30 == 0:
                print(
                    f"[WAIT] Colibri model loading for {time.monotonic() - started:.0f}s",
                    flush=True,
                )
            time.sleep(2)
        raise TimeoutError(
            f"Colibri did not become ready in {self.args.server_start_timeout}s; "
            f"last probe: {last_error}; log: {_safe_tail(self.server_log_path)}"
        )

    def _stop_server(self) -> None:
        if self.server is not None and self.server.poll() is None:
            try:
                os.killpg(self.server.pid, signal.SIGTERM)
                self.server.wait(timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.server.pid, signal.SIGKILL)
                except OSError:
                    pass
                self.server.wait(timeout=10)
        if self.server_log_handle is not None:
            self.server_log_handle.close()
            self.server_log_handle = None
        self.server = None

    def _restart_server(self) -> dict[str, Any]:
        self._stop_server()
        return self._start_server()

    def _run_probe(self) -> dict[str, Any]:
        output = self.run_dir / "colibri_endpoint_probe.json"
        env = dict(os.environ)
        env.update(
            {
                "CUSTOM_BASE_URL": f"http://127.0.0.1:{self.args.port}/v1",
                "CUSTOM_API_KEY": _LOCAL_API_KEY,
                "LLM_MODEL": self.model_id,
            }
        )
        command = self._run_logged(
            "colibri_endpoint_probe",
            [
                sys.executable,
                "-m",
                "benchmarks.colibri_agent_core.probe",
                "--base-url",
                env["CUSTOM_BASE_URL"],
                "--model",
                self.model_id,
                "--expected-context",
                str(self.args.context_window),
                "--long-context-tokens",
                str(self.args.long_context_tokens),
                "--timeout-seconds",
                str(self.args.probe_timeout),
                "--output",
                str(output),
            ],
            cwd=REPO_ROOT,
            env=env,
            timeout=int(self.args.probe_timeout * 6),
            check=False,
        )
        result = (
            json.loads(output.read_text(encoding="utf-8")) if output.is_file() else {}
        )
        phase_receipts = [
            {
                "name": phase.get("name"),
                "status": phase.get("status"),
                "elapsed_seconds": phase.get("elapsed_seconds"),
                "error": str(phase.get("error") or "")[:1000] or None,
            }
            for phase in result.get("phases", [])
            if isinstance(phase, dict)
        ]
        return {
            "command": command,
            "receipt": str(output),
            "receipt_sha256": _sha256_file(output) if output.is_file() else None,
            "status": result.get("status", "missing"),
            "phase_statuses": {
                phase.get("name"): phase.get("status") for phase in phase_receipts
            },
            "phase_receipts": phase_receipts,
        }

    def _agent_environment(self) -> dict[str, str]:
        crusor_home = self.run_dir / "crusorai-home"
        evidence_dir = crusor_home / "evidence" / "turns"
        env = dict(os.environ)
        env.update(
            {
                "LLM_PROVIDER": "custom",
                "LLM_MODEL": self.model_id,
                "CONTEXT_MODEL": self.model_id,
                "CUSTOM_BASE_URL": f"http://127.0.0.1:{self.args.port}/v1",
                "CUSTOM_API_KEY": _LOCAL_API_KEY,
                # Colibri /v1/models does not currently publish its configured
                # context, so this explicit value must match `coli serve --ctx`.
                "LLM_CONTEXT_WINDOW": str(self.args.context_window),
                "PROVIDER_SAFE_LIMIT": "0",
                "AUX_LLM_PROVIDER": "custom",
                "AUX_LLM_MODEL": self.model_id,
                "CRUSORAI_MEMORY": "off",
                "CRUSORAI_ALLOW_MODEL_DOWNLOADS": "off",
                "CRUSORAI_WEB_TOOLS": "off",
                "CRUSORAI_LLM_STREAMING": "on",
                "CRUSORAI_LLM_STALL_TIMEOUT_S": "300",
                "CRUSORAI_LLM_REQUEST_TIMEOUT_S": "600",
                "CRUSORAI_MAX_TOOLS": "12",
                "CRUSORAI_HOME": str(crusor_home),
                "CRUSORAI_EVIDENCE_DIR": str(evidence_dir),
                "CRUSORAI_OBSERVABILITY": "on",
                "CRUSORAI_OBSERVABILITY_PATH": str(
                    self.run_dir / "observability" / "turns.jsonl"
                ),
            }
        )
        return env

    def _run_agent_turn(self) -> dict[str, Any]:
        workspace = self.run_dir / "agent-workspace"
        workspace.mkdir(parents=True)
        project = workspace / "project.py"
        test = workspace / "test_project.py"
        readme = workspace / "README.md"
        project.write_text(
            "def total(values: list[int]) -> int:\n"
            '    """Return the sum of all values."""\n'
            "    return sum(values[:-1])\n",
            encoding="utf-8",
        )
        test.write_text(
            "from project import total\n\n"
            "def test_total_includes_every_value():\n"
            "    assert total([2, 3, 5]) == 10\n",
            encoding="utf-8",
        )
        readme.write_text("A tiny read-only diagnosis fixture.\n", encoding="utf-8")
        fixture_files = [project, test, readme]
        before = _tree_hash(fixture_files)
        prompt = self.run_dir / "agent_prompt.txt"
        prompt.write_text(
            "Inspect project.py and test_project.py using workspace tools. Identify the exact "
            "defect and explain the smallest repair, but do not modify any file. Ground the "
            "answer in what you read, then finish with the exact token "
            "PULSEAI_AGENT_CORE_DONE.\n",
            encoding="utf-8",
        )
        results_root = self.run_dir / "agent-core-runs"
        env = self._agent_environment()
        command = self._run_logged(
            "agent_core_turn",
            [
                sys.executable,
                "scripts/run_bridge_turn.py",
                "--workspace",
                str(workspace),
                "--prompt-file",
                str(prompt),
                "--timeout-s",
                str(self.args.agent_timeout),
                "--max-llm-calls",
                str(self.args.max_llm_calls),
                "--max-input-tokens",
                str(self.args.max_input_tokens),
                "--max-no-delivery-calls",
                "0",
                "--reasoning-effort",
                "none",
                "--results-root",
                str(results_root),
            ],
            cwd=REPO_ROOT,
            env=env,
            timeout=self.args.agent_timeout + 120,
            check=False,
        )
        after = _tree_hash(fixture_files)
        outcomes = sorted(results_root.glob("*/outcome.json"))
        outcome = (
            json.loads(outcomes[-1].read_text(encoding="utf-8")) if outcomes else {}
        )
        run_path = outcomes[-1].parent if outcomes else None
        frame_counts = outcome.get("frame_counts") or {}
        tool_frames = sum(
            int(count or 0)
            for name, count in frame_counts.items()
            if str(name).startswith("tool")
        )
        completed = outcome.get("result") == "turn_done" and bool(
            outcome.get("completed")
        )
        frames_path = run_path / "frames.jsonl" if run_path else None
        response = (
            _agent_response_receipt(frames_path)
            if frames_path is not None and frames_path.is_file()
            else {
                "terminal_type": None,
                "response_utf8_bytes": 0,
                "response_sha256": hashlib.sha256(b"").hexdigest(),
                "completion_sentinel_present": False,
                "defect_identified": False,
                "response_body_persisted_in_receipt": False,
            }
        )
        return {
            "command": command,
            "result_directory": str(run_path) if run_path else None,
            "outcome": outcome,
            "turn_completed": completed,
            "tool_frames": tool_frames,
            "fixture_sha256_before": before,
            "fixture_sha256_after": after,
            "fixture_unchanged": before == after,
            "response": response,
        }

    def _validate_agent_evidence(self, agent: dict[str, Any]) -> dict[str, Any]:
        result_dir = agent.get("result_directory")
        if not result_dir:
            raise RuntimeError("Agent Core run has no result directory")
        frames_path = Path(result_dir) / "frames.jsonl"
        terminal: dict[str, Any] | None = None
        for line in frames_path.read_text(encoding="utf-8").splitlines():
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            if frame.get("type") in {"turn_done", "turn_failed"}:
                terminal = frame
        evidence = (terminal or {}).get("evidence") or {}
        manifest = evidence.get("manifest_path")
        if not manifest:
            raise RuntimeError("terminal frame has no runtime evidence manifest")
        output = self.run_dir / "agent_core_evidence_validation.json"
        completed, command = self._run_capture(
            "agent_core_evidence_validation",
            [
                sys.executable,
                "scripts/verify_runtime_evidence.py",
                str(manifest),
                "--require-complete",
            ],
            cwd=REPO_ROOT,
            env=self._agent_environment(),
            timeout=300,
            check=False,
        )
        try:
            validation = json.loads(completed.stdout)
        except json.JSONDecodeError:
            validation = {
                "valid": False,
                "error": "validator did not emit JSON",
                "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
            }
        _atomic_json(output, validation)
        return {
            "command": command,
            "manifest": str(manifest),
            "manifest_sha256": _sha256_file(Path(manifest))
            if Path(manifest).is_file()
            else None,
            "validator_exit_code": completed.returncode,
            "validation": validation,
            "validation_receipt": str(output),
        }

    def _gpu_execution_receipt(self, probe: dict[str, Any]) -> dict[str, Any]:
        completed, nvidia = self._run_capture(
            "nvidia_smi_after_inference",
            [
                "nvidia-smi",
                "--query-gpu=name,uuid,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=False,
        )
        text = self.server_log_path.read_text(encoding="utf-8", errors="replace")
        required_markers = self._required_gpu_markers()
        markers = {marker: marker in text for marker in required_markers}
        activity = _cuda_activity_from_log(text)
        memory_used_mib = _nvidia_memory_used_mib(completed.stdout)
        generation_passed = (
            probe.get("phase_statuses", {}).get("basic_chat") == "passed"
        )
        verified = (
            completed.returncode == 0
            and bool(completed.stdout.strip())
            and memory_used_mib > 0
            and all(markers.values())
            and activity["max_device_hits"] > 0
            and activity["max_group_calls"] > 0
            and activity["max_group_experts"] > 0
            and generation_passed
        )
        return {
            "verified": verified,
            "meaning": (
                "A real generation completed while the CUDA-linked qwen36 engine "
                "reported positive routed-expert hits and CUDA group calls with "
                "device memory resident."
                if verified
                else "GPU inference is not proven by the available receipts."
            ),
            "required_log_markers": markers,
            "cuda_activity": activity,
            "nvidia_memory_used_mib_total": memory_used_mib,
            "effective_cache_slots_per_layer": self.effective_cache_slots_per_layer,
            "experts_per_layer": self.experts_per_layer,
            "partial_residency_verified": (
                _PARTIAL_RESIDENCY_MARKER in markers
                and markers.get(_PARTIAL_RESIDENCY_MARKER) is True
            ),
            "generation_passed": generation_passed,
            "nvidia_smi": nvidia,
            "gpu_state": [
                line for line in completed.stdout.splitlines() if line.strip()
            ],
            "server_log_sha256": _sha256_file(self.server_log_path),
        }

    def _dry_run(self) -> int:
        self.output_parent.mkdir(parents=True, exist_ok=True)
        self._prepare_paths()
        started = time.monotonic()
        valid = False
        error = None
        try:
            evidence = self._validate_configuration()
            self._phase("configuration", "passed", evidence=evidence, started=started)
            valid = True
        except Exception as exc:  # noqa: BLE001 - invalid plans still need a receipt
            error = f"{type(exc).__name__}: {exc}"
            self._phase("configuration", "failed", error=error, started=started)
        self.receipt.update(
            {
                "status": "dry_run" if valid else "failed",
                "finished_at": _utc_now(),
                "dry_run": True,
                "fatal_error": error,
                "claim": "No Kaggle GPU, model download, endpoint, or Agent Core turn was executed.",
            }
        )
        self._write_receipt()
        self._archive()
        return 0 if valid else 1

    def _archive(self) -> Path:
        archive = Path(
            shutil.make_archive(
                str(self.run_dir),
                "gztar",
                root_dir=self.run_dir.parent,
                base_dir=self.run_dir.name,
            )
        )
        archive.with_suffix(archive.suffix + ".sha256").write_text(
            f"{_sha256_file(archive)}  {archive.name}\n", encoding="ascii"
        )
        print(f"[RESULT] {archive}", flush=True)
        return archive

    def run(self) -> int:
        if self.args.dry_run:
            return self._dry_run()
        self.output_parent.mkdir(parents=True, exist_ok=True)
        self.runtime_parent.mkdir(parents=True, exist_ok=True)
        self._prepare_paths()
        fatal: Exception | None = None
        probe: dict[str, Any] = {}
        agent: dict[str, Any] = {}
        evidence: dict[str, Any] = {}
        try:
            for name, operation in (
                ("configuration", self._validate_configuration),
                ("hardware_preflight", self._preflight),
                ("pulseai_identity", self._pulseai_identity),
                ("colibri_checkout", self._clone_colibri),
                ("pulseai_dependencies", self._install_dependencies),
                ("colibri_cuda_build", self._build_colibri),
                ("model_download", self._download_model),
                ("colibri_resource_plan", self._resource_plan),
                ("colibri_server_start", self._start_server),
            ):
                started = time.monotonic()
                try:
                    value = operation()
                    self._phase(name, "passed", evidence=value, started=started)
                except Exception as exc:
                    self._phase(
                        name,
                        "failed",
                        error=f"{type(exc).__name__}: {exc}",
                        started=started,
                    )
                    raise

            started = time.monotonic()
            probe = self._run_probe()
            if probe.get("status") != "passed" and not self.args.skip_agent_turn:
                recovery_started = time.monotonic()
                try:
                    recovery = self._restart_server()
                    recovery["status"] = "passed"
                    recovery["elapsed_seconds"] = round(
                        time.monotonic() - recovery_started, 3
                    )
                    recovery["reason"] = (
                        "isolate Agent Core from a timed-out or orphaned probe request"
                    )
                    probe["server_recovery"] = recovery
                except Exception as exc:
                    probe["server_recovery"] = {
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}"[:2000],
                    }
                    self._phase(
                        "colibri_endpoint_probe",
                        "failed",
                        evidence=probe,
                        started=started,
                    )
                    raise
            self._phase(
                "colibri_endpoint_probe",
                "passed" if probe.get("status") == "passed" else "failed",
                evidence=probe,
                started=started,
            )

            if self.args.skip_agent_turn:
                self._phase(
                    "agent_core_turn",
                    "skipped",
                    evidence={"reason": "--skip-agent-turn"},
                )
            else:
                started = time.monotonic()
                agent = self._run_agent_turn()
                response = agent.get("response") or {}
                agent_ok = (
                    agent.get("turn_completed")
                    and agent.get("fixture_unchanged")
                    and int(agent.get("tool_frames") or 0) > 0
                    and response.get("completion_sentinel_present") is True
                    and response.get("defect_identified") is True
                )
                self._phase(
                    "agent_core_turn",
                    "passed" if agent_ok else "failed",
                    evidence=agent,
                    started=started,
                )
                started = time.monotonic()
                try:
                    evidence = self._validate_agent_evidence(agent)
                    validation = evidence.get("validation") or {}
                    evidence_ok = (
                        evidence.get("validator_exit_code") == 0
                        and validation.get("integrity_valid") is True
                        and validation.get("capture_complete") is True
                    )
                    self._phase(
                        "agent_core_evidence",
                        "passed" if evidence_ok else "failed",
                        evidence=evidence,
                        started=started,
                    )
                except Exception as exc:  # noqa: BLE001
                    self._phase(
                        "agent_core_evidence",
                        "failed",
                        error=f"{type(exc).__name__}: {exc}",
                        started=started,
                    )

            started = time.monotonic()
            gpu = self._gpu_execution_receipt(probe)
            self.receipt["gpu_execution"] = gpu
            self._phase(
                "gpu_execution_proof",
                "passed" if gpu["verified"] else "failed",
                evidence=gpu,
                started=started,
            )
        except Exception as exc:  # noqa: BLE001
            fatal = exc
        finally:
            self._stop_server()
            if self.server_log_path.is_file():
                self.receipt["colibri"]["server_log"] = _bound_log(self.server_log_path)

        required = {
            "configuration",
            "hardware_preflight",
            "pulseai_identity",
            "colibri_checkout",
            "pulseai_dependencies",
            "colibri_cuda_build",
            "model_download",
            "colibri_resource_plan",
            "colibri_server_start",
            "colibri_endpoint_probe",
            "gpu_execution_proof",
        }
        if not self.args.skip_agent_turn:
            required |= {"agent_core_turn", "agent_core_evidence"}
        statuses = {phase["name"]: phase["status"] for phase in self.phases}
        complete = fatal is None and all(
            statuses.get(name) == "passed" for name in required
        )
        self.receipt.update(
            {
                "status": "passed" if complete else "failed",
                "finished_at": _utc_now(),
                "fatal_error": (
                    f"{type(fatal).__name__}: {fatal}"[:2000] if fatal else None
                ),
                "required_phases": sorted(required),
                "phase_statuses": statuses,
                "claims": {
                    "kaggle_gpu_run_verified": bool(
                        self.receipt.get("gpu_execution", {}).get("verified")
                    ),
                    "colibri_endpoint_passed": probe.get("status") == "passed",
                    "agent_core_turn_completed": bool(agent.get("turn_completed")),
                    "runtime_evidence_integrity_valid": bool(
                        (evidence.get("validation") or {}).get("integrity_valid")
                    ),
                },
            }
        )
        self._write_receipt()
        self._archive()
        return 0 if complete else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--runtime-root", type=Path, default=Path("/kaggle/temp/pulseai-colibri")
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/kaggle/working/colibri-agent-core-results"),
    )
    parser.add_argument("--run-id")
    parser.add_argument("--context-window", type=int, default=65536)
    parser.add_argument("--long-context-tokens", type=int, default=16384)
    parser.add_argument(
        "--cache-cap",
        type=int,
        default=0,
        help=(
            "expert slots/layer; 0 uses Colibri's machine-local plan, while an "
            "explicit value must not exceed that safe plan"
        ),
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--probe-timeout", type=int, default=1800)
    parser.add_argument("--server-start-timeout", type=int, default=1800)
    parser.add_argument("--agent-timeout", type=int, default=3600)
    parser.add_argument("--max-llm-calls", type=int, default=10)
    parser.add_argument("--max-input-tokens", type=int, default=120000)
    parser.add_argument("--min-ram-gb", type=float, default=24.0)
    parser.add_argument("--min-available-ram-gb", type=float, default=18.0)
    parser.add_argument("--skip-agent-turn", action="store_true")
    parser.add_argument("--allow-non-kaggle", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate configuration and create a receipt without network/GPU/model work",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        runner = Runner(args)
        return runner.run()
    except Exception as exc:  # noqa: BLE001 - a pre-receipt failure still needs a bounded CLI error
        print(f"FATAL {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
