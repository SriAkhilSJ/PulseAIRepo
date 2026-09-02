/*
 * Carries the built SPA into the fork so the CopilotKit tab can frame it from the workbench's own
 * origin. `frame-src 'self'` is the only thing a workbench document is allowed to frame, and the app
 * root is `desktop/vscode` (dev) or the packaged app dir -- so the files have to live inside it.
 *
 * Two destinations, deliberately: `src/.../media/pulseai-spa` is the durable one the fork's own
 * copy step carries into `out/` on the next compile, and `out/...` is written too when it exists so a
 * window that is already built shows the new bundle without waiting for a recompile.
 */
import { cpSync, existsSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const webview = path.resolve(here, '..');
const dist = path.join(webview, 'dist');
const rel = path.join('vs', 'workbench', 'contrib', 'pulseai', 'browser', 'media', 'pulseai-spa');
const vscodeRoot = path.resolve(webview, '..', 'desktop', 'vscode');

if (!existsSync(dist)) {
  console.error('[pulseai] no dist/ to copy -- run `vite build` first.');
  process.exit(1);
}

const targets = [path.join(vscodeRoot, 'src', rel)];
const outDir = path.join(vscodeRoot, 'out', rel);
if (existsSync(path.join(vscodeRoot, 'out'))) { targets.push(outDir); }

for (const target of targets) {
  rmSync(target, { recursive: true, force: true });
  cpSync(dist, target, { recursive: true });
  console.log(`[pulseai] copied dist/ -> ${path.relative(path.resolve(webview, '..', '..'), target)}`);
}
console.log('[pulseai] the CopilotKit tab reads this at pulseai.copilotWebview.url = "local".');
