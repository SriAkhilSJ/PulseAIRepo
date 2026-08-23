#!/usr/bin/env python3
"""
Generate the PulseAI Dark color theme from the fork's built-in "Dark 2026" theme.

Why generated instead of hand-written:
  * Dark 2026 defines 298 workbench colors. Hand-authoring drifts and misses keys,
    which is how forks end up with stray upstream teal in odd corners of the UI.
  * Regenerating is the supported way to re-sync when the upstream pin moves.

Transform:
  1. Surfaces  -> true black.  The grey ramp (#121314 / #191A1B / #202122 / ...)
     is pushed down to #000000 and near-black elevation planes.
  2. Accents   -> Pulse blue.  Dark 2026's teal family (#3994BC / #297AA0 / ...)
     is remapped to the Pulse blue ramp, alpha suffixes preserved.
  3. Everything else (syntax token colors, semantic states: red/green/amber)
     is inherited untouched.

Usage:
    python3 scripts/generate_pulseai_theme.py
Writes:
    desktop/vscode/extensions/theme-defaults/themes/pulseai-dark.json
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
THEMES = REPO / "desktop/vscode/extensions/theme-defaults/themes"
SOURCE = THEMES / "2026-dark.json"
TARGET = THEMES / "pulseai-dark.json"

# --- 1. Surface ramp: Dark 2026 grey -> Pulse true black -------------------
#     Keep a small amount of elevation so panes/tabs/hovers stay legible.
SURFACES = {
    "#121314": "#000000",  # editor background          -> true black
    "#191A1B": "#000000",  # chrome (activity/side/status/title/panel/tabs)
    "#202122": "#0A0A0A",  # raised chrome (inactive tab, dropdown, widget)
    "#242526": "#101010",  # hover / secondary button
    "#2A2B2C": "#1A1A1A",  # borders + separators (most common, x27)
    "#333536": "#202020",  # stronger border / scrollbar
    "#1E1F20": "#080808",
    "#2D2E2F": "#1C1C1C",
    "#0F1011": "#000000",
    "#1A1B1C": "#050505",
}

# --- 2. Accent ramp: Dark 2026 teal -> Pulse blue --------------------------
#     Matched by RGB prefix so any #RRGGBB + alpha suffix carries through.
ACCENTS = {
    "3994BC": "3B82F6",  # primary accent (focus border, links, badges)
    "3A94BC": "3B82F6",
    "297AA0": "2563EB",  # button background
    "307E9F": "2563EB",  # activity bar badge
    "2B7DA3": "2563EB",
    "48A0C7": "60A5FA",  # text link
    "53A5CA": "60A5FA",
    "5BA8CC": "60A5FA",
    "488FAE": "3B82F6",
    "276782": "1D4ED8",  # selection / inactive selection
    "1C546F": "172554",  # deep accent wash
    "1E3A47": "0C1A30",  # subtle accent surface
    "59A4F9": "60A5FA",  # already-blue: normalise onto the Pulse ramp
    "58A4F9": "60A5FA",
    "57A3F8": "60A5FA",
}

HEX = re.compile(r"#([0-9A-Fa-f]{6})([0-9A-Fa-f]{2})?\b")


def remap(value: str) -> str:
    """Remap one #RRGGBB[AA] literal, preserving any alpha suffix."""

    def sub(m: re.Match[str]) -> str:
        rgb = m.group(1).upper()
        alpha = m.group(2) or ""
        full = f"#{rgb}"
        if full in SURFACES:
            return SURFACES[full] + alpha
        if rgb in ACCENTS:
            return f"#{ACCENTS[rgb]}{alpha}"
        return m.group(0)

    return HEX.sub(sub, value)


def load_jsonc(path: Path) -> dict:
    """VS Code theme files are JSONC: strip line comments and trailing commas."""
    raw = path.read_text(encoding="utf-8")
    raw = re.sub(r"^\s*//.*$", "", raw, flags=re.M)
    raw = re.sub(r",(\s*[}\]])", r"\1", raw)
    return json.loads(raw, strict=False)


def main() -> None:
    theme = load_jsonc(SOURCE)

    colors = {k: remap(v) if isinstance(v, str) else v
              for k, v in theme.get("colors", {}).items()}

    # --- 3. Explicit overrides: the pixels that define the brand -----------
    colors.update({
        # True-black chrome, hairline seams
        "editor.background": "#000000",
        "sideBar.background": "#000000",
        "activityBar.background": "#000000",
        "statusBar.background": "#000000",
        "titleBar.activeBackground": "#000000",
        "titleBar.inactiveBackground": "#000000",
        "panel.background": "#000000",
        "terminal.background": "#000000",
        "editorGroupHeader.tabsBackground": "#000000",
        "breadcrumb.background": "#000000",
        "tab.inactiveBackground": "#000000",
        "tab.activeBackground": "#0A0A0A",
        "sideBarSectionHeader.background": "#000000",
        "menu.background": "#0A0A0A",
        "quickInput.background": "#0A0A0A",
        "editorWidget.background": "#0A0A0A",
        "dropdown.background": "#0A0A0A",
        "input.background": "#0A0A0A",
        "widget.border": "#1F1F1F",
        "sideBar.border": "#1A1A1A",
        "panel.border": "#1A1A1A",
        "statusBar.border": "#1A1A1A",
        "titleBar.border": "#1A1A1A",
        "editorGroup.border": "#1A1A1A",
        "contrastBorder": "#00000000",

        # Text: white = emphasis, grey = secondary
        "foreground": "#E8E8E8",
        "editor.foreground": "#E8E8E8",
        "sideBar.foreground": "#BFBFBF",
        "descriptionForeground": "#9B9B9B",
        "disabledForeground": "#6A6A6A",
        "tab.activeForeground": "#FFFFFF",
        "tab.inactiveForeground": "#9B9B9B",
        "statusBar.foreground": "#9B9B9B",
        "titleBar.activeForeground": "#E8E8E8",

        # Blue: the single action accent
        "button.background": "#3B82F6",
        "button.foreground": "#FFFFFF",
        "button.hoverBackground": "#5B9BFF",
        "button.secondaryBackground": "#1A1A1A",
        "button.secondaryForeground": "#E8E8E8",
        "button.secondaryHoverBackground": "#252525",
        "focusBorder": "#3B82F6",
        "textLink.foreground": "#60A5FA",
        "textLink.activeForeground": "#93B4F5",
        "progressBar.background": "#3B82F6",
        "activityBarBadge.background": "#3B82F6",
        "activityBarBadge.foreground": "#FFFFFF",
        "activityBar.activeBorder": "#3B82F6",
        "activityBar.foreground": "#FFFFFF",
        "activityBar.inactiveForeground": "#6A6A6A",
        "badge.background": "#3B82F6",
        "badge.foreground": "#FFFFFF",
        "tab.activeBorderTop": "#3B82F6",
        "statusBarItem.remoteBackground": "#3B82F6",
        "statusBarItem.remoteForeground": "#FFFFFF",
        "list.activeSelectionBackground": "#0C1A30",
        "list.activeSelectionForeground": "#FFFFFF",
        "list.inactiveSelectionBackground": "#101010",
        "list.hoverBackground": "#101010",
        "editor.selectionBackground": "#1D4ED855",
        "editor.lineHighlightBorder": "#141414",
        "scrollbarSlider.background": "#FFFFFF14",
        "scrollbarSlider.hoverBackground": "#FFFFFF22",
        "scrollbarSlider.activeBackground": "#3B82F655",

        # Pulse semantic states (mirror media/pulseAI-tokens.css)
        "charts.blue": "#3B82F6",
        "charts.green": "#3FD68A",
        "charts.yellow": "#F0B64F",
        "charts.red": "#F2646F",
        "charts.purple": "#9B8CFF",
    })

    out = {
        "$schema": theme.get("$schema", "vscode://schemas/color-theme"),
        "name": "PulseAI Dark",
        "type": "dark",
        "semanticHighlighting": theme.get("semanticHighlighting", True),
        "colors": colors,
        "tokenColors": theme.get("tokenColors", []),
    }
    if "include" in theme:
        out["include"] = theme["include"]

    TARGET.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {TARGET.relative_to(REPO)}  ({len(colors)} colors, "
          f"{len(out['tokenColors'])} token rules)")


if __name__ == "__main__":
    main()
