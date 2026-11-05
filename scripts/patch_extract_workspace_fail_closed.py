import os

p = r"c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\src\tools\file_tools.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

old_func = '''def _extract_workspace(config: Any = None) -> tuple[str, Optional[str]]:
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
    return str(configurable.get("workspace") or "."), None'''

new_func = '''def _extract_workspace(config: Any = None) -> tuple[str, Optional[str]]:
    """
    Extract the workspace path from a RunnableConfig, dict, or runtime context.
    Fail-closed security contract (Phase 9.3.1.2):
    1. Missing workspace context must fail closed for workspace-scoped tools.
    2. Explicitly empty workspace must be rejected.
    3. Valid configured workspace must be accepted.
    4. All paths must remain inside the configured workspace.
    5. No tool may silently select the process working directory as an authorization fallback.
    """
    if config is None:
        return "", "⛔ Tool execution refused: missing workspace restriction"

    configurable = None
    if isinstance(config, dict):
        configurable = config.get("configurable", config)
    else:
        configurable = getattr(config, "configurable", None)

    if not isinstance(configurable, dict):
        return "", "⛔ Tool execution refused: missing workspace restriction"

    ws = configurable.get("workspace")
    if ws is None or not str(ws).strip():
        return "", "⛔ Tool execution refused: missing workspace restriction"

    return str(ws).strip(), None'''

assert old_func in text, "Target old _extract_workspace not found!"
text = text.replace(old_func, new_func, 1)

with open(p, "w", encoding="utf-8") as f:
    f.write(text)

print("Updated _extract_workspace to fail-closed contract successfully!")

