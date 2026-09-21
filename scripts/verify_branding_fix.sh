#!/usr/bin/env bash
# verify_branding_fix.sh — one-click source verification for CrusorAI branding leak fix
# Branch: arena/01a0c320-pulseairepo
set -e
failed=0
check() {
  local name="$1" cond="$2" expect="$3"
  if eval "$cond"; then echo "[OK] $name"; else echo "[FAIL] $name -- expect: $expect"; failed=$((failed+1)); fi
}
echo "=== CrusorAI Branding Fix — Source Verification ==="
echo "Branch: $(git rev-parse --abbrev-ref HEAD) $(git log --oneline -1)"

# 1. Theme is full black/grey (not blue)
theme=$(cat desktop/vscode/extensions/theme-defaults/themes/crusorai-dark.json)
check "theme editor.background #000000" "echo \"\$theme\" | grep -q '\"editor.background\".*#000000'" "#000000"
check "theme button.background #2d2d2d" "echo \"\$theme\" | grep -q '\"button.background\".*#2d2d2d'" "#2d2d2d"
check "theme focusBorder #3c3c3c" "echo \"\$theme\" | grep -q '\"focusBorder\".*#3c3c3c'" "#3c3c3c"
check "theme NOT blue #3B82F6" "! echo \"\$theme\" | grep -q \"#3B82F6\"" "no #3B82F6"

# 2. product.json has NO configurationDefaults
check "product.json NO configurationDefaults" "! grep -q configurationDefaults desktop/vscode/product.json" "no configurationDefaults"

# 3. theme-defaults HAS the proper defaults
pkg=$(cat desktop/vscode/extensions/theme-defaults/package.json)
check "theme-defaults colorTheme CrusorAI Dark" "echo \"\$pkg\" | grep -q '\"workbench.colorTheme\".*CrusorAI Dark'" "CrusorAI Dark"
check "theme-defaults disableAIFeatures true" "echo \"\$pkg\" | grep -q '\"chat.disableAIFeatures\".*true'" "true"
check "theme-defaults signIn false" "echo \"\$pkg\" | grep -q 'signIn.enabled.*false'" "false"
check "theme-defaults startupEditor none" "echo \"\$pkg\" | grep -q '\"workbench.startupEditor\".*none'" "none"
check "theme-defaults walkthroughs false" "echo \"\$pkg\" | grep -q 'walkthroughs.openOnInstall.*false'" "false"
check "theme-defaults hideBuiltInCopilotUI true" "echo \"\$pkg\" | grep -q 'hideBuiltInCopilotUI.*true'" "true"

# 4. onboardingThemes CrusorAI Dark first
check "onboardingThemes CrusorAI Dark first" "grep -q 'crusorai-dark' desktop/vscode/product.json && [ \$(grep -n crusorai-dark desktop/vscode/product.json | cut -d: -f1) -lt \$(grep -n 'dark-2026' desktop/vscode/product.json | cut -d: -f1) ]" "crusorai-dark before dark-2026"

# 5. watermark is fully Crusor (no VS Code entries)
check "watermark baseEntries []" "grep -q 'const baseEntries: WatermarkEntry\[\] = \[\];' desktop/vscode/src/vs/workbench/browser/parts/editor/editorGroupWatermark.ts" "baseEntries = []"
check "watermark workspaceEntries []" "grep -q 'const workspaceEntries: WatermarkEntry\[\] = \[\];' desktop/vscode/src/vs/workbench/browser/parts/editor/editorGroupWatermark.ts" "workspaceEntries = []"
check "watermark otherEntries []" "grep -q 'const otherEntries: WatermarkEntry\[\] = \[\];' desktop/vscode/src/vs/workbench/browser/parts/editor/editorGroupWatermark.ts" "otherEntries = []"

# 6. Copilot hide is early + OR logic
check "Copilot hide OR logic" "grep -q 'crusorHide || upstreamDisabled' desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIHideCopilot.ts" "crusorHide || upstreamDisabled"
check "Copilot hide BlockRestore" "grep -q 'WorkbenchPhase.BlockRestore' desktop/vscode/src/vs/workbench/contrib/crusorai/browser/crusorAIHideCopilot.ts" "BlockRestore"

echo ""
if [ $failed -eq 0 ]; then echo "All source checks passed — ready to build (npm run compile)"; exit 0; else echo "$failed check(s) failed"; exit 1; fi
