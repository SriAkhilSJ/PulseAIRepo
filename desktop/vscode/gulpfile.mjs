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
 *      media/ tree — including the crusorai-spa website the Crusor panel
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

function crusorLog(message) {
	console.log(`[crusorai-compile] ${message}`);
}

function ensureNodeModules() {
	if (!fs.existsSync(path.join(FORK_ROOT, 'node_modules', 'typescript'))) {
		throw new Error(
			'[crusorai-compile] node_modules is missing or incomplete — run `npm install` in desktop/vscode first.'
		);
	}
}

function runTsc() {
	crusorLog('typescript -> out/ (this takes MINUTES; do not abort on silence)');
	// The pinned CLI package is npm:@typescript/typescript6, which ships its
	// binary as bin/tsc6 + lib/tsc.js — the classic bin/tsc path only exists
	// on the classic layout. Field 2026-09-09: with a fresh npm ci every
	// compile died in <1s ("tsc failed (exit 1)") and the compiled panel
	// silently stayed old for days. Resolve whatever the installed package
	// actually provides.
	const tsPkg = path.join(FORK_ROOT, 'node_modules', 'typescript');
	const tscRel = ['bin/tsc', 'bin/tsc6', 'lib/tsc.js'].find((rel) => fs.existsSync(path.join(tsPkg, rel)));
	if (!tscRel) {
		throw new Error('[crusorai-compile] no tsc CLI found in node_modules/typescript — run npm install in desktop/vscode first');
	}
	// Layer 33: the parent gulp process has --max-old-space-size=8192 but
	// that flag does NOT cross a spawn boundary. The tsc child spawned bare
	// ran on Node's default ~4GB heap and OOM'd (exit 134). Give the child
	// its own 8GB ceiling, overridable via CRUSORAI_TSC_MAX_OLD_SPACE.
	const tscHeap = process.env.CRUSORAI_TSC_MAX_OLD_SPACE || '8192';
	crusorLog(`using node_modules/typescript/${tscRel} (child heap: --max-old-space-size=${tscHeap})`);
	const result = spawnSync(process.execPath, [`--max-old-space-size=${tscHeap}`, path.join(tsPkg, tscRel), '-p', SRC], {
		stdio: 'inherit',
		cwd: FORK_ROOT,
	});
	if (result.status !== 0) {
		throw new Error(`[crusorai-compile] tsc failed (exit ${result.status})`);
	}
	crusorLog('tsc finished');
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
				crusorLog('resources copied (css / ttf / wasm / media incl. crusorai-spa)');
				resolve();
			})
			.on('error', reject);
	});
}

function writeBuildInfo() {
	// Stamp the compiled panel with the commit it was built from. The engine
	// reads this file to tell the owner, in the log they already read, whether
	// the compiled panel is current — no mtime jitter, no guessing.
	const dir = path.join(OUT, 'vs', 'workbench', 'contrib', 'crusorai', 'browser');
	let commit = 'unknown';
	try {
		const proc = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: FORK_ROOT, encoding: 'utf8' });
		if (proc.status === 0) { commit = proc.stdout.trim(); }
	} catch {
		// not a git checkout — stamp the time only
	}
	fs.mkdirSync(dir, { recursive: true });
	fs.writeFileSync(path.join(dir, 'BUILD_INFO.json'), `${JSON.stringify({ commit, builtAt: new Date().toISOString() }, null, 2)}\n`);
}

export async function compile() {
	ensureNodeModules();
	runTsc();
	await copyResources();
	writeBuildInfo();
	crusorLog('done: out/ is ready — fully quit the app and reopen it');
}

export function compileWeb() {
	throw new Error(
		'compile-web is not supported in this fork: the CrusorAI desktop target is Electron-only.'
	);
}

export default gulp.series(compile);
