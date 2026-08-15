/*---------------------------------------------------------------------------------------------
 * GENERATED FILE — scripts/generate_bridge_protocol.py
 * Source: src/bridge/protocol_v2.json
 * Do not edit by hand.
 *--------------------------------------------------------------------------------------------*/

export const PULSE_AI_PROTOCOL_VERSION = 2 as const;

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
	'checkpoint_list',
	'checkpoint_restore',
	'subagent_launch',
	'subagent_status',
	'subagent_cancel',
	'subagent_result',
	'events_replay',
	'shutdown',
] as const;
export type PulseClientMethodName = (typeof PULSE_AI_CLIENT_METHODS)[number];

export const PULSE_AI_SERVER_EVENTS = [
	'hello',
	'session_info',
	'token',
	'reasoning',
	'plan_updated',
	'tool_call_start',
	'tool_call_end',
	'safety_request',
	'verification_updated',
	'subagent_updated',
	'telemetry',
	'turn_started',
	'turn_done',
	'turn_failed',
	'checkpoint_event',
	'runtime_degraded',
	'events_replay',
	'error',
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
