import type { Component } from "solid-js";

interface UsageReceiptProps {
  context: number;
  input: number;
  cache: number;
  output: number;
  calls: number;
  cost: string;
  compact?: boolean;
}

const compact = (value: number) =>
  value >= 1000 ? `${(value / 1000).toFixed(value >= 10_000 ? 1 : 2)}k` : String(value);

export const UsageReceipt: Component<UsageReceiptProps> = (props) => (
  <div class="usage-receipt" classList={{ "usage-compact": props.compact }}>
    <div class="usage-primary">
      <span class="usage-label">Context</span>
      <strong>{compact(props.context)}</strong>
      <span class="usage-muted">/ 128k</span>
    </div>
    <span class="usage-separator" />
    <div class="usage-item"><span>In</span><strong>{compact(props.input)}</strong></div>
    <div class="usage-item usage-cache"><span>Cache</span><strong>{compact(props.cache)}</strong></div>
    <div class="usage-item"><span>Out</span><strong>{compact(props.output)}</strong></div>
    <div class="usage-item"><span>Calls</span><strong>{props.calls}</strong></div>
    <div class="usage-item"><span>Cost</span><strong>{props.cost}</strong></div>
  </div>
);
