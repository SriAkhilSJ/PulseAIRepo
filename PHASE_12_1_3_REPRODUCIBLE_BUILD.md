# Phase 12.1.3 Reproducible Build Report
**Report ID:** `P12-1-3-REP-BUILD-01`  
**Component:** Crusor AI IDE Desktop Build System  
**Repository:** `SriAkhilSJ/PulseAIRepo`  
**Branch:** `feat/prompt-cache-stabilization`  
**Baseline Commit:** `7e8279919b9fde39a09f9a8b92267188f8138500`  
**Date:** 2026-11-06  

---

## 1. Objective & Background

Phase 12.1.2 applied an ESM compatibility patch directly to `desktop/vscode/out/main.js` to circumvent a runtime `SyntaxError: The requested module 'electron' does not provide an export named 'Menu'` caused by Node.js v24 ESM lexer limitations. Because `desktop/vscode/out/main.js` is a generated build artifact, Phase 12.1.3 required:
1. Identifying the canonical upstream source.
2. Determining how `out/main.js` is produced.
3. Establishing a repository-owned, reproducible build transformation that survives clean rebuilds without manual edits.
4. Strictly maintaining Upstream Code OSS Invariant 7 (zero unauthorized drift on upstream tracked files in `desktop/`).

---

## 2. Canonical Source & Build Mechanism Analysis

- **Canonical Source:** `desktop/vscode/src/main.ts`
  - Upstream VS Code declares:
    ```typescript
    import { app, protocol, crashReporter, Menu, contentTracing } from 'electron';
    ```
  - This file is an upstream tracked file under `desktop/vscode/src/`. Under Code OSS Invariant 7, direct in-tree modification of upstream source files is prohibited unless cataloged in `desktop/SELECTIVE_MANIFEST.json`.
- **Transpilation Pipeline:**
  - Upstream build uses `node build/next/index.ts transpile` (ESBuild / TypeScript runner) to compile `src/` -> `out/`.
  - During transpilation, `out/` is wiped (`[clean] out`) and 8,324 files are emitted.
- **Crusor AI Contribution Layer:**
  - Crusor AI extensions and workbench contributions are maintained in `desktop/vscode/src/vs/workbench/contrib/crusorai/` and transpiled via the repository-owned script `scripts/transpile_crusorai.mjs`.

---

## 3. Repository-Owned Build Transformation

To achieve 100% reproducible builds without manual intervention, the transformation was integrated directly into:
1. `scripts/transpile_crusorai.mjs` via `patchElectronEsmCompatibility(vscodeRoot)`.
2. `scripts/reproduce_desktop_build.mjs` as an end-to-end clean build orchestrator.

### Transformation Logic:
```javascript
export async function patchElectronEsmCompatibility(vscodeRoot) {
    const mainJsPath = path.join(vscodeRoot, 'out/main.js');
    if (fs.existsSync(mainJsPath)) {
        let content = await fs.promises.readFile(mainJsPath, 'utf8');
        const badImportPattern = /import\s*\{\s*([^}]+)\s*\}\s*from\s*['"]electron['"];?/;
        if (badImportPattern.test(content)) {
            content = content.replace(badImportPattern, (_match, names) => {
                return `import electron from "electron";\nconst { ${names.trim()} } = electron;`;
            });
            await fs.promises.writeFile(mainJsPath, content, 'utf8');
            console.log(`[ESM Compatibility] Successfully applied Node v24 ESM transform to ${mainJsPath}`);
        }
    }
}
```

---

## 4. Clean Rebuild Verification

Executing `node scripts/reproduce_desktop_build.mjs`:
1. Clean transpile executed: `node build/next/index.ts transpile` -> 8,324 files compiled in 16.7s.
2. Crusor overlay transpiled: 42 TypeScript files synchronized.
3. ESM compatibility transform applied to `desktop/vscode/out/main.js`.
4. Runtime syntax check executed against `desktop/vscode/.build/electron/CrusorAI.exe`:
   ```
   VERIFY_LOAD: electron default import succeeded, type: object
   --- PHASE 12.1.3 REPRODUCIBLE DESKTOP BUILD SUCCESSFUL ---
   ```
5. `git status --short desktop/` verified: exactly 0 tracked files modified.

**Qualification Status:** **REPRODUCIBLE BUILD QUALIFIED**

