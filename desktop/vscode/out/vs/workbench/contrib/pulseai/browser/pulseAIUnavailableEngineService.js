/*---------------------------------------------------------------------------------------------
 * Web-safe fallback. Desktop registration replaces this descriptor with the utility-process host.
 *--------------------------------------------------------------------------------------------*/
import { Emitter } from '../../../../base/common/event.js';
import { Disposable } from '../../../../base/common/lifecycle.js';
import { PulseAIEngineState } from '../common/pulseAIEngineService.js';
export class PulseAIUnavailableEngineService extends Disposable {
    constructor() {
        super(...arguments);
        this._state = PulseAIEngineState.Stopped;
        this._onDidChangeState = this._register(new Emitter());
        this.onDidChangeState = this._onDidChangeState.event;
        this._onDidReceiveFrame = this._register(new Emitter());
        this.onDidReceiveFrame = this._onDidReceiveFrame.event;
    }
    get state() { return this._state; }
    async start(_workspace) {
        this._state = PulseAIEngineState.Degraded;
        this._onDidChangeState.fire(this._state);
        throw new Error('The local PulseAI engine is available in the desktop product only');
    }
    send(_frame) {
        throw new Error('The local PulseAI engine is unavailable in this host');
    }
    async stop() {
        this._state = PulseAIEngineState.Stopped;
        this._onDidChangeState.fire(this._state);
    }
}
