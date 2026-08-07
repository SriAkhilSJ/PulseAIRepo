
from pathlib import Path
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

PROJECT_ROOT = Path.cwd()

# search_code guards (round-12 review: rglob("*") descended .git and
# node_modules with zero skips and no caps). Substring-grep semantics kept
# deliberately — BM25 in chunk_index answers a DIFFERENT question.
_SEARCH_SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build",
    ".tox", ".idea", ".vscode", "generated",
}
_SEARCH_MAX_FILE_BYTES = 2 * 1024 * 1024   # 2 MB: minified bundles, logs
_SEARCH_MAX_FILES = 2_000                   # worst-case scan budget
_SEARCH_MAX_RESULTS = 500                   # context budget, not grep's

def resolve_workspace_path(
    workspace: str,
    path: str
) -> Path:

    workspace_path = Path(workspace).resolve()
    requested_path = (workspace_path / path).resolve()

    if not requested_path.is_relative_to(workspace_path):
        raise ValueError(
            f"Path escapes workspace: {path}"
        )

    return requested_path



@tool
def read_file(
    path: str,
    config: RunnableConfig
) -> str:
    """
    Read and return the contents of a file inside the current workspace.

    WHEN TO USE:
    - Before editing any existing file, read it first to see current contents.
    - To inspect configuration files, code, data, prompts, or tests.
    - To verify that write_file or edit_file produced the expected content.

    WHEN NOT TO USE:
    - Do not use for directories; use list_files instead.
    - Do not repeatedly read the same unchanged file in one task unless needed.

    Args:
        path: Workspace-relative path to the file.

    Returns:
        File contents as text, or a tool error if reading fails.
    """

    workspace = config["configurable"]["workspace"]

    safe_path = resolve_workspace_path(
        workspace,
        path
    )

    with open(
        safe_path,
        "r",
        encoding="utf-8"
    ) as file:
        return file.read()

@tool
def list_files(
    path: str,
    config: RunnableConfig
) -> str:
    """
    List files and directories inside a workspace directory.

    WHEN TO USE:
    - To inspect a directory when the repo map is insufficient.
    - To verify whether a file or folder exists.
    - To explore a small part of the workspace.

    WHEN NOT TO USE:
    - Do not recursively list the entire repo unless necessary.
    - Prefer the repo map or search_code when looking for known symbols.
    """

    workspace = config["configurable"]["workspace"]

    safe_path = resolve_workspace_path(
        workspace,
        path
    )

    if not safe_path.exists():
        return f"Directory does not exist: {path}"

    if not safe_path.is_dir():
        return f"Not a directory: {path}"

    items = []

    for item in safe_path.iterdir():
        items.append(item.name)

    return "\n".join(items)

@tool
def write_file(
    path: str,
    content: str,
    config: RunnableConfig
) -> str:
    """
    Create or overwrite a file inside the current workspace.

    WHEN TO USE:
    - Creating a new file.
    - Replacing an entire file intentionally.
    - Writing generated content where no current content needs preservation.

    WHEN NOT TO USE:
    - Do not use for small edits to existing files; use edit_file instead.
    - Do not overwrite important files without inspecting them first.
    """

    workspace = config["configurable"]["workspace"]

    safe_path = resolve_workspace_path(
        workspace,
        path
    )

    safe_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    # D31: shadow snapshot BEFORE mutating (once per turn per workspace;
    # transparent to the LLM, never raises).
    from src.tools.shadow_checkpoints import checkpoint_before_mutation
    checkpoint_before_mutation(workspace, f"write_file: {path}")

    safe_path.write_text(
        content,
        encoding="utf-8"
    )

    return f"File written: {path}"

@tool
def search_code(
    query: str,
    path: str,
    config: RunnableConfig
) -> str:
    """
    Search recursively for text within files inside the current workspace.

    WHEN TO USE:
    - To find functions, classes, imports, config keys, errors, or examples.
    - To locate where a file, symbol, or message appears.
    - Before editing code when you need to understand usages.

    WHEN NOT TO USE:
    - Do not use for reading a known file; use read_file.
    - Do not search the whole repo with vague queries if the repo map points to a file.
    """

    workspace = config["configurable"]["workspace"]

    safe_path = resolve_workspace_path(
        workspace,
        path
    )

    if not safe_path.exists():
        return f"Path does not exist: {path}"

    results = []

    # If the path itself is a file
    if safe_path.is_file():
        files = [safe_path]

    # If it's a directory, recursively find files.
    # .git internals and dependency forests grep nothing but garbage and
    # make an O(n) tool O(disaster). Same skip philosophy as chunk_index.
    else:
        files = (
            f for f in safe_path.rglob("*")
            if not any(part in _SEARCH_SKIP_DIRS for part in f.parts)
        )

    scanned = 0
    for file_path in files:

        if not file_path.is_file():
            continue

        try:
            if file_path.stat().st_size > _SEARCH_MAX_FILE_BYTES:
                continue  # minified bundles / logs / data dumps
            content = file_path.read_text(
                encoding="utf-8"
            )
            scanned += 1
            if scanned > _SEARCH_MAX_FILES:
                results.append(
                    f"... stopped after {_SEARCH_MAX_FILES} files "
                    f"(narrow the path or the query)"
                )
                break
        except (UnicodeDecodeError, PermissionError, OSError):
            # Skip binary/unreadable files
            continue

        for line_number, line in enumerate(
            content.splitlines(),
            start=1
        ):
            if query.lower() in line.lower():

                relative_path = file_path.relative_to(
                    safe_path if safe_path.is_dir()
                    else safe_path.parent
                )

                results.append(
                    f"{relative_path}:{line_number}: {line.strip()}"
                )

    if not results:
        return f"No results found for '{query}' in '{path}'."

    if len(results) > _SEARCH_MAX_RESULTS:
        results = results[:_SEARCH_MAX_RESULTS]
        results.append(f"... truncated at {_SEARCH_MAX_RESULTS} matches")

    return "\n".join(results)
    # Keep your EXISTING search logic below this point.
def _fuzzy_find_block(
    original: str, old_text: str, threshold: float = 0.88
) -> tuple[int, int] | None:
    """Locate old_text in original, tolerating per-line whitespace drift.

    Matches on whitespace-stripped lines and maps the best window back to an
    ORIGINAL line span, so the caller can replace the whole block — never a
    single line (which would corrupt multi-line edits). Returns
    (start_idx, end_idx_exclusive) into original.splitlines(), or None.
    """
    import difflib

    orig_lines = original.splitlines()
    old_lines = old_text.splitlines()
    if not orig_lines or not old_lines:
        return None
    if not any(line.strip() for line in old_lines):
        return None

    n = len(old_lines)
    orig_stripped = [line.strip() for line in orig_lines]
    old_join = "\n".join(line.strip() for line in old_lines)

    best_ratio, best_idx = 0.0, None
    for i in range(0, len(orig_lines) - n + 1):
        window = "\n".join(orig_stripped[i: i + n])
        if not window.strip():
            continue
        ratio = difflib.SequenceMatcher(None, old_join, window).ratio()
        if ratio > best_ratio:
            best_ratio, best_idx = ratio, i

    if best_idx is None or best_ratio < threshold:
        return None
    return (best_idx, best_idx + n)


def _atomic_write(path, content: str) -> None:
    """Write via tempfile + os.replace (same directory => same filesystem):
    concurrent readers never see a torn file, and the original mode survives.
    """
    import os
    import tempfile

    st_mode = path.stat().st_mode & 0o777
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp, st_mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@tool
def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    config: RunnableConfig
) -> str:
    """
    Replace specific text in an existing file inside the current workspace.

    WHEN TO USE:
    - Changing a small or precise part of an existing file.
    - Fixing bugs, imports, config values, or individual functions.
    - Preserving the rest of the file exactly.

    WHEN NOT TO USE:
    - Do not use for creating new files; use write_file.
    - Do not use before reading the file when current content matters.

    IMPORTANT:
    - old_text should match existing content; minor whitespace drift is
      tolerated automatically (the replacement covers the matched BLOCK).
    - Prefer small, targeted replacements.
    - A diff preview is returned so you can verify the edit — use it.
    """

    workspace = config["configurable"]["workspace"]

    safe_path = resolve_workspace_path(
        workspace,
        path
    )

    if not safe_path.exists():
        return f"❌ File not found: {path}"

    original = safe_path.read_text(
        encoding="utf-8"
    )

    match_mode = "exact"
    if old_text in original:
        updated_content = original.replace(
            old_text,
            new_text,
            1
        )
    else:
        span = _fuzzy_find_block(original, old_text)
        if span is None:
            return (
                f"❌ Text not found in {path}. "
                f"Read the file first and retry with current content."
            )
        match_mode = "fuzzy"
        orig_lines = original.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] += "\n"
        start, end = span
        updated_content = "".join(
            orig_lines[:start] + new_lines + orig_lines[end:]
        )

    if updated_content == original:
        return f"ℹ️ No change: new_text equals the existing content in {path}."

    # D31: shadow snapshot BEFORE mutating (captures the pre-edit state;
    # placed after the no-change early return so no-op edits cost nothing).
    from src.tools.shadow_checkpoints import checkpoint_before_mutation
    checkpoint_before_mutation(workspace, f"edit_file: {path}")

    _atomic_write(safe_path, updated_content)

    # Lazy import: chat_graph imports file_tools at module load time — a
    # module-level import here would be circular.
    from src.utils.diff_utils import compute_unified_diff

    diff = compute_unified_diff(original, updated_content, str(safe_path))

    preview_lines: list[str] = []
    marker = {"added": "+", "removed": "-", "context": " "}
    for chunk in diff["chunks"]:
        for line in chunk["lines"]:
            preview_lines.append(
                f"{marker[line['type']]}{line['text'].rstrip()}"
            )

    # Same flat {"file", "lines"} payload shape the dashboard already
    # renders for write_file. files.changed stays owned by progress_node
    # (it has the real tool_call_id for messageId).
    from src.dashboard.event_bus import event_bus
    event_bus.emit("diff.show", {
        "file": path,
        "lines": preview_lines[:20],
    })

    note = " (fuzzy match — verify the result)" if match_mode == "fuzzy" else ""
    preview = "\n".join(preview_lines[:12])
    return f"✅ Edited {path}{note}\n\nDiff preview:\n{preview}"
