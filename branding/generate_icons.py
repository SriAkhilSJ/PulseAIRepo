#!/usr/bin/env python3
"""Generate PulseAI IDE platform icons from the canonical vector geometry."""
from __future__ import annotations

from pathlib import Path
import shutil

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "branding"
DESKTOP = ROOT / "desktop" / "resources"
UI_PUBLIC = ROOT / "ui" / "public"
SCALE = 4
SIZE = 1024


def scaled(value: int) -> int:
    return value * SCALE


def render_mark() -> Image.Image:
    size = scaled(SIZE)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (scaled(42), scaled(42), scaled(982), scaled(982)),
        radius=scaled(224),
        fill="#071118",
    )
    draw.rounded_rectangle(
        (scaled(62), scaled(62), scaled(962), scaled(962)),
        radius=scaled(204),
        outline="#245461",
        width=scaled(8),
    )
    points = [(scaled(x), scaled(y)) for x, y in [
        (164, 536), (292, 536), (372, 306), (486, 746),
        (584, 382), (672, 552), (860, 552),
    ]]
    draw.line(points, fill="#22D3EE", width=scaled(54), joint="curve")
    for x, y in points:
        draw.ellipse(
            (x - scaled(27), y - scaled(27), x + scaled(27), y + scaled(27)),
            fill="#22D3EE",
        )

    highlight = Image.new("RGBA", image.size, (0, 0, 0, 0))
    highlight_draw = ImageDraw.Draw(highlight)
    highlight_draw.line(points, fill=(217, 250, 255, 86), width=scaled(8), joint="curve")
    image = Image.alpha_composite(image, highlight)

    draw = ImageDraw.Draw(image)
    draw.ellipse(
        (scaled(830), scaled(522), scaled(890), scaled(582)),
        fill="#9B8CFF",
    )
    draw.ellipse(
        (scaled(848), scaled(540), scaled(872), scaled(564)),
        fill="#F5F3FF",
    )
    return image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def save_png(source: Image.Image, path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    source.resize((size, size), Image.Resampling.LANCZOS).save(path, optimize=True)


def main() -> None:
    source = render_mark()
    generated = BRANDING / "generated"
    save_png(source, generated / "pulseai-mark-1024.png", 1024)
    save_png(source, generated / "pulseai-mark-512.png", 512)
    save_png(source, generated / "pulseai-mark-256.png", 256)

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

    (DESKTOP / "pulseai").mkdir(parents=True, exist_ok=True)
    UI_PUBLIC.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(BRANDING / "pulseai-mark.svg", DESKTOP / "pulseai" / "pulseai-mark.svg")
    shutil.copyfile(BRANDING / "pulseai-mark.svg", UI_PUBLIC / "pulseai-mark.svg")


if __name__ == "__main__":
    main()
