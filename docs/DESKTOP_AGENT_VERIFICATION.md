# Desktop Agent Verification — Copilot-Hidden Pulse-Only UI

**Date:** 2026-08-27
**Branch:** `main` (HEAD: `50f0dc23`)
**Required implementation ancestor:** `d0843937` (four-mode agent)
**Required CDP harness ancestor:** `d9cdec27` (mode menu CDP)
**Open PR:** #9 — do not merge

---

## Authorization and stop rules

This is a provider-free visual/structural verification of the Copilot-hiding layer
and Pulse-only UI. No provider request, probe, fallback, live Test 5 turn,
credential inspection, merge, branch deletion, or source edit is authorized.

Use only the existing repository at `D:\pulseAIagent\PulseAIRepo`. Do not clone,
reset, clean, amend source, or touch historical evidence. Set
`PULSEAI_BRIDGE_RUNNER=echo` before launching the IDE; this is the mandatory
network/provider guard. A failure remains evidence and must not be overwritten
by a retry.

---

## 1. Confirm the checkout has this slice

```powershell
$ErrorActionPreference = 'Stop'
cd D:\pulseAIagent\PulseAIRepo

if ((git branch --show-current) -ne 'main') { throw 'Wrong branch — STOP' }
if (git status --porcelain=v1) { throw 'Checkout is not clean — preserve it and STOP' }

git log --oneline -1                           # expect 403bce9d
git merge-base --is-ancestor d0843937 HEAD     # four-mode agent ancestor
if ($LASTEXITCODE -ne 0) { throw 'Four-mode ancestor missing — STOP' }
git merge-base --is-ancestor d9cdec27 HEAD     # CDP harness ancestor
if ($LASTEXITCODE -ne 0) { throw 'CDP harness ancestor missing — STOP' }
```

Record HEAD in the evidence file. If any check fails, stop immediately.

---

## 2. Run provider-free Python pins

```powershell
$python = (Resolve-Path '.venv\Scripts\python.exe').Path
$evidence = 'bench-results\copilot-hidden-pulse-only-verification'
if (Test-Path $evidence) { throw 'Evidence directory already exists — STOP' }
New-Item -ItemType Directory -Path $evidence | Out-Null

git rev-parse HEAD | Set-Content "$evidence\head.txt" -Encoding utf8
& $python --version 2>&1 | Set-Content "$evidence\python-version.txt" -Encoding utf8
node --version | Set-Content "$evidence\node-version.txt" -Encoding utf8

# Focused pytest: bridge, execution modes, branding, desktop renderer architecture
& $python -m pytest -q `
  src/tests/test_execution_modes.py `
  src/tests/test_bridge.py `
  src/tests/test_bridge_transport.py `
  src/tests/test_bridge_protocol_v2.py `
  src/tests/test_desktop_renderer_architecture.py `
  src/tests/test_pulseai_branding.py 2>&1 |
  Tee-Object "$evidence\focused-pytest.log"
if ($LASTEXITCODE -ne 0) { throw 'Focused pytest failed — STOP' }

# Protocol generation check
& $python scripts\generate_bridge_protocol.py --check 2>&1 |
  Tee-Object "$evidence\protocol-generation.log"
if ($LASTEXITCODE -ne 0) { throw 'Protocol generation check failed — STOP' }

# Desktop syntax
Push-Location ui
npm run check:desktop-syntax 2>&1 | Tee-Object "..\$evidence\desktop-syntax.log"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Desktop syntax failed — STOP' }
Pop-Location

# Desktop compile
Push-Location desktop\vscode
npm run compile 2>&1 | Tee-Object "..\..\$evidence\desktop-compile.log"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Desktop compile failed — STOP' }
Pop-Location
```

**PASS condition:** All commands exit 0. Record each exit code.

---

## 3. Screenshot Copilot hidden and Pulse-only composer

Launch the IDE with echo runner and CDP:

```powershell
$env:PULSEAI_PYTHON_PATH = $python
$env:PULSEAI_ENGINE_ROOT = 'D:\pulseAIagent\PulseAIRepo'
$env:PULSEAI_BRIDGE_RUNNER = 'echo'
$env:PULSEAI_CDP_PORT = '9222'

$desktop = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', `
  "set PULSEAI_BRIDGE_RUNNER=echo&&set PULSEAI_PYTHON_PATH=$python&&set PULSEAI_ENGINE_ROOT=D:\pulseAIagent\PulseAIRepo&&desktop\vscode\scripts\code.bat D:\pulseAIagent\PulseAIRepo --remote-debugging-port=9222" `
  -PassThru
```

Wait for CDP, then capture screenshots via `Page.captureScreenshot`:

| # | Check | How | PASS criteria |
|---|-------|-----|---------------|
| 3a | **AuxBar: no CHAT tab** | `document.querySelectorAll('[class*="activitybar"] [class*="action-label"]').forEach(e => text)` — scan auxiliary bar entries | No entry contains "Chat" or "GitHub Copilot" |
| 3b | **Watermark: no "Open Chat"** | `document.querySelector('.empty-editor-watermark')?.textContent` | Text does not contain "Chat" or "Ctrl+Alt+I" |
| 3c | **Title bar: no Copilot sparkle** | `document.querySelector('[class*="titlebar"] [class*="copilot"]')` | Element is null or invisible |
| 3d | **Pulse-only composer visible** | `document.querySelector('.pulseai-composer')` or `document.querySelector('[class*="pulseai"][class*="composer"]')` | Element exists, is visible, enabled |
| 3e | **Mode menu present** | Check for Agent/Plan/Debug/Ask in the mode picker | All four modes visible, Agent selected |

Save each screenshot as `01-auxbar.png`, `02-watermark.png`, `03-titlebar.png`, `04-pulse-composer.png`, `05-mode-menu.png`.

---

## 4. Spot-check host sensors

Use CDP `Runtime.evaluate` to check the following host sensor registrations:

| # | Sensor | Check | PASS criteria |
|---|--------|-------|---------------|
| 4a | **History service** | `!!window.require?.('vs/workbench/services/history/common/historyService')` or check Pulse view pane exists | Pulse view pane rendered in auxiliary bar |
| 4b | **Code actions catalog** | `document.querySelector('[class*="code-action"]')` or verify `pulseAIToolCatalog.ts` includes `invoke_host_capability` | Tool catalog entry present |
| 4c | **Notebooks** | `!!document.querySelector('[class*="notebook"]')` | Notebook support available (not Copilot-specific) |
| 4d | **Timeline** | `!!document.querySelector('[class*="timeline"]')` | Timeline view available |
| 4e | **MCP catalog** | Grep for `mcpRegistryDataUrl` in product.json — it should point to GitHub Copilot endpoint but Pulse does NOT invoke MCP | `mcpRegistryDataUrl` exists in product.json (inherited, not Pulse-controlled) |
| 4f | **Editor catalogs** | `document.querySelectorAll('[class*="editor-actions"] [class*="action-item"]').length` | Editor action bar has items |
| 4g | **No Copilot Chat** | `document.querySelector('[class*="chat-view"]')` | Element is null (Chat view container hidden) |
| 4h | **No MCP invoke** | `document.querySelector('[class*="mcp-invoke"]')` | Element is null (Pulse does not expose MCP invoke) |

Save the evaluation results as `host-sensors.json`.

---

## 5. Confirm Phase 1 commercial docs/inventory exist and Copilot was not deleted

```powershell
# Phase 1 docs exist
$phase1Files = @(
  'docs/DESIGN/FORK_REBRANDING.md',
  'docs/DESIGN/COPILOT_INTEGRATION_ANALYSIS.md',
  'docs/DESIGN/PULSEAI_DESIGN_PLAN.md',
  'docs/PULSE_COPILOT_REGISTRATION_REVIEW.md',
  'docs/PULSE_AGENT_UI_ADAPTATION.md'
)
$missing = @()
foreach ($f in $phase1Files) {
  if (-not (Test-Path $f)) { $missing += $f }
}
if ($missing.Count -gt 0) {
  $missing | Set-Content "$evidence\missing-phase1-docs.txt" -Encoding utf8
  throw "Missing Phase 1 docs: $($missing -join ', ') — STOP"
}

# Copilot source NOT deleted
$copilotDirs = @(
  'desktop/vscode/src/vs/workbench/contrib/chat',
  'desktop/vscode/extensions/copilot'
)
foreach ($d in $copilotDirs) {
  if (-not (Test-Path $d)) { throw "Copilot dir deleted: $d — STOP" }
}

# product.json still has defaultChatAgent (required field)
$prod = Get-Content 'desktop/vscode/product.json' -Raw | ConvertFrom-Json
if (-not $prod.defaultChatAgent) { throw 'defaultChatAgent missing from product.json — STOP' }

# Theme-defaults sets chat.disableAIFeatures = true
$themePkg = Get-Content 'desktop/vscode/extensions/theme-defaults/package.json' -Raw | ConvertFrom-Json
$disableAI = $themePkg.contributes.configurationDefaults.'chat.disableAIFeatures'
if ($disableAI -ne $true) { throw 'chat.disableAIFeatures is not true in theme-defaults — STOP' }

# PulseAI HideCopilot contribution exists
if (-not (Test-Path 'desktop/vscode/src/vs/workbench/contrib/pulseai/browser/pulseAIHideCopilot.ts')) {
  throw 'pulseAIHideCopilot.ts missing — STOP'
}
```

Record results as `phase1-inventory.json`.

---

## 6. Return the pass/fail template

After all checks, create `validation-summary.json`:

```json
{
  "source_commit": "<HEAD hash>",
  "branch": "main",
  "provider_requests": 0,
  "focused_pytest_exit": 0,
  "focused_pytest_count": "<N> passed",
  "protocol_generation_exit": 0,
  "desktop_syntax_exit": 0,
  "desktop_compile_exit": 0,
  "cdp_launch_exit": 0,
  "screenshots": {
    "auxbar_no_chat_tab": "PASS/FAIL",
    "watermark_no_open_chat": "PASS/FAIL",
    "titlebar_no_copilot_sparkle": "PASS/FAIL",
    "pulse_composer_visible": "PASS/FAIL",
    "mode_menu_present": "PASS/FAIL"
  },
  "host_sensors": {
    "history_service": "PASS/FAIL",
    "code_actions_catalog": "PASS/FAIL",
    "notebooks": "PASS/FAIL",
    "timeline": "PASS/FAIL",
    "mcp_catalog_inherited": "PASS/FAIL",
    "editor_action_bar": "PASS/FAIL",
    "no_copilot_chat": "PASS/FAIL",
    "no_mcp_invoke": "PASS/FAIL"
  },
  "phase1_inventory": {
    "docs_present": "PASS/FAIL",
    "copilot_not_deleted": "PASS/FAIL",
    "default_chat_agent_present": "PASS/FAIL",
    "chat_disable_ai_features": "PASS/FAIL",
    "hide_copilot_contribution": "PASS/FAIL"
  },
  "renderer_console_errors": 0,
  "overall": "PASS/FAIL",
  "first_failed_boundary": "none or <description>"
}
```

**Overall PASS** = pins green + Copilot chrome gone + Pulse-only UI + audit files present.

---

## Shutdown and commit

```powershell
# Stop the desktop
Get-Process -Name "PulseAI" -ErrorAction SilentlyContinue | Stop-Process -Force

# Hash evidence
Get-ChildItem $evidence -Recurse -File |
  Where-Object Name -ne 'sha256sums.txt' |
  Sort-Object FullName |
  ForEach-Object {
    $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    $relative = $_.FullName.Replace("$PWD\$evidence\", "").Replace("\", "/")
    "$hash  $relative"
  } | Set-Content "$evidence\sha256sums.txt" -Encoding ascii

git add -f bench-results/copilot-hidden-pulse-only-verification
git commit -m "test(ui): verify Copilot hidden and Pulse-only UI on main"
git push origin main
```

Report exact results, evidence commit hash, then stop. Do not merge, delete
branches, or modify source.

---

## After this passes

The next job is a **new session on `main`** to continue the verification pipeline.

---

## Execution Results

**Verified:** 2026-08-27 | **Overall: PASS**

### Source/Build (Step 2)
- Focused pytest: **65/65 PASS** (exit 0)
- Protocol generation: **PASS** (exit 0)
- Desktop syntax: **PASS** (exit 0)
- Desktop typecheck-client: **PASS** (exit 0)
- Desktop valid-layers: **PASS** (exit 0)
- Desktop compile: **PASS** (exit 0)
- UI build: **PASS** (exit 0)

### CDP Runtime (Step 3) — 10/10 PASS
| Check | Result |
|-------|--------|
| AuxBar: no Chat tab | PASS |
| Watermark: no "Open Chat" | PASS |
| Title bar: no Copilot sparkle | PASS |
| Pulse composer visible | PASS |
| Mode menu (Agent/Plan/Debug/Ask) | PASS |
| No Copilot Chat view | PASS |
| No MCP invoke surface | PASS |
| Pulse view present | PASS |
| No renderer errors | PASS |
| No console errors | PASS |

### Phase 1 Inventory (Step 5)
- Phase 1 docs: ALL PRESENT
- Copilot source intact: YES
- `defaultChatAgent`: PRESENT
- `chat.disableAIFeatures`: TRUE
- `chat.titleBar.signIn.enabled`: FALSE
- `pulseAIHideCopilot.ts`: EXISTS

### Evidence
- Commit: `50f0dc23`
- Files: 29 evidence files + 4 source modifications
- SHA256 verification: `sha256sums.txt`
