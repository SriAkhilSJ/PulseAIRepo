"""Server registry — per-language LSP server definitions.

Each :class:`ServerDef` knows how to:
- match a file by extension
- resolve a project root from a file path
- assemble the spawn command
- compute LSP ``initializationOptions``
"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.lsp.workspace import nearest_root

logger = logging.getLogger("src.lsp.servers")

LANGUAGE_BY_EXT: Dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".tsx": "typescriptreact",
    ".js": "javascript",
    ".jsx": "javascriptreact",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".vue": "vue",
    ".svelte": "svelte",
    ".astro": "astro",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".rake": "ruby",
    ".gemspec": "ruby",
    ".ru": "ruby",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".csx": "csharp",
    ".fs": "fsharp",
    ".fsi": "fsharp",
    ".fsx": "fsharp",
    ".swift": "swift",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".jsonc": "jsonc",
    ".lua": "lua",
    ".php": "php",
    ".prisma": "prisma",
    ".dart": "dart",
    ".ml": "ocaml",
    ".mli": "ocaml",
    ".sh": "shellscript",
    ".bash": "shellscript",
    ".zsh": "shellscript",
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".tex": "latex",
    ".bib": "bibtex",
    ".gleam": "gleam",
    ".clj": "clojure",
    ".cljs": "clojurescript",
    ".cljc": "clojure",
    ".edn": "clojure",
    ".nix": "nix",
    ".typ": "typst",
    ".typc": "typst",
    ".hs": "haskell",
    ".lhs": "haskell",
    ".jl": "julia",
    ".ex": "elixir",
    ".exs": "elixir",
    ".zig": "zig",
    ".zon": "zig",
    ".dockerfile": "dockerfile",
    ".ps1": "powershell",
    ".psm1": "powershell",
    ".psd1": "powershell",
}


@dataclass
class SpawnSpec:
    """The result of resolving a server for a file."""
    command: List[str]
    workspace_root: str
    cwd: str
    env: Dict[str, str] = field(default_factory=dict)
    initialization_options: Dict[str, Any] = field(default_factory=dict)
    seed_diagnostics_on_first_push: bool = False


@dataclass
class ServerDef:
    """Definition of one language server."""
    server_id: str
    extensions: Tuple[str, ...]
    resolve_root: Callable[[str, str], Optional[str]]
    build_spawn: Callable[[str, "ServerContext"], Optional[SpawnSpec]]
    seed_first_push: bool = False
    description: str = ""

    def matches(self, file_path: str) -> bool:
        ext = _file_ext_or_basename(file_path)
        return ext in self.extensions


@dataclass
class ServerContext:
    """Context passed into :meth:`ServerDef.build_spawn`."""
    workspace_root: str
    install_strategy: str = "auto"
    binary_overrides: Dict[str, List[str]] = field(default_factory=dict)
    env_overrides: Dict[str, Dict[str, str]] = field(default_factory=dict)
    init_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)


def _file_ext_or_basename(path: str) -> str:
    base = os.path.basename(path)
    _root, ext = os.path.splitext(base)
    if ext:
        return ext.lower()
    return base


def _which(*names: str) -> Optional[str]:
    for n in names:
        path = shutil.which(n)
        if path:
            return path
    return None


def _root_or_workspace(file_path: str, workspace: str, markers: Sequence[str], excludes: Sequence[str] = ()) -> Optional[str]:
    found = nearest_root(
        file_path,
        markers,
        excludes=excludes,
        ceiling=os.path.dirname(workspace) if workspace else None,
    )
    if found is None and excludes:
        recheck = nearest_root(
            file_path,
            markers,
            ceiling=os.path.dirname(workspace) if workspace else None,
        )
        if recheck is not None:
            return None
        return workspace
    return found or workspace


def _resolve_override(ctx: ServerContext, server_id: str) -> Optional[str]:
    override = ctx.binary_overrides.get(server_id)
    if override and override[0] and os.path.exists(override[0]):
        return override[0]
    return None


def _detect_python(root: str) -> Optional[str]:
    candidates = []
    if os.environ.get("VIRTUAL_ENV"):
        candidates.append(os.environ["VIRTUAL_ENV"])
    candidates.extend([os.path.join(root, ".venv"), os.path.join(root, "venv")])
    for v in candidates:
        for sub in ("bin/python", "bin/python3", "Scripts/python.exe"):
            p = os.path.join(v, sub)
            if os.path.exists(p):
                return p
    return None


# ── per-server spawn builders ─────────────────────────────────────────────

def _spawn_pyright(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "pyright") or _which("pyright-langserver", "pyright")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("pyright", ctx.install_strategy)
        if bin_path is None:
            return None
    base = os.path.basename(bin_path)
    if base in {"pyright", "pyright.exe"}:
        sibling = os.path.join(os.path.dirname(bin_path), "pyright-langserver")
        if os.path.exists(sibling):
            bin_path = sibling
    init: Dict[str, Any] = {}
    py = _detect_python(root)
    if py:
        init["python"] = {"pythonPath": py}
    if "pyright" in ctx.init_overrides:
        init.update(ctx.init_overrides["pyright"])
    return SpawnSpec(
        command=[bin_path, "--stdio"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("pyright", {}),
        initialization_options=init,
    )


def _spawn_typescript(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "typescript") or _which("typescript-language-server")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("typescript-language-server", ctx.install_strategy)
        if bin_path is None:
            return None

    # Pre-check: typescript-language-server needs a local 'typescript' package.
    # If missing, log a helpful message instead of letting the server crash
    # with a cryptic "Could not find a valid TypeScript installation" error.
    ts_dir = os.path.join(root, "node_modules", "typescript")
    if not os.path.isdir(ts_dir):
        import sys as _sys
        print(
            f"[LSP] WARNING: TypeScript LSP may fail — no 'typescript' package "
            f"found in {root}/node_modules/. Run 'npm install typescript' in "
            f"the workspace to enable full TS diagnostics.",
            file=_sys.stderr, flush=True,
        )

    return SpawnSpec(
        command=[bin_path, "--stdio"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("typescript", {}),
        initialization_options=ctx.init_overrides.get("typescript", {}),
        seed_diagnostics_on_first_push=True,
    )


def _spawn_gopls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "gopls") or _which("gopls")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("gopls", ctx.install_strategy)
        if bin_path is None:
            return None
    return SpawnSpec(
        command=[bin_path],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("gopls", {}),
        initialization_options=ctx.init_overrides.get("gopls", {}),
    )


def _spawn_rust_analyzer(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "rust-analyzer") or _which("rust-analyzer")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("rust-analyzer", ctx.install_strategy)
        if bin_path is None:
            return None
    return SpawnSpec(
        command=[bin_path],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("rust-analyzer", {}),
        initialization_options=ctx.init_overrides.get("rust-analyzer", {}),
    )


def _spawn_clangd(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "clangd") or _which("clangd")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("clangd", ctx.install_strategy)
        if bin_path is None:
            return None
    return SpawnSpec(
        command=[bin_path, "--background-index", "--clang-tidy"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("clangd", {}),
        initialization_options=ctx.init_overrides.get("clangd", {}),
    )


def _spawn_bash_ls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "bash-language-server") or _which("bash-language-server")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("bash-language-server", ctx.install_strategy)
        if bin_path is None:
            return None
    return SpawnSpec(
        command=[bin_path, "start"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("bash-language-server", {}),
        initialization_options=ctx.init_overrides.get("bash-language-server", {}),
    )


def _spawn_yaml_ls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "yaml-language-server") or _which("yaml-language-server")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("yaml-language-server", ctx.install_strategy)
        if bin_path is None:
            return None
    return SpawnSpec(
        command=[bin_path, "--stdio"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("yaml-language-server", {}),
        initialization_options=ctx.init_overrides.get("yaml-language-server", {}),
    )


def _spawn_lua_ls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "lua-language-server") or _which("lua-language-server")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("lua-language-server", ctx.install_strategy)
        if bin_path is None:
            return None
    return SpawnSpec(
        command=[bin_path],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("lua-language-server", {}),
        initialization_options=ctx.init_overrides.get("lua-language-server", {}),
    )


def _spawn_intelephense(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "intelephense") or _which("intelephense")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("intelephense", ctx.install_strategy)
        if bin_path is None:
            return None
    init = {"telemetry": {"enabled": False}}
    init.update(ctx.init_overrides.get("intelephense", {}))
    return SpawnSpec(
        command=[bin_path, "--stdio"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("intelephense", {}),
        initialization_options=init,
    )


def _spawn_ocamllsp(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "ocaml-lsp") or _which("ocamllsp")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("ocaml-lsp", {}),
        initialization_options=ctx.init_overrides.get("ocaml-lsp", {}),
    )


def _spawn_dockerfile_ls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "dockerfile-ls") or _which("docker-langserver")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("dockerfile-language-server-nodejs", ctx.install_strategy)
        if bin_path is None:
            return None
    return SpawnSpec(
        command=[bin_path, "--stdio"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("dockerfile-ls", {}),
        initialization_options=ctx.init_overrides.get("dockerfile-ls", {}),
    )


def _spawn_terraform_ls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "terraform-ls") or _which("terraform-ls")
    if bin_path is None:
        return None
    init = {
        "experimentalFeatures": {
            "prefillRequiredFields": True,
            "validateOnSave": True,
        }
    }
    init.update(ctx.init_overrides.get("terraform-ls", {}))
    return SpawnSpec(
        command=[bin_path, "serve"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("terraform-ls", {}),
        initialization_options=init,
    )


def _spawn_dart(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "dart") or _which("dart")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path, "language-server", "--lsp"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("dart", {}),
        initialization_options=ctx.init_overrides.get("dart", {}),
    )


def _spawn_haskell_ls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "haskell-language-server") or _which(
        "haskell-language-server-wrapper", "haskell-language-server"
    )
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path, "--lsp"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("haskell-language-server", {}),
        initialization_options=ctx.init_overrides.get("haskell-language-server", {}),
    )


def _spawn_julia(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "julia") or _which("julia")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[
            bin_path,
            "--startup-file=no",
            "--history-file=no",
            "-e",
            "using LanguageServer; runserver()",
        ],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("julia", {}),
        initialization_options=ctx.init_overrides.get("julia", {}),
    )


def _spawn_clojure_lsp(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "clojure-lsp") or _which("clojure-lsp")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path, "listen"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("clojure-lsp", {}),
        initialization_options=ctx.init_overrides.get("clojure-lsp", {}),
    )


def _spawn_nixd(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "nixd") or _which("nixd")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("nixd", {}),
        initialization_options=ctx.init_overrides.get("nixd", {}),
    )


def _spawn_zls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "zls") or _which("zls")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("zls", {}),
        initialization_options=ctx.init_overrides.get("zls", {}),
    )


def _spawn_gleam(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "gleam") or _which("gleam")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path, "lsp"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("gleam", {}),
        initialization_options=ctx.init_overrides.get("gleam", {}),
    )


def _spawn_elixir_ls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "elixir-ls") or _which("elixir-ls", "language_server.sh")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("elixir-ls", {}),
        initialization_options=ctx.init_overrides.get("elixir-ls", {}),
    )


def _spawn_prisma(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "prisma") or _which("prisma")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path, "language-server"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("prisma", {}),
        initialization_options=ctx.init_overrides.get("prisma", {}),
    )


def _spawn_kotlin_ls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "kotlin-language-server") or _which("kotlin-language-server")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("kotlin-language-server", {}),
        initialization_options=ctx.init_overrides.get("kotlin-language-server", {}),
    )


def _spawn_jdtls(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "jdtls") or _which("jdtls")
    if bin_path is None:
        return None
    return SpawnSpec(
        command=[bin_path],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("jdtls", {}),
        initialization_options=ctx.init_overrides.get("jdtls", {}),
    )


def _spawn_vue(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "vue-language-server") or _which("vue-language-server")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("@vue/language-server", ctx.install_strategy)
        if bin_path is None:
            return None
    return SpawnSpec(
        command=[bin_path, "--stdio"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("vue-language-server", {}),
        initialization_options=ctx.init_overrides.get("vue-language-server", {}),
    )


def _spawn_svelte(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "svelte-language-server") or _which("svelteserver", "svelte-language-server")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("svelte-language-server", ctx.install_strategy)
        if bin_path is None:
            return None
    return SpawnSpec(
        command=[bin_path, "--stdio"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("svelte-language-server", {}),
        initialization_options=ctx.init_overrides.get("svelte-language-server", {}),
    )


def _spawn_astro(root: str, ctx: ServerContext) -> Optional[SpawnSpec]:
    bin_path = _resolve_override(ctx, "astro-language-server") or _which("astro-ls", "astro-language-server")
    if bin_path is None:
        from src.lsp.install import try_install
        bin_path = try_install("@astrojs/language-server", ctx.install_strategy)
        if bin_path is None:
            return None
    return SpawnSpec(
        command=[bin_path, "--stdio"],
        workspace_root=root,
        cwd=root,
        env=ctx.env_overrides.get("astro-language-server", {}),
        initialization_options=ctx.init_overrides.get("astro-language-server", {}),
    )


# ── root resolvers ────────────────────────────────────────────────────────

def _root_python(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(
        file_path, workspace,
        ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "pyrightconfig.json"],
    )


def _root_typescript(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(
        file_path, workspace,
        ["package-lock.json", "bun.lockb", "bun.lock", "pnpm-lock.yaml", "yarn.lock", "package.json", "tsconfig.json"],
        excludes=["deno.json", "deno.jsonc"],
    )


def _root_go(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["go.work", "go.mod", "go.sum"])


def _root_rust(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["Cargo.toml", "Cargo.lock"])


def _root_ruby(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["Gemfile"])


def _root_clangd(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["compile_commands.json", "compile_flags.txt", ".clangd"])


def _root_bash(file_path: str, workspace: str) -> str:
    return workspace


def _root_yaml(file_path: str, workspace: str) -> str:
    return workspace


def _root_lua(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, [".luarc.json", ".luarc.jsonc", ".luacheckrc", ".stylua.toml", "stylua.toml", "selene.toml", "selene.yml"])


def _root_php(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["composer.json", "composer.lock", ".php-version"])


def _root_ocaml(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["dune-project", "dune-workspace", ".merlin", "opam"])


def _root_docker(file_path: str, workspace: str) -> str:
    return workspace


def _root_terraform(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, [".terraform.lock.hcl", "terraform.tfstate"])


def _root_dart(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["pubspec.yaml", "analysis_options.yaml"])


def _root_haskell(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["stack.yaml", "cabal.project", "hie.yaml"])


def _root_julia(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["Project.toml", "Manifest.toml"])


def _root_clojure(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["deps.edn", "project.clj", "shadow-cljs.edn", "bb.edn", "build.boot"])


def _root_nix(file_path: str, workspace: str) -> str:
    found = nearest_root(file_path, ["flake.nix"])
    return found or workspace


def _root_zig(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["build.zig"])


def _root_elixir(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["mix.exs", "mix.lock"])


def _root_prisma(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["schema.prisma", "prisma/schema.prisma"])


def _root_kotlin(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["settings.gradle", "settings.gradle.kts", "build.gradle", "build.gradle.kts", "pom.xml"])


def _root_java(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["pom.xml", "build.gradle", "build.gradle.kts", ".project", ".classpath", "settings.gradle"])


def _root_powershell(file_path: str, workspace: str) -> Optional[str]:
    return _root_or_workspace(file_path, workspace, ["PSScriptAnalyzerSettings.psd1"])


# ── the registry ──────────────────────────────────────────────────────────

SERVERS: List[ServerDef] = [
    ServerDef("pyright", (".py", ".pyi"), _root_python, _spawn_pyright, description="Python — pyright"),
    ServerDef("typescript", (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"), _root_typescript, _spawn_typescript, seed_first_push=True, description="JS/TS — typescript-language-server"),
    ServerDef("vue-language-server", (".vue",), _root_typescript, _spawn_vue, description="Vue — @vue/language-server"),
    ServerDef("svelte-language-server", (".svelte",), _root_typescript, _spawn_svelte, description="Svelte — svelte-language-server"),
    ServerDef("astro-language-server", (".astro",), _root_typescript, _spawn_astro, description="Astro — @astrojs/language-server"),
    ServerDef("gopls", (".go",), _root_go, _spawn_gopls, description="Go — gopls"),
    ServerDef("rust-analyzer", (".rs",), _root_rust, _spawn_rust_analyzer, description="Rust — rust-analyzer"),
    ServerDef("clangd", (".c", ".cpp", ".cc", ".cxx", ".h", ".hh", ".hpp", ".hxx"), _root_clangd, _spawn_clangd, description="C/C++ — clangd"),
    ServerDef("bash-language-server", (".sh", ".bash", ".zsh", ".ksh"), _root_bash, _spawn_bash_ls, description="Bash — bash-language-server"),
    ServerDef("yaml-language-server", (".yaml", ".yml"), _root_yaml, _spawn_yaml_ls, description="YAML — yaml-language-server"),
    ServerDef("lua-language-server", (".lua",), _root_lua, _spawn_lua_ls, description="Lua — lua-language-server"),
    ServerDef("intelephense", (".php",), _root_php, _spawn_intelephense, description="PHP — intelephense"),
    ServerDef("ocaml-lsp", (".ml", ".mli"), _root_ocaml, _spawn_ocamllsp, description="OCaml — ocaml-lsp"),
    ServerDef("dockerfile-ls", (".dockerfile", "Dockerfile"), _root_docker, _spawn_dockerfile_ls, description="Dockerfile — dockerfile-language-server"),
    ServerDef("terraform-ls", (".tf", ".tfvars"), _root_terraform, _spawn_terraform_ls, description="Terraform — terraform-ls"),
    ServerDef("dart", (".dart",), _root_dart, _spawn_dart, description="Dart — built-in language server"),
    ServerDef("haskell-language-server", (".hs", ".lhs"), _root_haskell, _spawn_haskell_ls, description="Haskell — haskell-language-server"),
    ServerDef("julia", (".jl",), _root_julia, _spawn_julia, description="Julia — LanguageServer.jl"),
    ServerDef("clojure-lsp", (".clj", ".cljs", ".cljc", ".edn"), _root_clojure, _spawn_clojure_lsp, description="Clojure — clojure-lsp"),
    ServerDef("nixd", (".nix",), _root_nix, _spawn_nixd, description="Nix — nixd"),
    ServerDef("zls", (".zig", ".zon"), _root_zig, _spawn_zls, description="Zig — zls"),
    ServerDef("gleam", (".gleam",), lambda fp, ws: _root_or_workspace(fp, ws, ["gleam.toml"]), _spawn_gleam, description="Gleam — built-in language server"),
    ServerDef("elixir-ls", (".ex", ".exs"), _root_elixir, _spawn_elixir_ls, description="Elixir — elixir-ls"),
    ServerDef("prisma", (".prisma",), _root_prisma, _spawn_prisma, description="Prisma — built-in language server"),
    ServerDef("kotlin-language-server", (".kt", ".kts"), _root_kotlin, _spawn_kotlin_ls, description="Kotlin — kotlin-language-server"),
    ServerDef("jdtls", (".java",), _root_java, _spawn_jdtls, description="Java — Eclipse JDT Language Server"),
    ServerDef("powershell", (".ps1", ".psm1", ".psd1"), _root_powershell, lambda r, c: None, description="PowerShell — PowerShellEditorServices (manual)"),
]


def find_server_for_file(file_path: str) -> Optional[ServerDef]:
    """Return the registry entry that handles ``file_path``, or None."""
    for srv in SERVERS:
        if srv.matches(file_path):
            return srv
    return None


def language_id_for(path: str) -> str:
    """Return the LSP languageId to send in didOpen for ``path``."""
    ext = _file_ext_or_basename(path)
    return LANGUAGE_BY_EXT.get(ext, "plaintext")


__all__ = [
    "ServerDef",
    "ServerContext",
    "SpawnSpec",
    "SERVERS",
    "find_server_for_file",
    "language_id_for",
    "LANGUAGE_BY_EXT",
]
