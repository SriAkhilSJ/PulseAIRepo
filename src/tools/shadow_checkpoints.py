# src/tools/shadow_checkpoints.py
"""
Shadow Checkpoints (D31, hermes steal #7)
==========================================

Plain English: before the agent touches your files (write_file, edit_file,
execute_code, run_terminal), we quietly take a snapshot of the whole
workspace. If the agent makes a mess, any earlier state can be restored —
including undoing the undo (a restore snapshots first).

This is transparent infrastructure, NOT a tool — the LLM never sees it.

Design stolen from hermes-agent `tools/checkpoint_manager.py` (receipts in
ARCHITECTURE_REVIEW.md §43), simplified for one transport:

Store layout (single shared store; git's object DB dedupes across projects
and across turns — a second worktree of one repo costs near-zero):

    ~/.crusorai/checkpoints/
        store/                      — bare-ish git repo (shared objects)
            HEAD, config, objects/, refs/crusorai/<hash16>, indexes/<hash16>
            info/exclude            — DEFAULT_EXCLUDES
        .last_gc                    — lazy daily gc idempotency marker

Git isolation (copied from their _git_env, receipts §43):
    GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE redirect every command into
    the store — the user's project NEVER gets a .git it didn't already have.
    GIT_CONFIG_GLOBAL/SYSTEM=/dev/null so user gitconfig (commit.gpgsign,
    hooks, credential helpers) can't break background snapshots or spawn
    pinentry windows mid-session. Identity is forced to "CrusorAI Shadow"
    because with config isolated there IS no user.email to commit with.

Safety rails kept from upstream: master switch + env kill-switch
(CRUSORAI_CHECKPOINTS=off), never-raise anywhere (a broken snapshot must
never break an edit), skip / and ~, lazy git-presence probe, per-turn
dedup (one snapshot per workspace per AI iteration at most), no-change
turns create no commit (diff-index --quiet), oversize files unstaged,
per-project history trimmed to max_snapshots via orphan-restart, plus a
guard hermes does NOT have: restore refuses any commit that is not an
ancestor of THIS project's checkpoint ref (no cross-project bleed).

Kill-switch: CRUSORAI_CHECKPOINTS=off — hooks become instant no-ops.
Test override: CRUSORAI_CHECKPOINT_HOME points the store elsewhere.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

_GIT_TIMEOUT = 30          # hermes HERMES_CHECKPOINT_TIMEOUT default (clamp 10..60)
_MAX_FILES = 50_000        # hermes _MAX_FILES: skip huge directories (bounded walk)
_COMMITTER_NAME = "CrusorAI Shadow"
_COMMITTER_EMAIL = "shadow@crusorai.local"

# Broad, boring excludes — the point is snapshots of YOUR work, not of
# dependency forests and build output. (Trimmed copy of upstream's list:
# hermes checkpoint_manager.py DEFAULT_EXCLUDES.)
DEFAULT_EXCLUDES = [
    # Dependency / build output
    "node_modules/", "dist/", "build/", "target/", "out/", ".next/", ".nuxt/",
    # Caches
    "__pycache__/", "*.pyc", "*.pyo", ".cache/", ".pytest_cache/",
    ".mypy_cache/", ".ruff_cache/", "coverage/", ".coverage",
    # Virtualenvs
    ".venv/", "venv/", "env/",
    # VCS internals (including the user's own .git — we snapshot the
    # working TREE, never the repository database)
    ".git/", ".hg/", ".svn/",
    # Native / compiled
    "*.so", "*.dylib", "*.dll", "*.o", "*.a", "*.class", "*.exe", "*.obj",
    # Our own state (checkpoint store nested inside a workspace must never
    # recursively snapshot itself; langgraph DBs are runtime state)
    ".crusorai/", "*.sqlite", "*.sqlite-shm", "*.sqlite-wal",
    # OS noise
    ".DS_Store", "Thumbs.db",
]

_HASH_RE = re.compile(r"^[0-9a-f]{6,40}$")

# Per-process circuit breaker (owner field run: EVERY terminal command paid
# the same 30s git-add give-up on a tree the snapshot can never cover —
# 30s/turn, forever). After a give-up for a workspace, snapshots are skipped
# for that workspace until the process restarts.
# CRUSORAI_SHADOW_RETRY_AFTER_GIVEUP=1 (read per call) restores retry behavior.
_GAVE_UP_LOCK = threading.Lock()
_GAVE_UP_WORKSPACES: set = set()


def _retry_after_giveup_enabled() -> bool:
    raw = os.environ.get("CRUSORAI_SHADOW_RETRY_AFTER_GIVEUP", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _mark_gave_up(abs_dir: str) -> None:
    with _GAVE_UP_LOCK:
        _GAVE_UP_WORKSPACES.add(abs_dir)


def _gave_up(abs_dir: str) -> bool:
    with _GAVE_UP_LOCK:
        return abs_dir in _GAVE_UP_WORKSPACES


# --------------------------------------------------------------------------
# paths + env
# --------------------------------------------------------------------------

def _normalize_path(path_value: str) -> Path:
    return Path(path_value).expanduser().resolve()


def checkpoint_base() -> Path:
    override = os.environ.get("CRUSORAI_CHECKPOINT_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".crusorai" / "checkpoints"


def _store_path(base: Optional[Path] = None) -> Path:
    return (base or checkpoint_base()) / "store"


def _project_hash(working_dir: str) -> str:
    return hashlib.sha256(
        str(_normalize_path(working_dir)).encode("utf-8")
    ).hexdigest()[:16]


def _ref_name(dir_hash: str) -> str:
    return f"refs/crusorai/{dir_hash}"


def _index_path(store: Path, dir_hash: str) -> Path:
    return store / "indexes" / dir_hash


def _project_meta_path(store: Path, dir_hash: str) -> Path:
    return store / "projects" / f"{dir_hash}.json"


def _git_env(store: Path, working_dir: str, index_file: Optional[Path]) -> dict:
    """Redirect git into the shared store with config fully isolated."""
    env = os.environ.copy()
    env["GIT_DIR"] = str(store)
    env["GIT_WORK_TREE"] = str(_normalize_path(working_dir))
    env.pop("GIT_NAMESPACE", None)
    env.pop("GIT_ALTERNATE_OBJECT_DIRECTORIES", None)
    if index_file is not None:
        env["GIT_INDEX_FILE"] = str(index_file)
    else:
        env.pop("GIT_INDEX_FILE", None)
    # Never inherit user/system gitconfig (gpgsign, hooks, helpers).
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    # With config isolated there is no user.email — force one.
    env["GIT_AUTHOR_NAME"] = _COMMITTER_NAME
    env["GIT_AUTHOR_EMAIL"] = _COMMITTER_EMAIL
    env["GIT_COMMITTER_NAME"] = _COMMITTER_NAME
    env["GIT_COMMITTER_EMAIL"] = _COMMITTER_EMAIL
    return env


def _run_git(
    args: list[str],
    store: Path,
    working_dir: str,
    timeout: int = _GIT_TIMEOUT,
    allowed_returncodes: frozenset[int] = frozenset(),
    index_file: Optional[Path] = None,
    preserve_output: bool = False,
) -> tuple[bool, str, str]:
    """Run git against the shared store. Returns (ok, stdout, stderr)."""
    wd = _normalize_path(working_dir)
    if not wd.is_dir():
        return False, "", f"working directory not found: {wd}"

    kwargs: dict = {}
    if sys.platform == "win32":
        # No console window flash per call on the desktop app (no-op POSIX).
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=_git_env(store, str(wd), index_file),
            cwd=str(wd),
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, "", str(exc)

    ok = result.returncode == 0
    stdout = result.stdout if preserve_output else result.stdout.strip()
    stderr = result.stderr.strip()
    return ok, stdout, stderr


# Directory patterns whose entries may already sit in a legacy store's index.
# Excludes only stop UNTRACKED files from being added; paths snapshotted
# before DEFAULT_EXCLUDES existed stay tracked and keep poisoning every
# `git add -A` (owner run #2: 87s on his IDE-source workspace).
_MIGRATION_DIRS = (
    "node_modules", "dist", "build", "target", "out", ".next", ".nuxt",
    "__pycache__", ".venv", "venv", "env", "coverage",
)


def _ensure_excludes(store: Path) -> None:
    """Keep the store's info/exclude current with DEFAULT_EXCLUDES, and
    migrate a legacy index that predates them.

    Hermes writes the exclude file once at store init AND ships an explicit
    legacy migration (_migrate_legacy_store) for stores from older layouts —
    this is the same two-part discipline: (1) idempotent top-up of the
    exclude file (the owner's checkpoint store predated DEFAULT_EXCLUDES, so
    `git add -A` on his IDE-source workspace spent 87s inside node_modules);
    (2) one-shot eviction of already-tracked migration paths from every
    per-project index, because info/exclude never untracks a file. Best-
    effort: any failure degrades to the old behavior, never crashes.
    """
    exclude = store / "info" / "exclude"
    try:
        if exclude.exists() and "node_modules/" in exclude.read_text(encoding="utf-8"):
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text("\n".join(DEFAULT_EXCLUDES) + "\n", encoding="utf-8")
    except OSError:
        return  # a read-only store degrades to the old behavior, never crashes
    # One-time migration: untrack the poisoned paths in every index.
    indexes_dir = store / "indexes"
    if not indexes_dir.is_dir():
        return
    env = {
        **os.environ,
        "GIT_DIR": str(store),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    for index_file in indexes_dir.iterdir():
        if not index_file.is_file():
            continue
        migrate_env = {**env, "GIT_INDEX_FILE": str(index_file)}
        subprocess.run(
            ["git", "rm", "-r", "--cached", "--quiet", "--ignore-unmatch",
             *_MIGRATION_DIRS],
            capture_output=True, timeout=_GIT_TIMEOUT, env=migrate_env,
            stdin=subprocess.DEVNULL,
        )


def _init_store(store: Path) -> None:
    """Create the shared store once (idempotent)."""
    if (store / "HEAD").exists():
        _ensure_excludes(store)
        return
    store.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", "-q", str(store)],
        capture_output=True,
        timeout=_GIT_TIMEOUT,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        },
        stdin=subprocess.DEVNULL,
    )
    # gc can remove refs/heads on a bare store; git needs the dirs present.
    (store / "refs" / "heads").mkdir(parents=True, exist_ok=True)
    (store / "branches").mkdir(exist_ok=True)
    (store / "indexes").mkdir(exist_ok=True)
    (store / "projects").mkdir(exist_ok=True)
    (store / "info").mkdir(exist_ok=True)
    (store / "info" / "exclude").write_text(
        "\n".join(DEFAULT_EXCLUDES) + "\n", encoding="utf-8"
    )


def _git_timeout() -> int:
    """Per-call snapshot git budget. Env-driven (CRUSORAI_SHADOW_GIT_TIMEOUT_S),
    read every call — the owner run burned 30s per turn here because the add
    budget (2x base) was a fixed constant the user could neither see nor tune."""
    raw = os.environ.get("CRUSORAI_SHADOW_GIT_TIMEOUT_S", "").strip()
    try:
        value = int(raw) if raw else _GIT_TIMEOUT
    except (TypeError, ValueError):
        value = _GIT_TIMEOUT
    # Hermes clamp: max(10, min(v, 60)) — one budget for every git call,
    # no 2x multipliers.
    return max(10, min(value, 60))


def _max_files() -> int:
    """Per-call file-count cap (CRUSORAI_SHADOW_MAX_FILES), read every call.
    Explicit user intent is honored exactly — a silently-overridden knob is
    a lie (clamped only to a positive int)."""
    raw = os.environ.get("CRUSORAI_SHADOW_MAX_FILES", "").strip()
    try:
        value = int(raw) if raw else _MAX_FILES
    except (TypeError, ValueError):
        value = _MAX_FILES
    return max(1, min(value, 5_000_000))


def _dir_file_count(path: Path, bail_at: int) -> int:
    """Count files with early exit (huge trees => skip snapshot, cheaply)."""
    count = 0
    for _dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules",
                                                        "__pycache__", ".venv"}]
        count += len(filenames)
        if count > bail_at:
            return count
    return count


def _touch_project(store: Path, working_dir: str) -> None:
    meta = _project_meta_path(store, _project_hash(working_dir))
    try:
        payload = {"workdir": str(_normalize_path(working_dir))}
        if meta.exists():
            try:
                payload = {**json.loads(meta.read_text(encoding="utf-8")),
                           "workdir": str(_normalize_path(working_dir))}
            except Exception:
                pass
        payload["last_touch"] = time.time()
        payload.setdefault("created_at", payload["last_touch"])
        meta.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # metadata is bookkeeping, never fatal


# --------------------------------------------------------------------------
# manager
# --------------------------------------------------------------------------

class ShadowCheckpoints:
    """Per-process checkpoint manager.

    Call ``new_turn()`` at the start of each AI iteration and
    ``ensure_checkpoint(workspace, reason)`` before any file-mutating
    action. At most one snapshot per workspace per turn; turns with no
    content change create no commit at all.
    """

    def __init__(
        self,
        enabled: Optional[bool] = None,
        max_snapshots: int = 20,
        max_file_size_mb: int = 10,
        base: Optional[Path] = None,
    ):
        if enabled is None:
            enabled = (
                os.environ.get("CRUSORAI_CHECKPOINTS", "").strip().lower()
                != "off"
            )
        self.enabled = enabled
        self.max_snapshots = max(1, int(max_snapshots))
        self.max_file_size_mb = max(0, int(max_file_size_mb))
        self._base = base  # None => checkpoint_base() at use time (env)
        self._done_this_turn: set[str] = set()
        self._git_available: Optional[bool] = None
        self._lock = threading.Lock()
        # Turn-addressable undo (the pane's "Undo turn"). Keyed by the SAME
        # normalized abs_dir as the dedup set, per process on purpose — the
        # store itself is the durable record and a restart re-derives the tip
        # with one rev-parse (latest_checkpoint), so nothing here can drift
        # from the git truth.
        #   _turn_undo  — the FIRST snapshot of the current user turn. `_take`
        #                 walks the tree before the mutation that triggered it,
        #                 so this commit IS the turn's starting state (user's
        #                 own edits included) and is the honest "Undo turn"
        #                 target. None until the turn writes anything.
        #   _last_created — newest snapshot this process took per workspace.
        self._turn_undo: dict[str, Optional[str]] = {}
        self._last_created: dict[str, str] = {}

    # -- turn lifecycle ----------------------------------------------------

    def new_turn(self) -> None:
        """Reset per-turn dedup. Called at the start of each AI iteration.

        Hermes CheckpointManager.new_turn(): dedup reset ONLY — snapshots are
        synchronous, and they are fast because the store's info/exclude keeps
        git out of dependency/build trees (see DEFAULT_EXCLUDES), not because
        of timeline tricks. Never raises.
        """
        self._done_this_turn.clear()

    # -- public API ---------------------------------------------------------

    def ensure_checkpoint(self, working_dir: str, reason: str = "auto") -> bool:
        """Snapshot if enabled/changed/not-done-this-turn. NEVER raises.

        Hermes CheckpointManager.ensure_checkpoint() verbatim shape: enabled
        probe, never root/home, once per directory per turn, synchronous —
        the git walk is bounded by info/exclude + the file-count cap + the
        per-call timeout, not by background machinery.
        """
        if not self.enabled:
            return False
        try:
            with self._lock:
                if self._git_available is None:
                    self._git_available = shutil.which("git") is not None
                if not self._git_available:
                    return False

                abs_dir = str(_normalize_path(working_dir))
                if abs_dir in {"/", str(Path.home())}:
                    return False
                if not _retry_after_giveup_enabled() and _gave_up(abs_dir):
                    return False
                if abs_dir in self._done_this_turn:
                    return False
                self._done_this_turn.add(abs_dir)
                return bool(self._take(abs_dir, reason))
        except Exception:
            return False  # a broken snapshot must never break an edit

    # -- turn-addressable undo (pane "Undo turn") ---------------------------

    def _ref_tip(self, abs_dir: str) -> Optional[str]:
        """Current checkpoint tip for a workspace, or None when there is no
        history. Read-only: never creates the store, never raises."""
        try:
            store = _store_path(self._base)
            if not (store / "HEAD").exists():
                return None
            ok, out, _ = _run_git(
                ["rev-parse", "--verify",
                 _ref_name(_project_hash(abs_dir)) + "^{commit}"],
                store, abs_dir, allowed_returncodes=frozenset({128}),
            )
            return out if ok and out else None
        except Exception:
            return None

    def mark_turn_start(self, working_dir: str) -> None:
        """Open a user turn: clear the workspace's undo slot.

        Called once when a user turn begins, BEFORE any mutation. The slot is
        then filled by the FIRST snapshot the turn takes — the commit `_take`
        creates from the tree as it stands before the first write — which is
        the state "undo this turn" must restore. Clearing (rather than
        recording the old ref tip) is deliberate: the ref tip may predate
        edits the user made by hand between turns, so restoring it would
        silently revert work this turn never touched. Never raises.
        """
        try:
            if not self.enabled:
                return
            abs_dir = str(_normalize_path(working_dir))
            if abs_dir in {"/", str(Path.home())}:
                return
            self._turn_undo[abs_dir] = None
        except Exception:
            return

    def turn_undo_point(self, working_dir: str) -> Optional[str]:
        """The current turn's undo target: its first snapshot, or None when
        the turn has not written anything yet (nothing to undo)."""
        try:
            return self._turn_undo.get(str(_normalize_path(working_dir)))
        except Exception:
            return None

    def latest_checkpoint(self, working_dir: str) -> Optional[str]:
        """Newest snapshot for a workspace: this process's last commit, else
        the ref tip (a restart keeps the answer truthful). Never raises."""
        try:
            abs_dir = str(_normalize_path(working_dir))
            return self._last_created.get(abs_dir) or self._ref_tip(abs_dir)
        except Exception:
            return None

    def list_checkpoints(self, working_dir: str) -> list[dict]:
        """Checkpoints for a directory, most recent first."""
        abs_dir = str(_normalize_path(working_dir))
        store = _store_path(self._base)
        if not (store / "HEAD").exists():
            return []
        ref = _ref_name(_project_hash(abs_dir))
        ok, stdout, _ = _run_git(
            ["log", ref, "--format=%H|%h|%aI|%s", "-n", str(self.max_snapshots)],
            store, abs_dir, allowed_returncodes=frozenset({128, 129}),
        )
        if not ok or not stdout:
            return []
        out: list[dict] = []
        for line in stdout.splitlines():
            parts = line.split("|", 3)
            if len(parts) == 4:
                out.append({
                    "hash": parts[0], "short_hash": parts[1],
                    "timestamp": parts[2], "reason": parts[3],
                })
        return out

    def _validated_restore_target(self, working_dir: str, commit_hash: str):
        """Return (absolute workspace, store, ref tip, error) for a checkpoint.

        The object database is shared across workspaces, so a valid object hash
        is not enough: restore targets must be ancestors of this workspace's
        own shadow-checkpoint ref.
        """
        if not _HASH_RE.match(commit_hash or ""):
            return None, None, None, {"success": False, "error": f"Invalid checkpoint hash: {commit_hash!r}"}
        abs_dir = str(_normalize_path(working_dir))
        store = _store_path(self._base)
        if not (store / "HEAD").exists():
            return None, None, None, {"success": False, "error": "No checkpoints exist for this directory"}
        ok, _, err = _run_git(["cat-file", "-t", commit_hash], store, abs_dir)
        if not ok:
            return None, None, None, {
                "success": False, "error": f"Checkpoint '{commit_hash}' not found", "debug": err or None,
            }
        ref = _ref_name(_project_hash(abs_dir))
        ok_ref, tip, _ = _run_git(
            ["rev-parse", "--verify", ref + "^{commit}"],
            store, abs_dir, allowed_returncodes=frozenset({128}),
        )
        if not (ok_ref and tip):
            return None, None, None, {"success": False, "error": "No checkpoint history for this directory"}
        ok_anc, _, _ = _run_git(["merge-base", "--is-ancestor", commit_hash, tip], store, abs_dir)
        if not ok_anc:
            return None, None, None, {
                "success": False,
                "error": "Checkpoint does not belong to this directory's history",
            }
        return abs_dir, store, tip, None

    def _preview_restore_unlocked(self, working_dir: str, commit_hash: str) -> dict:
        """Compare the snapshot policy's view of the current tree to a target.

        A throwaway index keeps preview read-only: the user's workspace, the
        shared checkpoint index, and the checkpoint ref are never changed.
        """
        abs_dir, store, _tip, error = self._validated_restore_target(working_dir, commit_hash)
        if error:
            return error
        index_file = _index_path(store, _project_hash(abs_dir)).with_name(
            f"{_project_hash(abs_dir)}.preview-{uuid.uuid4().hex}"
        )
        index_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            ok, _, err = _run_git(["read-tree", commit_hash], store, abs_dir, index_file=index_file)
            if not ok:
                return {"success": False, "error": f"Could not prepare checkpoint preview: {err}"}
            ok, _, err = _run_git(
                ["add", "-A"], store, abs_dir, timeout=_git_timeout(), index_file=index_file,
            )
            if not ok:
                return {"success": False, "error": f"Could not scan workspace for checkpoint preview: {err}"}
            if self.max_file_size_mb > 0:
                self._drop_oversize_from_index(store, abs_dir, index_file)
            ok_tree, tree_sha, err = _run_git(
                ["write-tree"], store, abs_dir, index_file=index_file,
            )
            if not ok_tree or not tree_sha:
                return {"success": False, "error": f"Could not fingerprint workspace for checkpoint preview: {err}"}
            ok_diff, raw, err = _run_git(
                ["diff-index", "--cached", "--name-status", "--no-renames", "-z", commit_hash],
                store, abs_dir, allowed_returncodes=frozenset({1}),
                index_file=index_file, preserve_output=True,
            )
            if not ok_diff:
                return {"success": False, "error": f"Could not compare workspace with checkpoint: {err}"}
            fields = raw.split("\x00")
            files: list[dict[str, str]] = []
            for index in range(0, len(fields) - 1, 2):
                status, path = fields[index], fields[index + 1]
                if not status or not path:
                    continue
                code = status[0]
                change = "added" if code == "A" else "deleted" if code == "D" else "modified"
                files.append({
                    "path": path,
                    "change": change,
                    "action": "delete" if change == "added" else "restore",
                })
            fingerprint = hashlib.sha256(
                f"{abs_dir}\0{commit_hash}\0{tree_sha}".encode("utf-8")
            ).hexdigest()
            return {
                "success": True,
                "checkpoint": commit_hash,
                "files": files,
                "changed_paths": len(files),
                "workspace_fingerprint": fingerprint,
                "limitations": [
                    "Ignored, generated/dependency, and oversized files are outside the shadow-checkpoint snapshot policy and are not included in this restore."
                ],
            }
        finally:
            try:
                index_file.unlink(missing_ok=True)
                index_file.with_name(index_file.name + ".lock").unlink(missing_ok=True)
            except OSError:
                pass

    def preview_restore(self, working_dir: str, commit_hash: str) -> dict:
        """Read-only list of workspace paths that a full revert would change."""
        try:
            with self._lock:
                return self._preview_restore_unlocked(working_dir, commit_hash)
        except Exception as exc:
            return {"success": False, "error": f"Checkpoint preview failed: {exc}"}

    def restore_full(
        self,
        working_dir: str,
        commit_hash: str,
        *,
        expected_fingerprint: str | None = None,
    ) -> dict:
        """Restore the complete checkpointed working tree, including removals.

        Unlike the older `restore` API (used by one-file and snapshot-log
        actions), this stages the current checkpointable tree into a temporary
        index before `reset --hard`. That lets Git remove paths added since the
        target while leaving ignored/excluded content outside the checkpoint
        policy untouched. A pre-restore checkpoint is required before any
        destructive workspace change.
        """
        try:
            with self._lock:
                abs_dir, store, _tip, error = self._validated_restore_target(working_dir, commit_hash)
                if error:
                    return error
                preview = self._preview_restore_unlocked(abs_dir, commit_hash)
                if not preview.get("success"):
                    return preview
                if expected_fingerprint and preview.get("workspace_fingerprint") != expected_fingerprint:
                    return {"success": False, "error": "Workspace changed after the preview. Review the affected paths and try again."}

                pre_restore = self._take(abs_dir, f"pre-rollback snapshot (full revert to {commit_hash[:8]})")
                if not pre_restore:
                    # If workspace matches the latest snapshot, latest_checkpoint is our pre_restore!
                    pre_restore = self.latest_checkpoint(abs_dir)
                # _take may advance the per-project ref to the safety snapshot.
                # Seed a private index from that tip, stage the current tree,
                # then reset it to the requested checkpoint. Added paths are
                # in the temporary index and are removed by reset --hard.
                ref = _ref_name(_project_hash(abs_dir))
                ok_tip, current_tip, _ = _run_git(
                    ["rev-parse", "--verify", ref + "^{commit}"],
                    store, abs_dir, allowed_returncodes=frozenset({128}),
                )
                if not (ok_tip and current_tip):
                    current_tip = commit_hash
                index_file = _index_path(store, _project_hash(abs_dir)).with_name(
                    f"{_project_hash(abs_dir)}.restore-{uuid.uuid4().hex}"
                )
                index_file.parent.mkdir(parents=True, exist_ok=True)
                try:
                    ok, _, err = _run_git(["read-tree", current_tip], store, abs_dir, index_file=index_file)
                    if not ok:
                        return {"success": False, "error": f"Could not prepare full restore: {err}"}
                    ok, _, err = _run_git(
                        ["add", "-A"], store, abs_dir, timeout=_git_timeout(), index_file=index_file,
                    )
                    if not ok:
                        return {"success": False, "error": f"Could not stage checkpointable workspace paths: {err}"}
                    if self.max_file_size_mb > 0:
                        self._drop_oversize_from_index(store, abs_dir, index_file)
                    ok, _, err = _run_git(
                        ["reset", "--hard", commit_hash], store, abs_dir,
                        timeout=_git_timeout(), index_file=index_file,
                    )
                    if not ok:
                        compensated = False
                        if pre_restore:
                            ok_restore, _, _ = _run_git(
                                ["reset", "--hard", pre_restore], store, abs_dir,
                                timeout=_git_timeout(), index_file=index_file,
                            )
                            compensated = ok_restore
                        return {
                            "success": False,
                            "error": f"Full restore failed: {err}",
                            "workspace_rollback": "restored" if compensated else "not_confirmed",
                        }
                finally:
                    try:
                        index_file.unlink(missing_ok=True)
                        index_file.with_name(index_file.name + ".lock").unlink(missing_ok=True)
                    except OSError:
                        pass
                return {
                    "success": True,
                    "restored_to": commit_hash[:8],
                    "directory": abs_dir,
                    "pre_restore": pre_restore or None,
                    "files": preview.get("files", []),
                    "workspace_fingerprint": preview.get("workspace_fingerprint"),
                    "limitations": preview.get("limitations", []),
                }
        except Exception as exc:
            return {"success": False, "error": f"Full restore failed: {exc}"}

    def restore(
        self,
        working_dir: str,
        commit_hash: str,
        file_path: Optional[str] = None,
    ) -> dict:
        """Restore `file_path` (or the whole tree with ".") to a checkpoint.

        Takes a pre-rollback snapshot first (undo-the-undo, upstream's
        nicest detail). Overwrite semantics: files CREATED after the
        checkpoint are left in place — restore rewrites content that the
        checkpoint knew about, it does not delete your newer files.
        """
        if not _HASH_RE.match(commit_hash or ""):
            return {"success": False, "error": f"Invalid checkpoint hash: {commit_hash!r}"}
        abs_dir = str(_normalize_path(working_dir))
        store = _store_path(self._base)
        if not (store / "HEAD").exists():
            return {"success": False, "error": "No checkpoints exist for this directory"}

        ok, _, err = _run_git(["cat-file", "-t", commit_hash], store, abs_dir)
        if not ok:
            return {"success": False, "error": f"Checkpoint '{commit_hash}' not found",
                    "debug": err or None}

        # Guard hermes lacks: the commit must belong to THIS project's
        # checkpoint history — the object DB is shared, so a raw cat-file
        # check would happily "restore" project B's snapshot into project A.
        ref = _ref_name(_project_hash(abs_dir))
        ok_ref, tip, _ = _run_git(
            ["rev-parse", "--verify", ref + "^{commit}"],
            store, abs_dir, allowed_returncodes=frozenset({128}),
        )
        if not (ok_ref and tip):
            return {"success": False, "error": "No checkpoint history for this directory"}
        ok_anc, _, _ = _run_git(
            ["merge-base", "--is-ancestor", commit_hash, tip],
            store, abs_dir,
        )
        if not ok_anc:
            return {"success": False,
                    "error": "Checkpoint does not belong to this directory's history"}

        if file_path:
            # No absolute paths / escapes: file_path stays workspace-relative.
            p = Path(file_path)
            if p.is_absolute() or ".." in p.parts:
                return {"success": False, "error": f"Invalid file path: {file_path!r}"}

        # Undo-the-undo: pre-rollback snapshot so a restore is itself
        # reversible. (Bypasses per-turn dedup on purpose.) Its hash rides
        # the result as `pre_restore`, which is what the pane's "Put it back"
        # sends back — a restore that cannot name where it came from is a
        # one-way door with a confirmation dialog bolted on.
        pre_restore = self._take(abs_dir, f"pre-rollback snapshot (restoring to {commit_hash[:8]})")

        index_file = _index_path(store, _project_hash(abs_dir))
        target = file_path if file_path else "."
        ok, _, err = _run_git(
            ["checkout", commit_hash, "--", target],
            store, abs_dir, timeout=_git_timeout(), index_file=index_file,
        )
        if not ok:
            return {"success": False, "error": f"Restore failed: {err}",
                    "debug": err or None}

        result = {"success": True, "restored_to": commit_hash[:8],
                  "directory": abs_dir, "pre_restore": pre_restore or None}
        if file_path:
            result["file"] = file_path
        return result

    # -- internals ----------------------------------------------------------

    def _take(self, working_dir: str, reason: str) -> str:
        """Snapshot now. Returns the new commit oid, or "" when nothing was
        taken (disabled, over cap, no change, git failure). Never raises —
        a broken snapshot must never break an edit."""
        store = _store_path(self._base)
        _init_store(store)
        _touch_project(store, working_dir)
        started = time.monotonic()
        cap = _max_files()

        if _dir_file_count(Path(working_dir), cap) > cap:
            _mark_gave_up(str(_normalize_path(working_dir)))
            print(
                f"[shadow_checkpoint] {working_dir}: skipped — tree over the "
                f"{cap}-file cap (CRUSORAI_SHADOW_MAX_FILES); NO undo point taken; "
                "snapshots are skipped for this workspace until restart "
                "(CRUSORAI_SHADOW_RETRY_AFTER_GIVEUP=1 to retry)",
                flush=True,
            )
            return ""

        dir_hash = _project_hash(working_dir)
        index_file = _index_path(store, dir_hash)
        ref = _ref_name(dir_hash)

        # Seed the per-project index from the last checkpoint so the
        # machinery sees only changes since then.
        ok_ref, ref_commit, _ = _run_git(
            ["rev-parse", "--verify", ref + "^{commit}"],
            store, working_dir, allowed_returncodes=frozenset({128}),
        )
        has_ref = ok_ref and bool(ref_commit)
        if has_ref:
            _run_git(["read-tree", ref_commit], store, working_dir,
                     index_file=index_file, allowed_returncodes=frozenset({128}))
        elif index_file.exists():
            index_file.unlink()
        index_file.parent.mkdir(parents=True, exist_ok=True)

        add_budget = _git_timeout()
        ok, _, _ = _run_git(["add", "-A"], store, working_dir,
                            timeout=add_budget, index_file=index_file)
        if not ok:
            # Owner field proof: this give-up used to be SILENT — the turn
            # burned the whole add budget (30s) every first terminal command
            # and the log said nothing. Name it, and trip the per-process
            # breaker so no later turn re-pays the same hopeless add.
            _mark_gave_up(str(_normalize_path(working_dir)))
            print(
                f"[shadow_checkpoint] {working_dir}: gave up after ~{add_budget}s "
                "on 'git add' — tree too large for the snapshot budget "
                "(CRUSORAI_SHADOW_GIT_TIMEOUT_S); NO undo point taken; "
                "snapshots are skipped for this workspace until restart "
                "(CRUSORAI_SHADOW_RETRY_AFTER_GIVEUP=1 to retry)",
                flush=True,
            )
            return ""

        if self.max_file_size_mb > 0:
            self._drop_oversize_from_index(store, working_dir, index_file)

        if has_ref:
            ok_same, _, _ = _run_git(
                ["diff-index", "--cached", "--quiet", ref_commit],
                store, working_dir,
                allowed_returncodes=frozenset({1}),
                index_file=index_file,
            )
            if ok_same:
                return ""  # no changes this turn => no commit
        else:
            ok_ls, ls_out, _ = _run_git(["ls-files", "--cached"],
                                        store, working_dir, index_file=index_file)
            if ok_ls and not ls_out.strip():
                return ""  # empty tree

        ok_tree, tree_sha, _ = _run_git(["write-tree"], store, working_dir,
                                        index_file=index_file)
        if not ok_tree or not tree_sha:
            return ""

        commit_args = ["commit-tree", tree_sha, "-m", f"[shadow] {reason}"]
        if has_ref:
            commit_args += ["-p", ref_commit]
        ok_c, new_commit, _ = _run_git(commit_args, store, working_dir)
        if not ok_c or not new_commit:
            return ""

        ok_u, _, _ = _run_git(["update-ref", ref, new_commit], store, working_dir)
        if not ok_u:
            return ""

        self._trim_history(store, working_dir, ref, dir_hash)
        self._maybe_gc(store, working_dir)
        # Addressable undo point: remember it as this workspace's newest, and
        # — for the first snapshot of the user turn — as the turn's undo
        # target, so the pane can name hashes without re-reading git.
        key = str(_normalize_path(working_dir))
        self._last_created[key] = new_commit
        if not self._turn_undo.get(key):
            self._turn_undo[key] = new_commit
        print(
            f"[shadow_checkpoint] snapshot took {time.monotonic() - started:.1f}s "
            f"({working_dir})",
            flush=True,
        )
        return new_commit

    def _drop_oversize_from_index(self, store: Path, working_dir: str,
                                  index_file: Path) -> None:
        limit = self.max_file_size_mb * 1024 * 1024
        ok, listing, _ = _run_git(["ls-files", "--cached", "-z"],
                                  store, working_dir, index_file=index_file)
        if not ok or not listing:
            return
        root = _normalize_path(working_dir)
        for rel in listing.split("\x00"):
            if not rel:
                continue
            try:
                if (root / rel).stat().st_size > limit:
                    _run_git(["rm", "--cached", "-q", "--ignore-unmatch", rel],
                             store, working_dir, index_file=index_file)
            except OSError:
                continue  # vanished between add and check: not our problem

    def _trim_history(self, store: Path, working_dir: str, ref: str,
                      dir_hash: str) -> None:
        """Keep per-project history short: at 2x max_snapshots, restart the
        line with a fresh root commit of the CURRENT tree (history depth
        therefore stays between max and 2x max between collections; old
        snapshots become unreachable and the lazy gc reclaims them)."""
        ok, count_out, _ = _run_git(["rev-list", "--count", ref],
                                    store, working_dir,
                                    allowed_returncodes=frozenset({128}))
        if not ok or not count_out.isdigit() or int(count_out) < 2 * self.max_snapshots:
            return
        # Orphan-restart: new root commit carrying the tip's tree.
        ok_t, tip_tree, _ = _run_git(["rev-parse", ref + "^{tree}"],
                                     store, working_dir)
        if not ok_t or not tip_tree:
            return
        ok_c, new_root, _ = _run_git(
            ["commit-tree", tip_tree,
             "-m", f"[shadow] history trimmed (kept {self.max_snapshots} latest)"],
            store, working_dir,
        )
        if ok_c and new_root:
            _run_git(["update-ref", ref, new_root], store, working_dir)

    def _maybe_gc(self, store: Path, working_dir: str) -> None:
        """Lazy daily gc so trim/orphan garbage is eventually reclaimed."""
        marker = checkpoint_base() / ".last_gc" if self._base is None \
            else self._base / ".last_gc"
        try:
            if marker.exists() and time.time() - marker.stat().st_mtime < 86_400:
                return
            _run_git(["gc", "--prune=now", "--quiet"], store, working_dir,
                     timeout=_GIT_TIMEOUT * 4)
            marker.touch()
        except OSError:
            pass


# --------------------------------------------------------------------------
# wiring helpers (file tools call these; the LLM never sees any of it)
# --------------------------------------------------------------------------

_SINGLETON: Optional[ShadowCheckpoints] = None
_SINGLETON_LOCK = threading.Lock()


def get_shadow_checkpoints() -> ShadowCheckpoints:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = ShadowCheckpoints()
    return _SINGLETON


def reset_shadow_checkpoints_for_tests() -> None:
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None


def checkpoint_before_mutation(workspace: str, reason: str) -> None:
    """Best-effort hook called by write_file / edit_file / execute_code /
    run_terminal before they mutate anything. Never raises, never blocks
    long: per-turn dedup means the common case is a set membership check."""
    try:
        get_shadow_checkpoints().ensure_checkpoint(workspace, reason)
    except Exception:
        pass


def begin_agent_turn() -> None:
    """Called at the start of each AI iteration (ai_node). Never raises."""
    try:
        get_shadow_checkpoints().new_turn()
    except Exception:
        pass


def mark_agent_turn_start(workspace: str) -> None:
    """Called once when a USER turn begins (bridge _run_turn). Never raises."""
    try:
        get_shadow_checkpoints().mark_turn_start(workspace)
    except Exception:
        pass


def agent_turn_undo_point(workspace: str) -> Optional[str]:
    """The current turn's "Undo turn" hash (its first snapshot), or None when
    the turn changed nothing. Never raises."""
    try:
        return get_shadow_checkpoints().turn_undo_point(workspace)
    except Exception:
        return None
