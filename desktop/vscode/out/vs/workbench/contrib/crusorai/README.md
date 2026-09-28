# CrusorAI Workbench Contribution

First-party Code OSS home for CrusorAI IDE.

```text
crusorai/
├── browser/           Agent View, Crusor Manager, shared renderer/host, native adapters
├── common/            protocol, renderer, tool-catalog, capability, and worker contracts
├── electron-browser/  desktop utility-worker engine client and registration
└── node/              validated Python process owner and IPC server
```

The compact Agent `ViewPane` and wide Crusor Manager `EditorPane` mount one framework-neutral renderer backed by one singleton Protocol v2 event model. The renderer covers streaming conversation, the 36-tool family catalog, compact disclosures, approvals, plans, verification, telemetry, engine state, and dense composers. A web-safe no-process engine fallback keeps common hosts constructable; the desktop entrypoint replaces it with the utility-process implementation.

The IDE chrome stays VS Code Dark 2026 native-neutral; Crusor contributes semantic colors only (`media/crusorAI-tokens.css`: cyan for running/focus/primary actions, violet for delegation, green for verified, amber for approval/warning, red for failure/destructive). No global workbench chrome is recolored, so user color customizations and high-contrast themes remain authoritative. The renderer uses the same crusor-and-agent-node brand geometry as the packaged platform icons.

Native adapters expose dirty buffers, diagnostics, language providers, trust, diffs/bulk edits, workspace search, SCM, tests, tasks, and terminal execution. The renderer never imports Electron, Node, or those Code OSS internals. No extension manifest or activation event is permitted.

## Crusor Preview

The Agent builds UI; the user needs to *look at it* and say what is wrong with it. Crusor Preview
renders that UI in its own window, lets the user click the element they mean, and hands the resulting
batch back to the Agent as one scoped turn.

```text
1  the Agent UI shows "a preview is available"     browser/crusorAIViewPane.ts (availability chip)
2  clicking it opens a SEPARATE desktop window     browser/crusorAIPreviewService.ts (auxiliary window)
3  that window renders the UI the agent built      media/crusor-preview/index.html frames the proxy
4  one button arms inspect-and-edit                media/crusor-preview/preview.js  (#cpw-inspect)
5  hovering wireframes the element                 media/crusor-preview/overlay/…overlay.js
6  clicking opens a panel anchored on it           (same file: .cp-panel, placed on the element)
7  fixes accumulate, one pin per element           (same file: .cp-pin)
8  Review, then Send to Crusor                     media/crusor-preview/preview.js (tray + sheet)
9  the turn lands on the Agent in the main window   browser/crusorAIPreviewService.ts (prompt frame)
```

The parts that decide whether this works at all:

- **The overlay is injected, not imported.** The previewed page is the user's own — any framework, any
  origin — so a cross-origin parent frame cannot touch its DOM. `src/preview/server.py` proxies the
  target and rewrites the document on the way through: a `<base href>` under the proxy prefix (so the
  page's own assets keep loading) plus the overlay script. The overlay and the window then talk over
  `postMessage`, which needs no shared origin. `src/preview/inject.py` holds that rewrite; it is
  idempotent and pinned by `src/tests/test_preview_inject.py`.
- **The window's chrome is ours, served from our own origin.** `FileAccess.asBrowserUri` on
  `media/crusor-preview/index.html`, the same trick the CopilotKit surface uses: the workbench
  document's CSP frames only `'self'` and `vscode-webview:`, so a frame pointed straight at
  `http://localhost:5173` is refused before the dev server is ever asked. Our page sets its own,
  narrower policy and frames the *proxied* document inside it.
- **The overlay paints with measured contrast.** The wireframe is the feature; the derived accent is a
  mid grey in CrusorAI Dark, and the page under it may be white. The overlay reads the element's own
  backdrop and enforces WCAG 1.4.11 (3:1) with the same lightness-only math as `crusorTheme.ts`, so an
  outline cannot vanish into the page it is describing.
- **A device panel is not a widget.** Nothing is injected into pages the user did not ask to preview,
  the proxy is loopback-only by default with a per-target capability token, file targets are confined
  to the workspace, off-origin redirects are refused rather than followed, and only `GET`/`HEAD` are
  proxied.

The IDE finds the proxy through the handshake file the runtime publishes
(`$CRUSORAI_HOME/preview/<session>.json`, written by `src/preview/endpoint.py`), so no port or token
is ever configured by hand:

```bash
python -m src.preview.server --workspace . --port 8931 --endpoint-session <session-id>
```

The turn itself is an ordinary Bridge Protocol v2 `prompt` frame — no new method, no version bump.
`src/preview/prompt.py` builds the scoped text (element label, CSS selector, grep-able fingerprints,
geometry, current styles, and the scope rules) and carries a `preview_batch` receipt for the
renderer's card. `src/tests/test_preview_contract.py` pins the message literals across the
TypeScript contract, the window chrome and the overlay, and runs the pure halves through node.

To see all of it without the desktop app, run `preview-lab/` (see its README): real window chrome,
real overlay, real proxy, real prompt builder, mock model turn.
