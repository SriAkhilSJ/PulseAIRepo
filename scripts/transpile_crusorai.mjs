import * as fs from 'fs';
import * as path from 'path';
import crypto from 'crypto';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
const ts = require(path.resolve('desktop/vscode/node_modules/typescript'));

const VSCODE_ROOT = path.resolve('desktop/vscode');
const SRC_ROOT = path.join(VSCODE_ROOT, 'src/vs/workbench/contrib/crusorai');
const OUT_ROOT = path.join(VSCODE_ROOT, 'out/vs/workbench/contrib/crusorai');

const compilerOptions = {
	target: ts.ScriptTarget.ES2024,
	module: ts.ModuleKind.ESNext,
	moduleResolution: ts.ModuleResolutionKind.NodeNext,
	experimentalDecorators: true,
	useDefineForClassFields: false,
	removeComments: false,
};

async function walk(dir) {
	let files = [];
	const entries = await fs.promises.readdir(dir, { withFileTypes: true });
	for (const entry of entries) {
		const full = path.join(dir, entry.name);
		if (entry.isDirectory()) {
			files = files.concat(await walk(full));
		} else {
			files.push(full);
		}
	}
	return files;
}

async function main() {
	console.log(`Transpiling ${SRC_ROOT} -> ${OUT_ROOT}...`);
	const srcFiles = await walk(SRC_ROOT);
	let count = 0;
	const fileHashes = {};

	for (const srcPath of srcFiles) {
		const rel = path.relative(SRC_ROOT, srcPath).replace(/\\/g, '/');
		const content = await fs.promises.readFile(srcPath);
		const hash = crypto.createHash('sha256').update(content).digest('hex');
		fileHashes[`src/vs/workbench/contrib/crusorai/${rel}`] = hash;

		if (srcPath.endsWith('.ts')) {
			const destRel = rel.replace(/\.ts$/, '.js');
			const destPath = path.join(OUT_ROOT, destRel);
			const source = content.toString('utf-8');
			const result = ts.transpileModule(source, {
				compilerOptions,
				fileName: srcPath,
			});
			await fs.promises.mkdir(path.dirname(destPath), { recursive: true });
			await fs.promises.writeFile(destPath, result.outputText, 'utf-8');
			count++;
		} else {
			const destPath = path.join(OUT_ROOT, rel);
			await fs.promises.mkdir(path.dirname(destPath), { recursive: true });
			await fs.promises.copyFile(srcPath, destPath);
		}
	}

	const sortedKeys = Object.keys(fileHashes).sort();
	const manifestHasher = crypto.createHash('sha256');
	for (const key of sortedKeys) {
		manifestHasher.update(`${key}:${fileHashes[key]}\n`);
	}
	const sourcesHash = manifestHasher.digest('hex');

	const browserOut = path.join(OUT_ROOT, 'browser');
	await fs.promises.mkdir(browserOut, { recursive: true });
	await fs.promises.writeFile(path.join(browserOut, 'SOURCES_HASH'), sourcesHash + '\n', 'utf-8');
	await fs.promises.writeFile(path.join(browserOut, 'SOURCES_MANIFEST.json'), JSON.stringify({
		sourcesHash,
		files: fileHashes
	}, null, '\t') + '\n', 'utf-8');
	await fs.promises.writeFile(path.join(browserOut, 'BUILD_INFO.json'), JSON.stringify({
		commit: 'crusorai-dev-phase-9.3.4.1',
		builtAt: new Date().toISOString()
	}, null, '\t') + '\n', 'utf-8');

	console.log(`Successfully transpiled and synchronized ${count} TypeScript files to ${OUT_ROOT}!`);

	// Phase 12.1.3: Repository-owned build transformation for Node v24 ESM Electron compatibility
	await patchElectronEsmCompatibility(VSCODE_ROOT);
}

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

main().catch(err => {
	console.error(err);
	process.exit(1);
});
