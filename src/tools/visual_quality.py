"""Cheap deterministic screenshot-quality receipts.

A file existing is transport evidence, not UI evidence. This module rejects
near-uniform captures before the runtime may classify browser verification as
passed. It is intentionally model-free and safe to run in the browser tool.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def analyze_screenshot(path: str | Path) -> dict[str, Any]:
    try:
        from PIL import Image, ImageFilter, ImageStat
    except Exception as exc:
        return {"available": False, "passed": False, "reason": f"Pillow unavailable: {exc}"}

    try:
        with Image.open(path) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            sample = rgb.copy()
            sample.thumbnail((160, 100))
            pixels = max(1, sample.width * sample.height)
            quantized = sample.quantize(colors=16)
            colors = quantized.getcolors(maxcolors=256) or []
            dominant = max((count for count, _ in colors), default=pixels)
            dominant_ratio = dominant / pixels

            gray = sample.convert("L")
            stddev = float(ImageStat.Stat(gray).stddev[0])
            edges = gray.filter(ImageFilter.FIND_EDGES)
            edge_mean = float(ImageStat.Stat(edges).mean[0]) / 255.0

            # A legitimate UI can be dark or light, but it should not be almost
            # entirely one color with negligible structure. Text on an otherwise
            # empty canvas is still weak visual proof and is rejected here.
            near_blank = dominant_ratio >= 0.97 and (stddev < 28.0 or edge_mean < 0.025)
            return {
                "available": True,
                "passed": not near_blank,
                "width": width,
                "height": height,
                "dominant_ratio": round(dominant_ratio, 4),
                "luma_stddev": round(stddev, 2),
                "edge_density": round(edge_mean, 4),
                "reason": "near-uniform/low-detail capture" if near_blank else "meaningful visual variation",
            }
    except Exception as exc:
        return {"available": True, "passed": False, "reason": f"image analysis failed: {exc}"}


def format_quality_receipt(quality: dict[str, Any]) -> str:
    metrics = (
        f"dominant={quality.get('dominant_ratio', 'n/a')}, "
        f"luma_stddev={quality.get('luma_stddev', 'n/a')}, "
        f"edge_density={quality.get('edge_density', 'n/a')}"
    )
    if quality.get("passed"):
        return f"VISUAL QUALITY PASSED ({metrics})."
    return f"VISUAL QUALITY FAILED: {quality.get('reason', 'insufficient evidence')} ({metrics})."
