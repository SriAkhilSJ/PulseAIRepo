"""Bounded workspace scan for the initial context build.

All three cold-start workspace walks (repo map, chunk index sync, convention
scan) shared the same failure mode: an unbounded rglob/os.walk that can visit
every node of a huge tree (the desktop fork alone is 40k+ files). This module
pins the scan budget so a cold start is always bounded and can report WHY it
truncated (surfaced as a ``runtime.degraded`` receipt by the callers).

Budget (all enforced together, first-hit wins):
  - elapsed:  wall-clock cap (default 5.0s)
  - files:    max files consumed (default 1000)
  - bytes:    aggregate size of consumed files, counted via stat() so no
              caller ever reads past the budget (default 16 MiB)
  - max_file: individual files larger than this are skipped (default 1 MiB)
  - symlinks: junctions/symlinks are never followed or consumed
  - exclusions: skip dirs (the repo_map IGNORED_DIRS set) + dot-dirs/dotfiles
              + binary/media/database assets + generated bundles + the root
              ``.gitignore`` (practical subset)
  - stop predicate: polled per entry for turn cancellation

Optional ``priority`` mode orders consumed files deterministic-first (shallow,
non-test, largest first) so a truncated build indexes the most importable
files, not whatever the tree order happened to put last.

:class:`ContextBudget` is the ONE shared deadline a context preparation threads
through scan → read → chunk → index → embed; every consumer derives its scan
limits and stop predicate from it, so the whole pipeline (not just traversal)
is capped together.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Iterable

# Canonical exclusion set (superset of the per-consumer lists so every scan
# skips the same vendored/junk trees on the first descent).
SCAN_SKIP_DIRS = frozenset({
    "__pycache__", ".git", ".svn", ".hg", ".venv", "venv", ".direnv",
    "node_modules", "bower_components", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".nox", ".eggs", ".egg-info", "dist", "build",
    "out", "coverage", "target", ".idea", ".vscode", ".vscode-test",
    "generated", ".next", ".nuxt", ".turbo", ".yarn", ".cache",
    "site-packages",
})

# Binary / media / database / archive assets are never chunked or embedded.
BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff",
    ".svg", ".avif", ".heic", ".psd", ".ai", ".eps",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav", ".flac", ".ogg",
    ".webm", ".m4a", ".aac", ".wmv",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".bin", ".exe", ".dll", ".so", ".dylib", ".class", ".jar", ".war",
    ".a", ".o", ".obj", ".pyd", ".whl", ".wasm", ".node", ".crx",
    ".db", ".sqlite", ".sqlite3", ".mdb", ".parquet", ".avro", ".feather",
    ".dat", ".h5", ".hdf5", ".npz", ".npy",
})

# Generated bundles / intermediate artifacts: excluded even when small.
GENERATED_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".egg", ".map", ".min.css", ".min.js", ".bundle.js",
    ".bundle.css", ".dll", ".pdb",
})
GENERATED_NAME_SUFFIXES = (".min.js", ".min.css", ".bundle.js", ".bundle.css", ".map")

_ELAPSED = "elapsed"
_FILES = "files"
_BYTES = "bytes"
_STOPPED = "stopped"

# Embedding a chunk batch must never start when less than this much of the
# shared initial deadline remains (see ContextBudget / chunk_index).
EMBED_MIN_REMAINING_S = 0.25


@dataclass(frozen=True)
class ScanLimits:
    max_files: int = 1000
    max_bytes: int = 16 * 1024 * 1024
    max_file_bytes: int = 1024 * 1024
    max_elapsed: float = 5.0
    skip_symlinks: bool = True


@dataclass
class ScanReport:
    visited: int = 0            # entries examined (dirs + files)
    files: int = 0              # files consumed (yielded)
    bytes: int = 0              # aggregate stat size of consumed files
    elapsed: float = 0.0
    truncated: bool = False
    reason: str | None = None   # field name that bit, e.g. "files"
    considered: int = 0         # files examined (consumed + skipped)
    skipped_dirs: int = 0
    skipped_hidden_files: int = 0
    skipped_symlinks: int = 0
    skipped_oversize: int = 0
    skipped_ext: int = 0
    skipped_binary: int = 0
    skipped_generated: int = 0
    skipped_gitignore: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def skipped_total(self) -> int:
        return (
            self.skipped_hidden_files + self.skipped_symlinks
            + self.skipped_oversize + self.skipped_ext
            + self.skipped_binary + self.skipped_generated
            + self.skipped_gitignore
        )

    def summarize(self) -> str:
        bits = [
            f"visited={self.visited}",
            f"files={self.files}",
            f"bytes={self.bytes}",
            f"elapsed={self.elapsed:.3f}s",
        ]
        if self.truncated:
            bits.append(f"truncated({self.reason})")
        return "; ".join(bits)


@dataclass
class ContextBudget:
    """ONE shared deadline for a single initial context preparation.

    The default synchronous budget covers the COMPLETE pipeline — scan, read,
    chunk, index, embed — not just directory traversal. Every consumer derives
    its ``ScanLimits`` and stop predicate from this object, so once any stage
    exhausts the budget the remaining stages stop too.
    """

    max_elapsed: float = 5.0
    max_files: int = 1000
    max_bytes: int = 16 * 1024 * 1024
    max_file_bytes: int = 1024 * 1024
    cancelled: bool = False
    read_files: int = 0         # PHYSICAL read operations downstream
    read_bytes: int = 0         # bytes actually read downstream
    # Optional live stop hook (P1): consulted on every should_stop() so a
    # user cancel (turn_controls) halts the whole pipeline — traversal, reads,
    # chunking, indexing — promptly, not just the budget's own limits.
    extra_stop: Callable[[], bool] | None = None

    def __post_init__(self) -> None:
        self._start = time.perf_counter()
        self._degraded_emitted = False
        # P1-fix: ONE shared pool. max_files/max_bytes are the PIPELINE caps;
        # consumed_* accumulate what the walkers have already taken, so
        # to_limits() hands each consumer only the REMAINING allowance. Three
        # walkers can no longer each consume a fresh 1,000-file/16 MiB slice.
        self.consumed_files: int = 0
        self.consumed_bytes: int = 0
        self.considered_files: int = 0

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._start

    @property
    def remaining(self) -> float:
        if self.max_elapsed <= 0:
            return float("inf")
        return max(0.0, self.max_elapsed - self.elapsed)

    @property
    def expired(self) -> bool:
        return self.cancelled or (self.max_elapsed > 0 and self.elapsed >= self.max_elapsed)

    def should_stop(self) -> bool:
        if self.expired:
            return True
        if self.extra_stop is not None:
            try:
                if self.extra_stop():
                    self.cancelled = True
                    return True
            except Exception:
                pass  # a failing hook must never block the pipeline
        return False

    def record_read(self, size: int) -> None:
        """Count ONE physical read of ``size`` bytes.

        Every content-bearing read in the pipeline must call this exactly
        once, so ``read_files``/``read_bytes`` are true physical-read totals
        (a file read by two consumers counts twice; a stat-only walk counts
        zero).
        """
        self.read_files += 1
        self.read_bytes += max(0, int(size))

    def absorb(self, report: "ScanReport") -> None:
        """Fold ONE bounded scan's consumption into the shared pool so the
        next walker sees only the remaining allowance."""
        self.consumed_files += report.files
        self.consumed_bytes += report.bytes
        self.considered_files += report.considered

    def to_limits(self) -> ScanLimits:
        return ScanLimits(
            max_files=max(0, self.max_files - self.consumed_files),
            max_bytes=max(0, self.max_bytes - self.consumed_bytes),
            max_file_bytes=self.max_file_bytes,
            max_elapsed=self.max_elapsed,
        )

    def share(self, n: int) -> "ContextBudget":
        """Carve ONE of ``n`` equal slices of this pool for a single walker.

        Every slice shares the same deadline (``_start``), cancellation hook,
        and session routing, but owns its own file/byte allowance — so three
        walkers get ~cap/3 each (pipeline total <= cap) instead of three
        fresh full caps. Receipts emitted per walker therefore show that
        walker's OWN physical reads, not a cross-walker accumulation.
        """
        slice_budget = ContextBudget(
            max_elapsed=self.max_elapsed,
            max_files=max(1, self.max_files // n),
            max_bytes=max(1, self.max_bytes // n),
            max_file_bytes=self.max_file_bytes,
            cancelled=self.cancelled,
        )
        slice_budget._start = self._start
        slice_budget.extra_stop = self.extra_stop
        return slice_budget

    def emit_degraded(self, payload: dict) -> bool:
        """Emit the structured ``runtime.degraded`` receipt ONCE per build."""
        if self._degraded_emitted:
            return False
        self._degraded_emitted = True
        try:
            from src.dashboard.event_bus import event_bus
            event_bus.emit("runtime.degraded", payload)
        except Exception:
            pass
        return True


def default_priority(path: Path) -> tuple[int, int, int, str]:
    """Deterministic scan priority: shallow non-test files first, larger first."""
    testish = bool(
        "test" in (p.lower() for p in path.parts)
        or path.name.lower().startswith("test_")
        or path.name.lower().endswith(("_test", ".test"))
    )
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    depth = len(path.parts)
    return (testish, depth, -size, path.as_posix())


# ---------------------------------------------------------------------------
# .gitignore support (practical subset: the ROOT .gitignore of the workspace)
# ---------------------------------------------------------------------------


def _glob_to_regex(glob: str) -> re.Pattern:
    """Translate a gitignore glob (``*``, ``?``, ``**``, ``[...]``) to a regex."""
    out: list[str] = []
    i, n = 0, len(glob)
    while i < n:
        c = glob[i]
        if c == "*":
            if i + 1 < n and glob[i + 1] == "*":
                out.append(".*")
                i += 2
                if i < n and glob[i] == "/":
                    i += 1  # "**/" matches zero or more directories
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            end = glob.find("]", i + 1)
            if end == -1:
                out.append("\\[")
                i += 1
            else:
                out.append(glob[i:end + 1])
                i = end + 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("".join(out))


class GitIgnore:
    """Minimal root-.gitignore matcher (no nested files, no parent-required).

    Patterns without a ``/`` match the basename at any depth; anchored ``/``
    patterns match from the workspace root; trailing ``/`` is dir-only;
    ``!`` re-includes. Enough for the common vendored/junk exclusions.
    """

    def __init__(self, root: str | Path) -> None:
        self._rules: list[tuple[re.Pattern, bool, bool, bool]] = []
        path = Path(root) / ".gitignore"
        if not path.is_file():
            return
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            negate = line.startswith("!")
            if negate:
                line = line[1:].lstrip()
            if not line:
                continue
            dir_only = line.endswith("/")
            if dir_only:
                line = line[:-1]
            anchored = line.startswith("/")
            if anchored:
                line = line[1:]
            if not line:
                continue
            self._rules.append((
                _glob_to_regex(line), dir_only, negate, anchored,
            ))

    def ignored(self, rel: str, is_dir: bool) -> bool:
        matched = False
        for rx, dir_only, negate, anchored in self._rules:
            if dir_only and not is_dir:
                continue
            ok = rx.match(rel) if anchored else rx.search(rel)
            if ok:
                matched = not negate
        return matched


class BoundedScan:
    """Single-use bounded iterator over a workspace's file tree.

    Yields :class:`pathlib.Path` until a budget bit or a stop predicate fires.
    ``report`` is populated as you iterate (read it after the loop).
    """

    def __init__(
        self,
        workspace: str | Path,
        *,
        limits: ScanLimits | None = None,
        skip_dirs: Iterable[str] | None = None,
        extensions: set[str] | None = None,
        should_stop: Callable[[], bool] | None = None,
        priority: bool = False,
    ) -> None:
        self.root = Path(workspace)
        self.limits = limits or ScanLimits()
        self.skip_dirs = (
            frozenset(skip_dirs) if skip_dirs is not None else SCAN_SKIP_DIRS
        )
        self.extensions = (
            frozenset(extensions) if extensions is not None else None
        )
        self.should_stop = should_stop
        self.priority = priority
        self.report = ScanReport()
        self._gitignore = GitIgnore(self.root)
        self._start = time.perf_counter()
        self._done = False

    # -- internal budget helpers -------------------------------------------------

    def _elapsed_now(self) -> float:
        return time.perf_counter() - self._start

    def _truncate(self, reason: str) -> None:
        self.report.truncated = True
        self.report.reason = reason

    def _check_limits(self) -> bool:
        """Return True when iteration must stop (already recorded the reason)."""
        if self.should_stop is not None and self.should_stop():
            if not self.report.truncated:
                self._truncate(_STOPPED)
            return True
        if self.limits.max_elapsed > 0 and self._elapsed_now() > self.limits.max_elapsed:
            if not self.report.truncated:
                self._truncate(_ELAPSED)
            return True
        if self.report.files >= self.limits.max_files:
            if not self.report.truncated:
                self._truncate(_FILES)
            return True
        if (self.limits.max_bytes > 0 and self.report.bytes >= self.limits.max_bytes):
            if not self.report.truncated:
                self._truncate(_BYTES)
            return True
        return False

    def _consume(self, path: Path) -> bool:
        """Try to consume ``path``. Returns True when it was yielded."""
        if self.report.files >= self.limits.max_files:
            self._truncate(_FILES)
            return False
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if self.limits.max_file_bytes > 0 and size > self.limits.max_file_bytes:
            self.report.skipped_oversize += 1
            return False
        if self.limits.max_bytes > 0 and self.report.bytes + size > self.limits.max_bytes:
            self._truncate(_BYTES)
            return False
        self.report.files += 1
        self.report.bytes += size
        return True

    def _is_skip_dir(self, name: str) -> bool:
        if name in self.skip_dirs:
            return True
        if name.startswith("out-"):
            return True  # out, out-vscode-min, out-build, ...
        return False

    def _skip_generated_name(self, name: str) -> bool:
        lower = name.lower()
        if lower.endswith(GENERATED_NAME_SUFFIXES):
            return True
        suffix = Path(name).suffix.lower()
        return suffix in GENERATED_SUFFIXES

    def _iter_direct(self) -> Iterator[Path]:
        for dirpath, dirnames, filenames in os.walk(
            self.root, topdown=True, followlinks=False
        ):
            self.report.visited += 1
            if self._check_limits():
                return
            pruned: list[str] = []
            for dirname in dirnames:
                if dirname.startswith(".") or self._is_skip_dir(dirname):
                    self.report.skipped_dirs += 1
                    continue
                if self.limits.skip_symlinks and (self.root / dirpath / dirname).is_symlink():
                    self.report.skipped_symlinks += 1
                    continue
                rel_dir = os.path.relpath(os.path.join(dirpath, dirname), self.root)
                if rel_dir != "." and self._gitignore.ignored(rel_dir, is_dir=True):
                    self.report.skipped_gitignore += 1
                    continue
                pruned.append(dirname)
            dirnames[:] = pruned

            for filename in filenames:
                self.report.considered += 1
                if self._check_limits():
                    return
                if filename.startswith("."):
                    self.report.skipped_hidden_files += 1
                    continue
                if self._skip_generated_name(filename):
                    self.report.skipped_generated += 1
                    continue
                path = Path(dirpath) / filename
                if self.limits.skip_symlinks and path.is_symlink():
                    self.report.skipped_symlinks += 1
                    continue
                if self.extensions is not None and path.suffix.lower() not in self.extensions:
                    if path.suffix.lower() in BINARY_EXTENSIONS:
                        self.report.skipped_binary += 1
                    else:
                        self.report.skipped_ext += 1
                    continue
                if path.suffix.lower() in BINARY_EXTENSIONS:
                    self.report.skipped_binary += 1
                    continue
                rel_file = os.path.relpath(path, self.root)
                if self._gitignore.ignored(rel_file, is_dir=False):
                    self.report.skipped_gitignore += 1
                    continue
                if self._consume(path):
                    yield path

    def _iter_priority(self) -> Iterator[Path]:
        """Collect candidates (bounded), then emit in priority order."""
        candidates: list[Path] = []
        for path in self._iter_direct():
            candidates.append(path)
        if not candidates:
            return
        # Re-yield without recounting the files/bytes budgets (already consumed
        # during collection); only stop/elapsed enforcement applies while
        # emitting the sorted prefix.
        for path in sorted(candidates[: self.limits.max_files], key=default_priority):
            if self.should_stop is not None and self.should_stop():
                if not self.report.truncated:
                    self._truncate(_STOPPED)
                return
            if self.limits.max_elapsed > 0 and self._elapsed_now() > self.limits.max_elapsed:
                if not self.report.truncated:
                    self._truncate(_ELAPSED)
                return
            yield path

    def __iter__(self) -> Iterator[Path]:
        if self._done:
            return
        self._done = True
        iterator = self._iter_priority if self.priority else self._iter_direct
        for path in iterator():
            yield path
        self.report.elapsed = self._elapsed_now()


def scan_files(
    workspace: str | Path,
    *,
    limits: ScanLimits | None = None,
    skip_dirs: Iterable[str] | None = None,
    extensions: set[str] | None = None,
    should_stop: Callable[[], bool] | None = None,
    priority: bool = False,
) -> tuple[Iterator[Path], ScanReport]:
    """Convenience wrapper returning ``(iterator, report)``."""
    scan = BoundedScan(
        workspace,
        limits=limits,
        skip_dirs=skip_dirs,
        extensions=extensions,
        should_stop=should_stop,
        priority=priority,
    )
    return iter(scan), scan.report
