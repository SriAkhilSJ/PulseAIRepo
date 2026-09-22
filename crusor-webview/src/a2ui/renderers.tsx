import type { CatalogRenderers } from "@copilotkit/a2ui-renderer";
import type { definitions } from "./definitions";

type Definitions = typeof definitions;

function s(value: unknown): string {
  return typeof value === "string" ? value : String(value ?? "");
}

function agentColor(name: string): string {
  const palette = ['#0b6bcb', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return palette[hash % palette.length];
}

export const renderers: CatalogRenderers<Definitions> = {
  Card: ({ props, children }) => (
    <div className="w-full max-w-md p-5 rounded-xl border border-neutral-200 shadow-sm bg-white" data-testid="crusor-task-card">
      {props.child ? children(props.child) : null}
    </div>
  ),
  Title: ({ props }) => (
    <h3 className="text-base font-semibold leading-none tracking-tight text-neutral-900">
      {s(props.text)}
    </h3>
  ),
  StatusBadge: ({ props }) => (
    <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">
      {s(props.status)}
    </span>
  ),
  PriorityTag: ({ props }) => (
    <span className="inline-flex items-center rounded border px-2 py-0.5 text-xs text-neutral-600">
      {s(props.level)}
    </span>
  ),
  AssigneeBadge: ({ props }) => (
    <span className="text-xs text-neutral-500">@{s(props.name)}</span>
  ),
  Button: ({ props, children }) => (
    // The A2UI generic binder converts an `action`-shaped prop into a callable
    // that dispatches the event back to the agent. Wiring it to onClick is what
    // makes the card interactive; without it the button is inert.
    <button
      className="w-full rounded bg-blue-600 px-4 py-2 text-white text-sm"
      data-testid="crusor-task-action"
      onClick={typeof props.action === "function" ? props.action : undefined}
    >
      {props.child ? children(props.child) : null}
    </button>
  ),
  // OpenCode parity: Task tool card for delegate_to_subagent
  TaskToolCard: ({ props }: any) => {
    const description = s(props.description || props.goal || props.prompt || 'Sub-agent task');
    const agentName = s(props.subagent_type || props.agent_name || props.mode || 'general');
    const background = Boolean(props.background);
    const toolCalls = props.toolCalls ?? props.tool_calls;
    const sessionId = s(props.sessionId || props.child_thread_id || '');
    const status = s(props.status || 'running');
    const running = status === 'running' || status === 'pending';
    const color = agentColor(agentName);
    return (
      <div
        data-component="task-tool-card"
        data-testid="task-tool-card"
        style={{ ['--task-agent-color' as any]: color } as any}
        className={`flex items-center gap-2 p-2 rounded-md border border-neutral-200 bg-white ${sessionId ? 'cursor-pointer hover:bg-neutral-50' : ''}`}
        onClick={sessionId ? () => {
          // Navigate to child session if webview has router, else emit event
          try {
            const ev = new CustomEvent('crusorai:navigate-to-session', { detail: { sessionId } });
            window.dispatchEvent(ev);
          } catch {}
        } : undefined}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <span className="inline-flex" style={{ color }}>
            {running ? '◍' : '●'}
          </span>
          <span className="font-medium capitalize" style={{ color }}>{agentName}</span>
          <span className="text-xs text-neutral-500 truncate">
            {description}{background ? ' (background)' : ''}{toolCalls ? ` · ${toolCalls} calls` : ''}
          </span>
        </div>
        {sessionId && <span className="text-xs opacity-60">↗</span>}
      </div>
    );
  },
};
