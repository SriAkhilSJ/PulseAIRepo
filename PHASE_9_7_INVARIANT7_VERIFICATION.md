# PHASE 9.7 UPSTREAM INVARIANT 7 VERIFICATION

**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Manifest:** `desktop/SELECTIVE_MANIFEST.json`  

## 1. INVARIANT 7 CONTRACT

Exactly 5 upstream files permitted in `desktop/SELECTIVE_MANIFEST.json`:
1. `build/buildfile.ts`
2. `build/next/index.ts`
3. `product.json`
4. `src/vs/workbench/workbench.common.main.ts`
5. `src/vs/workbench/workbench.desktop.main.ts`

## 2. AUDIT VERDICT

Verified via `scripts/refresh_selective_manifest.py`:
- All receipts match the tree.
- Zero upstream drift detected.
- Invariant 7 strictly upheld.
