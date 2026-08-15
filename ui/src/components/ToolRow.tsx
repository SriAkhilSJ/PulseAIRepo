import { For, Match, Show, Switch, type Component } from "solid-js";
import type { ToolRun } from "../types";
import { toolPresentation } from "../runtime/toolCatalog";
import { Icon } from "./Icon";

const stateLabel: Record<ToolRun["state"], string> = {
  queued: "queued",
  running: "running",
  passed: "passed",
  approval: "review",
  failed: "stopped",
};

interface ToolRowProps {
  tool: ToolRun;
}

const Fields: Component<{ rows: readonly (readonly [string, string])[] }> = (props) => (
  <div class="tool-fields">
    <For each={props.rows}>{(row) => <div><span>{row[0]}</span><code>{row[1]}</code></div>}</For>
  </div>
);

const ExpandedActions: Component<{ labels: readonly string[] }> = (props) => (
  <div class="tool-expanded-actions"><For each={props.labels}>{(label) => <button type="button">{label}</button>}</For></div>
);

const ToolDetails: Component<ToolRowProps> = (props) => {
  const presentation = () => toolPresentation(props.tool.toolName);
  const family = () => presentation().family;

  return (
    <div class="tool-expanded" data-renderer-family={family()}>
      <Switch fallback={
        <>
          <pre class="tool-output">{props.tool.detail}</pre>
          <ExpandedActions labels={["Copy result"]} />
        </>
      }>
        <Match when={family() === "terminal"}>
          <div class="terminal-meta"><span>Terminal</span><strong>PulseAI IDE</strong><span>Exit code</span><strong class="terminal-exit">1</strong></div>
          <pre class="tool-output terminal-output"><code><span class="terminal-command">$ {props.tool.target}</span>{"\n\n"} RUN  auth callback suite{"\n"}<span class="terminal-pass"> ✓ 17 tests passed</span>{"\n"}<span class="terminal-fail"> ✗ preserves destination after stale cookie</span>{"\n\n"}AssertionError: expected /dashboard, received /login</code></pre>
          <ExpandedActions labels={["Copy output", "Open terminal"]} />
        </Match>

        <Match when={family() === "process"}>
          <Fields rows={[["Process id", "pulse-4821"], ["PID", "4821"], ["Status", props.tool.state === "running" ? "running" : "exited"], ["Port", "4173"]]} />
          <pre class="tool-output terminal-output"><code><span class="terminal-command">$ npm run dev</span>{"\n"}VITE ready in 401 ms{"\n"}Local: http://localhost:4173/</code></pre>
          <ExpandedActions labels={["Open terminal", "Stop process"]} />
        </Match>

        <Match when={family() === "file-read"}>
          <Fields rows={[["Path", props.tool.target], ["Range", "1–152"], ["Encoding", "UTF-8"]]} />
          <pre class="tool-output tool-code-preview"><code><span>149</span> return redirect(destination);{"\n"}<span>150</span> {"}"}</code></pre>
          <ExpandedActions labels={["Open file", "Copy path"]} />
        </Match>

        <Match when={family() === "file-write"}>
          <Fields rows={[["File", props.tool.target], ["Change", "+12  −4"], ["Receipt", "syntax valid"]]} />
          <pre class="tool-output tool-diff-preview"><code><span class="diff-del">− redirect(destination)</span>{"\n"}<span class="diff-add">+ clearStaleOAuthState()</span>{"\n"}<span class="diff-add">+ redirect(safeDestination(destination))</span></code></pre>
          <ExpandedActions labels={["Open native diff", "Reveal file"]} />
        </Match>

        <Match when={family() === "search"}>
          <Fields rows={[["Query", props.tool.target], ["Scope", "workspace"], ["Matches", "3"]]} />
          <div class="search-results">
            <button type="button"><code>src/auth/callback.ts:42</code><span>redirect(destination)</span></button>
            <button type="button"><code>src/auth/session.ts:18</code><span>safeDestination</span></button>
            <button type="button"><code>src/auth/callback.test.ts:77</code><span>preserves destination</span></button>
          </div>
          <ExpandedActions labels={["Open Search"]} />
        </Match>

        <Match when={family() === "verification"}>
          <div class="tool-checks">
            <div><Icon name="check" size={13} /><span>Typecheck</span><strong>passed</strong></div>
            <div><Show when={props.tool.state === "running"} fallback={<Icon name="check" size={13} />}><span class="spinner" /></Show><span>Browser callback</span><strong>{props.tool.state === "passed" ? "passed" : "running"}</strong></div>
            <div><Icon name="circle" size={12} /><span>Destination assertion</span><strong>{props.tool.state === "passed" ? "passed" : "queued"}</strong></div>
          </div>
          <ExpandedActions labels={["Open evidence"]} />
        </Match>

        <Match when={family() === "web"}>
          <Fields rows={[["URL", props.tool.target], ["Status", "200 OK"], ["Received", "18.4 KB"]]} />
          <pre class="tool-output web-output">OAuth 2.0 redirect URI validation{"\n"}The redirect URI must exactly match one of the registered callback locations…</pre>
          <ExpandedActions labels={["Open source", "Copy URL"]} />
        </Match>

        <Match when={family() === "browser"}>
          <Fields rows={[["Page", "Authentication callback"], ["URL", props.tool.target], ["Viewport", "1280 × 800"]]} />
          <div class="browser-snapshot">
            <div><span>document</span><code>Authentication complete</code></div>
            <div class="snapshot-child"><span>heading</span><code>Welcome back</code></div>
            <div class="snapshot-child"><span>link</span><code>Continue to dashboard</code></div>
          </div>
          <ExpandedActions labels={["Open screenshot", "Open browser"]} />
        </Match>

        <Match when={family() === "session"}>
          <Fields rows={[["Query", props.tool.target], ["Sessions", "2"], ["Model calls", "0"]]} />
          <div class="session-results">
            <button type="button"><strong>Fix OAuth callback</strong><span>Today · 18 messages</span></button>
            <button type="button"><strong>Authentication refactor</strong><span>Yesterday · 31 messages</span></button>
          </div>
          <ExpandedActions labels={["Open session history"]} />
        </Match>

        <Match when={family() === "subagent"}>
          <Fields rows={[["Goal", props.tool.target], ["Mode", "research"], ["Children", "2"]]} />
          <div class="child-tool-list">
            <div><Icon name="check" size={13} /><span>Search code</span><code>3 matches</code></div>
            <div><span class="spinner" /><span>Read callback flow</span><code>running</code></div>
          </div>
          <ExpandedActions labels={["Open sub-agent tab", "Cancel"]} />
        </Match>

        <Match when={family() === "code" || family() === "scaffold"}>
          <Fields rows={[["Runtime", "Python 3.13"], ["Calls", "4 / 50"], ["Status", "completed"]]} />
          <pre class="tool-output terminal-output"><code>files = search_code("redirect"){"\n"}print([f["path"] for f in files]){"\n\n"}["src/auth/callback.ts", "src/auth/session.ts"]</code></pre>
          <ExpandedActions labels={["Copy output"]} />
        </Match>

        <Match when={family() === "control"}>
          <pre class="tool-output">{props.tool.detail}</pre>
          <ExpandedActions labels={["Copy result"]} />
        </Match>
      </Switch>
    </div>
  );
};

export const ToolRow: Component<ToolRowProps> = (props) => {
  const presentation = () => toolPresentation(props.tool.toolName);
  const expandable = () => props.tool.state !== "queued";
  const defaultOpen = () => expandable() && (props.tool.defaultOpen ?? (
    props.tool.state === "approval" ||
    props.tool.state === "failed" ||
    presentation().defaultOpen === "always" ||
    (presentation().defaultOpen === "running" && props.tool.state === "running")
  ));

  return (
    <details
      class={`tool-disclosure tool-${props.tool.state}`}
      data-tool-id={props.tool.id}
      data-tool-name={props.tool.toolName}
      data-renderer-family={presentation().family}
      data-expandable={expandable() ? "true" : "false"}
      open={defaultOpen()}
    >
      <summary
        class="tool-row"
        aria-label={`${props.tool.name} ${props.tool.target}`}
        onClick={(event) => { if (!expandable()) event.preventDefault(); }}
      >
        <span class="tool-state-mark">
          <Show when={props.tool.state === "passed"} fallback={
            <Show when={props.tool.state === "running"} fallback={
              <Show when={props.tool.state === "approval"} fallback={<span class="tool-ring" />}>
                <Icon name="lock" size={14} />
              </Show>
            }>
              <span class="spinner" />
            </Show>
          }>
            <Icon name="check" size={14} />
          </Show>
        </span>
        <strong>{props.tool.name}</strong>
        <span class="tool-target">{props.tool.target}</span>
        <span class="tool-detail">{props.tool.detail}</span>
        <span class="tool-result">{props.tool.statusText ?? props.tool.duration ?? stateLabel[props.tool.state]}</span>
        <Show when={expandable()}><Icon name="chevron" size={12} class="tool-chevron" /></Show>
      </summary>
      <Show when={expandable()}><ToolDetails tool={props.tool} /></Show>
    </details>
  );
};
