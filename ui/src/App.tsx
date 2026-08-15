import { Match, Switch, createSignal } from "solid-js";
import { Icon } from "./components/Icon";
import { PulseMark } from "./components/PulseMark";
import { StatusDot } from "./components/StatusDot";
import { createDemoRun } from "./runtime/demo";
import { AgentSurface } from "./surfaces/AgentSurface";
import { ManagerSurface } from "./surfaces/ManagerSurface";
import { ToolGallerySurface } from "./surfaces/ToolGallerySurface";
import type { Surface, Theme } from "./types";

export function App() {
  const [surface, setSurface] = createSignal<Surface>("agent");
  const [theme, setTheme] = createSignal<Theme>("dark");
  const demo = createDemoRun();

  return (
    <div class={`app theme-${theme()}`}>
      <header class="lab-header">
        <div class="lab-brand-group">
          <PulseMark />
          <span class="lab-badge">UI LAB</span>
        </div>

        <nav class="surface-switcher" aria-label="Preview surface">
          <button classList={{ active: surface() === "agent" }} type="button" onClick={() => setSurface("agent")}>
            <Icon name="panel" size={14} />Agent UI
          </button>
          <button classList={{ active: surface() === "manager" }} type="button" onClick={() => setSurface("manager")}>
            <Icon name="agent" size={15} />Agent Manager
          </button>
          <button classList={{ active: surface() === "tools" }} type="button" onClick={() => setSurface("tools")}>
            <Icon name="terminal" size={14} />Tool Gallery
          </button>
        </nav>

        <div class="lab-actions">
          <StatusDot state="running" label="Mock engine" />
          <button class="lab-action-button" type="button" onClick={demo.replay}>
            <Icon name="play" size={14} />Replay stream
          </button>
          <button
            class="icon-button lab-theme-button"
            type="button"
            aria-label="Toggle theme"
            onClick={() => setTheme((value) => value === "dark" ? "light" : "dark")}
          >
            <Icon name={theme() === "dark" ? "sun" : "moon"} />
          </button>
        </div>
      </header>

      <div class="lab-note">
        <span class="lab-note-mark"><Icon name="pulse" size={13} /></span>
        <span>
          Browser design surface for the first-party <code>src/vs/workbench/contrib/pulseai/</code> integration.
        </span>
        <span class="lab-note-rule">No extension host · No activity graphs</span>
      </div>

      <main class="preview-stage">
        <Switch>
          <Match when={surface() === "agent"}><AgentSurface demo={demo} /></Match>
          <Match when={surface() === "manager"}><ManagerSurface demo={demo} /></Match>
          <Match when={surface() === "tools"}><ToolGallerySurface /></Match>
        </Switch>
      </main>
    </div>
  );
}
