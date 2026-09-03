"""Bounded workspace scan for the initial context build.

All three cold-start workspace walks (repo map, chunk index sync, convention
scan) shared the same failure mode: an unbounded rglob/os.walk that can visit
every node of a huge tree (the desktop fork alone is 40k+ files). This module
pins the scan budget so a cold start is always bounded and can report WHY it
truncated (surfaced as a ``runtime.degraded`` receipt by the callers).

Budget (all enforced together, first-hit wins; every number is an
env getter read per construction -- PULSEAI_SCAN_MAX_SECONDS,
PULSEAI_SCAN_MAX_FILES, PULSEAI_SCAN_MAX_BYTES, PULSEAI_SCAN_MAX_FILE_BYTES,
PULSEAI_SCAN_MAX_ENTRIES, PULSEAI_SCAN_MAX_VISITED):
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
import threading
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

# ---------------------------------------------------------------------------
# Zero-hardcoding seam: every scan ceiling is an env getter, read PER CALL
# (per ContextBudget/ScanLimits construction), never captured at import.
# Hermes pattern (tools/file_tools.py::_get_max_read_chars): a configured
# accessor with a built-in fallback — the number never lives in logic. The
# owner's 40k-file desktop fork is the standing counter-example to baking
# 1,000-file ceilings into product code: raise the env, restart nothing —
# the next turn reads the new values.
# ---------------------------------------------------------------------------

def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return default
        value = int(str(raw).strip())
    except Exception:
        return default
    return max(lo, min(hi, value))


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return default
        value = float(str(raw).strip())
    except Exception:
        return default
    return max(lo, min(hi, value))


def default_scan_limits() -> "ScanLimits":
    """Build the product-default scan ceiling from the environment, per call.

    Knobs (all optional, all clamped):
      PULSEAI_SCAN_MAX_SECONDS    wall-clock cap      (default 5.0,  0.5 .. 120)
      PULSEAI_SCAN_MAX_FILES      files consumed      (default 1000, 1 .. 200_000)
      PULSEAI_SCAN_MAX_BYTES      aggregate bytes     (default 16 MiB, 64 KiB .. 1 GiB)
      PULSEAI_SCAN_MAX_FILE_BYTES per-file cap        (default 1 MiB, 1 KiB .. 64 MiB)
      PULSEAI_SCAN_MAX_ENTRIES    entries considered  (default 1000, 1 .. 500_000)
      PULSEAI_SCAN_MAX_VISITED    entries visited     (default 1000, 1 .. 500_000)
    """
    return ScanLimits(
        max_files=_env_int("PULSEAI_SCAN_MAX_FILES", 1000, 1, 200_000),
        max_bytes=_env_int("PULSEAI_SCAN_MAX_BYTES", 16 * 1024 * 1024, 65_536, 1_073_741_824),
        max_file_bytes=_env_int("PULSEAI_SCAN_MAX_FILE_BYTES", 1024 * 1024, 1_024, 67_108_864),
        max_elapsed=_env_float("PULSEAI_SCAN_MAX_SECONDS", 5.0, 0.5, 120.0),
        max_considered=_env_int("PULSEAI_SCAN_MAX_ENTRIES", 1000, 1, 500_000),
        max_visited=_env_int("PULSEAI_SCAN_MAX_VISITED", 1000, 1, 500_000),
    )


@dataclass(frozen=True)
class ScanLimits:
    max_files: int = 1000
    max_bytes: int = 16 * 1024 * 1024
    max_file_bytes: int = 1024 * 1024
    max_elapsed: float = 5.0
    # P1-fix: caps on ENTRIES EXAMINED, not only files yielded. A tree full of
    # unsupported/ignored/binary files must stop at these caps instead of
    # walking the complete tree while report.files stays zero.
    max_considered: int = 1000   # file entries examined (consumed + skipped)
    max_visited: int = 1000      # every entry examined (dirs + files)
    skip_symlinks: bool = True


@dataclass
class ScanReport:
    visited: int = 0            # entries examined (dirs + files)
    entries_requested: int = 0  # directory entries actually pulled from the OS
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
class ReadReservation:
    """One granted slice of the shared physical-read ledger.

    The caller must read NO MORE than ``reserved`` bytes and then call
    ``settle_read`` (success — actual bytes, clamped to the reservation) or
    ``refund_read`` (open/read failure). A reservation that is neither
    settled nor refunded leaks its allowance forever.
    """

    reserved: int = 0


@dataclass
class _SharedState:
    """ONE state shared by every slice of a single context preparation.

    Deadline, cancellation, the physical-read ledger, considered counts,
    skip/error aggregates, truncation, and degraded-receipt emission all live
    here — slices reference THIS object, never copies, so no counter can be
    double-spent and exactly one receipt fires per build.

    ``lock`` guards every shared mutation (ledger reservation/settlement,
    cancellation, aggregation, truncation, component summaries, receipt
    claim): concurrent consumers — the engine build and the file watcher can
    overlap in time — must never race past the byte cap or double-emit.
    """

    start: float
    lock: threading.RLock = field(default_factory=threading.RLock)
    cancelled: bool = False
    extra_stop: Callable[[], bool] | None = None
    considered_files: int = 0     # file entries examined (all walkers)
    read_files: int = 0           # successful PHYSICAL content reads downstream
    read_bytes: int = 0           # bytes ACTUALLY read downstream (settled)
    read_reserved: int = 0        # outstanding (unsettled) reservations
    skipped_dirs: int = 0
    skipped_hidden: int = 0
    skipped_symlinks: int = 0
    skipped_oversize: int = 0
    skipped_ext: int = 0
    skipped_binary: int = 0
    skipped_generated: int = 0
    skipped_gitignore: int = 0
    truncated: bool = False
    reason: str | None = None
    degraded_emitted: bool = False
    collect_receipts: bool = False   # engine build: record, don't emit
    components: dict = field(default_factory=dict)


class ContextBudget:
    """ONE shared deadline and ledger for a single context preparation.

    The default synchronous budget covers the COMPLETE pipeline — scan, read,
    chunk, index, embed — not just directory traversal. Every consumer derives
    its ``ScanLimits`` and stop predicate from this object, so once any stage
    exhausts the budget the remaining stages stop too.

    ``share(n)`` carves a FAIR per-walker candidate quota (``cap // n``, so
    zero-size slices mean zero allowance and the combined allowance can never
    exceed the parent cap), but every slice references the SAME shared state:
    deadline, cancellation, physical reads/bytes, considered entries, skip
    counts, truncation, and degraded-receipt emission.
    """

    def __init__(
        self,
        max_elapsed: float | None = None,
        max_files: int | None = None,
        max_bytes: int | None = None,
        max_file_bytes: int | None = None,
        max_considered: int | None = None,
        max_visited: int | None = None,
        allow_embedding_compute: bool = False,
    ):
        # Zero-hardcoding: every ceiling unresolved by the caller is read from
        # the environment HERE, per construction (a fresh pool per turn means
        # a fresh env read per turn). Explicit arguments always win — callers
        # that pass values (tests, unbounded(), share()) are untouched.
        env = default_scan_limits()
        self.max_elapsed = env.max_elapsed if max_elapsed is None else max_elapsed
        self.max_files = env.max_files if max_files is None else max_files
        self.max_bytes = env.max_bytes if max_bytes is None else max_bytes
        self.max_file_bytes = env.max_file_bytes if max_file_bytes is None else max_file_bytes
        self.max_considered = env.max_considered if max_considered is None else max_considered
        self.max_visited = env.max_visited if max_visited is None else max_visited
        # Explicit inference policy: production/default/turn/watcher budgets
        # are cache-only for embeddings. ONLY ``unbounded()`` (the explicit
        # offline maintenance rebuild) may set this True. ``max_elapsed``
        # being 0 does NOT imply compute permission — that is inferred from
        # this flag alone.
        self.allow_embedding_compute = allow_embedding_compute
        self._shared = _SharedState(start=time.perf_counter())
        # The PHYSICAL-read ledger cap is the pipeline cap, never a slice
        # quota — every consumer reserves against the GLOBAL allowance.
        self._ledger_bytes_cap = self.max_bytes
        # Per-walker candidate quotas (a pool's quotas ARE the pipeline caps).
        self._quota_files = self.max_files
        self._quota_bytes = self.max_bytes
        self._quota_considered = self.max_considered
        self._quota_visited = self.max_visited
        # This budget's own consumption of its quota.
        self.consumed_files = 0
        self.consumed_bytes = 0
        self.consumed_considered = 0
        self.consumed_visited = 0

    @classmethod
    def unbounded(cls) -> "ContextBudget":
        """No deadlines and INFERENCE PERMITTED — for EXPLICIT OFFLINE / MANUAL
        maintenance only (the full delete+rebuild ``index_workspace``). This
        is the ONLY constructor that sets ``allow_embedding_compute``; product
        runtime paths (turns, watcher, poll, per-turn sync, search) must never
        use it, and no automatic path may invoke it. It is the one place
        synchronous embedding is legitimate (never an abandoned thread)."""
        return cls(
            max_elapsed=0, max_files=2**31, max_bytes=0,
            max_file_bytes=0, max_considered=2**31, max_visited=2**31,
            allow_embedding_compute=True,
        )

    # -- shared state accessors -------------------------------------------------

    @property
    def _start(self) -> float:
        return self._shared.start

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self._shared.start

    @property
    def remaining(self) -> float:
        if self.max_elapsed <= 0:
            return float("inf")
        return max(0.0, self.max_elapsed - self.elapsed)

    @property
    def expired(self) -> bool:
        return (
            self._shared.cancelled
            or (self.max_elapsed > 0 and self.elapsed >= self.max_elapsed)
        )

    @property
    def cancelled(self) -> bool:
        return self._shared.cancelled

    @cancelled.setter
    def cancelled(self, value: bool) -> None:
        with self._shared.lock:
            self._shared.cancelled = bool(value)

    @property
    def extra_stop(self) -> Callable[[], bool] | None:
        return self._shared.extra_stop

    @extra_stop.setter
    def extra_stop(self, value: Callable[[], bool] | None) -> None:
        with self._shared.lock:
            self._shared.extra_stop = value

    @property
    def read_files(self) -> int:
        return self._shared.read_files

    @property
    def read_bytes(self) -> int:
        return self._shared.read_bytes

    @property
    def considered_files(self) -> int:
        return self._shared.considered_files

    @property
    def truncated(self) -> bool:
        return self._shared.truncated

    @property
    def reason(self) -> str | None:
        return self._shared.reason

    @property
    def collect_receipts(self) -> bool:
        return self._shared.collect_receipts

    @collect_receipts.setter
    def collect_receipts(self, value: bool) -> None:
        with self._shared.lock:
            self._shared.collect_receipts = bool(value)

    @property
    def skipped_dirs(self) -> int:
        return self._shared.skipped_dirs

    @property
    def skipped_generated(self) -> int:
        return self._shared.skipped_generated

    @property
    def skipped_gitignore(self) -> int:
        return self._shared.skipped_gitignore

    @property
    def skipped_oversize(self) -> int:
        return self._shared.skipped_oversize

    @property
    def skipped_binary(self) -> int:
        return self._shared.skipped_binary

    # -- budget behaviour ---------------------------------------------------------

    def should_stop(self) -> bool:
        if self.expired:
            return True
        if self._shared.extra_stop is not None:
            try:
                if self._shared.extra_stop():
                    with self._shared.lock:
                        self._shared.cancelled = True
                    return True
            except Exception:
                pass  # a failing hook must never block the pipeline
        return False

    def reserve_read(self, size: int) -> ReadReservation | None:
        """Atomically reserve ``size`` bytes of the shared physical-read
        ledger BEFORE the read happens.

        Returns a ``ReadReservation`` (or ``None`` when the GLOBAL allowance
        is exhausted — the caller must decline, never read past the cap). The
        caller must then read NO MORE than ``reservation.reserved`` bytes and
        settle or refund it. Combined successful reads across ALL consumers
        (a file read by two consumers counts twice) can never exceed
        ``max_bytes``, even when several threads reserve concurrently.
        """
        size = max(0, int(size))
        sh = self._shared
        with sh.lock:
            cap = self._ledger_bytes_cap
            if (
                cap > 0
                and sh.read_bytes + sh.read_reserved + size > cap
            ):
                return None
            sh.read_reserved += size
            return ReadReservation(reserved=size)

    def settle_read(
        self, reservation: ReadReservation, actual_bytes: int
    ) -> None:
        """Record a SUCCESSFUL physical read of ``actual_bytes`` (clamped to
        the reservation: a file that grew after its stat() can never bill
        more than what was reserved). Counts one successful read operation.
        """
        sh = self._shared
        with sh.lock:
            actual = min(max(0, int(actual_bytes)), reservation.reserved)
            sh.read_reserved = max(0, sh.read_reserved - reservation.reserved)
            sh.read_files += 1
            sh.read_bytes += actual

    def refund_read(self, reservation: ReadReservation) -> None:
        """Return an unsettled reservation after an open/read failure — no
        read op and no bytes are counted, and the allowance is restored.
        """
        sh = self._shared
        with sh.lock:
            sh.read_reserved = max(0, sh.read_reserved - reservation.reserved)

    def absorb(self, report: "ScanReport") -> None:
        """Fold ONE bounded scan's consumption into this slice's quota AND the
        shared pipeline state (considered entries, skip counts, truncation)."""
        self.consumed_files += report.files
        self.consumed_bytes += report.bytes
        self.consumed_considered += report.considered
        self.consumed_visited += report.visited
        sh = self._shared
        with sh.lock:
            sh.considered_files += report.considered
            sh.skipped_dirs += report.skipped_dirs
            sh.skipped_hidden += report.skipped_hidden_files
            sh.skipped_symlinks += report.skipped_symlinks
            sh.skipped_oversize += report.skipped_oversize
            sh.skipped_ext += report.skipped_ext
            sh.skipped_binary += report.skipped_binary
            sh.skipped_generated += report.skipped_generated
            sh.skipped_gitignore += report.skipped_gitignore
            if report.truncated:
                sh.truncated = True
                if sh.reason is None:
                    sh.reason = report.reason

    def to_limits(self) -> ScanLimits:
        """Remaining allowance of THIS budget's quota (0 = zero, not unlimited)."""
        return ScanLimits(
            max_files=max(0, self._quota_files - self.consumed_files),
            max_bytes=max(0, self._quota_bytes - self.consumed_bytes),
            max_file_bytes=self.max_file_bytes,
            max_elapsed=self.max_elapsed,
            max_considered=max(0, self._quota_considered - self.consumed_considered),
            max_visited=max(0, self._quota_visited - self.consumed_visited),
        )

    def share(self, n: int) -> "ContextBudget":
        """Carve ONE of ``n`` equal slices of this pool for a single walker.

        Every slice references the SAME shared state (deadline, cancellation,
        physical-read ledger, considered counts, skip aggregates, truncated
        flag, degraded-receipt emission) — nothing is copied. Only the
        per-walker candidate quota is split, by FLOOR division: splitting a
        cap of 1 among 3 walkers yields 0/0/0 (zero allowance = zero work),
        never 1/1/1, and the combined allowance can never exceed the parent
        cap.
        """
        n = max(1, int(n))
        s = ContextBudget(
            max_elapsed=self.max_elapsed,
            max_files=self.max_files // n,
            max_bytes=self.max_bytes // n,
            max_file_bytes=self.max_file_bytes,
            max_considered=self.max_considered // n,
            max_visited=self.max_visited // n,
        )
        s._shared = self._shared
        s._ledger_bytes_cap = self._ledger_bytes_cap
        s._quota_files = s.max_files
        s._quota_bytes = s.max_bytes
        s._quota_considered = s.max_considered
        s._quota_visited = s.max_visited
        # Slice of an inference-enabled pool keeps the policy.
        s.allow_embedding_compute = self.allow_embedding_compute
        return s

    def mark_truncated(self, reason: str) -> None:
        """Record that this preparation's work was cut short (shared flag)."""
        sh = self._shared
        with sh.lock:
            sh.truncated = True
            if sh.reason is None:
                sh.reason = reason

    def record_component(self, name: str, report: "ScanReport") -> None:
        """Nest one walker's truncated scan inside the build-level receipt."""
        sh = self._shared
        with sh.lock:
            sh.components[name] = {
                "files_considered": report.considered,
                "files_read": report.files,
                "bytes_read": report.bytes,
                "truncated": report.truncated,
                "reason": report.reason,
            }

    def component_summaries(self) -> dict:
        sh = self._shared
        with sh.lock:
            return dict(sh.components)

    def emit_degraded(self, payload: dict) -> bool:
        """Emit the structured ``runtime.degraded`` receipt ONCE per build.
        The claim is atomic: concurrent emitters cannot double-fire."""
        sh = self._shared
        with sh.lock:
            if sh.degraded_emitted:
                return False
            sh.degraded_emitted = True
        try:
            from src.dashboard.event_bus import event_bus
            event_bus.emit("runtime.degraded", payload)
        except Exception:
            pass
        return True


def bounded_read_bytes(
    path: Path, budget: ContextBudget | None = None
) -> bytes | None:
    """Read one file through the shared physical-read ledger.

    Reserves the stat size atomically, reads NO MORE than the reservation (a
    file that grew after stat() can never bill past it), settles the ACTUAL
    bytes read on success or refunds on open/read failure. Returns ``None``
    when the file is gone/unreadable or the global allowance is exhausted.
    Every content read in the pipeline goes through this (or
    ``bounded_read_text``), so ``budget.read_bytes`` is the honest total of
    bytes ACTUALLY read and the global cap can never be exceeded — even by
    concurrent consumers.

    ``budget=None`` means NO ledger: the file is read fully and nothing is
    counted (legacy standalone behaviour). Every product runtime path passes
    an explicit budget — the bounded default is constructed by the CALLER
    (e.g. ``ChunkIndex.sync_file``), never silently here.
    """
    if budget is None:
        try:
            return path.read_bytes()
        except OSError:
            return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    reservation = budget.reserve_read(size)
    if reservation is None:
        return None
    try:
        with open(path, "rb") as f:
            data = f.read(reservation.reserved)
    except OSError:
        budget.refund_read(reservation)
        return None
    budget.settle_read(reservation, len(data))
    return data


def bounded_read_text(
    path: Path, budget: ContextBudget | None = None
) -> str | None:
    """``bounded_read_bytes`` decoded as lossy UTF-8 text."""
    data = bounded_read_bytes(path, budget)
    if data is None:
        return None
    return data.decode("utf-8", errors="ignore")


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
