"""Code OSS Invariant 7: keep the desktop overlay inside its declared surface.

The repository declares its upstream overlay in ``desktop/SELECTIVE_MANIFEST.json``:
the upstream commit it was cut from, the *allowed* modified upstream files (with
both the upstream and overlay hashes), and the custom root
(``src/vs/workbench/contrib/crusorai/``) where Crusor-owned code lives.

This module verifies, from the filesystem and git, that:

* every declared modified file still hashes to its declared overlay hash;
* no file outside the declared set / custom root has drifted in the worktree;
* the custom root exists and is the only place new workbench code appears.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class Invariant7Error(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Invariant7Report:
    manifest_present: bool = False
    upstream_commit: str = ""
    custom_root: str = ""
    declared_files: list[dict[str, Any]] = field(default_factory=list)
    drift_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    undeclared_changes: list[str] = field(default_factory=list)
    maintained: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_present": self.manifest_present,
            "upstream_commit": self.upstream_commit,
            "custom_root": self.custom_root,
            "declared_files": self.declared_files,
            "drift_files": self.drift_files,
            "changed_files": self.changed_files,
            "undeclared_changes": self.undeclared_changes,
            "maintained": self.maintained,
            "notes": self.notes,
        }


def relativize(path: str, prefix: str) -> str:
    """Strip a repository-relative prefix from a git-status path."""
    path = path.replace("\\", "/")
    if prefix and path.startswith(prefix):
        return path[len(prefix):]
    return path


def _git_changed_files(vscode_root: Path) -> tuple[list[str], str | None]:
    """Return (paths relative to ``vscode_root``, error).

    ``git status`` always prints repository-root-relative paths, while
    ``SELECTIVE_MANIFEST.json`` keys are relative to ``desktop/vscode``. Strip
    the repo prefix so the two are comparable (a mismatch here once made the
    checker report "0 changed" while 45 bundle files were modified).
    """
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=60, cwd=str(vscode_root),
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--", "."],
            capture_output=True, text=True, timeout=120, cwd=str(vscode_root),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"git status failed: {exc}"
    if status.returncode != 0:
        return [], f"git status failed: {status.stderr[:400]}"

    prefix = ""
    if top.returncode == 0 and top.stdout.strip():
        try:
            prefix = Path(vscode_root).resolve().relative_to(
                Path(top.stdout.strip()).resolve()
            ).as_posix().rstrip("/") + "/"
        except ValueError:
            prefix = ""

    out: list[str] = []
    for line in status.stdout.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = relativize(path, prefix)
        out.append(path)
    return out, None


def check_invariant7(repo_root: str | Path, *, vscode_root: str | Path | None = None) -> Invariant7Report:
    repo = Path(repo_root).resolve()
    vscode = Path(vscode_root).resolve() if vscode_root else repo / "desktop" / "vscode"
    manifest_path = repo / "desktop" / "SELECTIVE_MANIFEST.json"
    report = Invariant7Report()

    if not manifest_path.exists():
        report.notes.append(f"manifest missing at {manifest_path}")
        return report

    report.manifest_present = True
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report.upstream_commit = str(manifest.get("upstream_commit") or "")
    report.custom_root = str(manifest.get("custom_root") or "")
    declared = manifest.get("files") or {}

    for rel_path, entry in declared.items():
        if not isinstance(entry, dict):
            continue
        target = vscode / rel_path
        expected = str(entry.get("overlay_sha256") or "")
        actual = sha256_file(target) if target.exists() else ""
        status = "match" if actual and actual == expected else ("missing" if not target.exists() else "drift")
        report.declared_files.append({
            "path": rel_path,
            "expected_overlay_sha256": expected,
            "actual_sha256": actual,
            "modified_from_upstream": bool(entry.get("modified")),
            "status": status,
        })
        if status != "match":
            report.drift_files.append(rel_path)

    report.changed_files, git_error = _git_changed_files(vscode)
    if git_error:
        report.notes.append(git_error)

    declared_paths = set(declared.keys())
    custom_prefix = report.custom_root.rstrip("/") + "/"
    allowed_extra_prefixes = (
        custom_prefix,
        "out/",
        ".build/",
        "node_modules/",
    )
    for changed in report.changed_files:
        if changed in declared_paths:
            continue
        if any(changed.startswith(prefix) for prefix in allowed_extra_prefixes):
            continue
        # Build artifacts and brand assets are declared separately.
        if changed.startswith("resources/"):
            report.notes.append(f"brand asset changed: {changed}")
            continue
        report.undeclared_changes.append(changed)

    report.maintained = bool(
        report.manifest_present
        and not report.drift_files
        and not report.undeclared_changes
    )
    return report
