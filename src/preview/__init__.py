"""CrusorAI Preview — render the UI the agent built, then fix it by clicking on it.

The product flow this package serves:

1. the Agent surface shows that a **preview is available** (the agent wrote UI files, or started
   a dev server);
2. the user opens it and a **separate desktop window** appears (workbench auxiliary window);
3. that window **renders the UI** — a running dev-server URL, or a static ``.html`` the agent
   wrote in the workspace;
4. one button arms **inspect-and-edit**;
5. hovering **wireframes** the element under the cursor (full outline, corner brackets, edge
   guides, tag/class/size label);
6. clicking opens a **small input panel anchored on that element**;
7. the user types a fix — one, or several across different elements — and the window collects
   them as a pending batch;
8. **Review** opens the sheet, where each fix can be reworded or dropped;
9. **Send to Crusor** hands the batch to the Agent in the main window as one scoped turn, the
   agent edits the real source, and the preview reloads and flashes what changed.

Modules
-------
``inject``
    Pure HTML injection: the overlay ``<script>`` plus the ``<base href>`` that keeps a proxied
    document's assets resolving under the proxy prefix. Idempotent, stdlib only.
``server``
    The loopback preview proxy. Frames any target (dev-server URL or workspace file) with the
    overlay injected, behind a per-target capability token, with framing headers dropped and
    paths confined to the workspace.
``autostart``
    Start (or adopt) the proxy without asking the user for a terminal: the engine calls it the first
    time a session binds the opened folder, windowless, reusing a healthy proxy for the same
    workspace and falling back to a free port if 8931 is taken. ``ensure_stdio`` keeps a windowless
    proxy's output readable in ``<runtime home>/preview/proxy-<session>.log``.
``device``
    The device pane: a live mirror of an attached Android device served by the same proxy
    (multipart ``x-mixed-replace`` frames from ``adb screencap``, normalized tap/swipe/text/key
    input mapped back to real device pixels), so a mobile app can be *looked at* in the preview
    window the way a web page is.
``prompt``
    Batch -> scoped agent prompt -> bridge v2 ``prompt`` frame. This is what turns "click here and
    type" into an edit the agent can actually land: every fix names its element three ways (label,
    selector, grep-able fingerprints) and the batch is explicitly bounded.

The overlay itself and the preview window chrome live with the desktop contribution, because they
ship inside the app and are served from the workbench's own origin:
``desktop/vscode/src/vs/workbench/contrib/crusorai/browser/media/crusor-preview/``.

Nothing here changes Bridge Protocol v2: a preview turn is an ordinary ``prompt`` frame carrying
generated text plus a ``preview_batch`` receipt for the renderer.
"""
from __future__ import annotations

from .inject import INJECT_MARKER, has_overlay, inject_overlay, insert_base, is_html, relax_csp_meta
from .prompt import (
    MAX_PROMPT_CHARS,
    PREVIEW_PROMPT_MARKER,
    build_preview_prompt,
    build_prompt_frame,
    describe_element,
    summarize_batch,
)
from .server import PREVIEW_ASSET_ROOT, PreviewServer, TargetSpec

__all__ = [
    "INJECT_MARKER",
    "MAX_PROMPT_CHARS",
    "PREVIEW_ASSET_ROOT",
    "PREVIEW_PROMPT_MARKER",
    "PreviewServer",
    "TargetSpec",
    "build_preview_prompt",
    "build_prompt_frame",
    "describe_element",
    "has_overlay",
    "inject_overlay",
    "insert_base",
    "is_html",
    "relax_csp_meta",
    "summarize_batch",
]
