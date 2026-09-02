"""Locate an esbuild that can actually be executed, instead of trusting npm's `.bin` shim.

Two Windows rounds of the Manager verification died on this and on nothing else: the parity lanes ran
`node_modules/.bin/esbuild`, and in a `node_modules` tree installed on another platform that entry is a
POSIX shell script. `subprocess.run(..., shell=False)` cannot exec it, so node never started and the
result was `[WinError 193] %1 is not a valid Win32 application` -- reported as a test failure, with the
code under test never touched. The real executable sits in the platform package
(`@esbuild/win32-x64/esbuild.exe`, or its `bin/` child depending on the esbuild version).

So: probe candidates, believe the probe. `.bin/esbuild.cmd` is in the list because on a matching Windows
host it is the supported entry point; it is filtered out here rather than special-cased, since exec'ing a
batch file without a shell is exactly the failure this module exists to avoid.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# Ordered by "most likely to be the one your npm install produced", cheapest probe first.
_SHIM = ("node_modules/.bin/esbuild", "node_modules/.bin/esbuild.cmd")
_PKG = ("node_modules/@esbuild/{pkg}/bin/esbuild{exe}", "node_modules/@esbuild/{pkg}/esbuild{exe}")
_FALLBACK = ("node_modules/esbuild/bin/esbuild",)


def _usable(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        probe = subprocess.run(
            [str(path), "--version"], capture_output=True, stdin=subprocess.DEVNULL,
            timeout=90, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return False          # WinError 193, a denied exec, a timeout: all mean "not runnable here"
    return probe.returncode == 0


def candidates(webview_root: Path) -> list[Path]:
    exe = ".exe" if _is_windows() else ""
    found = [webview_root / rel for rel in _SHIM]
    packages = sorted(p.name for p in (webview_root / "node_modules" / "@esbuild").glob("*")) if (
        webview_root / "node_modules" / "@esbuild").is_dir() else []
    for rel in _PKG:
        for pkg in packages or ("win32-x64", "linux-x64", "linux-arm64", "darwin-x64", "darwin-arm64"):
            found.append(webview_root / rel.format(pkg=pkg, exe=exe))
    found.extend(webview_root / rel for rel in _FALLBACK)
    return found


def _is_windows() -> bool:
    import os
    return os.name == "nt"


def resolve_esbuild(webview_root: Path) -> Path | None:
    """The first candidate that runs `--version` successfully, or None when nothing on this host does.

    None is a host gap to skip and report -- never a pass, and never a failure blamed on the product.
    """
    return next((path for path in candidates(webview_root) if _usable(path)), None)


def esbuild_or_skip(webview_root: Path) -> Path:
    """For lanes whose whole point is executing bundles: skip with the searched paths in the reason."""
    import pytest
    found = resolve_esbuild(webview_root)
    if found is None:
        tried = ", ".join(str(p.relative_to(webview_root)) for p in candidates(webview_root)[:6])
        pytest.skip(f"no executable esbuild on this host (searched: {tried}) -- host gap, not a pass")
    return found
