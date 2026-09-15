"""Prompt & policy registry [PDF §3.2 prompt versioning, plan J31].

Read-only inventory of the versioned prompt corpus (git-tracked src/prompts):
per-file content hash + whole-corpus hash = the prompt policy version.
Per-turn attribution appears when receipts carry extra.prompt_id (demo seeds it;
engine emission is the one remaining additive gap).
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any

from .. import config
from . import receipts

_CACHE: dict[str, Any] = {"at": 0.0, "value": None}


def prompts_dir() -> Path:
    custom = os.environ.get("CRUSORAI_OPS_PROMPTS_DIR", "").strip()
    if custom:
        return Path(custom).expanduser()
    return Path(__file__).resolve().parents[3] / "src" / "prompts"


def _hash_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def registry() -> dict[str, Any]:
    now = time.time()
    if _CACHE["value"] and now - _CACHE["at"] < 10:
        return _CACHE["value"]
    root = prompts_dir()
    files: list[dict[str, Any]] = []
    if root.exists():
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix in {".py", ".md", ".json", ".txt"} and "__pycache__" not in str(p):
                fh = _hash_file(p)
                files.append({
                    "path": str(p.relative_to(root)),
                    "hash": fh,
                    "bytes": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                })
    corpus = hashlib.sha256("".join(f"{f['path']}:{f['hash']}\n" for f in files).encode()).hexdigest()[:12]
    # per-receipt prompt_id distribution
    dist: dict[str, int] = {}
    for r in receipts.turns(days=30, limit=5000):
        pid = (r.get("extra") or {}).get("prompt_id")
        if pid:
            dist[str(pid)] = dist.get(str(pid), 0) + 1
    value = {
        "dir": str(root),
        "available": root.exists(),
        "corpus_hash": corpus,
        "files": files,
        "turn_distribution": dist,
    }
    _CACHE.update(at=now, value=value)
    return value
