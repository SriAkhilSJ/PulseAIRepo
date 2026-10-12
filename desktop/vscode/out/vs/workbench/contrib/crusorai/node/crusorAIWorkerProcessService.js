/*---------------------------------------------------------------------------------------------
 * Node utility-process owner for the CrusorAI Python sidecar.
 *--------------------------------------------------------------------------------------------*/
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, isAbsolute, join } from 'node:path';
import { createInterface } from 'node:readline';
import { Emitter } from '../../../../base/common/event.js';
import { FileAccess, Schemas } from '../../../../base/common/network.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
const MAX_FRAME_BYTES = 1 << 20;
const STOP_GRACE_MS = 1_500;
const MAX_ENGINE_ROOT_UPWALK = 10;
/**
 * The engine root that actually owns `src/bridge`. The requested root is
 * honored only when it IS an engine (field 2026-09-05: the user changed the
 * opened folder to a Next.js app -> `python -m src.bridge` was doomed in a
 * directory with no src.bridge -> "send button not working", the failure
 * invisible because the throw surfaced nowhere the user reads). When the
 * requested root is a folder INSIDE the engine repo (the standing workflow:
 * test workspaces nested under PulseAIRepo), the owning repo is a few
 * parents up — walk and resolve, loudly.
 */
function ownsBridge(root) {
    return existsSync(join(root, 'src', 'bridge', '__main__.py'));
}
// This worker file lives in the ENGINE'S OWN INSTALL TREE
// (<repo>/desktop/vscode/out/vs/workbench/contrib/crusorai/node) — walking up
// from it finds the repo that owns src/bridge regardless of which folder the
// user opened (field 2026-09-05: d:\TestCrusorAI is a SIBLING of the repo, no
// up-walk from it can ever reach the engine — but the engine can reach
// itself). Self-location has two paths: real CommonJS Node contexts have
// __dirname — but THIS process doesn't: utility processes load the worker as
// ESM (bootstrap-fork.ts `await import(VSCODE_ESM_ENTRYPOINT)`, tsconfig
// module nodenext), and __dirname does not exist in ESM. Field 2026-09-05:
// `typeof __dirname` was 'undefined' and the first install-tree walk silently
// never ran ("up-walk and install tree both exhausted" even though the file
// sat inside the repo). So fall back to FileAccess, which resolves this
// module's own id against _VSCODE_FILE_ROOT (set by bootstrap-esm.ts from
// import.meta.dirname in this process, by workbench.ts in the renderer) and
// comes back as vscode-file://vscode-app/<appRoot>/out/vs/…
const MODULE_ID = 'vs/workbench/contrib/crusorai/node/crusorAIWorkerProcessService.js';
function currentModuleDir() {
    if (typeof __dirname !== 'undefined' && __dirname) {
        return __dirname;
    }
    try {
        const uri = FileAccess.asBrowserUri(MODULE_ID);
        if (uri.scheme === Schemas.file) {
            return dirname(uri.fsPath);
        }
        if (uri.scheme === Schemas.vscodeFileResource) {
            // vscode-file://vscode-app/D:/… — `fsPath` would UNC-ify the
            // authority, so take the path and strip the POSIX lead off a
            // Windows drive ("/D:/…" -> "D:/…").
            let p = decodeURIComponent(uri.path);
            if (/^\/[A-Za-z]:\//.test(p)) {
                p = p.slice(1);
            }
            return p ? dirname(p) : undefined;
        }
    }
    catch {
        // No file root in this context (web/remote) — the install tree is not
        // a local directory there anyway.
    }
    return undefined;
}
function resolveEngineDirectory(requested, note) {
    if (ownsBridge(requested)) {
        return requested;
    }
    let current = dirname(requested);
    for (let hops = 0; hops < MAX_ENGINE_ROOT_UPWALK; hops++) {
        if (ownsBridge(current)) {
            note(`engine root: '${requested}' has no src/bridge — resolved UP to '${current}'`);
            return current;
        }
        const parent = dirname(current);
        if (parent === current) {
            break;
        }
        current = parent;
    }
    const moduleDir = currentModuleDir();
    if (moduleDir) {
        current = moduleDir;
        for (let hops = 0; hops < MAX_ENGINE_ROOT_UPWALK; hops++) {
            if (ownsBridge(current)) {
                note(`engine root: workspace '${requested}' is outside the engine repo — resolved from the install tree to '${current}'`);
                return current;
            }
            const parent = dirname(current);
            if (parent === current) {
                break;
            }
            current = parent;
        }
    }
    note(`no src/bridge/__main__.py from '${requested}', its parents, or the install tree` +
        (moduleDir ? ` (probed from '${moduleDir}')` : ' (module self-location unavailable in this process)') + '. ' +
        `Open a folder inside the CrusorAI repo, or set 'crusorai.engineRoot' to the repo root.`);
    throw new Error(`CrusorAI bridge not found for workspace '${requested}' (up-walk and install tree both exhausted). ` +
        `Set 'crusorai.engineRoot' to the folder that contains src/bridge.`);
}
function checkedFrame(frame) {
    if (Buffer.byteLength(frame, 'utf8') > MAX_FRAME_BYTES) {
        throw new Error(`CrusorAI bridge frame exceeds ${MAX_FRAME_BYTES} bytes`);
    }
    if (frame.includes('\n') || frame.includes('\r')) {
        throw new Error('CrusorAI bridge frame must be one line');
    }
    const value = JSON.parse(frame);
    if (!value || typeof value !== 'object' || typeof value.type !== 'string') {
        throw new Error('CrusorAI bridge frame must contain a string type');
    }
    return frame;
}
export class CrusorAIWorkerProcessService extends Disposable {
    constructor() {
        super(...arguments);
        this.stopping = false;
        this._onDidReceiveFrame = this._register(new Emitter());
        this.onDidReceiveFrame = this._onDidReceiveFrame.event;
        this._onDidWriteStderr = this._register(new Emitter());
        this.onDidWriteStderr = this._onDidWriteStderr.event;
        this._onDidChangeState = this._register(new Emitter());
        this.onDidChangeState = this._onDidChangeState.event;
    }
    async start(options) {
        await this.stop();
        if (!isAbsolute(options.engineRoot)) {
            throw new Error('CrusorAI engine root must be an absolute path');
        }
        const engineRoot = resolveEngineDirectory(options.engineRoot, line => this._onDidWriteStderr.fire(line));
        this.stopping = false;
        this._onDidChangeState.fire({ state: 'starting' });
        const venvPython = process.platform === 'win32'
            ? join(engineRoot, '.venv', 'Scripts', 'python.exe')
            : join(engineRoot, '.venv', 'bin', 'python');
        const python = options.pythonPath || process.env['CRUSORAI_PYTHON_PATH'] || (existsSync(venvPython) ? venvPython : (process.platform === 'win32' ? 'python' : 'python3'));
        const child = spawn(python, ['-m', 'src.bridge'], {
            cwd: engineRoot,
            env: { ...process.env, PYTHONUNBUFFERED: '1' },
            stdio: ['pipe', 'pipe', 'pipe'],
            windowsHide: true,
            shell: false,
        });
        this.child = child;
        // A failed SPAWN (python not on PATH, permission denied) fires 'error'
        // and never reaches the stderr pipe — without this listener the only
        // symptom was "handshake timed out" with zero diagnostics.
        child.on('error', (err) => {
            this._onDidWriteStderr.fire(`engine spawn failed: ${err.message} (python='${python}', cwd='${engineRoot}'). ` +
                `Install Python or set 'crusorai.pythonPath'.`);
        });
        this.stdout = createInterface({ input: child.stdout, crlfDelay: Infinity });
        this.stdout.on('line', line => {
            if (Buffer.byteLength(line, 'utf8') <= MAX_FRAME_BYTES) {
                this._onDidReceiveFrame.fire(line);
            }
            else {
                this._onDidWriteStderr.fire(`Dropped oversized CrusorAI frame (${Buffer.byteLength(line, 'utf8')} bytes)`);
            }
        });
        this.stderr = createInterface({ input: child.stderr, crlfDelay: Infinity });
        this.stderr.on('line', line => this._onDidWriteStderr.fire(line.slice(0, 16_000)));
        child.once('spawn', () => this._onDidChangeState.fire({ state: 'running' }));
        child.once('error', error => {
            this._onDidWriteStderr.fire(error.message);
            this._onDidChangeState.fire({ state: 'crashed', detail: error.message });
        });
        child.once('exit', (code, signal) => {
            this.stdout?.close();
            this.stderr?.close();
            this.stdout = undefined;
            this.stderr = undefined;
            if (this.child === child) {
                this.child = undefined;
            }
            this._onDidChangeState.fire({
                state: this.stopping || code === 0 ? 'stopped' : 'crashed',
                code: code ?? undefined,
                signal: signal ?? undefined,
            });
        });
    }
    async send(frame) {
        const child = this.child;
        if (!child || !child.stdin.writable) {
            throw new Error('CrusorAI sidecar is not running');
        }
        const line = `${checkedFrame(frame)}\n`;
        await new Promise((resolve, reject) => {
            child.stdin.write(line, error => error ? reject(error) : resolve());
        });
    }
    async stop() {
        const child = this.child;
        if (!child) {
            return;
        }
        this.stopping = true;
        if (child.stdin.writable) {
            try {
                child.stdin.write('{"type":"shutdown"}\n');
            }
            catch { /* force-kill below */ }
        }
        await Promise.race([
            new Promise(resolve => child.once('exit', () => resolve())),
            new Promise(resolve => setTimeout(resolve, STOP_GRACE_MS)),
        ]);
        if (this.child === child) {
            child.kill();
        }
    }
    dispose() {
        void this.stop();
        super.dispose();
    }
}
