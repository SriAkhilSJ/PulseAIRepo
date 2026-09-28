# Crusor Preview — laptop setup

Everything you need to run **Crusor Preview** on your own machine, from "30-second demo in a
browser" to "the full flow inside the desktop app". Each section is self-contained; stop wherever
your goal is met.

Everything is on `main` (the preview branch `arena/01a0ca7c-pulseairepo` merged 2026-09-27).

---

## 0. What you need

| Tool | Version | Why |
| --- | --- | --- |
| `git` | any recent | to get the branch |
| `python` | **3.11+** | the preview proxy, injection, prompt builder, and tests |
| `node` | **24.18.0** (`desktop/.nvmrc`) | only for the desktop IDE build |
| `uv` *(optional)* | recent | the repo is uv-managed; plain `pip` works too |

The preview Python code is **stdlib only** — `pytest` is the only extra install, needed just for the
test suite. No npm install is needed for sections 1–4.

---

## 1. Get the code

```bash
git clone https://github.com/SriAkhilSJ/PulseAIRepo.git
cd PulseAIRepo
```

Already have the repo?

```bash
cd PulseAIRepo
git fetch origin
```

Only want the patch, on top of `main`?

```bash
git checkout main
git am patches/crusorai-preview-inspect-fix.patch
```

---

## 2. Verify in two minutes (no IDE, no npm)

```bash
# with uv (repo default)
uv sync --group dev

# or with plain pip
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install pytest

# run the preview suite
python -m pytest src/tests/test_preview_inject.py src/tests/test_preview_prompt.py \
                 src/tests/test_preview_server.py src/tests/test_preview_endpoint.py \
                 src/tests/test_preview_contract.py src/tests/test_preview_target_probe.py \
                 src/tests/test_preview_batch_turn_script.py -q
```

**Expected: `94 passed, 1 skipped`.** These are the real checks — the proxy runs over real sockets, the contract
test loads the shipped JavaScript through node and pins the message names in both directions.

---

## 3. See the whole flow in 30 seconds (the lab)

The lab runs the real window chrome, the real injected overlay, the real proxy and the real prompt
builder. Only the model turn is mocked, so it needs no provider key.

```bash
python preview-lab/lab_server.py --port 8931
# open http://127.0.0.1:8931/lab/
```

Then, in the page:

1. The Crusor panel shows **“Preview available”** (step 1 — the agent built UI).
2. Click **Open preview** → a panel labeled *auxiliary window* appears (step 2: in the IDE this is a
   real separate OS window).
3. It renders the agent-built page (step 3).
4. Click **Edit UI** (step 4).
5. Move the cursor: the hovered element gets a full wireframe — box, corner brackets, edge guides,
   and a `tag · class · W×H` label (step 5).
6. Click an element: it locks and a small panel opens **anchored on it** (step 6).
7. Type a fix (or use a quick-fix chip) and press **Enter**. Repeat on other elements — each leaves a
   numbered pin (step 7).
8. Click **Review** → reword or drop any fix → **Send to Crusor** (step 8).
9. The mock IDE focuses the Agent, the batch lands on the composer with the element chips and the
   generated scoped prompt, and **Send** runs the mocked turn — the preview reloads and flashes the
   element that changed (step 9).

Good first clicks: **“make it rounded, blue and bigger”** on the hero button, **“hide this
completely”** on the fine print under the hero. `Reset demo` (top right) clears the mock agent's edits.

---

## 4. Preview *your own* project in a browser (no IDE)

This is the real proxy pointed at a real dev server — the same thing the IDE window does.

```bash
# terminal A — your app
npm run dev                     # e.g. http://localhost:5173

# terminal B — the preview proxy (from the repo root)
python -m src.preview.server --workspace /path/to/your/project --port 8931 --url http://localhost:5173
```

Then open the printed preview-window URL with the target passed in:

```
http://127.0.0.1:8931/crusor-preview/ui/?endpoint=http://127.0.0.1:8931&target=http://localhost:5173/
```

The window registers the target itself (it needs a capability token) and frames your app with the
inspect overlay injected. For a static page the agent wrote instead of a dev server:

```bash
python -m src.preview.server --workspace /path/to/your/project --port 8931 --file dist/index.html
```

Notes that matter in practice:

- the target must be **loopback/private** (`localhost`, `127.0.0.1`, a LAN address). Remote targets
  are refused unless you pass `--allow-remote`;
- the token in the URL is per-target and unguessable — that is the only thing guarding the proxy, so
  do not paste these URLs anywhere shared;
- `Send to Crusor` in a browser has nothing to send *to*: it posts to the workbench host and logs a
  no-host warning. The click → fix → review loop works fully; the handoff needs the IDE (section 5).

---

## 5. The full flow inside the desktop app

The IDE build is the heavy part (a Code OSS fork: large `npm install`, long first compile).

### 5a. Build and launch the app

```bash
cd desktop/vscode
node --version                  # must be 24.18.0 (see desktop/.nvmrc)
npm install                     # large, one time
npm run typecheck-client
npm run valid-layers-check
npm run compile
npm run gulp minify-vscode     # only if you want a minified build

# launch (from the same directory)
./scripts/code.sh              # macOS / Linux
scripts\code.bat               # Windows
```

Then open the project folder you want to work in (`File → Open Folder`).

### 5b. Start the preview proxy for that folder

Nothing starts the proxy automatically yet (see *Known gaps*), so use the launcher — it starts
the proxy when needed and then opens the IDE (Windows):

```bash
crusor.bat D:\path\to\your\project
```

- The argument must be **the folder you open in the app**; the IDE resolves the proxy by matching
  that path in the handshake file. With no argument the current directory is used.
- An already-running proxy for the same folder is reused. `crusor.bat --proxy-only <folder>`
  starts/verifies the proxy without launching the IDE.
- Manual fallback (any OS), run in a terminal and leave it running:

```bash
cd /path/to/PulseAIRepo
python -m src.preview.server --workspace /path/to/your/project --port 8931 --endpoint-session ide
```

- `--workspace` must be **the folder you opened in the app**; the IDE resolves the proxy by matching
  that path in the handshake file.
- `--endpoint-session` writes `~/.crusorai/preview/ide.json` (`%USERPROFILE%\.crusorai\preview\` on
  Windows), which is how the IDE finds the port and token without any configuration. The file is
  removed when the proxy exits.

### 5c. Use it

1. Ask Crusor to build some UI, or let it start your dev server. When it does, the **Preview** chip in
   the Crusor panel lights up (step 1). It stays lit for the rest of the session.
2. Click **Preview** (or `Crusor: Open Crusor Preview` from the command palette, or the
   `Crusor → Open Crusor Preview` menu entry) → a **separate desktop window** opens (step 2).
3. Edit UI → hover, click, type, `Enter`, repeat (steps 4–7).
4. **Review** → check the fixes → **Send to Crusor** (step 8). The batch is dispatched as an ordinary
   bridge `prompt` frame and the Agent surface comes forward in the main window (step 9).
5. Press **Enter** in the composer to run the turn. The agent edits the real source; press **Reload**
   in the preview window to see the result.

---

## 6. Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `No module named pytest` | `pip install pytest`, or use `uv sync --group dev` |
| Lab page loads, preview window says “The preview proxy could not register this target” | the target (dev server) is not running, or the port in the URL is wrong |
| IDE: Preview chip never lights | no previewable evidence in that session yet — the agent must start a dev server, or write a `.html`/UI file. Run a prompt that builds UI first |
| IDE: Preview click does nothing | no handshake file. Check `~/.crusorai/preview/*.json` exists, and that its `workspace` matches the folder opened in the app |
| Browser blocks the frame, or the page renders unstyled | the target redirected off-origin (the proxy refuses rather than following — by design), or the page needs a websocket/HMR the proxy does not carry. Use **Reload** after edits |
| Blank preview, HTML present | the page sets its own CSP that the proxy could not widen, or it uses a JS frame-buster (not rewritten — by design) |
| `Address already in use` | another proxy/lab is on 8931: `--port 8932`, or `--port 0` to take a free port |
| Tests fail on Windows with a path error | run pytest from the repo root (`pytest.ini` puts the root on `sys.path`) |

---

## 7. First launch of the IDE fork

Once the app is up, work through [`CRUSOR_PREVIEW_LAUNCH_CHECKS.md`](CRUSOR_PREVIEW_LAUNCH_CHECKS.md):
one line per thing to look at, with the pass condition, the likely cause, and what to send back if it
fails. It starts from `npm run typecheck-client` and ends at the agent landing the edit.

## 8. Known gaps (read before filing anything as broken)

1. **The TypeScript layer has not been compiled on our side.** No `node_modules` and no Code OSS
   build were possible in the environment where this was written, so
   `crusorAIPreviewService.ts` and the `crusorAIViewPane.ts` edits are contract-pinned and reviewed
   but not type-checked. If `npm run typecheck-client` complains, expect small mechanical fixes —
   that is the one place to look first.
2. **Nothing starts the proxy automatically.** Hence the extra terminal in §5b. A natural follow-up is
   the engine spawning it when a session begins.
3. **The composer shows the batch as prompt text plus its `preview_batch` receipt**, not yet a bespoke
   card in the renderer.
4. **Ancillary `auxiliaryWindow.onDidLayout` / focus polishing** in the preview window (remembering
   size and position across sessions) is not wired.
5. Steps 3–8 were verified in the lab (real chrome, real overlay, real proxy) and by the test suite;
   they have not been exercised inside a real Electron auxiliary window on this machine.
