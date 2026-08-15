import ts from "typescript";
import { readdir, readFile } from "node:fs/promises";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../../desktop/vscode/src/vs/workbench/contrib/pulseai");

async function files(dir) {
  const result = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const path = resolve(dir, entry.name);
    if (entry.isDirectory()) result.push(...await files(path));
    else if (entry.name.endsWith(".ts")) result.push(path);
  }
  return result;
}

const inputs = await files(root);
for (const path of inputs) {
  const source = await readFile(path, "utf8");
  const result = ts.transpileModule(source, {
    fileName: path,
    reportDiagnostics: true,
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ESNext,
      experimentalDecorators: true,
      useDefineForClassFields: false,
    },
  });
  const errors = (result.diagnostics ?? []).filter((item) => item.category === ts.DiagnosticCategory.Error);
  if (errors.length > 0) {
    for (const error of errors) console.error(ts.flattenDiagnosticMessageText(error.messageText, "\n"));
    process.exitCode = 1;
    continue;
  }
  console.log(`syntax OK ${path.slice(root.length + 1)}`);
}
if (process.exitCode) process.exit(process.exitCode);
console.log(`${inputs.length} first-party contribution TypeScript files parsed`);
