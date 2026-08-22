"""Pulse Reliability Benchmark v1 - deterministic fixture generator.

PR 1C scope: first six tasks (PBR-001 .. PBR-006).

Design constraints:

- Deterministic: same spec always yields byte-identical files and hashes.
- No network, no model calls, no process spawning, no desktop execution.
- Fixtures are generated into an explicitly provided target root - never
  inside the repository. Nothing generated here is committed.
- ASCII-only content (repository convention) and LF line endings on every
  platform (``newline="\\n"`` is passed explicitly when writing).
- Import-safe: no I/O at import time.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TASK_ID = re.compile(r"^PBR-[0-9]{3}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FixtureFile(StrictModel):
    """A single deterministic fixture file (relative posix path + content)."""

    path: str
    content: str

    @field_validator("path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        p = PurePosixPath(value)
        if not value or p.is_absolute() or ".." in p.parts or value.endswith("/") or value.startswith("/"):
            raise ValueError("fixture file path must be a safe relative path")
        return value


class GeneratedTree(StrictModel):
    """A deterministic generated tree (e.g. the 20k-entry workspace)."""

    kind: Literal["large-20k"]
    prefix: str = Field(min_length=1)  # e.g. "entries/e_00001.txt"
    count: int = Field(gt=0, le=50_000)

    @field_validator("prefix")
    @classmethod
    def safe_prefix(cls, value: str) -> str:
        p = PurePosixPath(value)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError("generated prefix must be a safe relative path")
        return value

    def paths(self) -> list[str]:
        return [f"{self.prefix}{i:05d}.txt" for i in range(1, self.count + 1)]

    def content_for(self, path: str) -> str:
        index = int(Path(path).stem.split("_")[-1])
        return f"entry {index:05d} PBR-004 generated fixture entry\n"


class FixtureSpec(StrictModel):
    task_id: str
    root: str = Field(min_length=1)
    description: str = Field(min_length=1)
    git: bool = False
    line_endings: Literal["lf"] = "lf"
    files: tuple[FixtureFile, ...] = ()
    generated: GeneratedTree | None = None

    @field_validator("task_id")
    @classmethod
    def valid_task_id(cls, value: str) -> str:
        if not _TASK_ID.fullmatch(value):
            raise ValueError("task id must match PBR-NNN")
        return value

    @field_validator("root")
    @classmethod
    def safe_root(cls, value: str) -> str:
        p = PurePosixPath(value)
        if p.is_absolute() or ".." in p.parts:
            raise ValueError("fixture root must be a safe relative path")
        return value

    @model_validator(mode="after")
    def needs_content(self) -> "FixtureSpec":
        if not self.files and self.generated is None:
            raise ValueError("fixture spec must declare files or a generated tree")
        return self


class FixtureManifest(StrictModel):
    schema_id: Literal["pulse-benchmark-fixtures/v1"]
    suite_id: Literal["pulse-reliability-v1"]
    version: int = Field(ge=1)
    fixtures: tuple[FixtureSpec, ...]

    @model_validator(mode="after")
    def unique_ordered(self) -> "FixtureManifest":
        ids = [f.task_id for f in self.fixtures]
        if len(ids) != len(set(ids)):
            raise ValueError("fixture task ids must be unique")
        if ids != sorted(ids):
            raise ValueError("fixtures must be ordered by stable task id")
        return self


class FixtureBuild(StrictModel):
    root: str
    entry_count: int = Field(ge=0)
    files: tuple[str, ...]
    hashes: dict[str, str]  # relative path -> sha256 (deterministic)


def load_fixture_manifest(path: str | Path) -> FixtureManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return FixtureManifest.model_validate(payload)


def resolve_files(spec: FixtureSpec) -> dict[str, str]:
    """Return the full deterministic file map for a fixture spec."""
    out: dict[str, str] = {}
    for f in spec.files:
        out[f.path] = f.content
    if spec.generated is not None:
        for path in spec.generated.paths():
            out[path] = spec.generated.content_for(path)
    return dict(sorted(out.items()))


def _safe_join(root: Path, rel: str) -> Path:
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"unsafe relative path in fixture: {rel!r}")
    return root.joinpath(*p.parts)


def hash_tree(root: Path) -> dict[str, str]:
    """Deterministic sha256 map of every file under root (sorted, no dirs)."""
    result: dict[str, str] = {}
    if not root.is_dir():
        return result
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def build_fixture(spec: FixtureSpec, target_root: Path) -> FixtureBuild:
    """Generate a fixture into an explicit target root. Never under the repo."""
    target_root = Path(target_root)
    if not target_root.is_absolute():
        raise ValueError("fixture target root must be an absolute path")
    files = resolve_files(spec)
    for rel, content in files.items():
        dest = _safe_join(target_root, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
    hashes = hash_tree(target_root)
    return FixtureBuild(
        root=str(target_root),
        entry_count=len(hashes),
        files=tuple(sorted(hashes)),
        hashes=hashes,
    )


def load_fixture_manifest_at() -> FixtureManifest:
    """Convenience for tests: locate fixtures.json next to this module."""
    return load_fixture_manifest(Path(__file__).resolve().parent / "fixtures.json")
