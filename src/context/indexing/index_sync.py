"""
Index Synchronization — Workspace Traversal and Incremental Sync
================================================================

Handles workspace directory scanning, file change detection, atomic single-file
indexing, incremental workspace synchronization with ghost pruning, full workspace
rebuilding, import edge extraction, and degraded scan telemetry.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence

from src.context.budgeting.context_budget import ContextBudget, bounded_read_text
from src.context.bounded_scan import scan_files
from src.context.extraction.language_registry import (
    _EXT_JS_FAMILY,
    extract_source_chunks,
    source_extensions,
)
from src.context.extraction.python_extractor import _extract_py_import_edges
from src.context.extraction.treesitter_extractor import (
    extract_go_import_edges,
    extract_java_import_edges,
    extract_js_import_edges,
    extract_rust_import_edges,
)
from src.context.indexing.index_storage import (
    IndexStorage,
    insert_chunks_no_commit,
    remove_file,
)

_SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".tox", ".idea", ".vscode", "generated",
}


def read_source(file_path: Path, budget: ContextBudget | None = None) -> str | None:
    """Read one source file through the shared physical-read ledger."""
    return bounded_read_text(file_path, budget)


def edges_for(
    file_path: Path,
    rel: str,
    workspace: Path,
    budget: ContextBudget | None = None,
    source: str | None = None,
) -> set[str]:
    """Resolved in-repo import targets of one source file."""
    suffix = file_path.suffix.lower()
    if suffix == ".py":
        resolver = _extract_py_import_edges
    elif suffix in _EXT_JS_FAMILY:
        resolver = extract_js_import_edges
    elif suffix == ".go":
        resolver = extract_go_import_edges
    elif suffix == ".rs":
        resolver = extract_rust_import_edges
    elif suffix == ".java":
        resolver = extract_java_import_edges
    else:
        return set()

    if source is None:
        source = read_source(file_path, budget)
    if source is None:
        return set()
    try:
        return resolver(source, Path(rel), workspace)
    except Exception:
        return set()


def iter_source_files(
    workspace: Path,
    budget: ContextBudget | None = None,
) -> tuple[Iterator[Path], Any]:
    """Bounded file discovery for indexable source files."""
    budget = budget or ContextBudget()
    exts = source_extensions()
    return scan_files(
        workspace,
        limits=budget.to_limits(),
        skip_dirs=_SKIP_DIRS,
        extensions=exts,
        should_stop=budget.should_stop,
        priority=True,
        budget=budget,
    )


def emit_degraded_scan(
    report: Any,
    budget: ContextBudget | None = None,
    thread_id_hint: str | None = None,
) -> None:
    """Surface a truncated index walk as a structured runtime.degraded receipt."""
    if report is None or not getattr(report, "truncated", False):
        return
    budget = budget or ContextBudget()
    if getattr(budget, "collect_receipts", False):
        budget.record_component("chunk_index", report)
        return
    budget.emit_degraded({
        "thread_id": thread_id_hint or "unknown",
        "component": "chunk_index",
        "reason": "context scan bounded",
        "error": f"context index scan {report.summarize()}",
        "files_considered": report.considered,
        "files_read": budget.read_files,
        "bytes_read": budget.read_bytes,
        "elapsed_ms": int(budget.elapsed * 1000),
        "skipped_generated": (
            report.skipped_dirs + report.skipped_generated + report.skipped_gitignore
        ),
        "skipped_oversized": report.skipped_oversize,
        "skipped_binary": report.skipped_binary,
        "cancelled": budget.cancelled,
    })


def sync_file(
    storage: IndexStorage,
    workspace: Path,
    file_path: Path,
    budget: ContextBudget | None = None,
    embedder: Any = None,
    ensure_embedder_fn: Optional[Callable[[], None]] = None,
) -> None:
    """Atomic incremental re-index of one file (chunks, FTS, AND import edges)."""
    budget = budget if budget is not None else ContextBudget()
    try:
        st = file_path.stat()
    except OSError:
        return
    mtime = st.st_mtime
    if budget.max_file_bytes > 0 and st.st_size > budget.max_file_bytes:
        return
    if budget.expired:
        return
    source = read_source(file_path, budget)
    if source is None:
        return
    try:
        rel = str(file_path.relative_to(workspace))
    except ValueError:
        rel = str(file_path)

    chunks = extract_source_chunks(file_path, workspace, source)
    edges = edges_for(file_path, rel, workspace, budget, source)
    vec_table = "chunk_vec" if storage.uses_vec else "chunk_vec_fallback"

    with storage._write_lock:
        with storage.conn:
            old_ids = [r[0] for r in storage.conn.execute(
                "SELECT id FROM code_chunks WHERE file_path = ?", (rel,)
            )]
            for cid in old_ids:
                storage.conn.execute(f"DELETE FROM {vec_table} WHERE chunk_id = ?", (cid,))
                storage.conn.execute("DELETE FROM chunk_fts WHERE chunk_id = ?", (cid,))
            storage.conn.execute("DELETE FROM code_chunks WHERE file_path = ?", (rel,))
            insert_chunks_no_commit(
                conn=storage.conn,
                chunks=chunks,
                mtime=mtime,
                uses_vec=storage.uses_vec,
                embedder=embedder,
                budget=budget,
                ensure_embedder_fn=ensure_embedder_fn,
            )
            storage.conn.execute("DELETE FROM import_edges WHERE importer = ?", (rel,))
            for target in edges:
                storage.conn.execute(
                    "INSERT OR IGNORE INTO import_edges (importer, imported) VALUES (?, ?)",
                    (rel, target),
                )


def sync_workspace(
    storage: IndexStorage,
    workspace: Path,
    budget: ContextBudget | None = None,
    embedder: Any = None,
    ensure_embedder_fn: Optional[Callable[[], None]] = None,
    thread_id_hint: str | None = None,
    on_report_fn: Optional[Callable[[Any, ContextBudget], None]] = None,
) -> int:
    """Re-index files whose mtime is newer than what we stored. Returns count."""
    budget = budget if budget is not None else ContextBudget()
    with storage._write_lock:
        force_all = storage._needs_edge_resync
        storage._needs_edge_resync = False
        if force_all:
            print("[ChunkIndex] v2 upgrade: one-time import-edge rebuild start")
        changed = 0
        on_disk: set[str] = set()

        iterator, report = iter_source_files(workspace, budget)
        if on_report_fn is not None:
            on_report_fn(report, budget)

        for fpath in iterator:
            if budget.expired:
                break
            try:
                rel = str(fpath.relative_to(workspace))
            except ValueError:
                rel = str(fpath)
            on_disk.add(rel)
            row = storage.conn.execute(
                "SELECT MAX(modified_time) FROM code_chunks WHERE file_path = ?", (rel,)
            ).fetchone()
            current = fpath.stat().st_mtime
            if force_all or not row or row[0] is None or row[0] < current:
                sync_file(
                    storage=storage,
                    workspace=workspace,
                    file_path=fpath,
                    budget=budget,
                    embedder=embedder,
                    ensure_embedder_fn=ensure_embedder_fn,
                )
                changed += 1
        if force_all:
            print("[ChunkIndex] v2 upgrade: import-edge rebuild done")

        incomplete = (
            budget.expired
            or budget.cancelled
            or (report is not None and report.truncated)
        )
        if not incomplete:
            indexed = {
                r[0] for r in storage.conn.execute(
                    "SELECT DISTINCT file_path FROM code_chunks"
                )
            }
            for ghost in indexed - on_disk:
                changed += storage.remove_file(workspace, workspace / ghost)

        if report is not None:
            budget.absorb(report)
        emit_degraded_scan(report, budget, thread_id_hint)
        return changed


def index_workspace(
    storage: IndexStorage,
    workspace: Path,
    budget: ContextBudget | None = None,
    embedder: Any = None,
    ensure_embedder_fn: Optional[Callable[[], None]] = None,
    thread_id_hint: str | None = None,
    on_report_fn: Optional[Callable[[Any, ContextBudget], None]] = None,
) -> None:
    """Full delete + rebuild of the workspace index."""
    budget = budget if budget is not None else ContextBudget.unbounded()
    with storage._write_lock:
        vec_table = "chunk_vec" if storage.uses_vec else "chunk_vec_fallback"
        storage.conn.execute(f"DELETE FROM {vec_table}")
        storage.conn.execute("DELETE FROM code_chunks")
        storage.conn.execute("DELETE FROM chunk_fts")
        storage.conn.execute("DELETE FROM import_edges")
        storage.conn.commit()

    iterator, report = iter_source_files(workspace, budget)
    if on_report_fn is not None:
        on_report_fn(report, budget)

    for i, fpath in enumerate(iterator):
        if budget.expired:
            break
        try:
            source = read_source(fpath, budget)
            if source is None:
                continue
            chunks = extract_source_chunks(fpath, workspace, source)
            try:
                rel = str(fpath.relative_to(workspace))
            except ValueError:
                rel = str(fpath)
            edges = edges_for(fpath, rel, workspace, budget, source)
            if chunks or edges:
                with storage._write_lock:
                    if chunks:
                        insert_chunks_no_commit(
                            conn=storage.conn,
                            chunks=chunks,
                            mtime=fpath.stat().st_mtime,
                            uses_vec=storage.uses_vec,
                            embedder=embedder,
                            budget=budget,
                            ensure_embedder_fn=ensure_embedder_fn,
                        )
                    for target in edges:
                        storage.conn.execute(
                            "INSERT OR IGNORE INTO import_edges (importer, imported) VALUES (?, ?)",
                            (rel, target),
                        )
        except Exception:
            continue
        if (i + 1) % 25 == 0:
            with storage._write_lock:
                storage.conn.commit()
    with storage._write_lock:
        storage.conn.commit()
    emit_degraded_scan(report, budget, thread_id_hint)


class IndexSynchronizer:
    """Encapsulates workspace scanning, incremental synchronization,
    and full rebuilding for an index storage instance.
    """

    def __init__(
        self,
        workspace: Path,
        storage: IndexStorage,
        embedder: Any = None,
        ensure_embedder_fn: Optional[Callable[[], None]] = None,
    ):
        self.workspace = workspace
        self.storage = storage
        self.embedder = embedder
        self.ensure_embedder_fn = ensure_embedder_fn
        self._last_scan_report = None
        self._last_budget: ContextBudget | None = None
        self.thread_id_hint: str | None = None

    @property
    def last_scan_report(self) -> Any:
        return self._last_scan_report

    @property
    def last_budget(self) -> ContextBudget | None:
        return self._last_budget

    def _on_report(self, report: Any, budget: ContextBudget) -> None:
        self._last_scan_report = report
        self._last_budget = budget

    def iter_source_files(self, budget: ContextBudget | None = None):
        iterator, report = iter_source_files(self.workspace, budget)
        self._on_report(report, budget or ContextBudget())
        return iterator

    def read_source(self, file_path: Path, budget: ContextBudget | None = None) -> str | None:
        return read_source(file_path, budget)

    def edges_for(
        self,
        file_path: Path,
        rel: str,
        budget: ContextBudget | None = None,
        source: str | None = None,
    ) -> set[str]:
        return edges_for(file_path, rel, self.workspace, budget, source)

    def emit_degraded_scan(self, budget: ContextBudget | None = None) -> None:
        emit_degraded_scan(
            self._last_scan_report,
            budget or self._last_budget,
            self.thread_id_hint,
        )

    def sync_file(self, file_path: Path, budget: ContextBudget | None = None) -> None:
        sync_file(
            storage=self.storage,
            workspace=self.workspace,
            file_path=file_path,
            budget=budget,
            embedder=self.embedder,
            ensure_embedder_fn=self.ensure_embedder_fn,
        )

    def sync_workspace(self, budget: ContextBudget | None = None) -> int:
        return sync_workspace(
            storage=self.storage,
            workspace=self.workspace,
            budget=budget,
            embedder=self.embedder,
            ensure_embedder_fn=self.ensure_embedder_fn,
            thread_id_hint=self.thread_id_hint,
            on_report_fn=self._on_report,
        )

    def index_workspace(self, budget: ContextBudget | None = None) -> None:
        index_workspace(
            storage=self.storage,
            workspace=self.workspace,
            budget=budget,
            embedder=self.embedder,
            ensure_embedder_fn=self.ensure_embedder_fn,
            thread_id_hint=self.thread_id_hint,
            on_report_fn=self._on_report,
        )


__all__ = [
    "_SKIP_DIRS",
    "read_source",
    "edges_for",
    "iter_source_files",
    "emit_degraded_scan",
    "sync_file",
    "sync_workspace",
    "index_workspace",
    "IndexSynchronizer",
]
