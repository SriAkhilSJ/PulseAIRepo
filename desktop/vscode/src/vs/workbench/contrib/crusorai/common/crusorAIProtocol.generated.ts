/*---------------------------------------------------------------------------------------------
 * GENERATED FILE — scripts/generate_bridge_protocol.py
 * Source: src/bridge/protocol_v2.json
 * Do not edit by hand.
 *--------------------------------------------------------------------------------------------*/

export const CRUSOR_AI_PROTOCOL_VERSION = 2 as const;

export const CRUSOR_AI_EXECUTION_MODES = [
	'agent',
	'plan',
	'debug',
	'ask',
] as const;
export type CrusorExecutionMode = (typeof CRUSOR_AI_EXECUTION_MODES)[number];

export const CRUSOR_AI_CLIENT_METHODS = [
	'cancel',
	'checkpoint_list',
	'checkpoint_preview',
	'checkpoint_restore',
	'clarify_reply',
	'events_replay',
	'hello',
	'host_capabilities_update',
	'host_tool_result',
	'inline_completion',
	'next_edit_suggestions',
	'oneshot',
	'prompt',
	'queue',
	'safety_reply',
	'session_archive',
	'session_create',
	'session_delete',
	'session_fork',
	'session_list',
	'session_load',
	'session_messages',
	'session_pin',
	'session_rename',
	'session_resume',
	'session_rewind',
	'shutdown',
	'skills_hub_op',
	'steer',
	'subagent_cancel',
	'subagent_launch',
	'subagent_list',
	'subagent_result',
	'subagent_status',
	'voice_transcribe',
] as const;
export type CrusorClientMethodName = (typeof CRUSOR_AI_CLIENT_METHODS)[number];

export const CRUSOR_AI_SERVER_EVENTS = [
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
	'session_messages',
	'session_deleted',
	'subagent_updated',
	'subagent_list',
	'subagent_background_completed',
	'skills_hub_result',
	'oneshot_result',
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
export type CrusorServerEventName = (typeof CRUSOR_AI_SERVER_EVENTS)[number];

export const CRUSOR_AI_IDENTITY_FIELDS = [
	'workspace_id',
	'session_id',
	'runtime_session_id',
	'turn_id',
	'event_id',
	'tool_id',
	'lineage_id',
] as const;
export type CrusorIdentityField = (typeof CRUSOR_AI_IDENTITY_FIELDS)[number];

export const CRUSOR_AI_APPROVAL_IDENTITY_FIELD = 'tool_id' as const;
