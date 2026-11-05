import os
import sys

repo_root = r"c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo"
file_path = os.path.join(repo_root, "src", "tools", "file_tools.py")

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Insert _extract_workspace helper before read_file if not already present
helper_def = '''def _extract_workspace(config: Any = None) -> tuple[str, Optional[str]]:
    """
    Safely extract the workspace path from a RunnableConfig, dict, or None.
    Returns (workspace, error_message).
    If workspace restriction is present but explicitly empty, returns ("", error_message).
    Otherwise returns (workspace_path, None), defaulting to '.' if not configured.
    """
    if config is None:
        return ".", None
    configurable = getattr(config, "configurable", None)
    if configurable is None and isinstance(config, dict):
        configurable = config.get("configurable", config)
    if not isinstance(configurable, dict):
        return ".", None
    if "workspace" in configurable and not str(configurable.get("workspace") or "").strip():
        return "", "⛔ Tool execution refused: missing workspace restriction"
    return str(configurable.get("workspace") or "."), None


@tool
def read_file('''

assert "@tool\ndef read_file(" in content, "Target @tool def read_file( not found!"
content = content.replace("@tool\ndef read_file(", helper_def, 1)

# 2. Update read_file workspace extraction
read_target = '''    configurable = (config or {}).get("configurable", {})
    if "workspace" in configurable and not str(configurable.get("workspace") or "").strip():
        return "⛔ Tool execution refused: missing workspace restriction"
    workspace = str(configurable.get("workspace") or ".")'''

read_replacement = '''    workspace, ws_err = _extract_workspace(config)
    if ws_err:
        return ws_err'''

assert read_target in content, "read_target not found!"
content = content.replace(read_target, read_replacement, 1)

# 3. Update list_files workspace extraction
list_target = '    workspace = str((config or {}).get("configurable", {}).get("workspace") or ".")'
list_replacement = '''    workspace, ws_err = _extract_workspace(config)
    if ws_err:
        return ws_err'''

assert list_target in content, "list_target not found!"
content = content.replace(list_target, list_replacement, 1)

# 4. Update write_file signature and workspace extraction
write_sig_target = '''@tool
def write_file(
    path: str,
    content: str,
    config: RunnableConfig
) -> str:'''

write_sig_replacement = '''@tool
def write_file(
    path: str,
    content: str,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:'''

assert write_sig_target in content, "write_sig_target not found!"
content = content.replace(write_sig_target, write_sig_replacement, 1)

write_body_target = '    workspace = config["configurable"]["workspace"]\n\n    # Empty-content guard:'
write_body_replacement = '''    if not path or not isinstance(path, str) or not path.strip():
        return "❌ Missing or invalid required parameter: 'path' must be a non-empty string."
    if content is None or not isinstance(content, str):
        return "❌ Missing or invalid required parameter: 'content' must be a string."

    workspace, ws_err = _extract_workspace(config)
    if ws_err:
        return ws_err

    # Empty-content guard:'''

assert write_body_target in content, "write_body_target not found!"
content = content.replace(write_body_target, write_body_replacement, 1)

# Also wrap write_file resolve_workspace_path in try-except
write_resolve_target = '''    safe_path = resolve_workspace_path(
        workspace,
        path
    )'''
write_resolve_replacement = '''    try:
        safe_path = resolve_workspace_path(
            workspace,
            path
        )
    except ValueError as exc:
        return f"⛔ Security violation: {exc}"'''
assert write_resolve_target in content, "write_resolve_target not found!"
content = content.replace(write_resolve_target, write_resolve_replacement, 1)

# 5. Update copy_file signature and workspace extraction
copy_sig_target = '''@tool
def copy_file(
    src: str,
    dst: str,
    config: RunnableConfig,
) -> str:'''

copy_sig_replacement = '''@tool
def copy_file(
    src: str,
    dst: str,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:'''

assert copy_sig_target in content, "copy_sig_target not found!"
content = content.replace(copy_sig_target, copy_sig_replacement, 1)

copy_body_target = '''    workspace = config["configurable"]["workspace"]
    safe_src = resolve_workspace_path(workspace, src)
    safe_dst = resolve_workspace_path(workspace, dst)'''

copy_body_replacement = '''    if not src or not isinstance(src, str) or not src.strip():
        return "❌ Missing or invalid required parameter: 'src' must be a non-empty string."
    if not dst or not isinstance(dst, str) or not dst.strip():
        return "❌ Missing or invalid required parameter: 'dst' must be a non-empty string."

    workspace, ws_err = _extract_workspace(config)
    if ws_err:
        return ws_err
    try:
        safe_src = resolve_workspace_path(workspace, src)
        safe_dst = resolve_workspace_path(workspace, dst)
    except ValueError as exc:
        return f"⛔ Security violation: {exc}"'''

assert copy_body_target in content, "copy_body_target not found!"
content = content.replace(copy_body_target, copy_body_replacement, 1)

# 6. Update search_files signature and workspace extraction
search_sig_target = '''@tool
def search_files(
    pattern: str,
    path: str,
    config: RunnableConfig,
    query: str = "",
) -> str:'''

search_sig_replacement = '''@tool
def search_files(
    pattern: str,
    path: str,
    config: RunnableConfig = None,  # type: ignore[assignment]
    query: str = "",
) -> str:'''

assert search_sig_target in content, "search_sig_target not found!"
content = content.replace(search_sig_target, search_sig_replacement, 1)

search_body_target = '''    workspace = config["configurable"]["workspace"]

    safe_path = resolve_workspace_path(
        workspace,
        path
    )'''

search_body_replacement = '''    workspace, ws_err = _extract_workspace(config)
    if ws_err:
        return ws_err

    try:
        safe_path = resolve_workspace_path(
            workspace,
            path
        )
    except ValueError as exc:
        return f"⛔ Security violation: {exc}"'''

assert search_body_target in content, "search_body_target not found!"
content = content.replace(search_body_target, search_body_replacement, 1)

# 7. Update search_code signature
search_code_sig_target = '''@tool
def search_code(
    query: str,
    path: str,
    config: RunnableConfig
) -> str:'''

search_code_sig_replacement = '''@tool
def search_code(
    query: str,
    path: str,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:'''

assert search_code_sig_target in content, "search_code_sig_target not found!"
content = content.replace(search_code_sig_target, search_code_sig_replacement, 1)

# 8. Update typecheck_workspace signature and workspace extraction
typecheck_sig_target = '@tool\ndef typecheck_workspace(config: RunnableConfig) -> str:'
typecheck_sig_replacement = '@tool\ndef typecheck_workspace(config: RunnableConfig = None) -> str:  # type: ignore[assignment]'

assert typecheck_sig_target in content, "typecheck_sig_target not found!"
content = content.replace(typecheck_sig_target, typecheck_sig_replacement, 1)

typecheck_body_target = '    workspace = config["configurable"]["workspace"]\n    workspace_path = Path(workspace).resolve()'
typecheck_body_replacement = '''    workspace, ws_err = _extract_workspace(config)
    if ws_err:
        return ws_err
    workspace_path = Path(workspace).resolve()'''

assert typecheck_body_target in content, "typecheck_body_target not found!"
content = content.replace(typecheck_body_target, typecheck_body_replacement, 1)

# 9. Update edit_file signature, parameter validation, and workspace extraction
edit_sig_target = '''@tool
def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    config: RunnableConfig
) -> str:'''

edit_sig_replacement = '''@tool
def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:'''

assert edit_sig_target in content, "edit_sig_target not found!"
content = content.replace(edit_sig_target, edit_sig_replacement, 1)

edit_body_target = '''    workspace = config["configurable"]["workspace"]

    safe_path = resolve_workspace_path(
        workspace,
        path
    )

    if not safe_path.exists():
        return f"❌ File not found: {path}"'''

edit_body_replacement = '''    if not path or not isinstance(path, str) or not path.strip():
        return "❌ Missing or invalid required parameter: 'path' must be a non-empty string."
    if old_text is None or not isinstance(old_text, str):
        return "❌ Missing or invalid required parameter: 'old_text' must be a string."
    if new_text is None or not isinstance(new_text, str):
        return "❌ Missing or invalid required parameter: 'new_text' must be a string."

    workspace, ws_err = _extract_workspace(config)
    if ws_err:
        return ws_err

    try:
        safe_path = resolve_workspace_path(
            workspace,
            path
        )
    except ValueError as exc:
        return f"⛔ Security violation: {exc}"

    if safe_path.is_dir():
        return f"❌ '{path}' is a DIRECTORY, not a file."

    if not safe_path.exists():
        return f"❌ File not found: {path}"'''

assert edit_body_target in content, "edit_body_target not found!"
content = content.replace(edit_body_target, edit_body_replacement, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Successfully patched src/tools/file_tools.py!")

