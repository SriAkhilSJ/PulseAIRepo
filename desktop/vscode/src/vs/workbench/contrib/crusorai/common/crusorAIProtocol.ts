/*---------------------------------------------------------------------------------------------
 * CrusorAI Bridge Protocol v2 — workbench payload contract.
 * Frame-name/version constants are generated from src/bridge/protocol_v2.json.
 *--------------------------------------------------------------------------------------------*/

import { CRUSOR_AI_PROTOCOL_VERSION } from './crusorAIProtocol.generated.js';

export { CRUSOR_AI_PROTOCOL_VERSION } from './crusorAIProtocol.generated.js';
export type { CrusorExecutionMode } from './crusorAIProtocol.generated.js';

import type { CrusorExecutionMode } from './crusorAIProtocol.generated.js';

export interface CrusorIdentity {
	readonly workspace_id?: string;
	readonly session_id: string;
	readonly runtime_session_id?: string;
	readonly turn_id?: string;
	readonly event_id?: string;
	readonly tool_id?: string;
	readonly lineage_id?: string;
	readonly timestamp?: string;
}

/** Durable session row (Hermes SessionInfo parity — see src/runtime/session_store.py). */
export interface CrusorSessionRow {
	readonly id: string;
	readonly session_id?: string;
	readonly title?: string;
	readonly workspace?: string;
	readonly source?: string;
	readonly model?: string;
	readonly created_at?: number;
	readonly last_active?: number;
	readonly message_count?: number;
	readonly preview?: string;
	readonly pinned?: boolean;
	readonly archived?: boolean;
	readonly hidden?: boolean;
	readonly unread?: boolean;
	readonly parent_session_id?: string | null;
	readonly lineage_root_id?: string | null;
	/** Rowless lazy draft: exists only in the engine's live registry so far. */
	readonly lazy?: boolean;
}

/** One paged transcript message (Hermes SessionMessage parity). */
export interface CrusorSessionMessage {
	readonly id?: number | string;
	readonly role: 'user' | 'assistant' | 'tool';
	readonly content: string;
	/** Persisted thinking (Hermes reasoning parts): renders the Think card on history turns. */
	readonly reasoning?: string;
	readonly tool_calls?: readonly { readonly id?: string; readonly name: string; readonly args?: unknown }[];
	readonly tool_call_id?: string;
	readonly tool_name?: string;
}

export interface CrusorSessionInfo {
	readonly session_id: string;
	readonly workspace?: string;
	readonly resumed?: boolean;
	readonly forked_from?: string;
	readonly queued?: number;
	readonly cancel_requested?: boolean;
	readonly steer_accepted?: boolean;
	readonly safety_resolved?: boolean;
	readonly clarify_resolved?: boolean;
	readonly host_capabilities_updated?: number;
	readonly host_tool_result_resolved?: boolean;
	readonly events?: readonly unknown[];
	readonly agent_status?: Readonly<Record<string, unknown>>;
	/** Durable row for this session (create/resume), when one exists. */
	readonly session?: CrusorSessionRow;
	/** Hermes session.create identity: the durable key + lazy-draft flag. */
	readonly stored_session_id?: string;
	readonly lazy?: boolean;
	readonly info?: { readonly model?: string; readonly cwd?: string; readonly source?: string; readonly lazy?: boolean };
	/** Durable listing (session_list): rich rows, newest activity first. */
	readonly sessions?: readonly CrusorSessionRow[];
	readonly limit?: number;
	readonly offset?: number;
	readonly has_more?: boolean;
	/** Lineage tip the resume actually bound (fork children resolve here). */
	readonly resolved_session_id?: string;
	/** Rename / pin / archive acks. */
	readonly title?: string;
	readonly renamed?: boolean;
	readonly pinned?: boolean;
	readonly pin_updated?: boolean;
	readonly archive_updated?: boolean;
	/** Checkpointer history silently resumed by this id (never claimed fresh). */
	readonly prior_checkpoints?: number;
	/** Engine build ("<sha> <date>") — a stale engine is visible in the panel. */
	readonly build?: string;
}

/** Hermes todo_list item shape ({id, content, status, parent?} — parent nests a subtask). */
export interface CrusorTodoItem {
	readonly id: string;
	readonly content: string;
	readonly status: 'pending' | 'in_progress' | 'completed' | 'cancelled';
	readonly parent?: string;
}

/** One normalized clarify question (hermes clarify_tool._normalize_questions). */
export interface CrusorClarifyQuestion {
	readonly qid: string;
	readonly id?: string | null;
	readonly question: string;
	readonly choices?: readonly string[] | null;
	readonly choices_offered?: readonly string[] | null;
	readonly multi_select?: boolean;
}

/**
 * A2UI v0.9 surface envelope (docs/DESIGN/AGUI_A2UI_PLAN.md §4). It rides
 * INSIDE tool_call_end.result as {"a2ui_operations": [...]} — the shape
 * display_crusor_task already returns — so there is no protocol version
 * bump and no new frame type. The renderer validates operations against
 * the fixed Catalog v1 before paint; unknown ops/components are dropped.
 */
export interface CrusorA2UIComponent {
	readonly id: string;
	readonly component: string;
	readonly [key: string]: unknown;
}

export type CrusorA2UIOperation =
	| { readonly version?: string; readonly createSurface: { readonly surfaceId: string; readonly catalogId?: string } }
	| { readonly version?: string; readonly updateComponents: { readonly surfaceId: string; readonly components: readonly CrusorA2UIComponent[] } }
	| { readonly version?: string; readonly updateDataModel: { readonly surfaceId: string; readonly path?: string; readonly value: unknown } }
	| { readonly version?: string; readonly deleteSurface: { readonly surfaceId: string } };

export type CrusorServerEvent =
	| { readonly type: 'hello'; readonly protocol: typeof CRUSOR_AI_PROTOCOL_VERSION; readonly engine: 'crusorai'; readonly engine_version: string; readonly capabilities: readonly string[] }
	| ({ readonly type: 'session_info' } & CrusorSessionInfo)
	| ({ readonly type: 'session_messages'; readonly requested_session_id?: string; readonly messages: readonly CrusorSessionMessage[]; readonly pagination: { readonly limit: number; readonly offset: number; readonly order: 'latest' | 'oldest'; readonly returned: number; readonly total: number; readonly has_more: boolean } } & CrusorIdentity)
	| ({ readonly type: 'session_deleted'; readonly deleted: boolean } & CrusorIdentity)
	| ({ readonly type: 'turn_started' } & CrusorIdentity)
	| ({ readonly type: 'token'; readonly text: string } & CrusorIdentity)
	| ({ readonly type: 'reasoning'; readonly text: string } & CrusorIdentity)
	| ({ readonly type: 'plan_updated'; readonly steps: readonly unknown[] } & CrusorIdentity)
	| ({ readonly type: 'tool_call_start'; readonly tool_id: string; readonly name: string; readonly arguments?: unknown } & CrusorIdentity)
	| ({ readonly type: 'tool_call_end'; readonly tool_id: string; readonly status: string; readonly result?: unknown } & CrusorIdentity)
	| ({ readonly type: 'tool_output'; readonly tool_id: string; readonly name: string; readonly text: string } & CrusorIdentity)
	| ({ readonly type: 'safety_request'; readonly tool_id: string; readonly name: string; readonly arguments?: unknown; readonly diff?: unknown; readonly warning?: string } & CrusorIdentity)
	| ({ readonly type: 'clarify_request'; readonly tool_id?: string; readonly request_id: string; readonly title?: string; readonly questions: readonly CrusorClarifyQuestion[] } & CrusorIdentity)
	| ({ readonly type: 'todo_updated'; readonly todos: readonly CrusorTodoItem[]; readonly revision: number; readonly summary?: Readonly<Record<string, number>> } & CrusorIdentity)
	| ({ readonly type: 'verification_updated'; readonly status: string; readonly evidence?: unknown } & CrusorIdentity)
	| ({ readonly type: 'subagent_updated'; readonly subagent_id: string; readonly state: string } & CrusorIdentity)
	| ({ readonly type: 'subagent_list'; readonly subagents: readonly unknown[]; readonly error?: string } & CrusorIdentity)
	| ({ readonly type: 'skills_hub_result'; readonly op: string; readonly result: Record<string, unknown>; readonly error?: string } & CrusorIdentity)
	| ({ readonly type: 'oneshot_result'; readonly template: string; readonly text: string; readonly error?: string } & CrusorIdentity)
	| ({ readonly type: 'subagent_background_completed'; readonly subagent_id?: string; readonly child_thread_id?: string; readonly text: string; readonly description?: string } & CrusorIdentity)
	| ({ readonly type: 'telemetry'; readonly input?: number; readonly output?: number; readonly cache?: number; readonly cost?: number } & CrusorIdentity)
	| ({ readonly type: 'checkpoint_event'; readonly checkpoint_hash?: string; readonly checkpoints?: readonly unknown[]; readonly restore?: unknown } & CrusorIdentity)
	| ({ readonly type: 'turn_done'; readonly message?: string; readonly completed: boolean; readonly cancelled: boolean } & CrusorIdentity)
	| ({ readonly type: 'turn_failed'; readonly error: string; readonly completed: false } & CrusorIdentity)
	| ({ readonly type: 'runtime_degraded'; readonly reason: string } & CrusorIdentity)
		| ({ readonly type: 'voice_text'; readonly ok: boolean; readonly text?: string; readonly error?: string } & CrusorIdentity)
| ({ readonly type: 'context_status'; readonly phase: string; readonly message: string; readonly severity?: string; readonly usage_percent?: number; readonly last_prompt_tokens?: number; readonly threshold_tokens?: number; readonly context_length?: number } & CrusorIdentity)
	| { readonly type: 'events_replay'; readonly session_id: string; readonly events: readonly unknown[] }
	| ({ readonly type: 'workspace.bound'; readonly session_id: string; readonly workspace: string; readonly hops: string; readonly engine_root: string } & CrusorIdentity)
	| ({ readonly type: 'llm.request'; readonly model?: string; readonly attempt?: number; readonly message_count?: number; readonly messages?: readonly { readonly role: string; readonly head: string }[] } & CrusorIdentity)
	| ({ readonly type: 'llm.response'; readonly model?: string; readonly attempt?: number; readonly raw_finish_reason?: string; readonly finish_reason?: string; readonly incomplete?: boolean; readonly tool_call_count?: number; readonly tool_names?: readonly string[]; readonly content_chars?: number; readonly reasoning_chars?: number; readonly input_tokens?: number | null; readonly output_tokens?: number | null; readonly total_tokens?: number | null } & CrusorIdentity)
	| { readonly type: 'host_tool_request'; readonly request_id: string; readonly session_id: string; readonly workspace: string; readonly capability_id: string; readonly arguments: Readonly<Record<string, unknown>>; readonly deadline_ms: number }
	| { readonly type: 'inline_completion_result'; readonly session_id: string; readonly request_id: string; readonly completions: readonly { readonly text: string; readonly range_start_line: number; readonly range_start_column: number; readonly range_end_line: number; readonly range_end_column: number; readonly confidence: number }[]; readonly error?: string }
	| { readonly type: 'next_edit_result'; readonly session_id: string; readonly request_id: string; readonly suggestions: readonly { readonly resource: string; readonly line: number; readonly column: number; readonly end_line: number; readonly end_column: number; readonly title: string; readonly description: string; readonly confidence: number; readonly category: string }[]; readonly error?: string }
	| { readonly type: 'error'; readonly message: string; readonly fatal?: boolean; readonly request_id?: string };

interface CrusorSessionRequest {
	readonly session_id?: string;
	readonly thread_id?: string;
	readonly workspace?: string;
}

export type CrusorClientMethod =
	| { readonly type: 'hello'; readonly protocol: typeof CRUSOR_AI_PROTOCOL_VERSION }
	| ({ readonly type: 'session_create' } & CrusorSessionRequest)
	| ({ readonly type: 'session_load'; readonly include_events?: boolean } & CrusorSessionRequest)
	| ({ readonly type: 'session_resume'; readonly include_events?: boolean } & CrusorSessionRequest)
	| ({ readonly type: 'session_list'; readonly limit?: number; readonly offset?: number; readonly order?: 'recent' | 'created'; readonly archived?: 'exclude' | 'include' | 'only'; readonly query?: string; readonly min_messages?: number } & CrusorSessionRequest)
	| ({ readonly type: 'session_fork' } & CrusorSessionRequest)
	| ({ readonly type: 'session_rename'; readonly title: string } & CrusorSessionRequest)
	| ({ readonly type: 'session_pin'; readonly pinned?: boolean; readonly enabled?: boolean } & CrusorSessionRequest)
	| ({ readonly type: 'session_archive'; readonly archived?: boolean; readonly enabled?: boolean } & CrusorSessionRequest)
	| ({ readonly type: 'session_delete' } & CrusorSessionRequest)
	| ({ readonly type: 'session_messages'; readonly limit?: number; readonly offset?: number; readonly order?: 'latest' | 'oldest' } & CrusorSessionRequest)
	| ({ readonly type: 'prompt'; readonly text: string; readonly mode?: CrusorExecutionMode; readonly reasoning_effort?: string } & CrusorSessionRequest)
	| ({ readonly type: 'voice_transcribe'; readonly audio_b64: string; readonly filename?: string } & CrusorSessionRequest)
	| ({ readonly type: 'cancel' } & CrusorSessionRequest)
	| ({ readonly type: 'steer'; readonly text: string } & CrusorSessionRequest)
	| ({ readonly type: 'queue'; readonly text: string } & CrusorSessionRequest)
	| ({ readonly type: 'safety_reply'; readonly tool_id: string; readonly approved: boolean; readonly always_allow?: boolean } & CrusorSessionRequest)
	| ({ readonly type: 'clarify_reply'; readonly request_id: string; readonly answers: Readonly<Record<string, string | readonly string[]>>; readonly timed_out?: boolean } & CrusorSessionRequest)
	| ({ readonly type: 'checkpoint_list'; readonly workspace: string } & CrusorSessionRequest)
	| ({ readonly type: 'checkpoint_restore'; readonly workspace: string; readonly checkpoint_hash: string; readonly file_path?: string } & CrusorSessionRequest)
	| ({ readonly type: 'subagent_launch'; readonly goal: string; readonly mode?: string; readonly parent_capabilities?: readonly string[]; readonly allowed_capabilities?: readonly string[] } & CrusorSessionRequest)
	| ({ readonly type: 'subagent_list' } & CrusorSessionRequest)
	| ({ readonly type: 'subagent_status'; readonly subagent_id: string } & CrusorSessionRequest)
	| ({ readonly type: 'skills_hub_op'; readonly op: string; readonly source?: string; readonly name?: string; readonly query?: string; readonly category?: string; readonly pick?: string } & CrusorSessionRequest)
	| ({ readonly type: 'oneshot'; readonly template: string; readonly instructions?: string; readonly variables?: Record<string, string>; readonly input?: string } & CrusorSessionRequest)
	| ({ readonly type: 'subagent_cancel'; readonly subagent_id: string } & CrusorSessionRequest)
	| ({ readonly type: 'subagent_result'; readonly subagent_id: string } & CrusorSessionRequest)
	| ({ readonly type: 'events_replay'; readonly after_seq?: number } & CrusorSessionRequest)
	| ({ readonly type: 'host_capabilities_update'; readonly workspace: string; readonly capabilities: readonly Readonly<Record<string, unknown>>[] } & CrusorSessionRequest)
	| ({ readonly type: 'host_tool_result'; readonly workspace: string; readonly request_id: string; readonly status: 'ok' | 'error'; readonly result?: unknown; readonly error?: string; readonly duration_ms: number } & CrusorSessionRequest)
	| ({ readonly type: 'inline_completion'; readonly request_id: string; readonly resource: string; readonly language_id: string; readonly line: number; readonly column: number; readonly prefix: string; readonly suffix: string; readonly context_lines?: number; readonly max_tokens?: number } & CrusorSessionRequest)
	| ({ readonly type: 'next_edit_suggestions'; readonly request_id: string; readonly resource: string; readonly workspace: string; readonly max_suggestions?: number } & CrusorSessionRequest)
	| { readonly type: 'shutdown' };
