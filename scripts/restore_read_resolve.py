p = r"c:\Users\Administrator\Downloads\CRUSORAI\PulseAIRepo\src\tools\file_tools.py"
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

old = '''    try:
        safe_path = resolve_workspace_path(
            workspace,
            path
        )
    except ValueError as exc:
        return f"⛔ Security violation: {exc}"'''

new = '''    safe_path = resolve_workspace_path(
        workspace,
        path
    )'''

assert old in text, "Target block not found"
text = text.replace(old, new, 1)

with open(p, "w", encoding="utf-8") as f:
    f.write(text)

print("Restored direct resolve_workspace_path in read_file!")

