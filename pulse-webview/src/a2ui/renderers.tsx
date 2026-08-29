import type { CatalogRenderers } from "@copilotkit/a2ui-renderer";
import type { definitions } from "./definitions";

type Definitions = typeof definitions;

function s(value: unknown): string {
  return typeof value === "string" ? value : String(value ?? "");
}

export const renderers: CatalogRenderers<Definitions> = {
  Card: ({ props, children }) => (
    <div className="w-full max-w-md p-5 rounded-xl border border-neutral-200 shadow-sm bg-white" data-testid="pulse-task-card">
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
      data-testid="pulse-task-action"
      onClick={typeof props.action === "function" ? props.action : undefined}
    >
      {props.child ? children(props.child) : null}
    </button>
  ),
};
