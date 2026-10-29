"""Machine-readable engine and desktop-renderer build identity.

The bridge already logs a human freshness diagnosis. Evidence capture needs the
same facts as structured data so a turn cannot later be attributed to a build
by narrative alone.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from copy import deepcopy
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

BUILD_IDENTITY_SCHEMA_VERSION = 1
_STAMP_RE = re.compile(r"CRUSORAI_UI_STAMP\s*=\s*['\"]([^'\"]+)['\"]")


def _run_git(root: Path, *args: str) -> tuple[int | None, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None, ""


def _run_git_bytes(root: Path, *args: str) -> tuple[int | None, bytes]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=10,
            check=False,
        )
        return proc.returncode, proc.stdout
    except (OSError, subprocess.SubprocessError):
        return None, b""


def _worktree_fingerprint(root: Path) -> tuple[str | None, int | None]:
    """Hash exact tracked diffs plus every non-ignored untracked file.

    The probe is intentionally bounded: monitoring must not hold a user turn
    indefinitely because a workspace contains a huge generated artifact.  A
    bound hit returns ``None`` rather than presenting a partial digest as exact.
    """
    started = time.monotonic()
    deadline_s = 10.0
    max_bytes = 256 * 1024 * 1024
    diff_status, tracked_diff = _run_git_bytes(
        root, "diff", "--binary", "--no-ext-diff", "HEAD", "--"
    )
    untracked_status, untracked_raw = _run_git_bytes(
        root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )
    if diff_status != 0 or untracked_status != 0:
        return None, None
    untracked_paths = sorted(path for path in untracked_raw.split(b"\0") if path)
    if len(tracked_diff) > max_bytes or time.monotonic() - started >= deadline_s:
        return None, len(untracked_paths)
    digest = hashlib.sha256()
    digest.update(b"tracked-diff\0")
    digest.update(tracked_diff)
    digest.update(b"\0untracked-files\0")
    bytes_hashed = len(tracked_diff)
    try:
        for raw_path in untracked_paths:
            if time.monotonic() - started >= deadline_s:
                return None, len(untracked_paths)
            relative = Path(os.fsdecode(raw_path))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("unsafe untracked path")
            candidate = root / relative
            digest.update(raw_path)
            digest.update(b"\0")
            if candidate.is_symlink():
                link_target = os.readlink(candidate).encode("utf-8")
                bytes_hashed += len(link_target)
                if bytes_hashed > max_bytes:
                    return None, len(untracked_paths)
                digest.update(link_target)
            elif candidate.is_file():
                if bytes_hashed + candidate.stat().st_size > max_bytes:
                    return None, len(untracked_paths)
                with candidate.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        if time.monotonic() - started >= deadline_s:
                            return None, len(untracked_paths)
                        bytes_hashed += len(chunk)
                        digest.update(chunk)
            digest.update(b"\0")
    except (OSError, UnicodeError, ValueError):
        return None, len(untracked_paths)
    return digest.hexdigest(), len(untracked_paths)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _extract_stamp(path: Path) -> str | None:
    match = _STAMP_RE.search(_read_text(path))
    return match.group(1) if match else None


def _renderer_sources_hash(root: Path) -> str | None:
    """Mirror ``emit-crusorai-bundle.mjs`` byte-for-byte."""
    vscode_root = root / "desktop" / "vscode"
    source_dir = (
        vscode_root
        / "src"
        / "vs"
        / "workbench"
        / "contrib"
        / "crusorai"
    )
    emitter = vscode_root / "scripts" / "emit-crusorai-bundle.mjs"
    if not source_dir.is_dir() or not emitter.is_file():
        return None
    digest = hashlib.sha256()
    files = sorted(
        (path.relative_to(vscode_root).as_posix(), path)
        for path in source_dir.rglob("*")
        if path.is_file()
    )
    try:
        for relative, path in files:
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
            digest.update(b"\0")
        digest.update(emitter.relative_to(vscode_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(emitter.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    except OSError:
        return None
    return digest.hexdigest()


def _collect(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    commit_status, repo_commit = _run_git(root, "rev-parse", "HEAD")
    if commit_status != 0:
        repo_commit = os.getenv("CRUSORAI_BUILD_COMMIT", "").strip()
    dirty_status, dirty_output = _run_git(
        root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    dirty_lines = [line for line in dirty_output.splitlines() if line.strip()]
    worktree_fingerprint, untracked_count = _worktree_fingerprint(root)

    renderer_dir = (
        root
        / "desktop"
        / "vscode"
        / "out"
        / "vs"
        / "workbench"
        / "contrib"
        / "crusorai"
        / "browser"
    )
    build_info_path = renderer_dir / "BUILD_INFO.json"
    try:
        build_info = json.loads(_read_text(build_info_path) or "{}")
        if not isinstance(build_info, dict):
            build_info = {}
    except json.JSONDecodeError:
        build_info = {}
    renderer_commit = str(build_info.get("commit") or "").strip() or None
    built_at = str(build_info.get("builtAt") or "").strip() or None

    source_renderer = (
        root
        / "desktop"
        / "vscode"
        / "src"
        / "vs"
        / "workbench"
        / "contrib"
        / "crusorai"
        / "browser"
        / "crusorAIRenderer.ts"
    )
    emitted_renderer = renderer_dir / "crusorAIRenderer.js"
    source_stamp = _extract_stamp(source_renderer)
    emitted_stamp = _extract_stamp(emitted_renderer)
    committed_hash = _read_text(renderer_dir / "SOURCES_HASH") or None
    recomputed_hash = _renderer_sources_hash(root)

    stamp_match = bool(source_stamp and source_stamp == emitted_stamp)
    sources_match = bool(
        committed_hash
        and recomputed_hash
        and committed_hash == recomputed_hash
    )
    commit_match = bool(
        repo_commit
        and renderer_commit
        and repo_commit == renderer_commit
    )
    renderer_ancestor: bool | None = None
    if repo_commit and renderer_commit:
        ancestor_status, _ = _run_git(
            root,
            "merge-base",
            "--is-ancestor",
            renderer_commit,
            repo_commit,
        )
        if ancestor_status in {0, 1}:
            renderer_ancestor = ancestor_status == 0
    repo_dirty: bool | None = None
    if dirty_status == 0:
        repo_dirty = bool(dirty_lines)

    reasons: list[str] = []
    if not repo_commit:
        reasons.append("repository_commit_unavailable")
    if repo_dirty is None:
        reasons.append("repository_cleanliness_unavailable")
    elif repo_dirty:
        reasons.append("repository_dirty")
    if worktree_fingerprint is None:
        reasons.append("worktree_fingerprint_unavailable")
    if not renderer_commit:
        reasons.append("renderer_build_commit_unavailable")
    elif renderer_ancestor is None:
        reasons.append("renderer_build_ancestry_unavailable")
    elif not renderer_ancestor:
        reasons.append("renderer_build_commit_not_ancestor")
    if not source_stamp or not emitted_stamp:
        reasons.append("renderer_stamp_unavailable")
    elif not stamp_match:
        reasons.append("renderer_stamp_mismatch")
    if not committed_hash or not recomputed_hash:
        reasons.append("renderer_sources_hash_unavailable")
    elif not sources_match:
        reasons.append("renderer_sources_hash_mismatch")

    hard_mismatch = bool(
        {"renderer_stamp_mismatch", "renderer_sources_hash_mismatch"}
        & set(reasons)
    ) or (
        "renderer_build_commit_not_ancestor" in reasons
        and repo_dirty is not True
    )
    if not reasons:
        status = "matched"
    elif hard_mismatch:
        status = "mismatch"
    elif "repository_dirty" in reasons:
        # A dirty tree has exact content provenance through its fingerprint and
        # renderer source hash. Its HEAD ancestry does not describe those
        # uncommitted bytes, so a known ancestry difference remains a recorded
        # fact rather than falsely making the identity unavailable.
        status = "dirty"
    else:
        status = "unavailable"

    return {
        "schema_version": BUILD_IDENTITY_SCHEMA_VERSION,
        "captured_at": datetime.now(UTC).isoformat(),
        "status": status,
        "reasons": reasons,
        "repository": {
            "path": str(root),
            "commit": repo_commit or None,
            "dirty": repo_dirty,
            "worktree_change_count": (
                len(dirty_lines) if dirty_status == 0 else None
            ),
            "untracked_file_count": untracked_count,
            "worktree_fingerprint_sha256": worktree_fingerprint,
        },
        "renderer": {
            "build_commit": renderer_commit,
            "built_at": built_at,
            "source_stamp": source_stamp,
            "emitted_stamp": emitted_stamp,
            "stamp_match": stamp_match,
            "committed_sources_hash": committed_hash,
            "recomputed_sources_hash": recomputed_hash,
            "sources_match": sources_match,
            "build_commit_matches_repository": commit_match,
            "build_commit_is_repository_ancestor": renderer_ancestor,
        },
        "process": {
            "python": platform.python_version(),
            "python_executable": sys.executable,
            "platform": platform.platform(),
        },
    }


def build_identity_is_complete(build: dict[str, Any]) -> bool:
    """Return whether provenance is exact enough for a complete receipt.

    A dirty tree is acceptable only when its exact content fingerprint and the
    renderer's exact source/emitted hashes are present. In that case Git
    ancestry can truthfully differ from HEAD because HEAD omits the captured
    uncommitted bytes; the relationship is still retained in ``reasons``.
    """
    repository = dict(build.get("repository") or {})
    renderer = dict(build.get("renderer") or {})
    status = str(build.get("status") or "")
    reasons = set(build.get("reasons") or [])
    allowed_reasons = {"repository_dirty"}
    if (
        repository.get("dirty") is True
        and repository.get("worktree_fingerprint_sha256")
        and renderer.get("build_commit")
        and renderer.get("stamp_match") is True
        and renderer.get("sources_match") is True
    ):
        allowed_reasons.update(
            {
                "renderer_build_ancestry_unavailable",
                "renderer_build_commit_not_ancestor",
            }
        )
    required = (
        repository.get("commit"),
        repository.get("worktree_fingerprint_sha256"),
        renderer.get("build_commit"),
        renderer.get("source_stamp"),
        renderer.get("recomputed_sources_hash"),
    )
    return bool(
        status in {"matched", "dirty"}
        and all(required)
        and renderer.get("stamp_match") is True
        and renderer.get("sources_match") is True
        and not (reasons - allowed_reasons)
    )


@lru_cache(maxsize=1)
def _default_identity() -> dict[str, Any]:
    return _collect(Path(__file__).resolve().parents[2])


def collect_build_identity(repo_root: str | Path | None = None) -> dict[str, Any]:
    """Return an isolated copy so callers cannot mutate the process cache."""
    if repo_root is not None:
        return _collect(Path(repo_root))
    return deepcopy(_default_identity())


def reset_build_identity_cache_for_tests() -> None:
    _default_identity.cache_clear()
