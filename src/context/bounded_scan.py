"""Bounded workspace scan for the initial context build.

All three cold-start workspace walks (repo map, chunk index sync, convention
scan) shared the same failure mode: an unbounded rglob/os.walk that can visit
every node of a huge tree (the desktop fork alone is 40k+ files). This module
pins the scan budget so a cold start is always bounded and can report WHY it
truncated (surfaced as a ``runtime.degraded`` receipt by the callers).

Budget (all enforced together, first-hit wins; every number is an
env getter read per construction -- CRUSORAI_SCAN_MAX_SECONDS,
CRUSORAI_SCAN_MAX_FILES, CRUSORAI_SCAN_MAX_BYTES, CRUSORAI_SCAN_MAX_FILE_BYTES,
CRUSORAI_SCAN_MAX_ENTRIES, CRUSORAI_SCAN_MAX_VISITED):
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
non-test, larger size class, stable relative path) so a truncated build indexes
a bounded ranked set, not an arbitrary filesystem-order prefix.

:class:`ContextBudget` is the ONE shared deadline a context preparation threads
through scan → read → chunk → index → embed; every consumer derives its scan
limits and stop predicate from it, so the whole pipeline (not just traversal)
is capped together.
"""
from __future__ import annotations

import heapq
import os
import re
import threading
import time
from dataclasses import dataclass, field, replace
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

from src.context.budgeting.context_budget import (
    ContextBudget,
    ReadReservation,
    ScanLimits,
    ScanReport,
    _SharedState,
    default_scan_limits,
    scan_budget_source,
    _env_int,
    _env_float,
    _SCAN_ENV_VARS,
    _ELAPSED,
    _FILES,
    _BYTES,
    _STOPPED,
    bounded_read_bytes,
    bounded_read_text,
    default_priority,
    _priority_key,
)


@dataclass(frozen=True)
class _PriorityCandidate:
    """Heap item whose smallest element is the *worst* retained candidate."""

    key: tuple[int, int, int, str]
    path: Path

    def __lt__(self, other: "_PriorityCandidate") -> bool:
        # heapq is a min-heap. Reverse the rank so heap[0] is the candidate to
        # evict when a better path arrives later in filesystem order.
        return self.key > other.key


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

    The root ignore file is a CONTENT read and goes through the shared
    physical-read ledger: it obeys the per-file size cap, counts against the
    global byte allowance, and is skipped safely when oversized, unreadable,
    or declined (a missing ledger means unbounded legacy reads).
    """

    def __init__(
        self, root: str | Path, budget: ContextBudget | None = None
    ) -> None:
        self._rules: list[tuple[re.Pattern, bool, bool, bool]] = []
        path = Path(root) / ".gitignore"
        if not path.is_file():
            return
        if budget is not None:
            # Per-file cap + ledger BEFORE reading: a giant .gitignore must
            # not consume unreported bytes before traversal starts.
            try:
                size = path.stat().st_size
            except OSError:
                return
            if budget.max_file_bytes > 0 and size > budget.max_file_bytes:
                return
            if budget.expired:
                return
            text = bounded_read_text(path, budget)
            if text is None:
                return
            lines = text.splitlines()
        else:
            try:
                lines = path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
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
        budget: ContextBudget | None = None,
    ) -> None:
        self.root = Path(workspace)
        self.limits = limits or default_scan_limits()
        self.skip_dirs = (
            frozenset(skip_dirs) if skip_dirs is not None else SCAN_SKIP_DIRS
        )
        self.extensions = (
            frozenset(extensions) if extensions is not None else None
        )
        self.should_stop = should_stop
        self.priority = priority
        self.budget = budget
        self.report = ScanReport()
        self._gitignore = GitIgnore(self.root, budget)
        self._start = time.perf_counter()
        self._root_resolved = self.root.resolve()
        self._done = False

    # -- internal budget helpers -------------------------------------------------

    def _elapsed_now(self) -> float:
        return time.perf_counter() - self._start

    def _truncate(self, reason: str) -> None:
        self.report.truncated = True
        self.report.reason = reason

    @staticmethod
    def _is_link(path: Path) -> bool:
        """Symlink OR Windows junction / reparse point.

        ``Path.is_symlink()`` alone is NOT sufficient on Windows: directory
        junctions are reparse points that report as regular directories to
        ``os.walk``, so a junction can otherwise silently escape the
        workspace. ``os.path.isjunction`` (3.12+) catches them explicitly;
        older Pythons fall back to the ``FILE_ATTRIBUTE_REPARSE_POINT`` stat
        bit.
        """
        try:
            if path.is_symlink():
                return True
        except OSError:
            return True
        try:
            if os.path.isjunction(path):
                return True
        except AttributeError:
            pass
        try:
            st = os.lstat(path)
            attrs = getattr(st, "st_file_attributes", 0) or 0
            if attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                return True
        except (OSError, AttributeError):
            pass
        return False

    def _within_root(self, path: Path) -> bool:
        """Resolve ``path`` and confirm it stays inside the canonical root.

        Belt-and-braces on Windows (where junction resolution can defeat
        ``is_symlink``-style checks): the resolved target must live under the
        workspace root, so an escape cannot be traversed or read even if a
        reparse-point detection was missed. Cheap relative to the scan itself;
        used only when ``skip_symlinks`` is on.
        """
        try:
            resolved = path.resolve()
            return (
                resolved == self._root_resolved
                or resolved.is_relative_to(self._root_resolved)
            )
        except (OSError, ValueError):
            return False

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
        # P1-fix: cap entries EXAMINED, not only files yielded — a tree full
        # of unsupported/ignored/binary files must stop here instead of
        # walking everything while report.files stays zero.
        if (
            self.limits.max_considered > 0
            and self.report.considered >= self.limits.max_considered
        ):
            if not self.report.truncated:
                self._truncate("considered")
            return True
        if (
            self.limits.max_visited > 0
            and self.report.visited >= self.limits.max_visited
        ):
            if not self.report.truncated:
                self._truncate("visited")
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
        """Incremental scandir traversal: entries are pulled ONE AT A TIME and
        each is counted against the visited/considered caps BEFORE filtering,
        so a flat root with 50,000 unsupported entries stops REQUESTING
        entries at the cap instead of materializing the whole directory first
        (``os.walk`` builds complete dirnames/filenames lists up front). The
        scandir handle is closed the moment the cap is hit, so the OS never
        serves the remaining entries.
        """
        pending: list[Path] = [self.root]
        while pending:
            if self._check_limits():
                return
            dirpath = pending.pop()
            self.report.visited += 1
            try:
                scandir_it = os.scandir(dirpath)
            except OSError:
                continue  # unreadable dir: skip, never fail the scan
            with scandir_it:
                for entry in scandir_it:
                    if self._check_limits():
                        return
                    self.report.visited += 1
                    self.report.entries_requested += 1
                    name = entry.name
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir:
                        if name.startswith(".") or self._is_skip_dir(name):
                            self.report.skipped_dirs += 1
                            continue
                        cand = dirpath / name
                        if self.limits.skip_symlinks and self._is_link(cand):
                            self.report.skipped_symlinks += 1
                            continue
                        if (
                            self.limits.skip_symlinks
                            and os.name == "nt"
                            and not self._within_root(cand)
                        ):
                            self.report.skipped_symlinks += 1
                            continue
                        rel_dir = os.path.relpath(cand, self.root)
                        if rel_dir != "." and self._gitignore.ignored(rel_dir, is_dir=True):
                            self.report.skipped_gitignore += 1
                            continue
                        pending.append(cand)
                        continue
                    # file entry
                    self.report.considered += 1
                    if name.startswith("."):
                        self.report.skipped_hidden_files += 1
                        continue
                    if self._skip_generated_name(name):
                        self.report.skipped_generated += 1
                        continue
                    path = dirpath / name
                    if self.limits.skip_symlinks and self._is_link(path):
                        self.report.skipped_symlinks += 1
                        continue
                    if (
                        self.limits.skip_symlinks
                        and os.name == "nt"
                        and not self._within_root(path)
                    ):
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
        """Select the best bounded prefix, independent of candidate order.

        The old implementation asked ``_iter_direct`` for ``max_files`` and
        sorted only that filesystem-order prefix. A high-priority file arriving
        one entry later could never win, and identical clean checkouts produced
        different context. Here traversal is still bounded by elapsed,
        considered, and visited ceilings, while a worst-first heap retains the
        best ``max_files`` paths from every candidate actually considered.

        No bounded scanner can discover the global lexical best of a directory
        it is forbidden to finish reading. The deterministic guarantee is
        therefore explicit: order-independent over the bounded considered
        window, with truncation receipts preserved when that window itself is
        exhausted.
        """
        output_limit = max(0, int(self.limits.max_files))
        if output_limit == 0:
            self._truncate(_FILES)
            return

        original_limits = self.limits
        # Candidate discovery must not stop merely because the OUTPUT heap is
        # full. It remains bounded by the configured considered/visited/time
        # ceilings. The synthetic candidate-file cap is only a final guard for
        # configurations that disabled one of those entry ceilings.
        candidate_file_cap = max(
            output_limit,
            int(original_limits.max_considered or 0),
            int(original_limits.max_visited or 0),
        )
        candidate_limits = replace(
            original_limits,
            max_files=candidate_file_cap,
            max_bytes=0,
        )

        retained: list[_PriorityCandidate] = []
        candidate_count = 0
        self.limits = candidate_limits
        try:
            for path in self._iter_direct():
                candidate_count += 1
                candidate = _PriorityCandidate(
                    _priority_key(path, root=self.root), path
                )
                if len(retained) < output_limit:
                    heapq.heappush(retained, candidate)
                elif candidate.key < retained[0].key:
                    heapq.heapreplace(retained, candidate)
        finally:
            self.limits = original_limits

        traversal_truncated = self.report.truncated
        traversal_reason = self.report.reason
        # Candidate discovery used _consume only for filtering/size checks.
        # Re-account bytes/files for the selected output, not for every path
        # that competed for a heap slot.
        self.report.files = 0
        self.report.bytes = 0
        self.report.truncated = False
        self.report.reason = None
        self.report.extra["priority_candidates"] = candidate_count
        self.report.extra["priority_retained"] = len(retained)
        self.report.extra["priority_policy"] = "bounded_top_k_v1"

        for candidate in sorted(retained, key=lambda item: item.key):
            if self.should_stop is not None and self.should_stop():
                self._truncate(_STOPPED)
                break
            if (
                self.limits.max_elapsed > 0
                and self._elapsed_now() > self.limits.max_elapsed
            ):
                self._truncate(_ELAPSED)
                break
            if self._consume(candidate.path):
                yield candidate.path
            if self.report.truncated:
                break

        if not self.report.truncated:
            if candidate_count > output_limit:
                self._truncate(_FILES)
            elif traversal_truncated and traversal_reason:
                self._truncate(traversal_reason)

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
    budget: ContextBudget | None = None,
) -> tuple[Iterator[Path], ScanReport]:
    """Convenience wrapper returning ``(iterator, report)``.

    ``budget`` is threaded into the root ``.gitignore`` read so the ignore
    file is metered against the shared physical-read ledger (per-file cap,
    global byte allowance, deadline).
    """
    scan = BoundedScan(
        workspace,
        limits=limits,
        skip_dirs=skip_dirs,
        extensions=extensions,
        should_stop=should_stop,
        priority=priority,
        budget=budget,
    )
    return iter(scan), scan.report
