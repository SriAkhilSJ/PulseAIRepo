import type { Component } from "solid-js";

interface StatusDotProps {
  state: "running" | "queued" | "completed" | "attention" | "offline";
  label?: string;
  pulse?: boolean;
}

export const StatusDot: Component<StatusDotProps> = (props) => (
  <span class={`status status-${props.state}`} classList={{ "status-pulse": props.pulse }}>
    <span class="status-dot" />
    {props.label && <span>{props.label}</span>}
  </span>
);
