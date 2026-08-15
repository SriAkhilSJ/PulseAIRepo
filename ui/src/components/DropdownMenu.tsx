import { For, Show, type Component, type JSX } from "solid-js";
import { Icon, type IconName } from "./Icon";

export interface MenuItem {
  label: string;
  shortcut?: string;
  icon?: IconName;
  danger?: boolean;
  separatorBefore?: boolean;
}

interface DropdownMenuProps {
  label: string;
  items: readonly MenuItem[];
  icon?: IconName;
  compact?: boolean;
  align?: "left" | "right";
  class?: string;
  children?: JSX.Element;
}

export const DropdownMenu: Component<DropdownMenuProps> = (props) => (
  <details class={`dropdown ${props.class ?? ""}`} classList={{ compact: props.compact, "align-right": props.align === "right" }}>
    <summary>
      <Show when={props.icon}>{(name) => <Icon name={name()} size={props.compact ? 12 : 13} />}</Show>
      <span>{props.label}</span>
      <Icon name="chevron" size={10} />
    </summary>
    <div class="dropdown-popover" role="menu">
      <For each={props.items}>{(item) => (
        <button class="dropdown-item" classList={{ danger: item.danger, separated: item.separatorBefore }} type="button" role="menuitem">
          <span class="dropdown-item-icon"><Show when={item.icon}>{(name) => <Icon name={name()} size={13} />}</Show></span>
          <span>{item.label}</span>
          <Show when={item.shortcut}><kbd>{item.shortcut}</kbd></Show>
        </button>
      )}</For>
      {props.children}
    </div>
  </details>
);

const fileItems: MenuItem[] = [
  { label: "New Text File", shortcut: "Ctrl+N", icon: "file" },
  { label: "Open File…", shortcut: "Ctrl+O", icon: "folder" },
  { label: "Open Folder…", shortcut: "Ctrl+K Ctrl+O", icon: "folder" },
  { label: "Save", shortcut: "Ctrl+S", icon: "check", separatorBefore: true },
];

const editItems: MenuItem[] = [
  { label: "Undo", shortcut: "Ctrl+Z" },
  { label: "Redo", shortcut: "Ctrl+Y" },
  { label: "Find", shortcut: "Ctrl+F", icon: "search", separatorBefore: true },
];

const selectionItems: MenuItem[] = [
  { label: "Select All", shortcut: "Ctrl+A" },
  { label: "Expand Selection", shortcut: "Shift+Alt+Right" },
  { label: "Add Cursor Above", shortcut: "Ctrl+Alt+Up", separatorBefore: true },
];

const viewItems: MenuItem[] = [
  { label: "Command Palette…", shortcut: "Ctrl+Shift+P", icon: "search" },
  { label: "Explorer", shortcut: "Ctrl+Shift+E", icon: "files", separatorBefore: true },
  { label: "Pulse", shortcut: "Ctrl+Shift+I", icon: "pulse" },
  { label: "Pulse Manager", icon: "agent" },
];

const goItems: MenuItem[] = [
  { label: "Go to File…", shortcut: "Ctrl+P", icon: "file" },
  { label: "Go to Symbol…", shortcut: "Ctrl+Shift+O", icon: "search" },
  { label: "Back", shortcut: "Alt+Left", separatorBefore: true },
];

const runItems: MenuItem[] = [
  { label: "Start Debugging", shortcut: "F5", icon: "play" },
  { label: "Run Without Debugging", shortcut: "Ctrl+F5", icon: "play" },
  { label: "Stop", shortcut: "Shift+F5", icon: "pause", separatorBefore: true },
];

const terminalItems: MenuItem[] = [
  { label: "New Terminal", shortcut: "Ctrl+Shift+`", icon: "terminal" },
  { label: "Split Terminal", icon: "panel" },
  { label: "Run Task…", icon: "play", separatorBefore: true },
];

const helpItems: MenuItem[] = [
  { label: "Welcome", icon: "sparkles" },
  { label: "Documentation" },
  { label: "Show All Commands", shortcut: "Ctrl+Shift+P", separatorBefore: true },
  { label: "About PulseAI IDE", separatorBefore: true },
];

const pulseItems: MenuItem[] = [
  { label: "New Agent Session", shortcut: "Ctrl+Alt+N", icon: "plus" },
  { label: "Open Pulse Manager", shortcut: "Ctrl+Alt+M", icon: "agent" },
  { label: "Review Changes", icon: "diff", separatorBefore: true },
  { label: "Checkpoints", icon: "restore" },
  { label: "Stop Active Run", icon: "pause", danger: true, separatorBefore: true },
  { label: "Pulse Settings", icon: "settings", separatorBefore: true },
];

interface NativeMenuBarProps {
  title?: string;
}

export const NativeMenuBar: Component<NativeMenuBarProps> = (props) => (
  <header class="native-menu-bar">
    <div class="window-brand"><Icon name="pulse" size={15} /><strong>PulseAI</strong></div>
    <nav class="native-menu-items" aria-label="Application menu">
      <DropdownMenu label="File" items={fileItems} />
      <DropdownMenu label="Edit" items={editItems} />
      <DropdownMenu label="Selection" items={selectionItems} />
      <DropdownMenu label="View" items={viewItems} />
      <DropdownMenu label="Go" items={goItems} />
      <DropdownMenu label="Run" items={runItems} />
      <DropdownMenu label="Terminal" items={terminalItems} />
      <DropdownMenu label="Help" items={helpItems} />
      <DropdownMenu label="Pulse" items={pulseItems} class="pulse-menu" />
    </nav>
    <button class="command-center" type="button"><Icon name="search" size={12} /><span>{props.title ?? "PulseAI IDE"}</span></button>
    <div class="window-controls" aria-hidden="true"><span>—</span><span>□</span><span>×</span></div>
  </header>
);
