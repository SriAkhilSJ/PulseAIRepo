/*---------------------------------------------------------------------------------------------
 * Utility-process contract. The workbench exchanges JSON strings with a Node worker that owns
 * the Python sidecar; Python/process privileges never enter the renderer.
 *--------------------------------------------------------------------------------------------*/
export const PULSE_AI_WORKER_CHANNEL = 'pulseAIWorker';
export const PULSE_AI_WORKER_MODULE_ID = 'vs/workbench/contrib/pulseai/node/pulseAIWorkerMain';
