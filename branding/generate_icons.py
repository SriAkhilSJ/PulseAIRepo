#!/usr/bin/env python3
"""Generate CrusorAI IDE platform icons from the canonical logo.

The canonical source of truth is ``branding/crusorai-mark.png`` (the uploaded
CrusorAI logo: a silver monochrome mark on a black square, 1536x1536).
This script derives every platform asset consumed by the canonical fork
(``desktop/vscode/resources/``) from that single PNG. Pillow is required
only for this branding generation step.
"""
from __future__ import annotations

from pathlib import Path
import shutil

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "branding"
DESKTOP = ROOT / "desktop" / "vscode" / "resources"
SCALE_SOURCE = BRANDING / "crusorai-mark.png"
SCALE = 4
SIZE = 1024


def load_mark() -> Image.Image:
    """Load the canonical CrusorAI mark (opaque, square)."""
    source = Image.open(SCALE_SOURCE)
    if source.mode != "RGBA":
        source = source.convert("RGBA")
    return source


def save_png(source: Image.Image, path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    source.resize((size, size), Image.Resampling.LANCZOS).save(path, optimize=True)


def main() -> None:
    source = load_mark()
    generated = BRANDING / "generated"
    save_png(source, generated / "crusorai-mark-1024.png", 1024)
    save_png(source, generated / "crusorai-mark-512.png", 512)
    save_png(source, generated / "crusorai-mark-256.png", 256)

    save_png(source, DESKTOP / "linux" / "code.png", 512)
    save_png(source, DESKTOP / "server" / "code-192.png", 192)
    save_png(source, DESKTOP / "server" / "code-512.png", 512)
    save_png(source, DESKTOP / "win32" / "code_150x150.png", 150)
    save_png(source, DESKTOP / "win32" / "code_70x70.png", 70)

    (DESKTOP / "win32").mkdir(parents=True, exist_ok=True)
    source.save(
        DESKTOP / "win32" / "code.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    (DESKTOP / "server").mkdir(parents=True, exist_ok=True)
    source.save(
        DESKTOP / "server" / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )
    (DESKTOP / "darwin").mkdir(parents=True, exist_ok=True)
    source.save(
        DESKTOP / "darwin" / "code.icns",
        format="ICNS",
        sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)],
    )

    (DESKTOP / "crusorai").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BRANDING / "crusorai-mark.svg", DESKTOP / "crusorai" / "crusorai-mark.svg")


if __name__ == "__main__":
    main()
