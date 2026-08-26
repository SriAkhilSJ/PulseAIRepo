/*---------------------------------------------------------------------------------------------
 * PulseAI Bridge Protocol v2 — workbench payload contract.
 * Frame-name/version constants are generated from src/bridge/protocol_v2.json.
 *--------------------------------------------------------------------------------------------*/

import { PULSE_AI_PROTOCOL_VERSION } from './pulseAIProtocol.generated.js';

export { PULSE_AI_PROTOCOL_VERSION } from './pulseAIProtocol.generated.js';

export interface PulseIdentity {
	readonly workspace_id?: string;
	readonly session_id: string;
	readonly runtime_session_id?: string;
	readonly turn_id?: string;
	readonly event_id?: string;
	readonly tool_id?: string;
	readonly lineage_id?: string;
	readonly timestamp?: string;
}

export interface PulseSessionInfo {
	readonly session_id: string;
	readonly workspace?: string;
	readonly resumed?: boolean;
	readonly forked_from?: string;
	readonly queued?: number;
	readonly cancel_requested?: boolean;
	readonly steer_accepted?: boolean;
	readonly safety_resolved?: boolean;
	readonly host_capabilities_updated?: number;
	readonly host_tool_result_resolved?: boolean;
	readonly events?: readonly unknown[];
	readonly agent_status?: Readonly<Record<string, unknown>>;
}

export type PulseServerEvent =
	| { readonly type: 'hello'; readonly protocol: typeof PULSE_AI_PROTOCOL_VERSION; readonly engine: 'pulseai'; readonly engine_version: string; readonly capabilities: readonly string[] }
	| ({ readonly type: 'session_info' } & PulseSessionInfo)
	| ({ readonly type: 'turn_started' } & PulseIdentity)
	| ({ readonly type: 'token'; readonly text: string } & PulseIdentity)
	| ({ readonly type: 'reasoning'; readonly text: string } & PulseIdentity)
	| ({ readonly type: 'plan_updated'; readonly steps: readonly unknown[] } & PulseIdentity)
	| ({ readonly type: 'tool_call_start'; readonly tool_id: string; readonly name: string; readonly arguments?: unknown } & PulseIdentity)
	| ({ readonly type: 'tool_call_end'; readonly tool_id: string; readonly status: string; readonly result?: unknown } & PulseIdentity)
	| ({ readonly type: 'safety_request'; readonly tool_id: string; readonly name: string; readonly arguments?: unknown; readonly diff?: unknown; readonly warning?: string } & PulseIdentity)
	| ({ readonly type: 'verification_updated'; readonly status: string; readonly evidence?: unknown } & PulseIdentity)
	| ({ readonly type: 'subagent_updated'; readonly subagent_id: string; readonly state: string } & PulseIdentity)
	| ({ readonly type: 'telemetry'; readonly input?: number; readonly output?: number; readonly cache?: number; readonly cost?: number } & PulseIdentity)
	| ({ readonly type: 'checkpoint_event'; readonly checkpoint_hash?: string; readonly checkpoints?: readonly unknown[]; readonly restore?: unknown } & PulseIdentity)
	| ({ readonly type: 'turn_done'; readonly message?: string; readonly completed: boolean } & PulseIdentity)
	| ({ readonly type: 'turn_failed'; readonly error: string; readonly completed: false } & PulseIdentity)
	| ({ readonly type: 'runtime_degraded'; readonly reason: string } & PulseIdentity)
	| { readonly type: 'events_replay'; readonly session_id: string; readonly events: readonly unknown[] }
	| ({ readonly type: 'workspace.bound'; readonly session_id: string; readonly workspace: string; readonly hops: string; readonly engine_root: string } & PulseIdentity)
	| ({ readonly type: 'llm.request'; readonly model?: string; readonly attempt?: number; readonly message_count?: number; readonly messages?: readonly { readonly role: string; readonly head: string }[] } & PulseIdentity)
	| ({ readonly type: 'llm.response'; readonly model?: string; readonly attempt?: number; readonly raw_finish_reason?: string; readonly finish_reason?: string; readonly incomplete?: boolean; readonly tool_call_count?: number; readonly tool_names?: readonly string[]; readonly content_chars?: number; readonly reasoning_chars?: number; readonly input_tokens?: number | null; readonly output_tokens?: number | null; readonly total_tokens?: number | null } & PulseIdentity)
	| { readonly type: 'host_tool_request'; readonly request_id: string; readonly session_id: string; readonly workspace: string; readonly capability_id: string; readonly arguments: Readonly<Record<string, unknown>>; readonly deadline_ms: number }
	| { readonly type: 'error'; readonly message: string; readonly fatal?: boolean; readonly request_id?: string };

interface PulseSessionRequest {
	readonly session_id?: string;
	readonly thread_id?: string;
	readonly workspace?: string;
}

export type PulseClientMethod =
	| { readonly type: 'hello'; readonly protocol: typeof PULSE_AI_PROTOCOL_VERSION }
	| ({ readonly type: 'session_create' } & PulseSessionRequest)
	| ({ readonly type: 'session_load' } & PulseSessionRequest)
	| ({ readonly type: 'session_resume' } & PulseSessionRequest)
	| ({ readonly type: 'session_list' } & PulseSessionRequest)
	| ({ readonly type: 'session_fork' } & PulseSessionRequest)
	| ({ readonly type: 'prompt'; readonly text: string } & PulseSessionRequest)
	| ({ readonly type: 'cancel' } & PulseSessionRequest)
	| ({ readonly type: 'steer'; readonly text: string } & PulseSessionRequest)
	| ({ readonly type: 'queue'; readonly text: string } & PulseSessionRequest)
	| ({ readonly type: 'safety_reply'; readonly tool_id: string; readonly approved: boolean; readonly always_allow?: boolean } & PulseSessionRequest)
	| ({ readonly type: 'checkpoint_list'; readonly workspace: string } & PulseSessionRequest)
	| ({ readonly type: 'checkpoint_restore'; readonly workspace: string; readonly checkpoint_hash: string; readonly file_path?: string } & PulseSessionRequest)
	| ({ readonly type: 'subagent_launch'; readonly goal: string; readonly mode?: string; readonly parent_capabilities?: readonly string[]; readonly allowed_capabilities?: readonly string[] } & PulseSessionRequest)
	| ({ readonly type: 'subagent_status'; readonly subagent_id: string } & PulseSessionRequest)
	| ({ readonly type: 'subagent_cancel'; readonly subagent_id: string } & PulseSessionRequest)
	| ({ readonly type: 'subagent_result'; readonly subagent_id: string } & PulseSessionRequest)
	| ({ readonly type: 'events_replay'; readonly after_seq?: number } & PulseSessionRequest)
	| ({ readonly type: 'host_capabilities_update'; readonly workspace: string; readonly capabilities: readonly Readonly<Record<string, unknown>>[] } & PulseSessionRequest)
	| ({ readonly type: 'host_tool_result'; readonly workspace: string; readonly request_id: string; readonly status: 'ok' | 'error'; readonly result?: unknown; readonly error?: string; readonly duration_ms: number } & PulseSessionRequest)
	| { readonly type: 'shutdown' };
