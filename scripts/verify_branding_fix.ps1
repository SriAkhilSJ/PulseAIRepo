#!/usr/bin/env pwsh
# verify_branding_fix.ps1 — one-click source verification for CrusorAI branding leak fix
# Branch: arena/01a0c320-pulseairepo (96606eea + 60c0892c on top of 40ecb862)
# No build needed — checks source files only

$ErrorActionPreference = "Stop"
$failed = 0
function Check($name, $condition, $expect) {
    if ($condition) { Write-Host "[OK] $name" -ForegroundColor Green }
    else { Write-Host "[FAIL] $name -- expect: $expect" -ForegroundColor Red; $script:failed++ }
}

Write-Host "=== CrusorAI Branding Fix — Source Verification ===" -ForegroundColor Cyan
Write-Host "Branch: $(git rev-parse --abbrev-ref HEAD) $(git log --oneline -1)"
Write-Host ""

# 1. Theme is full black/grey (not blue)
$theme = Get-Content desktop/vscode/extensions/theme-defaults/themes/crusorai-dark.json -Raw
Check "theme editor.background #000000" ($theme -match '"editor\.background"\s*:\s*"#000000"') "editor.background #000000"
Check "theme button.background #2d2d2d" ($theme -match '"button\.background"\s*:\s*"#2d2d2d"') "button.background #2d2d2d"
Check "theme focusBorder #3c3c3c" ($theme -match '"focusBorder"\s*:\s*"#3c3c3c"') "focusBorder #3c3c3c"
Check "theme NOT blue #3B82F6" ($theme -notmatch "#3B82F6") "no #3B82F6"

# 2. product.json has NO configurationDefaults (would break desktop)
$product = Get-Content desktop/vscode/product.json -Raw
Check "product.json NO configurationDefaults" ($product -notmatch "configurationDefaults") "no configurationDefaults in product.json"

# 3. theme-defaults HAS the proper defaults
$pkg = Get-Content desktop/vscode/extensions/theme-defaults/package.json -Raw
Check "theme-defaults workbench.colorTheme CrusorAI Dark" ($pkg -match '"workbench\.colorTheme"\s*:\s*"CrusorAI Dark"') "CrusorAI Dark"
Check "theme-defaults chat.disableAIFeatures true" ($pkg -match '"chat\.disableAIFeatures"\s*:\s*true') "true"
Check "theme-defaults signIn.enabled false" ($pkg -match 'signIn\.enabled.*false') "false"
Check "theme-defaults startupEditor none" ($pkg -match '"workbench\.startupEditor"\s*:\s*"none"') "none"
Check "theme-defaults walkthroughs.openOnInstall false" ($pkg -match 'walkthroughs\.openOnInstall.*false') "false"
Check "theme-defaults crusorai.hideBuiltInCopilotUI true" ($pkg -match 'hideBuiltInCopilotUI.*true') "true"

# 4. onboardingThemes includes CrusorAI Dark first
$onboard = (Get-Content desktop/vscode/product.json | Select-String -Pattern "onboardingThemes" -Context 0,20 | Out-String)
Check "onboardingThemes CrusorAI Dark first" ($product -match '"id"\s*:\s*"crusorai-dark".*?"label"\s*:\s*"CrusorAI Dark"' -and $product.IndexOf("crusorai-dark") -lt $product.IndexOf("dark-2026")) "crusorai-dark before dark-2026"

# 5. watermark is fully Crusor (no VS Code entries)
$wm = Get-Content desktop/vscode/src/vs/workbench/browser/parts/editor/editorGroupWatermark.ts -Raw
Check "watermark baseEntries []" ($wm -match "const baseEntries: WatermarkEntry\[\] = \[\];") "baseEntries = []"
Check "watermark workspaceEntries []" ($wm -match "const workspaceEntries: WatermarkEntry\[\] = \[\];") "workspaceEntries = []"
Check "watermark otherEntries []" ($wm -match "const otherEntries: WatermarkEntry\[\] = \[\];") "otherEntries = []"

# 6. Copilot hide is early + OR logic
$hide = Get-Content desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIHideCopilot.ts -Raw
Check "Copilot hide OR logic" ($hide -match "crusorHide \|\| upstreamDisabled") "crusorHide || upstreamDisabled"
Check "Copilot hide BlockRestore" ($hide -match "WorkbenchPhase\.BlockRestore") "BlockRestore"
Check "Copilot hide crusorHide !== false" ($hide -match "getValue.*crusorai\.hideBuiltInCopilotUI.*!== false") "!== false"

Write-Host ""
if ($failed -eq 0) { Write-Host "All source checks passed — ready to build (npm run compile)" -ForegroundColor Green; exit 0 }
else { Write-Host "$failed check(s) failed — source not ready" -ForegroundColor Red; exit 1 }
