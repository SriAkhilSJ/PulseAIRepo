import type { IconName } from "../components/Icon";

export type ToolRendererFamily =
  | "control"
  | "file-read"
  | "file-write"
  | "search"
  | "terminal"
  | "process"
  | "code"
  | "verification"
  | "web"
  | "browser"
  | "session"
  | "subagent"
  | "scaffold"
  | "generic";

export type DefaultOpenPolicy = "never" | "running" | "always" | "preference";

export interface ToolPresentation {
  title: string;
  family: ToolRendererFamily;
  icon: IconName;
  defaultOpen: DefaultOpenPolicy;
}

const tool = (
  title: string,
  family: ToolRendererFamily,
  icon: IconName,
  defaultOpen: DefaultOpenPolicy = "never",
): ToolPresentation => ({ title, family, icon, defaultOpen });

/**
 * Every tool name currently exposed by src/tools/toolsets.py plus the graph's
 * control tools. Rendering is selected by family; individual tools can later
 * override the family body without changing the transcript shell.
 */
export const PULSE_TOOL_CATALOG: Readonly<Record<string, ToolPresentation>> = {
  think: tool("Think", "control", "sparkles"),
  verify: tool("Verify", "verification", "shield", "running"),
  ask_user: tool("Question", "control", "agent", "running"),
  session_search: tool("Search sessions", "session", "search"),

  read_file: tool("Read", "file-read", "file"),
  list_files: tool("List files", "file-read", "folder"),
  search_code: tool("Search code", "search", "search"),
  write_file: tool("Write", "file-write", "file", "preference"),
  edit_file: tool("Edit", "file-write", "diff", "preference"),
  copy_file: tool("Copy file", "file-write", "copy", "preference"),

  run_terminal: tool("Terminal", "terminal", "terminal", "always"),
  execute_code: tool("Execute code", "code", "code", "running"),
  start_terminal: tool("Start process", "process", "terminal", "running"),
  check_terminal: tool("Check process", "process", "terminal", "running"),
  read_terminal_output: tool("Read process output", "process", "terminal", "always"),
  stop_terminal: tool("Stop process", "process", "pause"),
  list_terminal_processes: tool("List processes", "process", "terminal"),
  cleanup_terminal_processes: tool("Clean up processes", "process", "terminal"),

  typecheck_workspace: tool("Typecheck", "verification", "test", "running"),
  verify_ui_workspace: tool("Verify UI", "verification", "test", "running"),
  verify_ui_routes: tool("Verify routes", "verification", "test", "running"),
  scaffold_nextjs: tool("Scaffold Next.js", "scaffold", "folder", "running"),

  web_search: tool("Search web", "web", "search"),
  web_fetch: tool("Fetch page", "web", "file"),

  browser_navigate: tool("Navigate", "browser", "panel", "running"),
  browser_snapshot: tool("Browser snapshot", "browser", "panel"),
  browser_screenshot: tool("Screenshot", "browser", "panel"),
  browser_click: tool("Click", "browser", "panel"),
  browser_type: tool("Type", "browser", "panel"),
  browser_hover: tool("Hover", "browser", "panel"),
  browser_select: tool("Select", "browser", "panel"),
  browser_evaluate: tool("Evaluate in browser", "browser", "code"),

  delegate_to_subagent: tool("Delegate", "subagent", "agent", "running"),
  delegate_to_subagent_batch: tool("Delegate batch", "subagent", "agent", "running"),
};

const GENERIC = tool("Tool", "generic", "code");

export function toolPresentation(name: string | undefined): ToolPresentation {
  if (!name) return GENERIC;
  return PULSE_TOOL_CATALOG[name] ?? GENERIC;
}
