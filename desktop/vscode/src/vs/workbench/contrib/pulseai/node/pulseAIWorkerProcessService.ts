/*---------------------------------------------------------------------------------------------
 * Node utility-process owner for the PulseAI Python sidecar.
 *--------------------------------------------------------------------------------------------*/

import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, isAbsolute, join } from 'node:path';
import { createInterface, type Interface as ReadlineInterface } from 'node:readline';
import { Emitter } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import {
	IPulseAIWorkerProcessService,
	PulseAIWorkerStartOptions,
	PulseAIWorkerStateChange,
} from '../common/pulseAIWorkerService.js';

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
function resolveEngineDirectory(requested: string, note: (line: string) => void): string {
	if (existsSync(join(requested, 'src', 'bridge', '__main__.py'))) {
		return requested;
	}
	let current = dirname(requested);
	for (let hops = 0; hops < MAX_ENGINE_ROOT_UPWALK; hops++) {
		if (existsSync(join(current, 'src', 'bridge', '__main__.py'))) {
			note(`engine root: '${requested}' has no src/bridge — resolved UP to '${current}'`);
			return current;
		}
		const parent = dirname(current);
		if (parent === current) { break; }
		current = parent;
	}
	note(
		`no src/bridge/__main__.py at '${requested}' or in ${MAX_ENGINE_ROOT_UPWALK} parent folder(s). ` +
		`Open a folder inside the PulseAI repo, or set 'pulseai.engineRoot' to the repo root.`
	);
	throw new Error(
		`PulseAI bridge not found under engine root: ${requested} (and ${MAX_ENGINE_ROOT_UPWALK} parent folders). ` +
		`Set 'pulseai.engineRoot' to the folder that contains src/bridge.`
	);
}

function checkedFrame(frame: string): string {
	if (Buffer.byteLength(frame, 'utf8') > MAX_FRAME_BYTES) {
		throw new Error(`PulseAI bridge frame exceeds ${MAX_FRAME_BYTES} bytes`);
	}
	if (frame.includes('\n') || frame.includes('\r')) {
		throw new Error('PulseAI bridge frame must be one line');
	}
	const value: unknown = JSON.parse(frame);
	if (!value || typeof value !== 'object' || typeof (value as { type?: unknown }).type !== 'string') {
		throw new Error('PulseAI bridge frame must contain a string type');
	}
	return frame;
}

export class PulseAIWorkerProcessService extends Disposable implements IPulseAIWorkerProcessService {
	private child: ChildProcessWithoutNullStreams | undefined;
	private stdout: ReadlineInterface | undefined;
	private stderr: ReadlineInterface | undefined;
	private stopping = false;

	private readonly _onDidReceiveFrame = this._register(new Emitter<string>());
	readonly onDidReceiveFrame = this._onDidReceiveFrame.event;
	private readonly _onDidWriteStderr = this._register(new Emitter<string>());
	readonly onDidWriteStderr = this._onDidWriteStderr.event;
	private readonly _onDidChangeState = this._register(new Emitter<PulseAIWorkerStateChange>());
	readonly onDidChangeState = this._onDidChangeState.event;

	async start(options: PulseAIWorkerStartOptions): Promise<void> {
		await this.stop();
		if (!isAbsolute(options.engineRoot)) {
			throw new Error('PulseAI engine root must be an absolute path');
		}
		const engineRoot = resolveEngineDirectory(options.engineRoot, line => this._onDidWriteStderr.fire(line));

		this.stopping = false;
		this._onDidChangeState.fire({ state: 'starting' });
		const venvPython = process.platform === 'win32'
			? join(engineRoot, '.venv', 'Scripts', 'python.exe')
			: join(engineRoot, '.venv', 'bin', 'python');
		const python = options.pythonPath || process.env['PULSEAI_PYTHON_PATH'] || (existsSync(venvPython) ? venvPython : (process.platform === 'win32' ? 'python' : 'python3'));
		const child = spawn(python, ['-m', 'src.bridge'], {
			cwd: engineRoot,
			env: { ...process.env, PYTHONUNBUFFERED: '1' },
			stdio: ['pipe', 'pipe', 'pipe'],
			windowsHide: true,
			shell: false,
		});
		this.child = child;

		this.stdout = createInterface({ input: child.stdout, crlfDelay: Infinity });
		this.stdout.on('line', line => {
			if (Buffer.byteLength(line, 'utf8') <= MAX_FRAME_BYTES) {
				this._onDidReceiveFrame.fire(line);
			} else {
				this._onDidWriteStderr.fire(`Dropped oversized PulseAI frame (${Buffer.byteLength(line, 'utf8')} bytes)`);
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
			if (this.child === child) { this.child = undefined; }
			this._onDidChangeState.fire({
				state: this.stopping || code === 0 ? 'stopped' : 'crashed',
				code: code ?? undefined,
				signal: signal ?? undefined,
			});
		});
	}

	async send(frame: string): Promise<void> {
		const child = this.child;
		if (!child || !child.stdin.writable) {
			throw new Error('PulseAI sidecar is not running');
		}
		const line = `${checkedFrame(frame)}\n`;
		await new Promise<void>((resolve, reject) => {
			child.stdin.write(line, error => error ? reject(error) : resolve());
		});
	}

	async stop(): Promise<void> {
		const child = this.child;
		if (!child) { return; }
		this.stopping = true;
		if (child.stdin.writable) {
			try { child.stdin.write('{"type":"shutdown"}\n'); } catch { /* force-kill below */ }
		}
		await Promise.race([
			new Promise<void>(resolve => child.once('exit', () => resolve())),
			new Promise<void>(resolve => setTimeout(resolve, STOP_GRACE_MS)),
		]);
		if (this.child === child) {
			child.kill();
		}
	}

	override dispose(): void {
		void this.stop();
		super.dispose();
	}
}
