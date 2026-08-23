# INSTRUCTIONS — Desktop Agent: visual verification of PulseAI Dark

**From:** Arena agent (Interface/Frontend session) · **Date:** 2026-08-23
**Repo:** `https://github.com/SriAkhilSJ/PulseAIRepo`
**Branch:** `arena/01a02fe3-pulseairepo` · **Verify tip:** `f2f1eb5e` or newer
**Read this whole file before running anything.**

---

## 0. Mission

The IDE previously shipped VS Code's **Dark 2026** theme (grey `#121314` chrome,
teal `#3994BC` accents), so it looked like VS Code. It now ships **PulseAI Dark**
— true black chrome, blue accents — as the **default** theme.

The change is statically verified (valid JSON, registered, zero leftover upstream
colors) but has **never been rendered in a running IDE**. That is your job.

**This task costs ZERO credits. No model calls. No API keys. Do not run any
benchmark or paid task.**

Deliverable: **5 screenshots + a short pass/fail report** (§5).

---

## 1. Sync

```powershell
cd <repo root>
git status                                  # note anything dirty
git stash push -u -m "pre-arena-sync"       # ONLY if dirty; do not lose work
git fetch origin
git checkout arena/01a02fe3-pulseairepo
git pull origin arena/01a02fe3-pulseairepo
git log --oneline -1                        # MUST be f2f1eb5e or newer
```

Confirm the new files arrived:

```powershell
Test-Path desktop\vscode\extensions\theme-defaults\themes\pulseai-dark.json   # True
Test-Path scripts\generate_pulseai_theme.py                                    # True
```

> `.env`, `.venv`, `desktop\vscode\.build\`, `bench-results\` are gitignored — the
> pull will not touch them. Your existing build and venv are safe.

---

## 2. Pre-flight (10 seconds, catches 90% of failures)

```powershell
node -v          # expect v24.18.0 (desktop\.nvmrc)
python -c "import json;d=json.load(open(r'desktop\vscode\extensions\theme-defaults\themes\pulseai-dark.json'));print(d['name'],len(d['colors']))"
# expect:  PulseAI Dark 305
python -c "import json;p=json.load(open(r'desktop\vscode\extensions\theme-defaults\package.json'));print(p['contributes']['configurationDefaults'])"
# expect:  {'workbench.colorTheme': 'PulseAI Dark'}
```

If any of these fail, **STOP and report** — do not try to fix them.

---

## 3. Build + launch

Themes are **built-in extension resources**, not TypeScript, so a full recompile
is usually unnecessary. Try the fast path first.

### 3a. Fast path — launch what you already have

```powershell
cd desktop\vscode
.\scripts\code.bat
```

`code.bat` runs `build/lib/preLaunch.ts` (fetches electron, compiles, builds
built-in extensions), then launches `.build\electron\PulseAI.exe`.

If a stale build causes trouble, skip prelaunch and run the existing binary:

```powershell
$env:VSCODE_SKIP_PRELAUNCH=1
.\scripts\code.bat
```

### 3b. If the theme does NOT appear

Built-in extension metadata is cached. In order, cheapest first:

1. In the IDE: **Ctrl+Shift+P → "Developer: Reload Window"**.
2. Launch with a clean profile (does not touch your real settings):
   ```powershell
   .build\electron\PulseAI.exe . --user-data-dir .freebuff\pulseai-theme-check
   ```
   **A clean profile is the honest test** — `configurationDefaults` only applies
   where the user has not already set `workbench.colorTheme`. If you previously
   picked a theme, your existing profile will keep it. **This is expected, not a bug.**
3. Only if 1 and 2 both fail:
   ```powershell
   npm run compile
   ```

**Do NOT run a full clean rebuild.** It is multi-hour and out of scope. If
nothing works after step 3, stop and report.

---

## 4. What to check (this is the actual review)

Use the **clean profile** from §3b.2 so the default is genuinely exercised.

### 4a. Is it default?

- **Ctrl+Shift+P → "Preferences: Color Theme"**
- **"PulseAI Dark" must be the selected/checked entry**, and it should appear in
  the list. If it is listed but not selected → `configurationDefaults` is not
  applying; report that specifically.

### 4b. Colors — the pass/fail list

| # | Where | Expected |
|---|---|---|
| 1 | Editor background | **True black** `#000000` — not dark grey |
| 2 | Activity bar / side bar / status bar / title bar | **True black**, separated only by faint `#1A1A1A` hairlines |
| 3 | Active tab | Very slightly lifted (`#0A0A0A`) with a **blue** top border |
| 4 | Focus ring (Tab through the UI, or click a text field) | **Blue** `#3B82F6` — **not teal/cyan** |
| 5 | Any badge (e.g. Source Control count) | **Blue** background, white text |
| 6 | Buttons in dialogs / Getting Started | **Blue** fill, white text |
| 7 | Explorer selected row | Deep blue wash `#0C1A30`, white text |
| 8 | Syntax colors in an open code file | **Unchanged** from before — inherited on purpose |
| 9 | Errors / warnings / git decorations | Still red / amber / green — **not** recolored blue |

### 4c. Hunt for leftover teal — the thing most likely to be wrong

Open several surfaces and look for any **teal/cyan** (`#3994BC`-ish) still
showing. Check specifically:

- Command Palette (Ctrl+Shift+P) — selected row, matched-text highlight
- Settings UI (Ctrl+,) — links, modified-setting indicator, section headers
- Source Control panel
- Terminal panel (Ctrl+`) — tab, selection, cursor
- Notification toast (trigger any)
- Find widget (Ctrl+F) — match highlights
- Hover tooltip over a symbol

**Any teal you find is a bug — screenshot it and note exactly where.**

### 4d. Two known open questions — please answer both

1. **Doubled panel header.** Open Pulse in the auxiliary bar. Does it show **two**
   stacked headers (a container title *and* a view title)? We believe it does, and
   the fix is a one-line option. **Screenshot the top of the Pulse panel.**
2. **Two agent icons.** Does the auxiliary bar show **both** a Copilot/Chat icon
   **and** the Pulse icon? Copilot should hide itself when no Copilot extension is
   present. **Report which icons you see.** Do **not** delete or edit anything
   under `contrib/chat/` or `extensions/copilot/` — that code is our integration
   reference and is deliberately untouched.

---

## 5. Report back

Save screenshots to `.freebuff\evidence\theme\` (gitignored) and paste:

1. `git log --oneline -1` (sync proof)
2. **Screenshot 1** — full window, a code file open, Pulse panel visible
3. **Screenshot 2** — Color Theme picker showing PulseAI Dark selected
4. **Screenshot 3** — Command Palette open (teal check)
5. **Screenshot 4** — Settings UI (teal check)
6. **Screenshot 5** — top of the Pulse panel (doubled-header question)
7. The §4b table with **pass/fail per row**
8. Any teal found: **where**, plus a screenshot
9. Answers to §4d.1 and §4d.2
10. Which launch path worked (3a / skip-prelaunch / clean profile / `npm run compile`)

---

## 6. Hard constraints

- **Zero credits.** No model calls, no benchmarks, no paid tasks, no `.env` changes.
- **No code edits.** If something looks wrong, **report it — do not patch it.**
  The Arena agent owns code changes.
- **Never touch** `desktop\vscode\src\vs\workbench\contrib\chat\` or
  `desktop\vscode\extensions\copilot\`.
- **No pushing from the laptop** (local `main` history contains the old leaked key).
- **No full clean rebuild** — multi-hour, out of scope.
- If a launch hangs > 10 min: `taskkill /T /F /PID <pid>`, then report.

---

## 7. Context (why this matters)

`PulseAI Dark` is generated from upstream `2026-dark.json` by
`scripts/generate_pulseai_theme.py` — 298 upstream colors remapped (grey → true
black, teal → Pulse blue with alpha preserved), plus ~60 explicit brand overrides.
It is registered additively inside `extensions/theme-defaults`, so **zero upstream
source files were modified** and fork invariant 7 still holds.

Full background: `docs/DESIGN/FORK_REBRANDING.md`.
Design direction: `docs/DESIGN/PULSEAI_DESIGN_PLAN.md`.
Intended look (mockup, not a real screenshot):
`branding/pulseai-dark-theme-preview.svg`.
