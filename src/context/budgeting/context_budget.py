"""
Context Budget — Shared Deadline, Resource Ledger, and Scan Ceilings
=====================================================================

Provides `ContextBudget`, `ScanLimits`, `ScanReport`, `ReadReservation`,
and environment-driven scan limit configuration.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Iterable

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


_SCAN_ENV_VARS = (
    "CRUSORAI_SCAN_MAX_SECONDS", "CRUSORAI_SCAN_MAX_FILES",
    "CRUSORAI_SCAN_MAX_BYTES", "CRUSORAI_SCAN_MAX_FILE_BYTES",
    "CRUSORAI_SCAN_MAX_ENTRIES", "CRUSORAI_SCAN_MAX_VISITED",
)


def scan_budget_source() -> str:
    """'env' when any CRUSORAI_SCAN_* knob is present in the process env,
    else 'defaults'. Boot-log honesty: a bound that silently ignored the
    env is exactly the bug that took a desktop session to find."""
    for name in _SCAN_ENV_VARS:
        raw = os.getenv(name)
        if raw is not None and str(raw).strip():
            return "env"
    return "defaults"


def default_scan_limits() -> "ScanLimits":
    """Build the product-default scan ceiling from the environment, per call.

    Knobs (all optional, all clamped):
      CRUSORAI_SCAN_MAX_SECONDS    wall-clock cap      (default 5.0,  0.5 .. 120)
      CRUSORAI_SCAN_MAX_FILES      files consumed      (default 1000, 1 .. 200_000)
      CRUSORAI_SCAN_MAX_BYTES      aggregate bytes     (default 16 MiB, 64 KiB .. 1 GiB)
      CRUSORAI_SCAN_MAX_FILE_BYTES per-file cap        (default 1 MiB, 1 KiB .. 64 MiB)
      CRUSORAI_SCAN_MAX_ENTRIES    entries considered  (default 1000, 1 .. 500_000)
      CRUSORAI_SCAN_MAX_VISITED    entries visited     (default 1000, 1 .. 500_000)
    """
    return ScanLimits(
        max_files=_env_int("CRUSORAI_SCAN_MAX_FILES", 1000, 1, 200_000),
        max_bytes=_env_int("CRUSORAI_SCAN_MAX_BYTES", 16 * 1024 * 1024, 65_536, 1_073_741_824),
        max_file_bytes=_env_int("CRUSORAI_SCAN_MAX_FILE_BYTES", 1024 * 1024, 1_024, 67_108_864),
        max_elapsed=_env_float("CRUSORAI_SCAN_MAX_SECONDS", 5.0, 0.5, 120.0),
        max_considered=_env_int("CRUSORAI_SCAN_MAX_ENTRIES", 1000, 1, 500_000),
        max_visited=_env_int("CRUSORAI_SCAN_MAX_VISITED", 1000, 1, 500_000),
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


def _priority_key(path: Path, *, root: Path | None = None) -> tuple[int, int, int, str]:
    """Stable rank using a workspace-relative path when a root is available.

    Exact byte size is a poor importance signal: a one-character edit or the
    extra digit in ``module100`` must not reshuffle a bounded context prefix.
    Size *classes* retain the useful distinction between a real source module
    and a tiny stub while relative-path order resolves near-sized peers.
    """
    ranked_path = path
    if root is not None:
        try:
            ranked_path = path.relative_to(root)
        except ValueError:
            ranked_path = path
    testish = bool(
        "test" in (part.lower() for part in ranked_path.parts)
        or ranked_path.name.lower().startswith("test_")
        or ranked_path.name.lower().endswith(("_test", ".test"))
    )
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    # Decimal order of magnitude: 29 B and 33 B are peers; 2,000 B and 6 B
    # are not. This removes byte-level churn without discarding size priority.
    size_class = len(str(size)) - 1 if size > 0 else 0
    depth = len(ranked_path.parts)
    return (int(testish), depth, -size_class, ranked_path.as_posix())


def default_priority(path: Path) -> tuple[int, int, int, str]:
    """Deterministic priority: shallow non-tests, size class, stable path."""
    return _priority_key(path)
