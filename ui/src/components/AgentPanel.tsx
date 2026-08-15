import { For, Show, type Component } from "solid-js";
import type { DemoRun } from "../runtime/demo";
import { DropdownMenu } from "./DropdownMenu";
import { Icon } from "./Icon";
import { PermissionDock } from "./PermissionDock";
import { StatusDot } from "./StatusDot";
import { ToolRow } from "./ToolRow";
import { UsageReceipt } from "./UsageReceipt";

interface AgentPanelProps {
  demo: DemoRun;
  embedded?: boolean;
}

const modeItems = [
  { label: "Agent — execute and verify", icon: "agent" as const },
  { label: "Plan — propose before acting", icon: "file" as const },
  { label: "Ask — explain only", icon: "search" as const },
];

const modelItems = [
  { label: "Auto — best available", icon: "sparkles" as const },
  { label: "Fast", icon: "pulse" as const },
  { label: "Deep", icon: "agent" as const },
];

const approvalItems = [
  { label: "Ask before edits", icon: "shield" as const },
  { label: "Approve workspace edits", icon: "check" as const },
  { label: "Read only", icon: "lock" as const },
];

export const AgentPanel: Component<AgentPanelProps> = (props) => {
  const busy = () => ["streaming", "verifying"].includes(props.demo.stage());
  const complete = () => props.demo.stage() === "verified";

  return (
    <section class="agent-panel" classList={{ "agent-panel-embedded": props.embedded }}>
      <header class="agent-header">
        <div class="agent-title-row">
          <div>
            <div class="eyebrow">CURRENT SESSION</div>
            <h2>Fix authentication redirect</h2>
            <div class="session-subline"><DropdownMenu label="Agent" items={modeItems} compact /><span>·</span><span>2 of 3 steps</span></div>
          </div>
          <div class="agent-header-actions">
            <StatusDot
              state={complete() ? "completed" : props.demo.stage() === "denied" ? "attention" : "running"}
              label={complete() ? "Verified" : props.demo.stage() === "denied" ? "Stopped" : busy() ? "Working" : "Waiting"}
              pulse={busy()}
            />
            <button class="icon-button" type="button" aria-label="More options"><Icon name="more" /></button>
          </div>
        </div>
        <UsageReceipt context={38_420} input={props.demo.inputTokens()} cache={props.demo.cacheTokens()} output={1_928} calls={6} cost="$0.031" compact />
      </header>

      <div class="agent-scroll">
        <div class="transcript-heading"><span>TRANSCRIPT</span><time>10:42</time></div>

        <article class="transcript-turn user-turn">
          <div class="turn-rail" />
          <div class="turn-content">
            <div class="turn-author">You</div>
            <p>Fix the redirect loop after login. Keep the original destination and verify it in the browser.</p>
          </div>
        </article>

        <article class="transcript-turn pulse-turn">
          <div class="turn-rail" />
          <div class="turn-content">
            <div class="assistant-label"><Icon name="pulse" size={13} />Pulse</div>
            <p>
              {props.demo.streamed()}
              <Show when={props.demo.stage() === "streaming"}><span class="stream-caret" /></Show>
            </p>
          </div>
        </article>

        <section class="action-ledger">
          <div class="section-label-row"><span class="section-label">ACTIONS</span><span class="section-count">{props.demo.tools().length}</span></div>
          <For each={props.demo.tools()}>{(tool) => <ToolRow tool={tool} />}</For>
        </section>

        <section class="plan-ledger">
          <div class="section-label-row"><span class="section-label">PLAN</span><span class="section-count">2 / 3</span></div>
          <ol class="plan-list">
            <li class="plan-done"><Icon name="check" size={13} /><span>Trace callback and cookie lifecycle</span></li>
            <li classList={{ "plan-done": complete(), "plan-active": !complete() }}>
              <Show when={complete()} fallback={<span class="plan-active-dot" />}><Icon name="check" size={13} /></Show>
              <span>Repair stale-session redirect handling</span>
            </li>
            <li classList={{ "plan-done": complete(), "plan-queued": !complete() }}>
              <Show when={complete()} fallback={<span class="plan-dot" />}><Icon name="check" size={13} /></Show>
              <span>Verify callback flow in the browser</span>
            </li>
          </ol>
        </section>

        <Show when={complete()}>
          <section class="verification-row">
            <Icon name="shield" size={15} />
            <div><strong>Change verified</strong><span>Typecheck passed · callback rendered · destination preserved</span></div>
            <time>1.4s</time>
          </section>
        </Show>

        <Show when={props.demo.stage() === "denied"}>
          <section class="denied-row">
            <Icon name="warning" size={15} />
            <div><strong>Edit denied</strong><span>No files were changed.</span></div>
          </section>
        </Show>
      </div>

      <Show when={props.demo.stage() === "approval"}>
        <PermissionDock onApprove={props.demo.approve} onDeny={props.demo.deny} />
      </Show>

      <footer class="composer-wrap">
        <div class="composer">
          <div class="composer-input">Steer Pulse or add context…</div>
          <div class="composer-toolbar">
            <div class="composer-left">
              <button type="button" class="composer-pill"><span class="at-sign">@</span> Context</button>
              <DropdownMenu label="Auto model" items={modelItems} compact align="left" />
              <DropdownMenu label="Ask" items={approvalItems} icon="shield" compact align="left" />
            </div>
            <button class={`send-button ${busy() ? "send-stop" : ""}`} type="button" aria-label={busy() ? "Stop" : "Send"}>
              <Icon name={busy() ? "pause" : "send"} size={15} />
            </button>
          </div>
        </div>
        <div class="composer-hint"><span>Enter to send</span><span>Shift+Enter for new line</span></div>
      </footer>
    </section>
  );
};
