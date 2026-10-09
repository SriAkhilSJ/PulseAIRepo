/*---------------------------------------------------------------------------------------------
 * Node utility-process owner for the CrusorAI Python sidecar.
 *--------------------------------------------------------------------------------------------*/
var __extends = (this && this.__extends) || (function () {
    var extendStatics = function (d, b) {
        extendStatics = Object.setPrototypeOf ||
            ({ __proto__: [] } instanceof Array && function (d, b) { d.__proto__ = b; }) ||
            function (d, b) { for (var p in b) if (Object.prototype.hasOwnProperty.call(b, p)) d[p] = b[p]; };
        return extendStatics(d, b);
    };
    return function (d, b) {
        if (typeof b !== "function" && b !== null)
            throw new TypeError("Class extends value " + String(b) + " is not a constructor or null");
        extendStatics(d, b);
        function __() { this.constructor = d; }
        d.prototype = b === null ? Object.create(b) : (__.prototype = b.prototype, new __());
    };
})();
var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
var __awaiter = (this && this.__awaiter) || function (thisArg, _arguments, P, generator) {
    function adopt(value) { return value instanceof P ? value : new P(function (resolve) { resolve(value); }); }
    return new (P || (P = Promise))(function (resolve, reject) {
        function fulfilled(value) { try { step(generator.next(value)); } catch (e) { reject(e); } }
        function rejected(value) { try { step(generator["throw"](value)); } catch (e) { reject(e); } }
        function step(result) { result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected); }
        step((generator = generator.apply(thisArg, _arguments || [])).next());
    });
};
var __generator = (this && this.__generator) || function (thisArg, body) {
    var _ = { label: 0, sent: function() { if (t[0] & 1) throw t[1]; return t[1]; }, trys: [], ops: [] }, f, y, t, g = Object.create((typeof Iterator === "function" ? Iterator : Object).prototype);
    return g.next = verb(0), g["throw"] = verb(1), g["return"] = verb(2), typeof Symbol === "function" && (g[Symbol.iterator] = function() { return this; }), g;
    function verb(n) { return function (v) { return step([n, v]); }; }
    function step(op) {
        if (f) throw new TypeError("Generator is already executing.");
        while (g && (g = 0, op[0] && (_ = 0)), _) try {
            if (f = 1, y && (t = op[0] & 2 ? y["return"] : op[0] ? y["throw"] || ((t = y["return"]) && t.call(y), 0) : y.next) && !(t = t.call(y, op[1])).done) return t;
            if (y = 0, t) op = [op[0] & 2, t.value];
            switch (op[0]) {
                case 0: case 1: t = op; break;
                case 4: _.label++; return { value: op[1], done: false };
                case 5: _.label++; y = op[1]; op = [0]; continue;
                case 7: op = _.ops.pop(); _.trys.pop(); continue;
                default:
                    if (!(t = _.trys, t = t.length > 0 && t[t.length - 1]) && (op[0] === 6 || op[0] === 2)) { _ = 0; continue; }
                    if (op[0] === 3 && (!t || (op[1] > t[0] && op[1] < t[3]))) { _.label = op[1]; break; }
                    if (op[0] === 6 && _.label < t[1]) { _.label = t[1]; t = op; break; }
                    if (t && _.label < t[2]) { _.label = t[2]; _.ops.push(op); break; }
                    if (t[2]) _.ops.pop();
                    _.trys.pop(); continue;
            }
            op = body.call(thisArg, _);
        } catch (e) { op = [6, e]; y = 0; } finally { f = t = 0; }
        if (op[0] & 5) throw op[1]; return { value: op[0] ? op[1] : void 0, done: true };
    }
};
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, isAbsolute, join } from 'node:path';
import { createInterface } from 'node:readline';
import { Emitter } from '../../../../base/common/event.js';
import { FileAccess, Schemas } from '../../../../base/common/network.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
var MAX_FRAME_BYTES = 1 << 20;
var STOP_GRACE_MS = 1500;
var MAX_ENGINE_ROOT_UPWALK = 10;
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
var MODULE_ID = 'vs/workbench/contrib/crusorai/node/crusorAIWorkerProcessService.js';
function currentModuleDir() {
    if (typeof __dirname !== 'undefined' && __dirname) {
        return __dirname;
    }
    try {
        var uri = FileAccess.asBrowserUri(MODULE_ID);
        if (uri.scheme === Schemas.file) {
            return dirname(uri.fsPath);
        }
        if (uri.scheme === Schemas.vscodeFileResource) {
            // vscode-file://vscode-app/D:/… — `fsPath` would UNC-ify the
            // authority, so take the path and strip the POSIX lead off a
            // Windows drive ("/D:/…" -> "D:/…").
            var p = decodeURIComponent(uri.path);
            if (/^\/[A-Za-z]:\//.test(p)) {
                p = p.slice(1);
            }
            return p ? dirname(p) : undefined;
        }
    }
    catch (_a) {
        // No file root in this context (web/remote) — the install tree is not
        // a local directory there anyway.
    }
    return undefined;
}
function resolveEngineDirectory(requested, note) {
    if (ownsBridge(requested)) {
        return requested;
    }
    var current = dirname(requested);
    for (var hops = 0; hops < MAX_ENGINE_ROOT_UPWALK; hops++) {
        if (ownsBridge(current)) {
            note("engine root: '".concat(requested, "' has no src/bridge \u2014 resolved UP to '").concat(current, "'"));
            return current;
        }
        var parent = dirname(current);
        if (parent === current) {
            break;
        }
        current = parent;
    }
    var moduleDir = currentModuleDir();
    if (moduleDir) {
        current = moduleDir;
        for (var hops = 0; hops < MAX_ENGINE_ROOT_UPWALK; hops++) {
            if (ownsBridge(current)) {
                note("engine root: workspace '".concat(requested, "' is outside the engine repo \u2014 resolved from the install tree to '").concat(current, "'"));
                return current;
            }
            var parent = dirname(current);
            if (parent === current) {
                break;
            }
            current = parent;
        }
    }
    note("no src/bridge/__main__.py from '".concat(requested, "', its parents, or the install tree") +
        (moduleDir ? " (probed from '".concat(moduleDir, "')") : ' (module self-location unavailable in this process)') + '. ' +
        "Open a folder inside the CrusorAI repo, or set 'crusorai.engineRoot' to the repo root.");
    throw new Error("CrusorAI bridge not found for workspace '".concat(requested, "' (up-walk and install tree both exhausted). ") +
        "Set 'crusorai.engineRoot' to the folder that contains src/bridge.");
}
function checkedFrame(frame) {
    if (Buffer.byteLength(frame, 'utf8') > MAX_FRAME_BYTES) {
        throw new Error("CrusorAI bridge frame exceeds ".concat(MAX_FRAME_BYTES, " bytes"));
    }
    if (frame.includes('\n') || frame.includes('\r')) {
        throw new Error('CrusorAI bridge frame must be one line');
    }
    var value = JSON.parse(frame);
    if (!value || typeof value !== 'object' || typeof value.type !== 'string') {
        throw new Error('CrusorAI bridge frame must contain a string type');
    }
    return frame;
}
var CrusorAIWorkerProcessService = /** @class */ (function (_super) {
    __extends(CrusorAIWorkerProcessService, _super);
    function CrusorAIWorkerProcessService() {
        var _this = _super !== null && _super.apply(this, arguments) || this;
        _this.stopping = false;
        _this._onDidReceiveFrame = _this._register(new Emitter());
        _this.onDidReceiveFrame = _this._onDidReceiveFrame.event;
        _this._onDidWriteStderr = _this._register(new Emitter());
        _this.onDidWriteStderr = _this._onDidWriteStderr.event;
        _this._onDidChangeState = _this._register(new Emitter());
        _this.onDidChangeState = _this._onDidChangeState.event;
        return _this;
    }
    CrusorAIWorkerProcessService.prototype.start = function (options) {
        return __awaiter(this, void 0, Promise, function () {
            var engineRoot, venvPython, python, child;
            var _this = this;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0: return [4 /*yield*/, this.stop()];
                    case 1:
                        _a.sent();
                        if (!isAbsolute(options.engineRoot)) {
                            throw new Error('CrusorAI engine root must be an absolute path');
                        }
                        engineRoot = resolveEngineDirectory(options.engineRoot, function (line) { return _this._onDidWriteStderr.fire(line); });
                        this.stopping = false;
                        this._onDidChangeState.fire({ state: 'starting' });
                        venvPython = process.platform === 'win32'
                            ? join(engineRoot, '.venv', 'Scripts', 'python.exe')
                            : join(engineRoot, '.venv', 'bin', 'python');
                        python = options.pythonPath || process.env['CRUSORAI_PYTHON_PATH'] || (existsSync(venvPython) ? venvPython : (process.platform === 'win32' ? 'python' : 'python3'));
                        child = spawn(python, ['-m', 'src.bridge'], {
                            cwd: engineRoot,
                            env: __assign(__assign({}, process.env), { PYTHONUNBUFFERED: '1' }),
                            stdio: ['pipe', 'pipe', 'pipe'],
                            windowsHide: true,
                            shell: false,
                        });
                        this.child = child;
                        // A failed SPAWN (python not on PATH, permission denied) fires 'error'
                        // and never reaches the stderr pipe — without this listener the only
                        // symptom was "handshake timed out" with zero diagnostics.
                        child.on('error', function (err) {
                            _this._onDidWriteStderr.fire("engine spawn failed: ".concat(err.message, " (python='").concat(python, "', cwd='").concat(engineRoot, "'). ") +
                                "Install Python or set 'crusorai.pythonPath'.");
                        });
                        this.stdout = createInterface({ input: child.stdout, crlfDelay: Infinity });
                        this.stdout.on('line', function (line) {
                            if (Buffer.byteLength(line, 'utf8') <= MAX_FRAME_BYTES) {
                                _this._onDidReceiveFrame.fire(line);
                            }
                            else {
                                _this._onDidWriteStderr.fire("Dropped oversized CrusorAI frame (".concat(Buffer.byteLength(line, 'utf8'), " bytes)"));
                            }
                        });
                        this.stderr = createInterface({ input: child.stderr, crlfDelay: Infinity });
                        this.stderr.on('line', function (line) { return _this._onDidWriteStderr.fire(line.slice(0, 16000)); });
                        child.once('spawn', function () { return _this._onDidChangeState.fire({ state: 'running' }); });
                        child.once('error', function (error) {
                            _this._onDidWriteStderr.fire(error.message);
                            _this._onDidChangeState.fire({ state: 'crashed', detail: error.message });
                        });
                        child.once('exit', function (code, signal) {
                            var _a, _b;
                            (_a = _this.stdout) === null || _a === void 0 ? void 0 : _a.close();
                            (_b = _this.stderr) === null || _b === void 0 ? void 0 : _b.close();
                            _this.stdout = undefined;
                            _this.stderr = undefined;
                            if (_this.child === child) {
                                _this.child = undefined;
                            }
                            _this._onDidChangeState.fire({
                                state: _this.stopping || code === 0 ? 'stopped' : 'crashed',
                                code: code !== null && code !== void 0 ? code : undefined,
                                signal: signal !== null && signal !== void 0 ? signal : undefined,
                            });
                        });
                        return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIWorkerProcessService.prototype.send = function (frame) {
        return __awaiter(this, void 0, Promise, function () {
            var child, line;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        child = this.child;
                        if (!child || !child.stdin.writable) {
                            throw new Error('CrusorAI sidecar is not running');
                        }
                        line = "".concat(checkedFrame(frame), "\n");
                        return [4 /*yield*/, new Promise(function (resolve, reject) {
                                child.stdin.write(line, function (error) { return error ? reject(error) : resolve(); });
                            })];
                    case 1:
                        _a.sent();
                        return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIWorkerProcessService.prototype.stop = function () {
        return __awaiter(this, void 0, Promise, function () {
            var child;
            return __generator(this, function (_a) {
                switch (_a.label) {
                    case 0:
                        child = this.child;
                        if (!child) {
                            return [2 /*return*/];
                        }
                        this.stopping = true;
                        if (child.stdin.writable) {
                            try {
                                child.stdin.write('{"type":"shutdown"}\n');
                            }
                            catch ( /* force-kill below */_b) { /* force-kill below */ }
                        }
                        return [4 /*yield*/, Promise.race([
                                new Promise(function (resolve) { return child.once('exit', function () { return resolve(); }); }),
                                new Promise(function (resolve) { return setTimeout(resolve, STOP_GRACE_MS); }),
                            ])];
                    case 1:
                        _a.sent();
                        if (this.child === child) {
                            child.kill();
                        }
                        return [2 /*return*/];
                }
            });
        });
    };
    CrusorAIWorkerProcessService.prototype.dispose = function () {
        void this.stop();
        _super.prototype.dispose.call(this);
    };
    return CrusorAIWorkerProcessService;
}(Disposable));
export { CrusorAIWorkerProcessService };
