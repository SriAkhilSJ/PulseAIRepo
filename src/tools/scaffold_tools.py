"""Deterministic project scaffolding for workspaces that contain provided files.

`create-next-app .` refuses when `_provided/` exists. Models then tend to create
`<workspace>/<workspace>/`, wasting a long install and leaving the deliverable at
the wrong root. This tool owns that boring environment transition: scaffold in
a temporary sibling with `--skip-install`, merge into the real workspace while
preserving `_provided`, then install once at the correct root.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

_PACKAGE_RE = re.compile(r"^(?:@[a-z0-9._-]+/)?[a-z0-9._-]+(?:@[a-zA-Z0-9._~^*<>=|-]+)?$")


def _normalize_generated_layout(workspace: Path) -> bool:
    """Repair create-next-app's occasionally unresolved generated LayoutProps.

    This is scaffold ownership, not task-specific application code: the same
    generator defect appeared in multiple independent labs. Return whether a
    normalization landed.
    """
    path = workspace / "src" / "app" / "layout.tsx"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    updated = re.sub(
        r":\s*LayoutProps<\s*[\"']/[\"']\s*>",
        ": { children: React.ReactNode }",
        text,
        count=1,
    )
    if updated == text:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def _run(argv: list[str], *, cwd: Path, timeout: int) -> tuple[int, str]:
    env = dict(os.environ)
    env.update({"CI": "1", "NO_COLOR": "1"})
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True,
            timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        return 124, f"Timed out after {timeout}s: {' '.join(argv)}"
    output = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    return proc.returncode, output


@tool
def scaffold_nextjs(
    packages: list[str],
    config: RunnableConfig,
) -> str:
    """Scaffold Next.js + TypeScript + Tailwind safely into the active workspace.

    USE when a UI task needs a new project and the workspace already contains
    `_provided/` inputs. Unlike `create-next-app .`, this preserves those files,
    avoids accidental `<workspace>/<workspace>/` nesting, and installs exactly
    once at the correct root. `packages` lists extra npm dependencies, e.g.
    ["three", "@react-three/drei", "@react-three/fiber"].

    Refuses a non-empty existing project rather than overwriting user work.
    """
    workspace = Path(config["configurable"]["workspace"]).resolve()
    if (workspace / "package.json").is_file():
        return "ℹ️ scaffold_nextjs skipped: package.json already exists at the workspace root."

    extras = [str(p).strip() for p in (packages or []) if str(p).strip()]
    invalid = [p for p in extras if not _PACKAGE_RE.fullmatch(p)]
    if invalid:
        return f"⛔ scaffold_nextjs refused invalid package name(s): {invalid}"

    existing = {p.name for p in workspace.iterdir()} if workspace.exists() else set()
    # COPY-FIRST may already have placed the explicit deliverables. Permit only
    # that narrow shape in addition to _provided; never merge over arbitrary src.
    allowed_existing = {"_provided"}
    src = workspace / "src"
    if src.exists():
        allowed_prefix = (src / "components" / "ui").resolve()
        safe_src = True
        for entry in src.rglob("*"):
            if entry.is_file():
                try:
                    entry.resolve().relative_to(allowed_prefix)
                except ValueError:
                    safe_src = False
                    break
        if safe_src:
            allowed_existing.add("src")
    unexpected = sorted(existing - allowed_existing)
    if unexpected:
        return (
            "⛔ scaffold_nextjs refused to merge over an existing project. "
            f"Unexpected workspace entries: {unexpected[:12]}. Inspect and use the existing setup."
        )

    npx = shutil.which("npx.cmd" if os.name == "nt" else "npx") or shutil.which("npx")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or shutil.which("npm")
    if not npx or not npm:
        return "⛔ scaffold_nextjs unavailable: npm/npx is not installed or not on PATH."

    workspace.mkdir(parents=True, exist_ok=True)
    parent = workspace.parent
    temp_name = f"pulse-scaffold-{uuid.uuid4().hex[:8]}"
    temp_project = parent / temp_name

    from src.tools.shadow_checkpoints import checkpoint_before_mutation
    checkpoint_before_mutation(str(workspace), "scaffold_nextjs")

    create_argv = [
        npx, "create-next-app@latest", temp_name,
        "--typescript", "--tailwind", "--eslint", "--app", "--src-dir",
        "--import-alias", "@/*", "--use-npm", "--skip-install", "--yes",
    ]
    code, output = _run(create_argv, cwd=parent, timeout=120)
    if code != 0 or not (temp_project / "package.json").is_file():
        shutil.rmtree(temp_project, ignore_errors=True)
        return f"⛔ scaffold_nextjs create step failed (exit {code}):\n{output[-4000:]}"

    try:
        for item in temp_project.iterdir():
            if item.name in {".git", "node_modules"}:
                continue
            dst = workspace / item.name
            if item.is_dir():
                shutil.copytree(item, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dst)
    finally:
        shutil.rmtree(temp_project, ignore_errors=True)

    # npm 10 can reject otherwise valid React/Three peer graphs while packages
    # are being resolved together. A fresh generated app has no user lockfile
    # contract to protect yet, so legacy peer resolution is the deterministic
    # non-interactive choice here (and avoids a second expensive install turn).
    _normalize_generated_layout(workspace)

    install_argv = [npm, "install", *extras, "--legacy-peer-deps"]
    code, install_output = _run(install_argv, cwd=workspace, timeout=240)
    if code != 0:
        return (
            "⚠️ scaffold_nextjs created the project at the correct root, but npm install "
            f"failed (exit {code}). Fix the install before finishing:\n{install_output[-4000:]}"
        )

    try:
        from src.context.repo_map import invalidate_repo_map
        invalidate_repo_map(str(workspace))
    except Exception:
        pass
    try:
        from src.tools.file_tools import _record_workspace_edit
        changed = [str(p) for p in workspace.iterdir() if p.name != "_provided"]
        _record_workspace_edit(config, str(workspace), changed)
    except Exception:
        pass

    return (
        "✅ scaffold_nextjs completed at the workspace root. "
        f"Installed base dependencies plus: {extras or '(none)'}. "
        "The `_provided` directory was preserved. Continue with the named copy_file deliverables."
    )
