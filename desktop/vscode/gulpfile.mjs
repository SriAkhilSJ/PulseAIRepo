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
 *      media/ tree from src/vs into out/vs.
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
	// Field 2026-10-03: this used to be `gulp.src(...).pipe(gulp.dest(OUT))`,
	// which failed at random with `EIO: i/o error, write` (reproduced ~1 run
	// in 3 on this box, no path in the error, so the file was unfindable).
	// A sequential fs copy of the SAME file set never fails, names the exact
	// file when it does, and retries the transient write errors.
	const RESOURCE_EXT = new Set(['.css', '.ttf', '.wasm', '.html']);
	let copied = 0;
	const copyOne = (from, to) => {
		fs.mkdirSync(path.dirname(to), { recursive: true });
		const data = readFileRetry(from);
		let lastErr;
		for (let attempt = 0; attempt < 3; attempt++) {
			try {
				fs.writeFileSync(to, data);
				// read-back verify: a silently short/NUL-filled write is
				// exactly the glitch this build step keeps hitting.
				const written = readFileRetry(to);
				if (written.length !== data.length || !written.equals(data)) {
					lastErr = new Error('read-back mismatch (partial write)');
					Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 200);
					continue;
				}
				copied++;
				return;
			} catch (err) {
				lastErr = err;
				Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 200);
			}
		}
		throw new Error(`[crusorai-compile] resource copy failed for ${from} -> ${to}: ${lastErr.message}`);
	};
	const walk = (dir) => {
		for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
			const full = path.join(dir, entry.name);
			if (entry.isDirectory()) {
				if (entry.name === 'media') { fs.mkdirSync(path.join(OUT, path.relative(SRC, full)), { recursive: true }); }
				walk(full);
				continue;
			}
			const isResource = RESOURCE_EXT.has(path.extname(entry.name).toLowerCase());
			const underMedia = full.slice(SRC.length + 1).split(path.sep).includes('media');
			if (isResource || underMedia) {
				copyOne(full, path.join(OUT, path.relative(SRC, full)));
			}
		}
	};
	walk(SRC);
	crusorLog(`resources copied: ${copied} files (css / ttf / wasm / html / media)`);
}

function readFileRetry(file) {
	// The D: volume (USB-attached Micron) throws transient
	// `UNKNOWN: unknown error, read` under load — never trust one read.
	let lastErr;
	for (let attempt = 0; attempt < 3; attempt++) {
		try {
			return fs.readFileSync(file);
		} catch (err) {
			lastErr = err;
			Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 200);
		}
	}
	throw lastErr;
}

function findTornOutputs() {
	// A torn write on this box leaves the first 4 KB of an emitted .js and
	// NUL-fills the rest — the app then dies with "SyntaxError: Invalid or
	// unexpected token" at a line that looks like normal code. Cheap to
	// detect (a NUL byte can never appear in emitted JS), fatal to ship.
	const torn = [];
	const unreadable = [];
	const walkOut = (dir) => {
		for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
			const full = path.join(dir, entry.name);
			if (entry.isDirectory()) { walkOut(full); continue; }
			if (!entry.name.endsWith('.js')) { continue; }
			try {
				if (readFileRetry(full).includes(0)) { torn.push(full); }
			} catch {
				// can't even read it back — treat as damaged and re-emit
				unreadable.push(full);
			}
		}
	};
	walkOut(OUT);
	return [...torn, ...unreadable];
}

function compileTscWithIntegrity() {
	runTsc();
	for (let attempt = 1; attempt <= 2; attempt++) {
		const torn = findTornOutputs();
		if (torn.length === 0) { return; }
		crusorLog(`torn emit detected (${torn.length} partial file(s)) — deleting and re-emitting (attempt ${attempt})`);
		for (const file of torn) { fs.rmSync(file, { force: true }); }
		runTsc();
	}
	const stillTorn = findTornOutputs();
	if (stillTorn.length > 0) {
		throw new Error(`[crusorai-compile] still torn after 2 re-emits: ${stillTorn.join(', ')}`);
	}
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
	compileTscWithIntegrity();
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
