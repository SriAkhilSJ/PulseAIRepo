// Scoped emitter: transpiles ONLY the crusorai contrib subtree for shipping
// inside git (a plain `git pull` updates the Agent pane with NO local
// compile step — field 2026-09-09: three rounds of UI fixes never reached
// the owner because the manual compile kept failing silently).
//
// Compiler options are parsed from the fork's REAL src/tsconfig.json chain
// (extends tsconfig.base.json) — NOT hand-picked. Round-1 lesson: omitting
// `experimentalDecorators: true` made every DI-injected class emit with the
// wrong decorator transform; vscode's InstantiationService could not read
// the parameter metadata and the pane died at construction (blank panel in
// the field). The full `tsc -p src` program needs >3GB heap and OOMs on
// modest machines, hence per-file transpile — but options come from the
// project, always. The crusorai subtree is `import type`-disciplined, so
// per-file emit preserves semantics; the emitted files are ESM (fork is
// "type": module).
import ts from '../node_modules/typescript/lib/typescript.js';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const FORK = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC_ROOT = path.join(FORK, 'src', 'vs', 'workbench', 'contrib', 'crusorai');
const OUT_ROOT = path.join(FORK, 'out', 'vs', 'workbench', 'contrib', 'crusorai');

const configPath = path.join(FORK, 'src', 'tsconfig.json');
const parsed = ts.getParsedCommandLineOfConfigFile(
	configPath,
	{ noEmit: false, declaration: false, sourceMap: false, rootDir: path.join(FORK, 'src') },
	{
		...ts.sys,
		getCurrentDirectory: () => path.dirname(configPath),
	},
);
if (!parsed) { throw new Error(`[emit] cannot parse ${configPath}`); }
// The workbench loader consumes these files as ES modules (fork is
// "type": module); the project's nodenext setting makes per-file
// transpileModule emit CommonJS (field round-3 regression), so the module
// kind is forced ESM while EVERYTHING else stays exactly as the project
// sets it.
const compilerOptions = {
	...parsed.options,
	module: ts.ModuleKind.ESNext,
	// pairs with the forced module kind; resolution is irrelevant for
	// transpile (specifiers emit verbatim) — this only silences the
	// nodenext-pairing diagnostic.
	moduleResolution: ts.ModuleResolutionKind.Bundler,
};
if (compilerOptions.experimentalDecorators !== true) {
	throw new Error('[emit] refusing to run: the fork tsconfig must set experimentalDecorators (DI parameter decorators)');
}
console.log(`[emit] compiler options inherited from src/tsconfig.json (target ${ts.ScriptTarget[compilerOptions.target]}, experimentalDecorators=${!!compilerOptions.experimentalDecorators})`);

let count = 0;
function emit(dir) {
	for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
		const src = path.join(dir, entry.name);
		if (entry.isDirectory()) { emit(src); continue; }
		if (!entry.name.endsWith('.ts')) { continue; }
		const rel = path.relative(SRC_ROOT, src);
		const out = path.join(OUT_ROOT, rel.replace(/\.ts$/, '.js'));
		fs.mkdirSync(path.dirname(out), { recursive: true });
		const res = ts.transpileModule(fs.readFileSync(src, 'utf8'), {
			compilerOptions,
			fileName: src,
			reportDiagnostics: true,
		});
		const diags = (res.diagnostics ?? []).map((d) => ts.flattenDiagnosticMessageText(d.messageText, ' '));
		if (diags.length) { console.error(`DIAG ${rel}: ${diags.join('; ')}`); process.exitCode = 1; }
		fs.writeFileSync(out, res.outputText);
		count += 1;
	}
}
emit(SRC_ROOT);

// Sources hash: sha256 over EVERYTHING under the contrib tree (ts + css +
// media — CSS changes the UI too) plus this script, in a deterministic
// order. BUILD_INFO carries it and the ENGINE recomputes it from the pulled
// sources: match = the shipped bundle was emitted from exactly these
// sources; mismatch = STALE. Exact, no git ancestry guesswork (field
// 2026-09-10: the commit stamp captured a rolled-back HEAD and the
// ancestor check passed by luck), no mtime jitter.
function collectFiles(dir, out) {
	for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
		const src = path.join(dir, entry.name);
		if (entry.isDirectory()) { collectFiles(src, out); continue; }
		out.push(src);
	}
	return out;
}
// The engine recomputes this hash in Python — the recipe must match
// BYTE-FOR-BYTE: sort by the relative POSIX path in plain codepoint
// order (default string sort), feed rel + NUL + line-ending-normalized
// bytes + NUL. Normalization: CRLF -> LF at the BYTE level (latin1
// round-trips any byte sequence losslessly, utf8 would corrupt the
// binary assets). Field 2026-09-10: the owner's Windows checkout keeps
// CRLF copies of files a pull never rewrote (.gitattributes eol=lf only
// applies to files git actually checks out), so raw bytes hashed
// differently per machine and the exact-freshness banner cried STALE on
// a current panel. Content changes still flip the hash — only checkout
// line-ending state stops mattering.
function normalizeEol(buf) {
  return Buffer.from(buf.toString('latin1').replace(/\r\n/g, '\n'), 'latin1');
}
const hash = crypto.createHash('sha256');
const relOf = (f) => path.relative(FORK, f).split(path.sep).join('/');
for (const f of collectFiles(SRC_ROOT, []).map(relOf).sort()) {
	hash.update(f).update('\0').update(normalizeEol(fs.readFileSync(path.join(FORK, f)))).update('\0');
}
const emitterRel = relOf(path.join(FORK, 'scripts', 'emit-crusorai-bundle.mjs'));
hash.update(emitterRel).update('\0')
	.update(normalizeEol(fs.readFileSync(path.join(FORK, 'scripts', 'emit-crusorai-bundle.mjs')))).update('\0');
const SOURCES_HASH = hash.digest('hex');
fs.writeFileSync(path.join(OUT_ROOT, 'browser', 'SOURCES_HASH'), SOURCES_HASH + '\n');

// Per-file manifest for DIAGNOSIS only (the aggregate above stays the
// verdict). Field 2026-09-10: a Windows checkout still hashed differently
// from the sandbox for an on-disk reason nobody could see — the engine now
// diffs against this manifest and NAMES the differing/missing/extra files
// in the STALE banner, so the next mismatch is a one-look fix
// (`git status` / `git checkout -- <file>`), not a mystery.
const manifest = { sourcesHash: SOURCES_HASH, files: {} };
for (const f of collectFiles(SRC_ROOT, []).map(relOf).sort()) {
	manifest.files[f] = crypto.createHash('sha256')
		.update(normalizeEol(fs.readFileSync(path.join(FORK, f)))).digest('hex');
}
fs.writeFileSync(
	path.join(OUT_ROOT, 'browser', 'SOURCES_MANIFEST.json'),
	JSON.stringify(manifest, null, '\t') + '\n');

// Emit-time DI assertion (field 2026-09-10: a bundle whose parameter
// decorators were dropped loaded fine, then EVERY injected service was
// undefined — blank pane, contributions dead, Copilot took over; nothing
// in syntax or imports could see it). Any source file that decorates
// constructor parameters MUST emit legacy __param applications.
const diSources = [];
(function scan(dir) {
	for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
		const src = path.join(dir, entry.name);
		if (entry.isDirectory()) { scan(src); continue; }
		if (!entry.name.endsWith('.ts')) { continue; }
		if (/^\s*@[A-Za-z_$][\w$]*\s+(?:(?:private|public|protected|readonly)\s+)*[\w$]+\s*:/m.test(fs.readFileSync(src, 'utf8'))) {
			diSources.push(src);
		}
	}
})(SRC_ROOT);
let diFailures = 0;
for (const src of diSources) {
	const out = path.join(OUT_ROOT, path.relative(SRC_ROOT, src).replace(/\.ts$/, '.js'));
	const js = fs.readFileSync(out, 'utf8');
	if (!js.includes('__param(')) {
		console.error(`[emit] FATAL DI: ${path.relative(SRC_ROOT, src)} decorates constructor parameters but ${path.relative(OUT_ROOT, out)} has no __param applications`);
		diFailures += 1;
	}
}
if (diFailures) { throw new Error(`[emit] refusing to ship: ${diFailures} file(s) lost their DI parameter decorators`); }
console.log(`[emit] DI check ok (${diSources.length} DI-injected file(s) carry __param)`);
console.log(`[emit] wrote ${count} file(s)`);
