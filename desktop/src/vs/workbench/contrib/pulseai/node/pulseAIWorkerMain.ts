/*---------------------------------------------------------------------------------------------
 * Utility-process entrypoint registered through Code OSS's existing worker framework.
 *--------------------------------------------------------------------------------------------*/

import { DisposableStore } from '../../../../base/common/lifecycle.js';
import { ProxyChannel } from '../../../../base/parts/ipc/common/ipc.js';
import { Server as ChildProcessServer } from '../../../../base/parts/ipc/node/ipc.cp.js';
import { Server as UtilityProcessServer } from '../../../../base/parts/ipc/node/ipc.mp.js';
import { isUtilityProcess } from '../../../../base/parts/sandbox/node/electronTypes.js';
import { PULSE_AI_WORKER_CHANNEL } from '../common/pulseAIWorkerService.js';
import { PulseAIWorkerProcessService } from './pulseAIWorkerProcessService.js';

let server: ChildProcessServer<string> | UtilityProcessServer;
if (isUtilityProcess(process)) {
	server = new UtilityProcessServer();
} else {
	server = new ChildProcessServer('pulseAIWorker');
}

server.registerChannel(
	PULSE_AI_WORKER_CHANNEL,
	ProxyChannel.fromService(new PulseAIWorkerProcessService(), new DisposableStore()),
);
