# Launch checks — when the IDE fork starts

Run these in order the first time the desktop app runs with Crusor Preview. Each line is something
to *look at*, what a pass looks like, and what a failure means — so nothing here needs me in the
loop to diagnose.

Every check is tagged:

- **[code]** — pinned by the test suite (`python -m pytest src/tests/test_preview_*.py -q` → 61 passed),
  so a failure here means something in the environment or the build, not the logic;
- **[host]** — depends on the real Electron/workbench, and could not be verified before launch.

---

## 0. Before launching

| # | Check | Pass looks like | If it fails |
| --- | --- | --- | --- |
| 0.1 | **[host]** `npm run typecheck-client` in `desktop/vscode` | clean | the only place the preview code has never been compiled. Send me the errors — expect small mechanical fixes (unused imports, `IAuxiliaryWindow` member names) |
| 0.2 | **[code]** `python -m pytest src/tests/test_preview_*.py -q` | `61 passed` | if not, the engine side is broken independently of the app |
| 0.3 | Proxy running for the **same folder** you open in the app | `python -m src.preview.server --workspace <opened folder> --port 8931 --endpoint-session ide` printed an origin and an endpoint path | no endpoint file → the IDE will find no proxy (§2.1) |

---

## 1. The app comes up

| # | Check | Pass looks like | If it fails |
| --- | --- | --- | --- |
| 1.1 | **[host]** Workbench loads, no error dialog | normal window | unrelated to the preview — check `Help → Toggle Developer Tools` console for a module error naming `crusorAIPreviewService` / `crusorAIPreview` |
| 1.2 | **[host]** Crusor panel opens (`Ctrl/Cmd+L`, or Crusor → Open Agent) | the Agent pane renders as before | the preview code only *adds* to this pane; a blank pane means the renderer service (not the preview) broke |
| 1.3 | **[host]** The pane's tab row shows `Agent · Webview · Preview` | Preview chip present, greyed out, tooltip "No preview yet: when Crusor builds UI or starts a dev server, it appears here." | chip missing → the pane change did not compile/apply. Chip present but **hidden** when the CopilotKit webview is off is a bug I fixed in `761a4f98` — confirm you are on that commit or later |
| 1.4 | **[host]** Command palette has **Crusor: Open Crusor Preview** and the Crusor menu has the same entry | command listed, `Crusor → Open Crusor Preview` present | the contribution registration did not apply |

---

## 2. Step 1 — "a preview is available"

| # | Check | Pass looks like | If it fails |
| --- | --- | --- | --- |
| 2.1 | **[host]** Ask Crusor to build UI ("add a hero section and start the dev server") | the Preview chip lights (its dot turns green) and its tooltip names the target, e.g. `dev server · 5173` | check §2.3, then the log line below |
| 2.2 | **[host]** The chip stays lit after later turns (a test run, a lint) | still lit | the stickiness is [code]-pinned (`detectPreviewAvailability`); a regression means the new logic did not load |
| 2.3 | **[host]** `Help → Toggle Developer Tools` → console, filter `crusor-preview` | `[crusor-preview] window opened …` after a click; no `no preview proxy published for this workspace` before it | that warning means **no endpoint file for this workspace** → §2.4 |
| 2.4 | Endpoint file matches the opened folder | `~/.crusorai/preview/*.json` exists and its `"workspace"` equals the folder opened in the app (and `"secret"` is a non-empty string) | run the proxy from §0.3 with `--workspace` set to the **exact** opened folder path |
| 2.5 | **[code]** Only dev-server-ish evidence counts | a `pytest -q` run does **not** light the chip; `npm run dev`, `vite`, `next dev`, `python -m http.server`, a written `*.html`/`*.tsx` do | [code]-pinned in `test_preview_contract.py` |

---

## 3. Step 2 — the separate window

| # | Check | Pass looks like | If it fails |
| --- | --- | --- | --- |
| 3.1 | **[host]** Click the Preview chip | a **separate OS window** opens (not a tab, not a panel), ~1180×840, with a native titlebar | nothing opens → §2.3/§2.4. A tab opening means the auxiliary-window call fell back — check the console for `[crusor-preview] could not` |
| 3.2 | **[host]** The window shows the preview chrome: title bar "Crusor Preview", a target chip, a state chip, a URL field with a **Load** button, four viewport buttons, an **Edit UI** button | chrome visible, state chip probably `LIVE` | a **white/empty** window means our page did not load from the app origin — check the console for a CSP violation (`frame-src`/`script-src`) naming `crusor-preview` |
| 3.3 | **[host]** The target chip shows the dev server label (not `no target`) | `aurora-landing · dev server`, `dev server · 5173`, or `workspace file · …` | `no target` → the window opened without a target; close it and open again from a lit chip |
| 3.4 | **[host]** If it says "The preview proxy could not register this target" | — | the diagnosis is in the message: `secret` → the window URL lost its secret (§3.5); otherwise the proxy is not reachable/reachable-but-refusing |
| 3.5 | **[code]** Registration needs the run secret | opening the proxy URL **by hand** (without `&secret=…`) is refused with `403 … requires the run secret` | [code]-pinned; a hand-opened URL failing is *correct* behaviour, not a bug. Use §4 of the setup guide for the standalone browser flow |

---

## 4. Steps 3–7 — it renders, and clicking works

| # | Check | Pass looks like | If it fails |
| --- | --- | --- | --- |
| 4.1 | **[host]** The agent-built UI renders inside the window | your page, styled, images and fonts loading | unstyled/blank → the `<base href>` or a navigation went wrong: check the window's console for 404s on the proxied path, and whether the page redirected off-origin (the proxy refuses those **by design**; the reason is printed in the frame body) |
| 4.2 | **[host]** Viewport buttons | clicking Desktop/Tablet/Phone frames the page at 1440×900 / 834×1112 / 390×844 against the dotted stage | layout only; report and I will adjust |
| 4.3 | **[host]** Click **Edit UI** | the button turns accent-filled and reads "Editing UI"; a small pill appears at the top of the page: "INSPECT — CLICK ANY ELEMENT" | pill missing → the **overlay script** did not load in the framed page (the page is a different origin, so this is the injection path): look for `crusor-preview-overlay.js` in the window's network tab |
| 4.4 | **[host]** Move the cursor over the page | the hovered element gets a **full wireframe**: filled box, four corner brackets, edge guides across the viewport, and a label `tag · class · W×H` | hover shows nothing → 4.3. Box but no label → tell me (z-index/clip case) |
| 4.5 | **[host]** Hover a **white** area of the page (e.g. the hero on a light theme) | the wireframe is **visible**, not faint grey | this is the contrast-enforced path ([code]-pinned for the math); if it is faint, the backdrop detection mis-read a transparent ancestor — send me the element |
| 4.6 | **[host]** Click an element | it locks with a steady outline + centre ticks, and a **small input panel opens anchored on that element** (header "EDIT ELEMENT", the element name, a textarea, quick-fix chips, Cancel / Add fix) | panel opens elsewhere on screen → it falls back above/below when there is no room; report if it lands far from the element |
| 4.7 | **[code]** The page's own handlers do not fire while inspecting | clicking a button in the page does **not** trigger the app's own click behaviour; `Esc` exits inspect | [code]-pinned (`preventDefault`/`stopPropagation` in the capture phase) |
| 4.8 | **[host]** Type "make it rounded, blue and bigger" → `Enter` | panel closes, a toast says "Fix added — 1 pending", and a numbered pin appears at the element's top-right | pin missing → `pins` message; check the window console for `crusor-preview-overlay` errors |
| 4.9 | **[host]** Repeat on two more elements | pins **1, 2, 3**, tray at the bottom shows the count and the fix chips | — |
| 4.10 | **[host]** Click a tray chip | the corresponding element **flashes** (outlined) so you can see which fix it is | flash is brief (1.4s) by design |
| 4.11 | **[host]** `Esc` | exits inspect mode; the pending fixes **survive** | fixes lost → they should persist across entering/leaving inspect |
| 4.12 | **[host]** Click **Reload** with 3 fixes pending | the page reloads and the pins come back on the right elements | pins land on the wrong element → the selector did not survive the reload; send me the selector |

---

## 5. Step 8 — Review

| # | Check | Pass looks like | If it fails |
| --- | --- | --- | --- |
| 5.1 | **[host]** Click **Review** | a centred sheet lists every fix: number, element label, an **editable** textarea per fix, selector + box size, a remove button | — |
| 5.2 | **[host]** Edit one instruction, remove another | the list updates; the sheet footer count follows | — |
| 5.3 | **[host]** Remove **all** fixes | the Send button is disabled and the sheet says there is nothing pending | — |
| 5.4 | **[host]** Click the **source** icon next to a fix | for a page with `data-crusor-source`, the editor opens **that file at that line**; otherwise a toast says Crusor was asked to locate the source | nothing happens → no stamped source (expected for most projects) and the fallback is the toast |

---

## 6. Step 9 — the handoff to the Agent

| # | Check | Pass looks like | If it fails |
| --- | --- | --- | --- |
| 6.1 | **[host]** Click **Send to Crusor** | the sheet closes, the preview window reports "sent", and the **main window's Agent surface comes forward** | window does not come forward → the focus command; check the console for `could not focus the Agent surface` |
| 6.2 | **[host]** Turn content in the Agent | one turn whose text begins `<!-- crusor-preview:fix-batch count=N -->`, then the scope rules, then `Fix 1 — <button> "Get started"`, `instruction: …`, `selector: …`, `fingerprint: classes=… text=… attrs=…`, `box: …`, `styles: …` | a bare grey prompt / empty text → the frame was built but is not being rendered; send me what appears |
| 6.3 | **[host]** The engine accepts the turn (no protocol error) | normal streaming turn starts | `unsupported execution mode` / frame error → the `preview_batch` receipt is the only addition to a standard `prompt` frame; send me the error frame |
| 6.4 | **[host]** Let the turn finish | the agent edits the project's real source; the files it names are the ones the elements belong to | the agent guesses wrong files → that is the fingerprint heuristic, not the plumbing: send me the generated prompt and I will tune it |
| 6.5 | **[host]** Click **Reload** in the preview window | the change is visible | — |

---

## 7. Cross-cutting checks

| # | Check | Pass looks like | If it fails |
| --- | --- | --- | --- |
| 7.1 | **[code]** Theme match | preview chrome and overlay colours come from `--crusorai-*`; switch the workbench theme (`Ctrl/Cmd+K Ctrl/Cmd+T`) and both re-derive | [code]-pinned (no hardcoded palette outside the token block) |
| 7.2 | **[code]** SVG-only icons | no emoji anywhere in the chrome; every `<use href>` resolves to a sprite symbol | [code]-pinned |
| 7.3 | **[host]** Theme change while the preview window is open | the window and the overlay follow the new theme without reopening | the host pushes `configure` on `onDidColorThemeChange`; a stale palette means that listener did not attach |
| 7.4 | Closing the window | the window's own Close button and the OS titlebar close both work; reopening starts a fresh batch | reopening reuses the old window (state kept) — that is the intended "already open" path |
| 7.5 | **[host]** The proxy survives a window reload | reload the whole app; the chip re-lights and the window opens again using the same endpoint | if the endpoint file is gone, the proxy exited — restart §0.3 |

---

## 8. What to send me if something fails

For each failure:

1. the **step number** from this file;
2. what you saw instead (a screenshot of the window is ideal);
3. `Help → Toggle Developer Tools` → console lines mentioning `crusor-preview` (main window), and the
   same in the **preview window's** devtools (right-click inside it → Inspect);
4. for a prompt problem: the full text that landed in the composer.

Already known and expected, so not worth reporting:

- the preview window has **no auto-start** for the proxy (that is the extra terminal in the setup
  guide);
- a page that redirects off-origin, sets an un-widenable CSP, or uses a JS frame-buster will refuse to
  render — deliberate, with the reason printed in the frame;
- the composer shows the batch as **prompt text**, not a bespoke card yet.
