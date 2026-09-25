#!/usr/bin/env python3
"""Cut the approved Crusor file-icon sheets into a VS Code icon theme.

Source sheets live in branding/file-icon-preview/. The theme consumed by the
fork is written to desktop/vscode/extensions/theme-crusor-icons/.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SHEET_DIR = ROOT / "branding" / "file-icon-preview"
EXT = ROOT / "desktop" / "vscode" / "extensions" / "theme-crusor-icons"
IMG = EXT / "fileicons" / "images"
SETI = ROOT / "desktop" / "vscode" / "extensions" / "theme-seti" / "icons" / "vs-seti-icon-theme.json"
SHEETS = {
    "crusor-seti-style-sheet-v3.png": [
        "default", "javascript", "typescript", "react", "python", "html_3", "css", "json",
        "markdown", "rust", "go2", "java", "c", "cpp", "c-sharp", "shell",
        "yml", "php", "ruby", "vue", "docker", "git", "svg", "image",
        "sass", "kotlin", "swift", "lua", "xml", "db", "wasm", "dart",
    ],
    "crusor-seti-rest-2.png": [
        "config", "lock", "npm", "yarn", "makefile", "notebook", "pdf", "video",
        "audio", "powershell", "scala", "haskell", "elixir", "perl", "svelte", "graphql",
        "prisma", "terraform", "webpack", "vite", "github", "gitlab", "less", "stylus",
        "coffee", "clojure", "julia", "R", "csv", "license", "zip", "font",
    ],
    "crusor-seti-rest-3.png": [
        "gradle", "maven", "spring", "jenkins", "godot", "f-sharp", "ocaml", "nim",
        "zig", "elm", "reasonml", "rescript", "purescript", "haxe", "vala", "crystal",
        "d", "asm", "bicep", "bazel", "eslint", "stylelint", "rollup", "gulp",
        "todo", "tsconfig", "html_erb", "jinja", "ejs", "mustache", "pug", "haml",
    ],
    "crusor-seti-rest-4.png": [
        "twig", "liquid", "nunjucks", "cake", "clock", "ignored", "info", "illustrator",
        "photoshop", "word", "xls", "windows", "firefox", "heroku", "ionic", "salesforce",
        "firebase", "hex", "wat", "pipeline", "puppet", "prolog", "smarty", "slim",
        "livescript", "hacklang", "tex", "sublime", "platformio", "karma", "code-search", "bower",
    ],
}

# Color-variant and near-duplicate Seti ids that share one Crusor glyph.
ALIASES = {
    "html": "html_3",
    "html_1": "html_3",
    "html_2": "html_3",
    "go": "go2",
    "docker_1": "docker",
    "docker_2": "docker",
    "docker_3": "docker",
    "javascript_1": "javascript",
    "javascript_2": "javascript",
    "java_1": "java",
    "json_1": "json",
    "react_1": "react",
    "typescript_1": "typescript",
    "c_1": "c",
    "c_2": "c",
    "cpp_1": "cpp",
    "cpp_2": "cpp",
    "db_1": "db",
    "svg_1": "svg",
    "zip_1": "zip",
    "license_1": "license",
    "license_2": "license",
    "makefile_1": "makefile",
    "makefile_2": "makefile",
    "makefile_3": "makefile",
    "npm_1": "npm",
    "eslint_1": "eslint",
    "stylelint_1": "stylelint",
    "haxe_1": "haxe",
    "haxe_2": "haxe",
    "haxe_3": "haxe",
    "godot_1": "godot",
    "godot_2": "godot",
    "godot_3": "godot",
    "tex_1": "tex",
    "tex_2": "tex",
    "tex_3": "tex",
    "clock_1": "clock",
    "clojure_1": "clojure",
    "bazel_1": "bazel",
    "rescript_1": "rescript",
    "cu_1": "cu",
}

# crusor-seti-rest-5.png is not a clean 8×4 grid — the model duplicated a row.
# Cells are (row, column) into that sheet.
REST5_CELLS = {
    "argdown": (0, 0), "babel": (0, 1), "bsl": (0, 2), "code-climate": (0, 3),
    "coldfusion": (0, 4), "ethereum": (0, 5), "favicon": (0, 6), "grails": (0, 7),
    "grunt": (1, 0), "happenings": (1, 1), "mdo": (1, 2), "odata": (1, 3),
    "pddl": (1, 4), "plan": (1, 5), "sbt": (1, 6), "wgt": (1, 7),
    "cake_php": (2, 0), "crystal_embedded": (2, 1), "cu": (2, 2), "elixir_script": (2, 3),
    "go": (2, 4), "jade": (2, 5), "npm_ignored": (3, 7),
}


def dist(c, bg) -> int:
    return abs(c[0] - bg[0]) + abs(c[1] - bg[1]) + abs(c[2] - bg[2])


def sheet_bg(im: Image.Image) -> tuple[int, int, int]:
    px = im.load()
    w, h = im.size
    samples = [px[4, 4], px[w - 5, 4], px[4, h - 5], px[w - 5, h - 5], px[w // 2, 4]]
    return tuple(sum(c[i] for c in samples) // len(samples) for i in range(3))


def key_and_fit(crop: Image.Image, bg: tuple[int, int, int]) -> Image.Image:
    cp = crop.load()
    w, h = crop.size
    for y in range(h):
        for x in range(w):
            r, g, b, _a = cp[x, y]
            d = dist((r, g, b), bg)
            if d < 26:
                cp[x, y] = (r, g, b, 0)
            elif d < 52:
                cp[x, y] = (r, g, b, int(255 * (d - 26) / 26))
    canvas = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    scale = 108 / max(crop.size)
    nw, nh = max(1, int(crop.size[0] * scale)), max(1, int(crop.size[1] * scale))
    glyph = crop.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas.paste(glyph, ((128 - nw) // 2, (128 - nh) // 2), glyph)
    return canvas


def extract_sheet(path: Path, names: list[str] | dict[str, tuple[int, int]]) -> dict[str, Image.Image]:
    im = Image.open(path).convert("RGBA")
    bg = sheet_bg(im)
    w, h = im.size
    cols, rows = 8, 4
    cw, rh = w / cols, h / rows
    px = im.load()
    icons: dict[str, Image.Image] = {}
    items = names.items() if isinstance(names, dict) else ((name, divmod(i, cols)) for i, name in enumerate(names))
    for name, (r, c) in items:
        x0, x1 = int(c * cw + cw * 0.06), int((c + 1) * cw - cw * 0.06)
        y0, y1 = int(r * rh + rh * 0.04), int(r * rh + rh * 0.64)
        minx, miny, maxx, maxy = x1, y1, x0, y0
        found = False
        for y in range(y0, y1):
            for x in range(x0, x1):
                if dist(px[x, y][:3], bg) > 34:
                    found = True
                    minx, miny = min(minx, x), min(miny, y)
                    maxx, maxy = max(maxx, x), max(maxy, y)
        if not found:
            raise SystemExit(f"no pixels for {name} in {path.name}")
        pad = 4
        crop = im.crop((max(0, minx - pad), max(0, miny - pad), min(w, maxx + pad + 1), min(h, maxy + pad + 1)))
        icons[name] = key_and_fit(crop, bg)
    return icons


def folder_icon(open_: bool) -> Image.Image:
    """Filled folder. The cyan cap is thick enough to survive a 16px explorer slot."""
    im = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cyan = (34, 211, 238, 255)
    silver = (226, 226, 226, 255)
    shade = (150, 156, 162, 255)
    if not open_:
        d.rounded_rectangle((16, 8, 64, 40), radius=8, fill=cyan)
        d.rounded_rectangle((8, 32, 120, 120), radius=10, fill=silver)
        d.rectangle((8, 32, 120, 56), fill=cyan)
        d.pieslice((8, 32, 28, 52), 180, 270, fill=cyan)
        d.pieslice((100, 32, 120, 52), 270, 360, fill=cyan)
    else:
        d.rounded_rectangle((16, 4, 64, 36), radius=8, fill=cyan)
        d.rounded_rectangle((8, 24, 120, 64), radius=10, fill=shade)
        d.rectangle((8, 24, 120, 48), fill=cyan)
        d.pieslice((8, 24, 28, 44), 180, 270, fill=cyan)
        d.pieslice((100, 24, 120, 44), 270, 360, fill=cyan)
        d.rounded_rectangle((8, 56, 120, 120), radius=10, fill=silver)
    return im


def filename(name: str) -> str:
    return name.lower().replace(" ", "-") + ".png"


def collect_ids(node, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"fontCharacter", "fontColor", "fontId", "fontSize"}:
                continue
            if isinstance(value, str) and value.startswith("_"):
                found.add(value)
            else:
                collect_ids(value, found)
    elif isinstance(node, list):
        for item in node:
            collect_ids(item, found)


def resolve(icon_id: str, have: set[str]) -> str:
    name = icon_id[1:]
    if name.endswith("_light"):
        name = name[: -len("_light")]
    seen = set()
    while name not in have and name not in seen:
        seen.add(name)
        name = ALIASES.get(name, "")
        if not name:
            return "default"
    return name if name in have else "default"


def main() -> None:
    IMG.mkdir(parents=True, exist_ok=True)
    icons: dict[str, Image.Image] = {}
    for sheet, names in SHEETS.items():
        icons.update(extract_sheet(SHEET_DIR / sheet, names))
    icons.update(extract_sheet(SHEET_DIR / "crusor-seti-rest-5.png", REST5_CELLS))
    icons["folder"] = folder_icon(False)
    icons["folder-open"] = folder_icon(True)

    for name, image in icons.items():
        image.save(IMG / filename(name), optimize=True)

    seti = json.loads(SETI.read_text())
    have = set(icons)
    used: set[str] = set()
    collect_ids({k: seti[k] for k in ("file", "fileExtensions", "fileNames", "languageIds", "light") if k in seti}, used)

    definitions = {
        "_folder": {"iconPath": "./images/folder.png"},
        "_folder-open": {"iconPath": "./images/folder-open.png"},
    }
    unresolved = []
    for icon_id in sorted(used):
        target = resolve(icon_id, have)
        if target == "default" and icon_id.lstrip("_").removesuffix("_light") not in have and icon_id.lstrip("_").removesuffix("_light") not in ALIASES:
            unresolved.append(icon_id)
        definitions[icon_id] = {"iconPath": f"./images/{filename(target)}"}

    theme = {
        "iconDefinitions": definitions,
        "file": "_default",
        "folder": "_folder",
        "folderExpanded": "_folder-open",
        "fileExtensions": seti.get("fileExtensions", {}),
        "fileNames": seti.get("fileNames", {}),
        "languageIds": seti.get("languageIds", {}),
        "light": seti.get("light", {}),
        "showLanguageModeIcons": True,
        "hidesExplorerArrows": False,
    }
    theme_path = EXT / "fileicons" / "crusor-icon-theme.json"
    theme_path.write_text(json.dumps(theme, indent="\t") + "\n")
    print(f"icons {len(icons)} definitions {len(definitions)} unresolved {len(unresolved)}")
    if unresolved:
        print("unresolved", ", ".join(unresolved))


if __name__ == "__main__":
    main()
