// Scoped emitter: transpiles ONLY the pulseai contrib subtree with the
import { fileURLToPath } from 'node:url';
// fork's compiler options. Rationale: the full `tsc -p src` program needs
// >3GB heap (OOMs on modest machines/sandboxes), and the field has been
// stuck on a Sept-5 panel for days. The pulseai subtree is `import type`-
// disciplined, so per-file emit preserves semantics: type-only imports are
// erased by syntax, value imports are kept verbatim (ESM, "type": module).
import ts from '../node_modules/typescript/lib/typescript.js';
import fs from 'node:fs';
import path from 'node:path';

const FORK = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC_ROOT = path.join(FORK, 'src', 'vs', 'workbench', 'contrib', 'pulseai');
const OUT_ROOT = path.join(FORK, 'out', 'vs', 'workbench', 'contrib', 'pulseai');

const compilerOptions = {
	module: ts.ModuleKind.ESNext,
	target: ts.ScriptTarget.ES2024,
	esModuleInterop: true,
	preserveConstEnums: true,
	removeComments: false,
	useDefineForClassFields: false,
	sourceMap: false,
};

let count = 0;
function emit(dir) {
	for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
		const src = path.join(dir, entry.name);
		if (entry.isDirectory()) { emit(src); continue; }
		if (!entry.name.endsWith('.ts')) { continue; }
		const rel = path.relative(SRC_ROOT, src);
		const out = path.join(OUT_ROOT, rel.replace(/\.ts$/, '.js'));
		fs.mkdirSync(path.dirname(out), { recursive: true });
		const text = fs.readFileSync(src, 'utf8');
		const res = ts.transpileModule(text, {
			compilerOptions,
			fileName: src, // pins the nodenext module format via package.json "type"
			reportDiagnostics: true,
		});
		const diags = (res.diagnostics ?? []).map((d) => ts.flattenDiagnosticMessageText(d.messageText, ' '));
		if (diags.length) { console.error(`DIAG ${rel}: ${diags.join('; ')}`); process.exitCode = 1; }
		fs.writeFileSync(out, res.outputText);
		count += 1;
	}
}
emit(SRC_ROOT);
console.log(`emitted ${count} file(s)`);
