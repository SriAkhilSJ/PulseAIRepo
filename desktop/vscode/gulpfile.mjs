/*---------------------------------------------------------------------------------------------
 * The fork's build tasks — SELF-CONTAINED on purpose.
 *
 * History (owner field 2026-09-05): this file used to be a one-line TS
 * import of a gulpfile under build/, but `desktop/vscode/build/*` is
 * gitignored (.gitignore), so that file could never be committed — every
 * fresh checkout got a `compile` that died instantly, and the sandbox
 * snapshot dropped the untracked file on every restore. The compile now
 * lives HERE, in a tracked file: `npm run compile` cannot silently lose
 * its implementation again.
 *
 * What `compile` does (the minimal REAL build for this fork):
 *   1. guard: node_modules present (else `npm install` first);
 *   2. `tsc -p src/tsconfig.json` -> out/  (src/*.ts bootstraps emit to
 *      out/, src/vs/** to out/vs/ — common root is src/);
 *   3. copy what tsc never emits: css, ttf (codicons), wasm, and every
 *      media/ tree — including the pulseai-spa website the Pulse panel
 *      iframes — from src/vs into out/vs.
 * Expect MINUTES of tsc output, not seconds.
 *--------------------------------------------------------------------------------------------*/
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import gulp from 'gulp';

const FORK_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)));
const SRC = path.join(FORK_ROOT, 'src');
const OUT = path.join(FORK_ROOT, 'out');

function pulseLog(message) {
	console.log(`[pulseai-compile] ${message}`);
}

function ensureNodeModules() {
	if (!fs.existsSync(path.join(FORK_ROOT, 'node_modules', 'typescript'))) {
		throw new Error(
			'[pulseai-compile] node_modules is missing or incomplete — run `npm install` in desktop/vscode first.'
		);
	}
}

function runTsc() {
	pulseLog('typescript -> out/ (this takes MINUTES; do not abort on silence)');
	const tscBin = path.join(FORK_ROOT, 'node_modules', 'typescript', 'bin', 'tsc');
	const result = spawnSync(process.execPath, [tscBin, '-p', SRC], {
		stdio: 'inherit',
		cwd: FORK_ROOT,
	});
	if (result.status !== 0) {
		throw new Error(`[pulseai-compile] tsc failed (exit ${result.status})`);
	}
	pulseLog('tsc finished');
}

function copyResources() {
	return new Promise((resolve, reject) => {
		gulp
			.src(
				[
					'src/vs/**/*.css',
					'src/vs/**/*.ttf',
					'src/vs/**/*.wasm',
					'src/vs/**/media/**',
				],
				{ cwd: FORK_ROOT, base: SRC }
			)
			.pipe(gulp.dest(OUT))
			.on('finish', () => {
				pulseLog('resources copied (css / ttf / wasm / media incl. pulseai-spa)');
				resolve();
			})
			.on('error', reject);
	});
}

export async function compile() {
	ensureNodeModules();
	runTsc();
	await copyResources();
	pulseLog('done: out/ is ready — fully quit the app and reopen it');
}

export function compileWeb() {
	throw new Error(
		'compile-web is not supported in this fork: the PulseAI desktop target is Electron-only.'
	);
}

export default gulp.series(compile);
