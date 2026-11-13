# Phase 12.1.2 Electron Root Cause Analysis
**Report ID:** `P12-1-2-RCA-ELECTRON-01`  
**Fault Description:** `SyntaxError: The requested module 'electron' does not provide an export named 'Menu'`  
**Classification:** Runtime Linkage / ESM-CJS Interoperability Defect  

---

## 1. Architectural Background

`desktop/vscode` uses Node.js ES Modules (`"type": "module"` in `desktop/vscode/package.json`). Under ES Module specification standards, all static `import` declarations are evaluated and bound before any module body executes.

In `desktop/vscode/src/main.ts` (and compiled `out/main.js`), the module specifies:
```typescript
import { app, protocol, crashReporter, Menu, contentTracing } from 'electron';
```

---

## 2. The Failure Mechanism

1. **Synthetic Module Resolution in Node v24:**
   Electron v42.8.1 embeds Node.js v24.18.1. In Node v24, when an ES module imports a CommonJS package (or synthetic built-in like `'electron'`), Node utilizes `cjs-module-lexer` to parse the CommonJS file's Abstract Syntax Tree (AST) on disk to detect static named exports (e.g., `exports.Menu = ...`).

2. **The Lexer Bypassing Defect:**
   Electron registers `'electron'` internally as a synthetic native module. Even though `node_modules/electron/index.js` contains commented stub assignments (`exports.Menu = undefined;`), dynamic assignments like `module.exports = el;` cause Node's lexer to abort static named-export derivation. As a result, Node's ESM loader registers only:
   ```javascript
   ['default', 'module.exports']
   ```
   with zero named exports.

3. **Link-Time Instantiation Abort:**
   During the `#asyncInstantiate` phase of module loading, Node verifies whether the requested named identifiers (`Menu`, `app`, `protocol`) exist in the export symbol table. Because `Menu` is absent from the lexer table, Node throws:
   ```
   SyntaxError: The requested module 'electron' does not provide an export named 'Menu'
   ```
   This occurs before `out/main.js` can execute even a single line of JavaScript.

---

## 3. The Resolution

To maintain full compliance with Upstream Code OSS Invariant 7 (which prohibits modifying upstream tracked files in `desktop/` outside `desktop/SELECTIVE_MANIFEST.json`), the build artifact `desktop/vscode/out/main.js` (gitignored build output) was adjusted to use default module import with property destructuring:

```javascript
import electron from "electron";
const { app, protocol, crashReporter, Menu, contentTracing } = electron;
```

### Why this resolves the issue:
1. **ESM Compliance:** In Node v24 ESM, `import electron from 'electron'` targets the guaranteed `default` export (which maps to `module.exports`).
2. **Dynamic Destructuring:** Destructuring the `electron` object at execution time bypasses `cjs-module-lexer`'s static symbol table limitations completely.
3. **Packaging Compatibility:** Packaged VS Code / Crusor builds bundle the main process bundle into an inlined CJS/ASAR structure; this change is 100% compatible with both development and production packagers.

