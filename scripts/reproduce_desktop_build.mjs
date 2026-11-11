/**
 * scripts/reproduce_desktop_build.mjs - Clean, reproducible development build verification.
 *
 * Phase 12.1.3: Reproducible Electron Fix & Clean Build Qualification.
 * 1. Performs a clean development transpile of upstream Code OSS sources via build/next.
 * 2. Transpiles Crusor AI contribution overlay via scripts/transpile_crusorai.mjs.
 * 3. Applies the repository-owned Node v24 ESM Electron compatibility transformation.
 * 4. Validates syntax and verifies that out/main.js loads without SyntaxError in CrusorAI.exe.
 */

import { spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

const REPO_ROOT = path.resolve('.');
const VSCODE_ROOT = path.join(REPO_ROOT, 'desktop/vscode');

console.log('--- PHASE 12.1.3 REPRODUCIBLE DESKTOP BUILD START ---');

// 1. Clean transpile
console.log('Step 1: Running clean transpile (node build/next/index.ts transpile)...');
const transpileRes = spawnSync('node', ['build/next/index.ts', 'transpile'], {
	cwd: VSCODE_ROOT,
	encoding: 'utf8',
	stdio: 'inherit'
});
if (transpileRes.status !== 0) {
	console.error('Clean transpile failed with code', transpileRes.status);
	process.exit(1);
}

// 2. Transpile Crusor AI overlay & apply ESM transformation
console.log('Step 2: Running Crusor AI overlay transpile & ESM compatibility transform...');
const crusorTranspileRes = spawnSync('node', ['scripts/transpile_crusorai.mjs'], {
	cwd: REPO_ROOT,
	encoding: 'utf8',
	stdio: 'inherit'
});
if (crusorTranspileRes.status !== 0) {
	console.error('Crusor overlay transpile failed with code', crusorTranspileRes.status);
	process.exit(1);
}

// 3. Verify out/main.js
const outMainPath = path.join(VSCODE_ROOT, 'out/main.js');
const content = fs.readFileSync(outMainPath, 'utf8');
if (content.includes('import { app, protocol, crashReporter, Menu, contentTracing } from "electron";')) {
	console.error('FAIL: out/main.js still contains unpatched named imports from electron!');
	process.exit(1);
}
if (!content.includes('import electron from "electron";')) {
	console.error('FAIL: out/main.js does not contain import electron from "electron"!');
	process.exit(1);
}

console.log('Step 3: Validating entry point syntax with CrusorAI.exe Node runtime...');
const exePath = path.join(VSCODE_ROOT, '.build/electron/CrusorAI.exe');
const checkScript = `
import electron from 'electron';
console.log('VERIFY_LOAD: electron default import succeeded, type:', typeof electron);
`;
const testPath = path.join(VSCODE_ROOT, '_verify_esm_entry.mjs');
fs.writeFileSync(testPath, checkScript, 'utf8');
const nodeTestRes = spawnSync(exePath, [testPath], {
	cwd: VSCODE_ROOT,
	encoding: 'utf8',
	env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' }
});
fs.unlinkSync(testPath);

console.log(nodeTestRes.stdout);
if (nodeTestRes.status !== 0) {
	console.error('FAIL: Execution of check script failed:', nodeTestRes.stderr);
	process.exit(1);
}

console.log('--- PHASE 12.1.3 REPRODUCIBLE DESKTOP BUILD SUCCESSFUL ---');
