"""Every Seti file glyph has its own Crusor icon, and the theme is the default.

Color variants of the same Seti glyph (``_light``, ``_1``) may share that
glyph's PNG. Two different glyphs must not.
"""
from __future__ import annotations

import hashlib
import json
import struct
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORK = ROOT / "desktop" / "vscode"
SETI = FORK / "extensions" / "theme-seti" / "icons" / "vs-seti-icon-theme.json"
THEME = FORK / "extensions" / "theme-crusor-icons" / "fileicons" / "crusor-icon-theme.json"
IMAGES = FORK / "extensions" / "theme-crusor-icons" / "fileicons" / "images"
THEME_SERVICE = FORK / "src" / "vs" / "workbench" / "services" / "themes"


def _load() -> tuple[dict, dict]:
    return (
        json.loads(SETI.read_text(encoding="utf-8")),
        json.loads(THEME.read_text(encoding="utf-8")),
    )


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
    return struct.unpack(">II", data[16:24])


def _unique_glyphs(seti: dict) -> dict[str, str]:
    """Map each non-light Seti font character to one primary icon name."""
    groups: dict[str, list[str]] = defaultdict(list)
    for name, spec in seti["iconDefinitions"].items():
        if name.endswith("_light"):
            continue
        groups[spec["fontCharacter"]].append(name.lstrip("_"))
    primary: dict[str, str] = {}
    for char, names in groups.items():
        primary[char] = sorted(names, key=lambda n: (n[-1].isdigit(), len(n), n))[0]
    return primary


def _image_for(theme: dict, icon_id: str) -> str:
    spec = theme["iconDefinitions"][icon_id]
    return spec["iconPath"].split("/")[-1]


def test_crusor_is_the_default_file_icon_theme():
    common = (THEME_SERVICE / "common" / "workbenchThemeService.ts").read_text(encoding="utf-8")
    browser = (THEME_SERVICE / "browser" / "workbenchThemeService.ts").read_text(encoding="utf-8")
    assert "export const FILE_ICON_THEME = 'crusor';" in common
    assert "DEFAULT_FILE_ICON_THEME_ID = 'crusorai.theme-crusor-icons-crusor';" in browser
    package = json.loads(
        (FORK / "extensions" / "theme-crusor-icons" / "package.json").read_text(encoding="utf-8")
    )
    theme = package["contributes"]["iconThemes"][0]
    assert package["publisher"] == "crusorai"
    assert package["name"] == "theme-crusor-icons"
    assert theme["id"] == "crusor"


def test_every_unique_seti_glyph_has_its_own_png():
    seti, theme = _load()
    glyphs = _unique_glyphs(seti)
    assert len(glyphs) == 151

    used: dict[str, str] = {}
    hashes: dict[str, str] = {}
    for char, name in glyphs.items():
        icon_id = f"_{name}"
        assert icon_id in theme["iconDefinitions"], f"{icon_id} missing from Crusor theme"
        filename = _image_for(theme, icon_id)
        path = IMAGES / filename
        assert path.is_file(), f"{name} -> missing {path}"
        assert _png_size(path) == (128, 128), f"{filename} is not 128x128"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert filename not in used or used[filename] == name, (
            f"{name} shares {filename} with {used.get(filename)}"
        )
        assert digest not in hashes or hashes[digest] == filename, (
            f"{filename} is a byte-for-byte copy of {hashes.get(digest)}"
        )
        used[filename] = name
        hashes[digest] = filename
        assert filename != "default.png" or name == "default"

    assert len(used) == 151
    assert (IMAGES / "folder.png").is_file()
    assert (IMAGES / "folder-open.png").is_file()
    assert hashlib.sha256((IMAGES / "folder.png").read_bytes()).hexdigest() != hashlib.sha256(
        (IMAGES / "folder-open.png").read_bytes()
    ).hexdigest()


def test_no_definition_borrows_another_glyphs_file():
    seti, theme = _load()
    char_of: dict[str, str] = {}
    for name, spec in seti["iconDefinitions"].items():
        if name.endswith("_light"):
            continue
        char_of[name.lstrip("_")] = spec["fontCharacter"]

    file_owner: dict[str, str] = {}
    for icon_id, spec in theme["iconDefinitions"].items():
        if icon_id in {"_folder", "_folder-open"}:
            continue
        bare = icon_id.lstrip("_").removesuffix("_light")
        filename = spec["iconPath"].split("/")[-1]
        assert (IMAGES / filename).is_file(), f"{icon_id} points at missing {filename}"
        glyph = char_of.get(bare)
        assert glyph is not None, f"{icon_id} is not a known Seti glyph"
        previous = file_owner.setdefault(filename, glyph)
        assert previous == glyph, f"{filename} is used by both {previous!r} and {glyph!r}"
        if icon_id not in {"_default", "_default_light"}:
            assert filename != "default.png", icon_id


def test_every_seti_association_resolves():
    seti, theme = _load()
    referenced: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"fontCharacter", "fontColor", "fontId", "fontSize", "iconPath"}:
                    continue
                if isinstance(value, str) and value.startswith("_"):
                    referenced.add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for key in ("file", "fileExtensions", "fileNames", "languageIds", "light"):
        walk(seti[key])

    missing = sorted(icon_id for icon_id in referenced if icon_id not in theme["iconDefinitions"])
    assert missing == []
    assert set(seti["languageIds"]) <= set(theme["languageIds"])
    assert set(seti["fileExtensions"]) <= set(theme["fileExtensions"])
    assert set(seti["fileNames"]) <= set(theme["fileNames"])

    for icon_id, spec in theme["iconDefinitions"].items():
        assert (IMAGES / spec["iconPath"].split("/")[-1]).is_file()
        if icon_id not in {"_default", "_default_light"}:
            assert not spec["iconPath"].endswith("/default.png"), icon_id


def test_approved_marks_are_distinct():
    _seti, theme = _load()
    wanted = {
        "markdown": "_markdown",
        "python": "_python",
        "javascriptreact": "_react",
        "typescriptreact": "_react",
        "rust": "_rust",
        "java": "_java",
    }
    files = []
    for lang, icon_id in wanted.items():
        assert theme["languageIds"][lang] == icon_id
        files.append(_image_for(theme, icon_id))
    # git is a filename/extension icon, not a language id
    files.append(_image_for(theme, "_git"))
    files.append(_image_for(theme, "_image"))
    assert len(set(files)) == len(files) - 1  # both react mappings share _react, everything else is unique
    assert _image_for(theme, "_go") != _image_for(theme, "_go2")
    assert _image_for(theme, "_jade") != _image_for(theme, "_pug")
    assert _image_for(theme, "_cu") != _image_for(theme, "_cpp")
    assert _image_for(theme, "_npm_ignored") != _image_for(theme, "_npm")
