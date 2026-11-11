"""Build a versioned evidence manifest for a qualification run.

The manifest is a signed-by-sidecar list: every artifact is hashed, while the
manifest itself is excluded from its own list. ``EVIDENCE_MANIFEST.sha256``
contains the SHA-256 of the canonical manifest bytes, so the manifest can be
verified without a self-reference paradox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATUSES = {"COMPLETE", "DEGRADED", "FAILED"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build(
    *,
    run_dir: Path,
    run_id: str,
    mode: str,
    provider_mode: str,
    app_build: str,
    git_head: str,
    session_id: str = "",
    turn_id: str = "",
    prompt_id: str = "",
    before_workspace: str = "",
    after_workspace: str = "",
    receipts: list[Path] | None = None,
    finops: list[Path] | None = None,
    traces: list[Path] | None = None,
    checkpoints: list[Path] | None = None,
    screenshots: list[Path] | None = None,
    commands: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    seen: set[Path] = set()

    def add(path: Path, kind: str, required: bool = True, note: str = "") -> None:
        path = path.resolve()
        if path in seen or not path.exists():
            return
        seen.add(path)
        artifacts.append({
            "kind": kind,
            "path": rel(path, run_dir),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "required": required,
            "note": note,
        })

    for path in screenshots or []:
        add(path, "screenshot")
    for path in receipts or []:
        add(path, "turn_receipt")
    for path in finops or []:
        add(path, "finops_invocation_ledger")
    for path in traces or []:
        add(path, "event_trace")
    for path in checkpoints or []:
        add(path, "checkpoint_database")
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name not in {
            "EVIDENCE_MANIFEST.json", "EVIDENCE_MANIFEST.sha256",
        }:
            kind = {
                ".png": "screenshot", ".json": "run_artifact",
                ".log": "log", ".txt": "log", ".jsonl": "event_trace",
                ".py": "helper_source",
            }.get(path.suffix.lower(), "artifact")
            add(path, kind, required=False)

    # Required categories are checked by presence, not by guessed filenames.
    required_categories = {
        "screenshot", "run_artifact", "event_trace",
        "turn_receipt", "finops_invocation_ledger", "checkpoint_database",
    }
    present = {item["kind"] for item in artifacts}
    missing = sorted(required_categories - present)
    missing_required = list(missing)

    not_applicable = {}
    if provider_mode == "fixture":
        not_applicable["real_provider_trace"] = (
            "provider-free deterministic fixture: no paid provider call was made"
        )
        not_applicable["real_provider_cost"] = (
            "fixture usage is synthetic; cost certainty is reported as unknown"
        )

    status = "COMPLETE"
    if missing:
        status = "DEGRADED"
    if not artifacts:
        status = "FAILED"
    if status not in STATUSES:
        status = "DEGRADED"

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "test_mode": mode,
        "provider_mode": provider_mode,
        "provider_call_authorized": False,
        "application_build_id": app_build,
        "git_head": git_head,
        "session_id": session_id,
        "turn_id": turn_id,
        "prompt_id": prompt_id,
        "workspace": {
            "before_sha256": before_workspace,
            "after_sha256": after_workspace,
        },
        "artifacts": sorted(artifacts, key=lambda item: (item["kind"], item["path"])),
        "missing_required": missing,
        "not_applicable": not_applicable,
        "commands": commands or [],
        "evidence_status": status,
        "manifest_convention": (
            "This file is excluded from artifacts; EVIDENCE_MANIFEST.sha256 "
            "holds the SHA-256 of these canonical bytes."
        ),
    }
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", default="deterministic-electron")
    parser.add_argument("--provider-mode", default="fixture")
    parser.add_argument("--app-build", default="unknown")
    parser.add_argument("--git-head", default="unknown")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--turn-id", default="")
    parser.add_argument("--prompt-id", default="")
    parser.add_argument("--before-workspace", default="")
    parser.add_argument("--after-workspace", default="")
    parser.add_argument("--receipt", action="append", default=[])
    parser.add_argument("--finops", action="append", default=[])
    parser.add_argument("--trace", action="append", default=[])
    parser.add_argument("--checkpoint", action="append", default=[])
    parser.add_argument("--screenshot", action="append", default=[])
    parser.add_argument("--command-json", default="")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    commands = json.loads(args.command_json) if args.command_json else []
    manifest = build(
        run_dir=run_dir,
        run_id=args.run_id,
        mode=args.mode,
        provider_mode=args.provider_mode,
        app_build=args.app_build,
        git_head=args.git_head,
        session_id=args.session_id,
        turn_id=args.turn_id,
        prompt_id=args.prompt_id,
        before_workspace=args.before_workspace,
        after_workspace=args.after_workspace,
        receipts=[Path(p) for p in args.receipt],
        finops=[Path(p) for p in args.finops],
        traces=[Path(p) for p in args.trace],
        checkpoints=[Path(p) for p in args.checkpoint],
        screenshots=[Path(p) for p in args.screenshot],
        commands=commands,
    )
    payload = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
    manifest_path = run_dir / "EVIDENCE_MANIFEST.json"
    manifest_path.write_bytes(payload)
    (run_dir / "EVIDENCE_MANIFEST.sha256").write_text(
        hashlib.sha256(payload).hexdigest() + "\n", encoding="ascii",
    )
    print(json.dumps({
        "status": manifest["evidence_status"],
        "artifacts": len(manifest["artifacts"]),
        "missing": manifest["missing_required"],
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
    }, indent=2))
    return 0 if manifest["evidence_status"] == "COMPLETE" else 2


if __name__ == "__main__":
    sys.exit(main())
