import { For, type Component } from "solid-js";
import type { DemoRun } from "../runtime/demo";
import { AgentPanel } from "../components/AgentPanel";
import { NativeMenuBar } from "../components/DropdownMenu";
import { Icon, type IconName } from "../components/Icon";

interface AgentSurfaceProps {
  demo: DemoRun;
}

const code = [
  ["1", "import { cookies } from \"next/headers\";"],
  ["2", "import { redirect } from \"next/navigation\";"],
  ["3", ""],
  ["4", "export async function completeSession("],
  ["5", "  code: string,"],
  ["6", "  destination = \"/dashboard\","],
  ["7", ") {"],
  ["8", "  const jar = await cookies();"],
  ["9", "  const staleState = jar.get(\"oauth_state\");"],
  ["10", ""],
  ["11", "  if (staleState) {"],
  ["12", "    jar.delete(\"oauth_state\");"],
  ["13", "  }"],
  ["14", ""],
  ["15", "  await exchangeCodeForSession(code);"],
  ["16", "  redirect(safeDestination(destination));"],
  ["17", "}"],
];

const rail: { icon: IconName; label: string; active?: boolean }[] = [
  { icon: "files", label: "Explorer" },
  { icon: "search", label: "Search" },
  { icon: "branch", label: "Source Control" },
  { icon: "terminal", label: "Terminal" },
  { icon: "pulse", label: "Pulse", active: true },
];

export const AgentSurface: Component<AgentSurfaceProps> = (props) => (
  <div class="ide-shell">
    <NativeMenuBar title="pulseai-web — PulseAI IDE" />
    <aside class="activity-rail">
      <div class="rail-primary">
        <For each={rail}>{(item) => (
          <button class="rail-button" classList={{ active: item.active }} type="button" aria-label={item.label} title={item.label}>
            <Icon name={item.icon} size={19} />
          </button>
        )}</For>
      </div>
      <button class="rail-button" type="button" aria-label="Settings"><Icon name="settings" size={19} /></button>
    </aside>

    <aside class="explorer-pane">
      <header class="pane-title"><span>EXPLORER</span><Icon name="more" size={15} /></header>
      <div class="workspace-title"><Icon name="chevron" size={13} /><strong>PULSEAI-WEB</strong></div>
      <div class="file-tree">
        <div class="tree-row folder-row"><Icon name="chevron" size={12} /><Icon name="folder" size={14} /><span>src</span></div>
        <div class="tree-row folder-row depth-1"><Icon name="chevron" size={12} /><Icon name="folder" size={14} /><span>auth</span></div>
        <div class="tree-row depth-2 active"><Icon name="file" size={14} /><span>session.ts</span><span class="tree-modified">M</span></div>
        <div class="tree-row depth-2"><Icon name="file" size={14} /><span>callback.ts</span></div>
        <div class="tree-row depth-1"><Icon name="folder" size={14} /><span>components</span></div>
        <div class="tree-row depth-1"><Icon name="folder" size={14} /><span>routes</span></div>
        <div class="tree-row"><Icon name="file" size={14} /><span>package.json</span></div>
        <div class="tree-row"><Icon name="file" size={14} /><span>tsconfig.json</span></div>
      </div>
      <div class="explorer-section"><Icon name="chevron" size={12} /><span>OUTLINE</span></div>
      <div class="explorer-section"><Icon name="chevron" size={12} /><span>TIMELINE</span></div>
    </aside>

    <main class="editor-pane">
      <div class="editor-tabs">
        <div class="editor-tab active"><Icon name="code" size={14} /><span>session.ts</span><span class="tab-dirty" /></div>
        <div class="editor-tab"><Icon name="code" size={14} /><span>callback.ts</span><Icon name="close" size={12} /></div>
      </div>
      <div class="breadcrumbs"><span>src</span><span>/</span><span>auth</span><span>/</span><strong>session.ts</strong><span>/</span><span>completeSession</span></div>
      <div class="code-editor" aria-label="Code editor mock">
        <For each={code}>{(line) => (
          <div class="code-line" classList={{ "line-changed": ["11", "12", "13"].includes(line[0]) }}>
            <span class="line-number">{line[0]}</span>
            <code>{line[1]}</code>
          </div>
        )}</For>
      </div>
      <div class="editor-minimap" aria-hidden="true">
        <span style={{ top: "8%", width: "74%" }} /><span style={{ top: "15%", width: "62%" }} />
        <span style={{ top: "28%", width: "84%" }} /><span style={{ top: "35%", width: "45%" }} />
        <span class="mini-change" style={{ top: "49%", width: "78%" }} />
        <span style={{ top: "65%", width: "70%" }} /><span style={{ top: "73%", width: "58%" }} />
      </div>
    </main>

    <AgentPanel demo={props.demo} embedded />

    <footer class="statusbar">
      <div><span><Icon name="branch" size={12} /> main*</span><span><Icon name="circle" size={11} /> 0</span><span>△ 0</span></div>
      <div><span>Ln 12, Col 5</span><span>Spaces: 2</span><span>UTF-8</span><span>TypeScript React</span><span class="pulse-statusbar"><Icon name="pulse" size={12} /> Pulse ready</span></div>
    </footer>
  </div>
);
