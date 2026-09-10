// Bundle audit: every named import in the SHIPPED compiled pulseai slice
// must resolve to a runtime (value) export of its target — internal targets
// via the emitted JS, cross-slice targets via the source TS (the rest of the
// owner's out/ matches current source; only this slice changed). ESM named
// imports that the target does not export throw at instantiation and kill
// the whole contribution chain (field 2026-09-10: blank PULSE pane).
import ts from '../node_modules/typescript/lib/typescript.js';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FORK = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT_ROOT = path.join(FORK, 'out', 'vs', 'workbench', 'contrib', 'pulseai');
const SRC = path.join(FORK, 'src');

function valueExports(file, depth = 0) {
	const sf = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.ESNext, true);
	const names = new Set();
	const visit = (node) => {
		if (ts.isExportDeclaration(node) && node.exportClause && ts.isNamedExports(node.exportClause)) {
			for (const el of node.exportClause.elements) {
				if (el.isTypeOnly) continue;
				names.add((el.propertyName ?? el.name).text);
			}
		}
		const exported = !!node.modifiers?.some((m) => m.kind === ts.SyntaxKind.ExportKeyword);
		if (exported) {
			if ((ts.isClassDeclaration(node) || ts.isFunctionDeclaration(node) || ts.isEnumDeclaration(node)) && node.name) names.add(node.name.text);
			else if (ts.isModuleDeclaration(node) && node.name && ts.isIdentifier(node.name)) names.add(node.name.text);
			else if (ts.isVariableStatement(node)) {
				for (const d of node.declarationList.declarations) {
					if (ts.isIdentifier(d.name)) names.add(d.name.text);
				}
			}
		}
		if (ts.isExportDeclaration(node) && node.moduleSpecifier && !node.exportClause && depth < 3) {
			const base = path.resolve(path.dirname(file), node.moduleSpecifier.text);
			for (const c of [base, base.replace(/\.js$/, '.ts'), base + '.ts']) {
				if (fs.existsSync(c) && fs.statSync(c).isFile()) { for (const n of valueExports(c, depth + 1)) names.add(n); break; }
			}
		}
		ts.forEachChild(node, visit);
	};
	visit(sf);
	return names;
}

function resolveTarget(fromFile, spec) {
	if (!spec.startsWith('.')) return null;
	const base = path.resolve(path.dirname(fromFile), spec);
	// The sandbox/repo tree only carries the compiled pulseai slice under
	// out/ — every OTHER dependency exists only as SOURCE under src/. Try
	// the compiled location first, then the source-tree equivalents.
	const OUT_TREE = path.join(FORK, 'out');
	const srcBase = base.startsWith(OUT_TREE) ? base.replace(OUT_TREE, SRC) : base;
	for (const c of [base, base.replace(/\.js$/, '.ts'), base + '.ts', srcBase, srcBase.replace(/\.js$/, '.ts'), srcBase + '.ts']) {
		if (fs.existsSync(c) && fs.statSync(c).isFile()) return c;
	}
	return null;
}

let bad = 0;
const files = [];
(function walk(d) { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); e.isDirectory() ? walk(p) : p.endsWith('.js') && files.push(p); } })(OUT_ROOT);
for (const f of files) {
	const sf = ts.createSourceFile(f, fs.readFileSync(f, 'utf8'), ts.ScriptTarget.ESNext, true);
	const visit = (node) => {
		if (ts.isImportDeclaration(node) && node.importClause?.namedBindings && ts.isNamedImports(node.importClause.namedBindings)) {
			const spec = node.moduleSpecifier.text;
			if (!spec.startsWith('.')) { ts.forEachChild(node, visit); return; }
			const target = resolveTarget(f, spec);
			if (!target) { console.log(`MISSING TARGET: ${spec} from ${path.relative(OUT_ROOT, f)}`); bad++; ts.forEachChild(node, visit); return; }
			const exports = valueExports(target);
			for (const el of node.importClause.namedBindings.elements) {
				const name = (el.propertyName ?? el.name).text;
				if (!exports.has(name)) {
					console.log(`DEAD BINDING: ${name} (${path.relative(OUT_ROOT, f)} <- ${spec})`);
					bad++;
				}
			}
		}
		ts.forEachChild(node, visit);
	};
	visit(sf);
}
console.log(bad === 0 ? `AUDIT OK: ${files.length} file(s), every named import resolves to a runtime export` : `${bad} dead binding(s)`);
process.exitCode = bad === 0 ? 0 : 1;
