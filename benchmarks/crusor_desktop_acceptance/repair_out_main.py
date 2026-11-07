"""Restore desktop/vscode/out/main.js to the semantics of src/main.ts.

The checkout's gitignored build artifact `out/main.js` was hand-patched with an
Electron *stub fallback* (a fake `app`/`protocol`/`crashReporter`/`Menu`/
`contentTracing` with no-op methods). `src/main.ts` — the source of truth —
just imports them from 'electron'.

Consequences of the stub when the real module is not detected:
  * `protocol.registerSchemesAsPrivileged` becomes a no-op, so `vscode-file://`
    is never registered and `loadURL()` produces NO renderer process (the
    workbench window never materialises, /json/list stays empty);
  * `app.commandLine.appendSwitch` becomes a no-op, so launch switches such as
    `--remote-debugging-port` are dropped;
  * the shim's `electron` object lacks session APIs, so
    `webContents.session.setProxy` throws during window construction.

The file is gitignored (`desktop/vscode/.gitignore: /out/*`) and is not part of
any tracked source, so this repair changes no source file, no manifest entry and
no Invariant 7 surface. A backup of the patched artifact is kept alongside.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

MAIN_JS = Path(__file__).resolve().parents[2] / "desktop" / "vscode" / "out" / "main.js"
CANONICAL_IMPORT = 'import { app, protocol, crashReporter, Menu, contentTracing } from "electron";'
START_MARKER = 'import electronModule from "electron";'


def main() -> int:
    text = MAIN_JS.read_text(encoding="utf-8")
    lines = text.splitlines()

    if START_MARKER not in text:
        print("[restore] out/main.js already matches the canonical import — nothing to do")
        return 0

    start = lines.index(START_MARKER)
    # The shim ends at the closing brace of the contentTracing stub, immediately
    # before the next `import` statement.
    end = start + 1
    while end < len(lines) and not lines[end].startswith("import "):
        end += 1
    removed = end - start

    backup = MAIN_JS.with_suffix(".js.patched-shim.bak")
    if not backup.exists():
        shutil.copy2(MAIN_JS, backup)
        print(f"[restore] backup written: {backup.name}")

    restored = lines[:start] + [CANONICAL_IMPORT] + lines[end:]
    MAIN_JS.write_text("\n".join(restored) + "\n", encoding="utf-8")
    print(f"[restore] replaced {removed} shim line(s) with the canonical electron import")
    print(f"[restore] byte size now: {MAIN_JS.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
