
from pathlib import Path
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

PROJECT_ROOT = Path.cwd()

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
    """Read and return the contents of a file inside the current workspace."""

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
    """List files and directories inside a workspace directory."""

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
    """Create or overwrite a file inside the current workspace."""

    workspace = config["configurable"]["workspace"]

    safe_path = resolve_workspace_path(
        workspace,
        path
    )

    safe_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

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
    """Search recursively for text within files inside the current workspace."""

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

    # If it's a directory, recursively find files
    else:
        files = safe_path.rglob("*")

    for file_path in files:

        if not file_path.is_file():
            continue

        try:
            content = file_path.read_text(
                encoding="utf-8"
            )
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

    return "\n".join(results)
    # Keep your EXISTING search logic below this point.
@tool
def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    config: RunnableConfig
) -> str:
    """Replace specific text in an existing file inside the current workspace."""

    workspace = config["configurable"]["workspace"]

    safe_path = resolve_workspace_path(
        workspace,
        path
    )

    content = safe_path.read_text(
        encoding="utf-8"
    )

    if old_text not in content:
        return f"Text not found in {path}"

    updated_content = content.replace(
        old_text,
        new_text,
        1
    )

    safe_path.write_text(
        updated_content,
        encoding="utf-8"
    )

    return f"File edited: {path}"