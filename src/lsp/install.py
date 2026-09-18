"""Auto-installation of LSP server binaries.

Tries to install missing servers using whatever package manager is
appropriate.  All installs go to a PulseAI-owned bin staging dir,
``<PULSEAI_HOME>/lsp/bin/``, so we don't pollute the user's global
toolchain.

Strategies:
- ``auto`` — attempt to install with the best available package manager.
- ``manual`` — never install; if a binary is missing, the server is silently skipped.
- ``off`` — same as ``manual`` for now.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("src.lsp.install")

INSTALL_RECIPES: Dict[str, Dict[str, Any]] = {
    "pyright": {"strategy": "npm", "pkg": "pyright", "bin": "pyright-langserver"},
    "typescript-language-server": {
        "strategy": "npm",
        "pkg": "typescript-language-server",
        "bin": "typescript-language-server",
        "extra_pkgs": ["typescript"],
    },
    "@vue/language-server": {
        "strategy": "npm",
        "pkg": "@vue/language-server",
        "bin": "vue-language-server",
    },
    "svelte-language-server": {
        "strategy": "npm",
        "pkg": "svelte-language-server",
        "bin": "svelteserver",
    },
    "@astrojs/language-server": {
        "strategy": "npm",
        "pkg": "@astrojs/language-server",
        "bin": "astro-ls",
    },
    "yaml-language-server": {
        "strategy": "npm",
        "pkg": "yaml-language-server",
        "bin": "yaml-language-server",
    },
    "bash-language-server": {
        "strategy": "npm",
        "pkg": "bash-language-server",
        "bin": "bash-language-server",
    },
    "intelephense": {"strategy": "npm", "pkg": "intelephense", "bin": "intelephense"},
    "dockerfile-language-server-nodejs": {
        "strategy": "npm",
        "pkg": "dockerfile-language-server-nodejs",
        "bin": "docker-langserver",
    },
    "gopls": {"strategy": "go", "pkg": "golang.org/x/tools/gopls@latest", "bin": "gopls"},
    "rust-analyzer": {"strategy": "manual", "pkg": "", "bin": "rust-analyzer"},
    "clangd": {"strategy": "manual", "pkg": "", "bin": "clangd"},
    "lua-language-server": {"strategy": "manual", "pkg": "", "bin": "lua-language-server"},
    "powershell": {"strategy": "manual", "pkg": "", "bin": "pwsh"},
}

_install_locks: Dict[str, threading.Lock] = {}
_install_results: Dict[str, Optional[str]] = {}
_install_lock_meta = threading.Lock()
_WINDOWS_WRAPPER_SUFFIXES = (".cmd", ".exe", ".bat")


def _is_windows() -> bool:
    return os.name == "nt"


def _find_node_executable(name: str) -> Optional[str]:
    """Find node/npm executable, checking common locations."""
    path = shutil.which(name)
    if path:
        return path
    # Check common Node.js install locations on Windows
    if _is_windows():
        for base in [
            os.path.expandvars(r"%ProgramFiles%\nodejs"),
            os.path.expandvars(r"%AppData%\npm"),
        ]:
            candidate = os.path.join(base, name + ".cmd")
            if os.path.isfile(candidate):
                return candidate
            candidate = os.path.join(base, name)
            if os.path.isfile(candidate):
                return candidate
    return None


def pulseai_lsp_bin_dir() -> Path:
    """Return the PulseAI-owned bin staging dir for LSP servers."""
    home = Path(os.environ.get("PULSEAI_HOME", Path.home() / ".pulseai"))
    p = home / "lsp" / "bin"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _native_binary_candidates(base: Path) -> list[Path]:
    """Return platform-native executable candidates for a staged binary."""
    candidates = [base]
    if _is_windows():
        existing = {str(base).lower()}
        for suffix in _WINDOWS_WRAPPER_SUFFIXES:
            candidate = Path(str(base) + suffix)
            key = str(candidate).lower()
            if key not in existing:
                candidates.append(candidate)
                existing.add(key)
    return candidates


def _existing_binary(name: str) -> Optional[str]:
    """Probe the staging dir + PATH for a binary named ``name``."""
    for staged in _native_binary_candidates(pulseai_lsp_bin_dir() / name):
        if staged.exists() and os.access(staged, os.X_OK):
            return str(staged)
    on_path = shutil.which(name)
    if on_path:
        return on_path
    if _is_windows():
        for suffix in _WINDOWS_WRAPPER_SUFFIXES:
            on_path = shutil.which(f"{name}{suffix}")
            if on_path:
                return on_path
    return None


def _get_lock(pkg: str) -> threading.Lock:
    with _install_lock_meta:
        lock = _install_locks.get(pkg)
        if lock is None:
            lock = threading.Lock()
            _install_locks[pkg] = lock
        return lock


def try_install(pkg: str, strategy: str = "auto") -> Optional[str]:
    """Try to install ``pkg`` and return the binary path if successful."""
    if strategy not in {"auto",}:
        recipe = INSTALL_RECIPES.get(pkg, {})
        bin_name = recipe.get("bin", pkg)
        return _existing_binary(bin_name)

    if pkg in _install_results:
        return _install_results[pkg]

    lock = _get_lock(pkg)
    with lock:
        if pkg in _install_results:
            return _install_results[pkg]
        result = _do_install(pkg)
        _install_results[pkg] = result
        return result


def _do_install(pkg: str) -> Optional[str]:
    recipe = INSTALL_RECIPES.get(pkg)
    if recipe is None:
        return shutil.which(pkg)

    strategy = recipe.get("strategy", "manual")
    bin_name = recipe.get("bin", pkg)

    existing = _existing_binary(bin_name)
    if existing:
        return existing

    if strategy == "manual":
        logger.debug("[install] %s requires manual install", pkg)
        return None

    if strategy == "npm":
        return _install_npm(
            recipe.get("pkg", pkg),
            bin_name,
            extra_pkgs=recipe.get("extra_pkgs") or [],
        )
    if strategy == "go":
        return _install_go(recipe.get("pkg", pkg), bin_name)
    if strategy == "pip":
        return _install_pip(recipe.get("pkg", pkg), bin_name)

    logger.warning("[install] unknown strategy %r for %s", strategy, pkg)
    return None


def _get_creationflags() -> int:
    """Return subprocess creation flags for Windows to hide console window."""
    if _is_windows():
        return 0x08000000  # CREATE_NO_WINDOW
    return 0


def _install_npm(
    pkg: str,
    bin_name: str,
    extra_pkgs: Optional[list] = None,
) -> Optional[str]:
    """Install an npm package into our staging dir."""
    npm = _find_node_executable("npm")
    if npm is None:
        logger.info("[install] cannot install %s: no usable npm found", pkg)
        return None
    staging = pulseai_lsp_bin_dir().parent
    install_targets = [pkg] + list(extra_pkgs or [])
    try:
        logger.info(
            "[install] npm install --prefix %s %s",
            staging,
            " ".join(install_targets),
        )
        proc = subprocess.run(
            [npm, "install", "--prefix", str(staging), "--silent", "--no-fund", "--no-audit", *install_targets],
            check=False,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=300,
            stdin=subprocess.DEVNULL,
            creationflags=_get_creationflags(),
        )
        if proc.returncode != 0:
            logger.warning(
                "[install] npm install failed for %s: %s", pkg, proc.stderr.strip()[:500]
            )
            return None
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("[install] npm install errored for %s: %s", pkg, e)
        return None

    nm_bin = staging / "node_modules" / ".bin" / bin_name
    for c in _native_binary_candidates(nm_bin):
        if c.exists():
            link = pulseai_lsp_bin_dir() / c.name
            if not link.exists():
                try:
                    link.symlink_to(c)
                except (OSError, NotImplementedError):
                    try:
                        shutil.copy2(c, link)
                    except OSError:
                        return str(c)
            return str(link if link.exists() else c)
    logger.warning("[install] npm install for %s succeeded but bin %s not found", pkg, bin_name)
    return None


def _install_go(pkg: str, bin_name: str) -> Optional[str]:
    """Install a Go module to GOBIN=<staging>."""
    go = shutil.which("go")
    if go is None:
        logger.info("[install] cannot install %s: go not on PATH", pkg)
        return None
    staging = pulseai_lsp_bin_dir()
    env = dict(os.environ)
    env["GOBIN"] = str(staging)
    try:
        logger.info("[install] go install %s (GOBIN=%s)", pkg, staging)
        proc = subprocess.run(
            [go, "install", pkg],
            check=False,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=600,
            env=env,
            stdin=subprocess.DEVNULL,
            creationflags=_get_creationflags(),
        )
        if proc.returncode != 0:
            logger.warning(
                "[install] go install failed for %s: %s", pkg, proc.stderr.strip()[:500]
            )
            return None
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("[install] go install errored for %s: %s", pkg, e)
        return None
    bin_path = staging / bin_name
    if _is_windows():
        bin_path = bin_path.with_suffix(".exe")
    if bin_path.exists():
        return str(bin_path)
    logger.warning("[install] go install for %s succeeded but bin %s not found", pkg, bin_name)
    return None


def _install_pip(pkg: str, bin_name: str) -> Optional[str]:
    """Install a Python package into a pulseai-owned target dir."""
    pip_target = pulseai_lsp_bin_dir().parent / "python-packages"
    pip_target.mkdir(parents=True, exist_ok=True)
    pip = shutil.which("pip") or shutil.which("pip3")
    if pip is None:
        logger.info("[install] cannot install %s: pip not on PATH", pkg)
        return None
    try:
        logger.info("[install] pip install --target %s %s", pip_target, pkg)
        proc = subprocess.run(
            [pip, "install", "--target", str(pip_target), "--quiet", pkg],
            check=False,
            capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=300,
            stdin=subprocess.DEVNULL,
            creationflags=_get_creationflags(),
        )
        if proc.returncode != 0:
            logger.warning(
                "[install] pip install failed for %s: %s", pkg, (proc.stderr or "").strip()[:500]
            )
            return None
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("[install] pip install errored for %s: %s", pkg, e)
        return None
    script_dirs = [pip_target / "bin"]
    if _is_windows():
        script_dirs.append(pip_target / "Scripts")
    for script_dir in script_dirs:
        for bin_path in _native_binary_candidates(script_dir / bin_name):
            if bin_path.exists():
                link = pulseai_lsp_bin_dir() / bin_path.name
                if not link.exists():
                    try:
                        link.symlink_to(bin_path)
                    except (OSError, NotImplementedError):
                        try:
                            shutil.copy2(bin_path, link)
                        except OSError:
                            return str(bin_path)
                return str(link if link.exists() else bin_path)
    return None


def detect_status(pkg: str) -> str:
    """Return ``installed``, ``missing``, or ``manual-only`` for a package."""
    recipe = INSTALL_RECIPES.get(pkg)
    bin_name = recipe.get("bin", pkg) if recipe else pkg
    if _existing_binary(bin_name):
        return "installed"
    if recipe and recipe.get("strategy") == "manual":
        return "manual-only"
    return "missing"


__all__ = [
    "INSTALL_RECIPES",
    "try_install",
    "detect_status",
    "pulseai_lsp_bin_dir",
]
