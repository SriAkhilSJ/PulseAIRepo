# Crusor Preview — lab

> Setting this up on your own machine (including the full desktop-app flow): see
> [`../CRUSOR_PREVIEW_SETUP.md`](../CRUSOR_PREVIEW_SETUP.md). Launching the desktop app for the
> first time: [`../CRUSOR_PREVIEW_LAUNCH_CHECKS.md`](../CRUSOR_PREVIEW_LAUNCH_CHECKS.md).

Runs the whole preview flow in a browser, with **the real feature code on the path** and only the
model turn mocked. There is no Electron here, so this lab is how the flow is demonstrated and
eyeballed on a machine that cannot launch the desktop app.

```bash
python preview-lab/lab_server.py            # http://127.0.0.1:8931/lab/
python preview-lab/lab_server.py --port 9000 --host 0.0.0.0
```

## The click-through (the nine steps)

1. **Agent UI shows a preview is available.** The mock IDE's Crusor panel carries the "Preview
   available" card and the header chip; both are wired to the same availability the real pane reads.
2. **Click it → a separate window appears.** In the IDE this is a workbench *auxiliary window*
   (`auxiliaryWindowService.open`); the lab floats an equivalent panel labeled as such.
3. **The window renders the UI the agent built.** The agent-built fixture appears inside it, through
   the proxy.
4. **`Edit UI`.** Arms inspect mode; the button shows its armed state.
5–7. **Hover** an element: bounding box, corner brackets, edge guides and a
   `tag · class · width×height` label. **Click**: the element locks and a small panel opens on it.
   Type a fix, `Enter`, and a numbered pin is left behind. Repeat on other elements.
8. **`Review`** opens the sheet: every fix can be reworded or dropped, then **`Send to Crusor`**.
9. **Back in the Agent.** The batch lands on the composer — element chips plus the scoped turn text
   built by `src/preview/prompt.py` — and `Send` runs the (mock) turn, after which the preview
   reloads and flashes the element that changed.

`Reset demo` in the mock title bar clears the mock agent's edits and the runtime sheet.

## What is real, and what is not

| Real (the shipped feature)                                             | Mocked (lab only)                        |
| ---------------------------------------------------------------------- | ---------------------------------------- |
| `media/crusor-preview/index.html` / `preview.css` / `preview.js` — the window chrome, toolbar, viewport presets, pending tray, review sheet | the workbench shell around it (a page, not Code OSS) |
| `media/crusor-preview/overlay/crusor-preview-overlay.js` — the injected inspect/fix overlay      | the auxiliary *window* (a floating panel) |
| `src/preview/server.py` — proxy, capability token, injection, framing-header stripping, redirect policy | the "preview is available" signal, which the lab asserts instead of deriving from tool calls |
| `src/preview/inject.py` — `<base href>`, CSP widening, overlay injection | —                                        |
| `src/preview/prompt.py` — the scoped agent prompt                        | the agent turn (`preview-lab/mock_agent.py`: keyword rules → CSS override sheet) |

The mock agent exists because a lab has no provider and no project to edit. It reads the same
instruction text the real agent would (`make it rounded, blue and bigger` → declarations), writes
them to `preview-lab/.runtime/preview-overrides.css`, and returns a receipt shaped like a real
edit result. Delete that file (or `Reset demo`) to start over.

`demo-app/` is "the UI the agent created": a small landing page with a nav, hero, stat row, feature
cards, CTA band and footer — enough shape that hovering and clicking is a real exercise. Two of its
elements carry `data-crusor-source` / `data-crusor-line`, so the **precise** source-mapping path is
visible (`open-source` in the review sheet opens that file at that line); everything else is found by
fingerprint, which is the path that works on any project with no setup.

## Runtime notes

- `preview-lab/.runtime/` is generated (git-ignored) and holds the mock agent's override sheet.
- The lab binds `0.0.0.0` so it is reachable from another host (an E2B/sandbox preview); in the IDE
  the proxy stays on `127.0.0.1` and the token gate is what keeps it private.
- Colors in `workbench.css` are the CrusorAI Dark seeds and the values
  `contrib/crusorai/browser/crusorTheme.ts` derives from them, computed offline and documented in
  that file's header — the lab has no workbench theme to derive from at runtime. The preview window
  and the overlay take their palette from the host at runtime, exactly as they do in the IDE.

## Tests

The lab is a demonstration, not the verification. Behavior is pinned by the suite:

```bash
python -m pytest src/tests/test_preview_*.py -q
```
