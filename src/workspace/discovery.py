"""Phase 2A - bounded, read-only workspace discovery tools.

The engineering engine previously planned from requirement text alone, so it
invented targets (``src/req_001_module.py``) instead of editing the project.
These three operations are the *only* way the engine inspects the workspace
before planning:

* ``workspace.list_files`` - bounded, ignore-aware directory walk.
* ``workspace.read_file``  - bounded text read with binary/size guards.
* ``workspace.search``     - literal, bounded content search.

Design rules:

* Read-only. Nothing here mutates the filesystem, and no operation accepts a
  command string - there is no shell in this module.
* Containment is delegated to the existing, tested
  :class:`src.workspace.path_safety.PathSafetyValidator`; this module adds a
  stricter input rule on top (workspace-relative paths only, no absolute
  paths, no ``..``, no NUL, no drive-relative forms).
* Every call produces a :class:`ToolCall` lifecycle record (identity, status,
  duration, result size, truncation, failure reason) so the orchestrator can
  journal it without parsing result payloads.
* Results are bounded *before* they can reach model context; truncation is
  always reported, never silent.

This is not a second tool registry: the general agent toolset lives in
``src/tools``. This is a narrow, capability-scoped service for the engineering
lifecycle, and it reuses the repository's ignore set and path validator instead
of re-implementing policy.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, List, Optional

from src.workspace.path_safety import PathSafetyValidator, PathSecurityViolation
from src.workspace.access_grants import (
    READ,
    AccessGrantSet,
    WorkspaceAccessGrant,
    WorkspaceAccessRequired,
    canonical_path,
    is_sensitive_external_path,
)

#: The repository's established ignore set (repo map / bounded scan). Reused so
#: discovery, context assembly and the agent toolset agree on what "generated"
#: means. Kept as a local fallback so a future split of that module cannot make
#: discovery silently scan ``node_modules``.
try:  # pragma: no cover - import shape guard
    from src.context.repo_map import IGNORED_DIRS as _REPO_MAP_IGNORED_DIRS
except Exception:  # pragma: no cover - defensive
    _REPO_MAP_IGNORED_DIRS = {
        "__pycache__", ".git", ".venv", "venv", "node_modules",
        ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    }

DEFAULT_IGNORED_DIRS = frozenset(
    {str(name).lower() for name in _REPO_MAP_IGNORED_DIRS}
    | {
        ".crusorai", ".cursor", ".cache", ".next", ".nuxt", ".turbo",
        "coverage", "htmlcov", ".coverage", "target", "out", ".eggs",
    }
)

TOOL_LIST_FILES = "workspace.list_files"
TOOL_READ_FILE = "workspace.read_file"
TOOL_SEARCH = "workspace.search"

WORKSPACE_TOOLS = (TOOL_LIST_FILES, TOOL_READ_FILE, TOOL_SEARCH)

#: Hard ceiling above which a file is refused instead of truncated. Truncating
#: a multi-megabyte blob would still burn the caller's budget for no signal.
MAX_READABLE_FILE_BYTES = 4_000_000
#: Files above this size are skipped by ``search`` (never read whole).
MAX_SEARCHABLE_FILE_BYTES = 1_000_000
#: Bytes inspected for binary detection.
_BINARY_SAMPLE_BYTES = 4096

_TEXT_SUFFIXES = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".kt", ".cs", ".rb", ".php", ".swift",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".m", ".mm",
    ".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".env.example",
    ".md", ".rst", ".txt", ".adoc", ".sql", ".sh", ".ps1", ".bat", ".cmd",
    ".html", ".css", ".scss", ".less", ".xml", ".gradle", ".dockerfile",
})


class WorkspaceBoundaryError(ValueError):
    """A path was rejected by the workspace boundary."""

    code = "path_rejected"


class DiscoveryCancelled(RuntimeError):
    """The turn was cancelled while a discovery tool was running."""

    code = "cancelled"


@dataclass(frozen=True)
class DiscoveryLimits:
    """Hard bounds for every discovery operation."""

    max_depth: int = 8
    max_entries: int = 400
    max_files_scanned: int = 2_000
    max_read_bytes: int = 64_000
    max_read_lines: int = 600
    max_search_results: int = 50
    max_search_excerpt: int = 160
    search_timeout_s: float = 5.0


@dataclass
class ToolCall:
    """Lifecycle record for one read-only tool invocation."""

    tool: str
    call_id: str
    status: str
    started_at: float
    duration_ms: float = 0.0
    result_bytes: int = 0
    truncated: bool = False
    truncated_reason: str = ""
    error: str = ""
    session_id: str = ""
    turn_id: str = ""
    task_id: str = ""
    sequence: int = 0
    event_id: str = ""
    journal_event_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "tool_call_id": self.call_id,
            "event_id": self.event_id,
            "journal_event_id": self.journal_event_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "task_id": self.task_id,
            "sequence": self.sequence,
            "status": self.status,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "result_bytes": self.result_bytes,
            "truncated": self.truncated,
            "truncated_reason": self.truncated_reason,
            "error": self.error,
        }


@dataclass
class ToolResult:
    """A bounded tool result plus its lifecycle record."""

    ok: bool
    data: Dict[str, Any]
    call: ToolCall
    error_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.call.tool,
            "error_code": self.error_code,
            "error": self.call.error,
            "data": self.data,
            "call": self.call.to_dict(),
        }


def _hash_call(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"tc_{digest[:16]}"


def classify_path(path: str) -> str:
    """Role-neutral file kind used for ranking (never for authorization)."""
    pure = PurePosixPath(str(path).replace("\\", "/"))
    name = pure.name.lower()
    suffix = pure.suffix.lower()
    parts = {part.lower() for part in pure.parts[:-1]}
    if parts & {"tests", "test", "__tests__", "spec", "specs", "testcases"}:
        return "test"
    if name.startswith("test_") or name.endswith("_test.py") or ".test." in name or ".spec." in name:
        return "test"
    if suffix in {".md", ".rst", ".adoc"} or "docs" in parts:
        return "documentation"
    if suffix in {".toml", ".yaml", ".yml", ".ini", ".cfg"} or name in {
        "pyproject.toml", "package.json", "tsconfig.json", "pytest.ini",
        "setup.cfg", "makefile", "dockerfile",
    }:
        return "configuration"
    if suffix in _TEXT_SUFFIXES:
        return "source"
    return "other"


def is_probably_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    # A high ratio of non-text bytes in the sample is treated as binary. The
    # NUL check above already covers the common executable/image cases.
    text_bytes = bytes(range(0x20, 0x7F)) + b"\n\r\t\f\b"
    non_text = sum(1 for byte in sample if byte not in text_bytes)
    return non_text / max(1, len(sample)) > 0.30


class WorkspaceDiscovery:
    """The three read-only engineering capabilities, bounded and auditable."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        limits: Optional[DiscoveryLimits] = None,
        ignored_dirs: Optional[Iterable[str]] = None,
        session_id: str = "",
        turn_id: str = "",
        task_id: str = "",
        cancellation_checker: Optional[Callable[[], bool]] = None,
        on_event: Optional[Callable[[ToolCall, Dict[str, Any]], None]] = None,
        clock: Callable[[], float] = time.monotonic,
        access_grants: Optional[AccessGrantSet] = None,
    ) -> None:
        root = Path(workspace_root)
        if not str(workspace_root or "").strip():
            raise WorkspaceBoundaryError("workspace root is required")
        if not root.exists():
            raise WorkspaceBoundaryError(f"workspace root does not exist: {root}")
        self.root = PathSafetyValidator.canonical_path(root)
        #: Phase 2D: human grants for exact paths outside the workspace.
        #: Read-only for now: mutations outside the workspace still fail at the
        #: broker boundary.
        self.access_grants = access_grants or AccessGrantSet()
        self.limits = limits or DiscoveryLimits()
        self.ignored_dirs = frozenset(
            str(name).lower() for name in (ignored_dirs or DEFAULT_IGNORED_DIRS)
        )
        self.session_id = str(session_id or "")
        self.turn_id = str(turn_id or "")
        self.task_id = str(task_id or "")
        self._cancelled = cancellation_checker
        self._on_event = on_event
        self._clock = clock
        self.records: List[ToolCall] = []
        self._sequence = 0

    # -- public API --------------------------------------------------------

    def call(self, tool: str, **kwargs: Any) -> ToolResult:
        """Dispatch by tool name (whitelist only)."""
        if tool == TOOL_LIST_FILES:
            return self.list_files(**kwargs)
        if tool == TOOL_READ_FILE:
            return self.read_file(**kwargs)
        if tool == TOOL_SEARCH:
            return self.search(**kwargs)
        started = self._clock()
        return self._reject(
            tool, started, "unknown_tool", f"unknown workspace tool: {tool!r}"
        )

    def list_files(
        self,
        path: str = ".",
        *,
        max_depth: Optional[int] = None,
        max_entries: Optional[int] = None,
    ) -> ToolResult:
        started = self._clock()
        depth_limit = max(0, int(max_depth if max_depth is not None else self.limits.max_depth))
        entry_limit = max(1, int(max_entries if max_entries is not None else self.limits.max_entries))
        try:
            base = self._resolve(path, must_exist=True)
        except WorkspaceAccessRequired as exc:
            return self._needs_access(TOOL_LIST_FILES, started, exc)
        except WorkspaceBoundaryError as exc:
            return self._reject(TOOL_LIST_FILES, started, exc.code, str(exc))
        if not base.is_dir():
            return self._reject(
                TOOL_LIST_FILES, started, "not_a_directory", f"not a directory: {path}"
            )

        entries: List[Dict[str, Any]] = []
        skipped_ignored = 0
        skipped_symlinks = 0
        skipped_unreadable = 0
        visited_dirs = 0
        truncated = False
        truncated_reason = ""
        try:
            for current, dirnames, filenames, depth in self._walk(base, depth_limit):
                self._check_cancelled(TOOL_LIST_FILES, started)
                visited_dirs += 1
                kept_dirs: List[str] = []
                for name in sorted(dirnames):
                    lowered = name.lower()
                    if lowered in self.ignored_dirs or lowered.startswith("."):
                        skipped_ignored += 1
                        continue
                    candidate = current / name
                    if candidate.is_symlink():
                        skipped_symlinks += 1
                        continue
                    kept_dirs.append(name)
                dirnames[:] = kept_dirs
                for name in sorted(filenames):
                    candidate = current / name
                    if candidate.is_symlink():
                        skipped_symlinks += 1
                        continue
                    try:
                        stat = candidate.stat()
                    except OSError:
                        skipped_unreadable += 1
                        continue
                    rel = self._relative(candidate)
                    entries.append({
                        "path": rel,
                        "kind": classify_path(rel),
                        "size": int(stat.st_size),
                        "depth": depth,
                    })
                    if len(entries) >= entry_limit:
                        truncated = True
                        truncated_reason = "max_entries"
                        break
                if truncated:
                    break
        except DiscoveryCancelled as exc:
            return self._finish(
                TOOL_LIST_FILES, started, "cancelled",
                {
                    "entries": entries,
                    "count": len(entries),
                    "truncated": True,
                    "truncated_reason": "cancelled",
                },
                truncated=True, truncated_reason="cancelled", error=str(exc), code="cancelled",
            )
        except OSError as exc:
            return self._reject(TOOL_LIST_FILES, started, "io_error", str(exc))

        entries.sort(key=lambda item: (item["path"].count("/"), item["path"]))
        data = {
            "root": str(self.root),
            "path": self._relative(base) or ".",
            "entries": entries,
            "count": len(entries),
            "truncated": truncated,
            "truncated_reason": truncated_reason,
            "depth_limit": depth_limit,
            "entry_limit": entry_limit,
            "visited_dirs": visited_dirs,
            "skipped_ignored": skipped_ignored,
            "skipped_symlinks": skipped_symlinks,
            "skipped_unreadable": skipped_unreadable,
        }
        return self._finish(
            TOOL_LIST_FILES, started, "ok", data,
            truncated=truncated, truncated_reason=truncated_reason,
        )

    def read_file(
        self,
        path: str,
        *,
        max_bytes: Optional[int] = None,
        max_lines: Optional[int] = None,
    ) -> ToolResult:
        started = self._clock()
        byte_limit = max(1, int(max_bytes if max_bytes is not None else self.limits.max_read_bytes))
        line_limit = max(1, int(max_lines if max_lines is not None else self.limits.max_read_lines))
        try:
            target = self._resolve(path, must_exist=True, consume_external=True)
        except WorkspaceAccessRequired as exc:
            return self._needs_access(TOOL_READ_FILE, started, exc)
        except WorkspaceBoundaryError as exc:
            return self._reject(TOOL_READ_FILE, started, exc.code, str(exc))
        if target.is_dir():
            return self._reject(
                TOOL_READ_FILE, started, "is_directory", f"is a directory: {path}"
            )
        try:
            total_bytes = target.stat().st_size
        except OSError as exc:
            return self._reject(TOOL_READ_FILE, started, "io_error", str(exc))
        if total_bytes > MAX_READABLE_FILE_BYTES:
            return self._reject(
                TOOL_READ_FILE, started, "file_too_large",
                f"file is {total_bytes} bytes; limit is {MAX_READABLE_FILE_BYTES}",
            )
        try:
            with open(target, "rb") as handle:
                sample = handle.read(_BINARY_SAMPLE_BYTES)
                if is_probably_binary(sample):
                    return self._reject(
                        TOOL_READ_FILE, started, "binary_file",
                        f"refusing to read binary file: {path}",
                    )
                handle.seek(0)
                raw = handle.read(byte_limit + 1)
                truncated_bytes = len(raw) > byte_limit
                if truncated_bytes:
                    raw = raw[:byte_limit]
        except OSError as exc:
            return self._reject(TOOL_READ_FILE, started, "io_error", str(exc))

        encoding = "utf-8"
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
            encoding = "utf-8-replaced"
        if text.startswith("\ufeff"):
            text = text[1:]

        lines = text.splitlines()
        truncated_lines = len(lines) > line_limit
        kept_lines = lines[:line_limit] if truncated_lines else lines
        if truncated_bytes or truncated_lines:
            # A bounded read may cut mid-line; render exactly the lines kept.
            text = "\n".join(kept_lines)
        truncated = truncated_bytes or truncated_lines
        reason = "max_bytes" if truncated_bytes else ("max_lines" if truncated_lines else "")

        data = {
            "path": self._relative(target),
            "content": text,
            "encoding": encoding,
            "bytes_read": len(raw),
            "total_bytes": total_bytes,
            "lines_returned": len(kept_lines),
            "truncated": truncated,
            "truncated_reason": reason,
        }
        return self._finish(
            TOOL_READ_FILE, started, "ok", data,
            truncated=truncated, truncated_reason=reason,
        )

    def search(
        self,
        query: str,
        *,
        path: str = ".",
        max_results: Optional[int] = None,
        case_sensitive: bool = False,
        max_files: Optional[int] = None,
        timeout_s: Optional[float] = None,
    ) -> ToolResult:
        started = self._clock()
        term = str(query or "")
        if not term.strip():
            return self._reject(TOOL_SEARCH, started, "invalid_query", "query is required")
        if len(term) > 200:
            return self._reject(TOOL_SEARCH, started, "invalid_query", "query exceeds 200 characters")
        result_limit = max(1, int(max_results if max_results is not None else self.limits.max_search_results))
        file_limit = max(1, int(max_files if max_files is not None else self.limits.max_files_scanned))
        deadline_s = float(timeout_s if timeout_s is not None else self.limits.search_timeout_s)
        deadline = started + max(0.001, deadline_s)
        pattern = re.compile(re.escape(term), 0 if case_sensitive else re.IGNORECASE)

        try:
            base = self._resolve(path, must_exist=True)
        except WorkspaceAccessRequired as exc:
            return self._needs_access(TOOL_SEARCH, started, exc)
        except WorkspaceBoundaryError as exc:
            return self._reject(TOOL_SEARCH, started, exc.code, str(exc))
        if not base.is_dir():
            return self._reject(TOOL_SEARCH, started, "not_a_directory", f"not a directory: {path}")

        matches: List[Dict[str, Any]] = []
        files_scanned = 0
        files_skipped = 0
        truncated = False
        truncated_reason = ""
        try:
            for current, dirnames, filenames, _depth in self._walk(base, self.limits.max_depth):
                self._check_cancelled(TOOL_SEARCH, started)
                dirnames[:] = [
                    name for name in sorted(dirnames)
                    if name.lower() not in self.ignored_dirs and not name.startswith(".")
                    and not (current / name).is_symlink()
                ]
                for name in sorted(filenames):
                    if files_scanned >= file_limit:
                        truncated, truncated_reason = True, "max_files"
                        break
                    if self._clock() > deadline:
                        truncated, truncated_reason = True, "timeout"
                        break
                    candidate = current / name
                    if candidate.is_symlink():
                        files_skipped += 1
                        continue
                    try:
                        if candidate.stat().st_size > MAX_SEARCHABLE_FILE_BYTES:
                            files_skipped += 1
                            continue
                        with open(candidate, "rb") as handle:
                            sample = handle.read(_BINARY_SAMPLE_BYTES)
                            if is_probably_binary(sample):
                                files_skipped += 1
                                continue
                            handle.seek(0)
                            body = handle.read()
                    except OSError:
                        files_skipped += 1
                        continue
                    files_scanned += 1
                    text = body.decode("utf-8", errors="replace")
                    for number, line in enumerate(text.splitlines(), start=1):
                        found = pattern.search(line)
                        if not found:
                            continue
                        matches.append({
                            "path": self._relative(candidate),
                            "line": number,
                            "column": found.start() + 1,
                            "excerpt": line.strip()[: self.limits.max_search_excerpt],
                        })
                        if len(matches) >= result_limit:
                            truncated, truncated_reason = True, "max_results"
                            break
                    if truncated:
                        break
                if truncated:
                    break
        except DiscoveryCancelled as exc:
            return self._finish(
                TOOL_SEARCH, started, "cancelled",
                {
                    "query": term,
                    "matches": matches,
                    "count": len(matches),
                    "truncated": True,
                    "truncated_reason": "cancelled",
                },
                truncated=True, truncated_reason="cancelled", error=str(exc), code="cancelled",
            )
        except OSError as exc:
            return self._reject(TOOL_SEARCH, started, "io_error", str(exc))

        data = {
            "query": term,
            "matches": matches,
            "count": len(matches),
            "truncated": truncated,
            "truncated_reason": truncated_reason,
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "result_limit": result_limit,
        }
        return self._finish(
            TOOL_SEARCH, started, "ok", data,
            truncated=truncated, truncated_reason=truncated_reason,
        )

    # -- internals ---------------------------------------------------------

    def _walk(
        self, base: Path, depth_limit: int
    ) -> Iterable[tuple[Path, List[str], List[str], int]]:
        """Deterministic breadth-first walk with a depth bound.

        Yields ``(directory, dirnames, filenames, depth)``. Callers may prune
        ``dirnames`` in place; the walk honours the pruned list.
        Yields the base directory first at depth 0.
        """
        queue: List[tuple[Path, int]] = [(base, 0)]
        while queue:
            current, depth = queue.pop(0)
            try:
                with os.scandir(current) as handle:
                    dirnames = []
                    filenames = []
                    for entry in handle:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                dirnames.append(entry.name)
                            elif entry.is_file(follow_symlinks=False):
                                filenames.append(entry.name)
                        except OSError:
                            continue
            except OSError:
                continue
            yield current, dirnames, filenames, depth
            if depth >= depth_limit:
                continue
            for name in dirnames:
                queue.append((current / name, depth + 1))

    def _resolve(self, raw: str, *, must_exist: bool, consume_external: bool = False) -> Path:
        """Resolve a path, honouring turn-scoped external grants.

        Workspace-relative inputs keep the Phase 2A contract: no ``..``, no
        symlink escape, no NUL. Absolute inputs are allowed when they resolve
        inside the workspace, or when a human grant covers them (Phase 2D).
        A ``..`` path is never an escalation prompt - the orchestrator asks for
        the canonical target before any tool sees it.
        """
        text = str(raw if raw is not None else ".").strip() or "."
        if "\x00" in text:
            raise WorkspaceBoundaryError("path contains a NUL byte")
        normalized = text.replace("\\", "/")
        if normalized.startswith("//"):
            raise WorkspaceBoundaryError("UNC paths are not allowed")
        if re.match(r"^[A-Za-z]:(?![\\/])", normalized):
            raise WorkspaceBoundaryError(f"drive-relative paths are not allowed: {raw!r}")
        absolute = normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:", normalized))
        if absolute:
            candidate = canonical_path(Path(os.path.expanduser(normalized)))
            resolved = (
                candidate if self._inside(candidate)
                else self._external(candidate, READ, consume=consume_external)
            )
        else:
            pure = PurePosixPath(normalized)
            if any(part == ".." for part in pure.parts):
                raise WorkspaceBoundaryError(f"path traversal is not allowed: {raw!r}")
            try:
                resolved = PathSafetyValidator.resolve_and_verify(self.root, normalized)
            except PathSecurityViolation as exc:
                raise WorkspaceBoundaryError(str(exc)) from exc
            except (OSError, RuntimeError) as exc:
                raise WorkspaceBoundaryError(f"path cannot be resolved: {exc}") from exc
        if must_exist and not resolved.exists():
            raise WorkspaceBoundaryError(f"path does not exist: {raw!r}")
        return resolved

    def resolve_external(self, path: str | Path, operation: str = READ) -> Path:
        """Resolve an already-approved external path (absolute, canonicalised)."""
        return self._external(canonical_path(path), operation)

    def _inside(self, path: Path) -> bool:
        try:
            root = os.path.normcase(str(self.root))
            candidate = os.path.normcase(str(path))
        except Exception:  # pragma: no cover - defensive
            return False
        return candidate == root or candidate.startswith(root + os.sep)

    def _external(self, path: Path, operation: str = READ, *, consume: bool = False) -> Path:
        if is_sensitive_external_path(path):
            raise WorkspaceBoundaryError(
                f"sensitive path is not accessible outside the workspace: {path}"
            )
        if not self.access_grants.allows(path, operation):
            raise WorkspaceAccessRequired(str(path), operation, "outside the workspace")
        if consume:
            # A ``once`` grant is spent by one content read, whether or not the
            # read afterwards succeeds. Conservative on purpose.
            self.access_grants.consume(path, operation)
        return path

    def _needs_access(
        self, tool: str, started: float, exc: WorkspaceAccessRequired
    ) -> ToolResult:
        return self._finish(
            tool,
            started,
            "blocked",
            {"path": exc.path, "operation": exc.operation, "reason": exc.reason},
            error=str(exc),
            code="access_required",
        )

    def _relative(self, path: Path) -> str:
        try:
            if not self._inside(path):
                return canonical_path(path).as_posix()
            return PathSafetyValidator.get_relative_normalized(self.root, path)
        except Exception:  # pragma: no cover - defensive
            return str(path)

    def _check_cancelled(self, tool: str, started: float) -> None:
        if self._cancelled is None:
            return
        try:
            cancelled = bool(self._cancelled())
        except Exception:
            cancelled = False
        if cancelled:
            raise DiscoveryCancelled(f"{tool} cancelled before completion")

    def _next_identity(self, tool: str, started: float) -> ToolCall:
        self._sequence += 1
        identity = _hash_call(
            self.task_id, self.turn_id, self.session_id, tool, str(self._sequence)
        )
        call = ToolCall(
            tool=tool,
            call_id=identity,
            status="running",
            started_at=started,
            session_id=self.session_id,
            turn_id=self.turn_id,
            task_id=self.task_id,
            sequence=self._sequence,
            event_id=f"evt_{identity[3:]}",
            journal_event_id=f"jrn_{identity[3:]}",
        )
        return call

    def _finish(
        self,
        tool: str,
        started: float,
        status: str,
        data: Dict[str, Any],
        *,
        truncated: bool = False,
        truncated_reason: str = "",
        error: str = "",
        code: str = "",
    ) -> ToolResult:
        call = self._next_identity(tool, started)
        call.status = status
        call.duration_ms = round(max(0.0, self._clock() - started) * 1000.0, 3)
        call.truncated = bool(truncated)
        call.truncated_reason = truncated_reason
        call.error = error[:500]
        try:
            call.result_bytes = len(json.dumps(data, default=str).encode("utf-8"))
        except Exception:  # pragma: no cover - defensive
            call.result_bytes = 0
        self.records.append(call)
        if self._on_event is not None:
            try:
                self._on_event(call, data)
            except Exception:
                pass
        return ToolResult(
            ok=status == "ok",
            data=data,
            call=call,
            error_code=code or ("" if status == "ok" else status),
        )

    def _reject(self, tool: str, started: float, code: str, message: str) -> ToolResult:
        return self._finish(
            tool, started, "error", {}, error=message, code=code
        )
