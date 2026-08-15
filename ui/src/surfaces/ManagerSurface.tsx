import { For, Show, type Component } from "solid-js";
import type { DemoRun } from "../runtime/demo";
import type { SessionSummary } from "../types";
import { NativeMenuBar } from "../components/DropdownMenu";
import { Icon } from "../components/Icon";
import { StatusDot } from "../components/StatusDot";
import { ToolRow } from "../components/ToolRow";
import { UsageReceipt } from "../components/UsageReceipt";

interface ManagerSurfaceProps {
  demo: DemoRun;
}

const sessions: SessionSummary[] = [
  {
    id: "auth",
    title: "Fix authentication redirect",
    branch: "fix/session-redirect",
    state: "running",
    elapsed: "3m 14s",
    additions: 12,
    deletions: 4,
    children: [
      { id: "research", title: "Trace callback flow", branch: "sub-agent", state: "completed", elapsed: "48s", additions: 0, deletions: 0 },
      { id: "verify", title: "Browser verification", branch: "sub-agent", state: "running", elapsed: "1m 02s", additions: 0, deletions: 0 },
    ],
  },
  { id: "retrieval", title: "Refactor retrieval ranking", branch: "refactor/context-rank", state: "queued", elapsed: "Queued", additions: 0, deletions: 0 },
  { id: "readme", title: "Update provider documentation", branch: "docs/providers", state: "completed", elapsed: "18m ago", additions: 42, deletions: 8 },
];

const SessionRow: Component<{ session: SessionSummary; child?: boolean; active?: boolean }> = (props) => (
  <button class="manager-session-row" classList={{ child: props.child, active: props.active }} type="button">
    <StatusDot state={props.session.state} pulse={props.session.state === "running"} />
    <div class="manager-session-copy">
      <strong>{props.session.title}</strong>
      <span>{props.session.branch}</span>
    </div>
    <span class="manager-session-time">{props.session.elapsed}</span>
  </button>
);

export const ManagerSurface: Component<ManagerSurfaceProps> = (props) => (
  <div class="manager-shell">
    <NativeMenuBar title="Pulse Manager — PulseAI IDE" />
    <aside class="manager-sidebar">
      <div class="manager-sidebar-head">
        <div><span class="eyebrow">CONTROL PLANE</span><h2>Workspaces</h2></div>
        <button class="icon-button" type="button" aria-label="Add workspace"><Icon name="plus" /></button>
      </div>
      <div class="manager-search"><Icon name="search" size={14} /><span>Find workspace or agent</span><kbd>⌘ K</kbd></div>

      <section class="workspace-group">
        <div class="workspace-group-head"><Icon name="chevron" size={12} /><Icon name="folder" size={15} /><strong>PulseAIRepo</strong><span>3</span></div>
        <button class="workspace-row active" type="button">
          <Icon name="code" size={14} /><div><strong>main</strong><span>Local workspace</span></div>
          <span class="diff-add">+12</span><span class="diff-del">−4</span>
        </button>
        <div class="sidebar-section-label">ACTIVE AGENTS</div>
        <For each={sessions.slice(0, 2)}>{(session, index) => (
          <>
            <SessionRow session={session} active={index() === 0} />
            <Show when={index() === 0}>
              <For each={session.children}>{(child) => <SessionRow session={child} child />}</For>
            </Show>
          </>
        )}</For>
      </section>

      <section class="workspace-group collapsed-workspace">
        <div class="workspace-group-head"><Icon name="chevron" size={12} /><Icon name="folder" size={15} /><strong>marketing-site</strong><span>2</span></div>
        <div class="collapsed-meta"><StatusDot state="queued" /><span>1 queued</span><span>·</span><span>1 completed</span></div>
      </section>

      <div class="sidebar-footer">
        <button type="button"><Icon name="settings" size={15} />Manager settings</button>
        <span>3 agents · 2 workspaces</span>
      </div>
    </aside>

    <main class="manager-main">
      <header class="manager-titlebar">
        <div class="manager-title-copy">
          <div class="manager-breadcrumb"><span>PulseAIRepo</span><span>/</span><span>fix/session-redirect</span></div>
          <div class="manager-heading"><h1>Fix authentication redirect</h1><StatusDot state="running" label="Working" pulse /></div>
        </div>
        <div class="manager-actions">
          <button class="button button-ghost" type="button"><Icon name="pause" size={14} />Pause</button>
          <button class="button button-secondary" type="button"><Icon name="diff" size={14} />Review changes</button>
          <button class="icon-button" type="button"><Icon name="more" /></button>
        </div>
      </header>

      <nav class="manager-tabs" aria-label="Session tabs">
        <button class="active" type="button"><Icon name="agent" size={14} />Session</button>
        <button type="button"><Icon name="terminal" size={14} />Terminal <span class="tab-count">1</span></button>
        <button type="button"><Icon name="diff" size={14} />Changes <span class="tab-count">2</span></button>
      </nav>

      <div class="manager-conversation-scroll">
        <div class="manager-reading-lane">
          <div class="manager-user-message">Fix the redirect loop after login. Keep the intended destination and verify the complete callback flow.</div>
          <div class="manager-assistant-copy">
            <div class="assistant-label"><span class="pulse-mini"><Icon name="pulse" size={13} /></span>Pulse</div>
            <p>{props.demo.streamed()}</p>
          </div>
          <div class="manager-tools">
            <For each={props.demo.tools()}>{(tool) => <ToolRow tool={tool} />}</For>
          </div>
          <div class="manager-subagents">
            <div class="section-label-row"><span class="section-label">SUB-AGENTS</span><span class="section-count">2</span></div>
            <div class="subagent-row"><StatusDot state="completed" /><Icon name="agent" size={15} /><div><strong>Trace callback flow</strong><span>Research · 48s</span></div><span class="subagent-result"><Icon name="check" size={13} />Complete</span></div>
            <div class="subagent-row"><StatusDot state="running" pulse /><Icon name="agent" size={15} /><div><strong>Browser verification</strong><span>Test · 1m 02s</span></div><span class="subagent-result running">Checking route</span></div>
          </div>
        </div>
      </div>

      <footer class="manager-composer">
        <div class="manager-composer-box"><span>Steer this agent or add context…</span><div><button type="button" class="composer-pill"><span class="at-sign">@</span> Context</button><button type="button" class="send-button"><Icon name="send" size={14} /></button></div></div>
        <span class="composer-hint">This message steers the active run without starting a new session.</span>
      </footer>
    </main>

    <aside class="manager-inspector">
      <header class="inspector-head"><div><span class="eyebrow">LIVE EVIDENCE</span><h2>Run inspector</h2></div><button class="icon-button" type="button"><Icon name="panel" /></button></header>

      <section class="inspector-section">
        <div class="inspector-section-title"><span>Plan</span><strong>2 / 3</strong></div>
        <ol class="inspector-plan">
          <li class="done"><Icon name="check" size={13} /><span>Trace callback and cookie lifecycle</span></li>
          <li class="active"><span class="mini-spinner" /><span>Repair stale-session handling</span></li>
          <li><span class="plan-dot" /><span>Prove browser callback flow</span></li>
        </ol>
      </section>

      <section class="inspector-section">
        <div class="inspector-section-title"><span>Changed files</span><strong>2</strong></div>
        <button class="changed-file" type="button"><Icon name="file" size={14} /><div><strong>session.ts</strong><span>src/auth</span></div><span class="diff-add">+12</span><span class="diff-del">−4</span></button>
        <button class="changed-file" type="button"><Icon name="file" size={14} /><div><strong>callback.test.ts</strong><span>src/auth</span></div><span class="diff-add">+18</span><span class="diff-del">−0</span></button>
      </section>

      <section class="inspector-section">
        <div class="inspector-section-title"><span>Verification</span><StatusDot state="running" label="Running" pulse /></div>
        <div class="evidence-row"><Icon name="check" size={14} /><span>Typecheck</span><strong>Passed</strong></div>
        <div class="evidence-row"><span class="spinner" /><span>Browser callback</span><strong>Running</strong></div>
        <div class="evidence-row muted"><Icon name="circle" size={13} /><span>Destination assertion</span><strong>Queued</strong></div>
      </section>

      <section class="inspector-section checkpoints-section">
        <div class="inspector-section-title"><span>Checkpoints</span><button type="button">View all</button></div>
        <button class="checkpoint-row" type="button"><Icon name="restore" size={14} /><div><strong>Before session edit</strong><span>10:42 · 2 files</span></div></button>
        <button class="checkpoint-row" type="button"><Icon name="clock" size={14} /><div><strong>Initial workspace</strong><span>10:38 · clean</span></div></button>
      </section>

      <div class="inspector-usage">
        <UsageReceipt context={38_420} input={props.demo.inputTokens()} cache={props.demo.cacheTokens()} output={1_928} calls={6} cost="$0.031" />
      </div>
    </aside>
  </div>
);
