/*---------------------------------------------------------------------------------------------
 * GENERATED FILE — scripts/generate_bridge_protocol.py
 * Source: src/bridge/protocol_v2.json
 * Do not edit by hand.
 *--------------------------------------------------------------------------------------------*/

export const PULSE_AI_PROTOCOL_VERSION = 2 as const;

export const PULSE_AI_EXECUTION_MODES = [
	'agent',
	'plan',
	'debug',
	'ask',
] as const;
export type PulseExecutionMode = (typeof PULSE_AI_EXECUTION_MODES)[number];

export const PULSE_AI_CLIENT_METHODS = [
	'hello',
	'session_create',
	'session_load',
	'session_resume',
	'session_list',
	'session_fork',
	'prompt',
	'cancel',
	'steer',
	'queue',
	'safety_reply',
	'clarify_reply',
	'checkpoint_list',
	'checkpoint_restore',
	'subagent_launch',
	'subagent_status',
	'subagent_cancel',
	'subagent_result',
	'events_replay',
	'host_capabilities_update',
	'host_tool_result',
	'inline_completion',
	'next_edit_suggestions',
	'shutdown',
	'voice_transcribe',
] as const;
export type PulseClientMethodName = (typeof PULSE_AI_CLIENT_METHODS)[number];

export const PULSE_AI_SERVER_EVENTS = [
	'checkpoint_event',
	'clarify_request',
	'context_status',
	'error',
	'events_replay',
	'hello',
	'host_tool_request',
	'inline_completion_result',
	'llm.request',
	'llm.response',
	'next_edit_result',
	'plan_updated',
	'reasoning',
	'runtime_degraded',
	'safety_request',
	'session_info',
	'subagent_updated',
	'telemetry',
	'todo_updated',
	'token',
	'tool_call_end',
	'tool_call_start',
	'turn_done',
	'turn_failed',
	'turn_started',
	'verification_updated',
	'voice_text',
	'workspace.bound',
] as const;
export type PulseServerEventName = (typeof PULSE_AI_SERVER_EVENTS)[number];

export const PULSE_AI_IDENTITY_FIELDS = [
	'workspace_id',
	'session_id',
	'runtime_session_id',
	'turn_id',
	'event_id',
	'tool_id',
	'lineage_id',
] as const;
export type PulseIdentityField = (typeof PULSE_AI_IDENTITY_FIELDS)[number];

export const PULSE_AI_APPROVAL_IDENTITY_FIELD = 'tool_id' as const;
