import type { ToolRun } from "../types";

export const TOOL_FAMILY_SAMPLES: readonly ToolRun[] = [
  { id: "sample-control", toolName: "think", name: "Think", target: "Choose a repair strategy", detail: "Compared the callback guard with session lifecycle evidence.", state: "passed", defaultOpen: false },
  { id: "sample-read", toolName: "read_file", name: "Read", target: "src/auth/callback.ts", detail: "152 lines · UTF-8", state: "passed", duration: "84ms", defaultOpen: false },
  { id: "sample-write", toolName: "edit_file", name: "Edit", target: "src/auth/session.ts", detail: "+12 −4 · syntax receipt passed", state: "passed", duration: "112ms", defaultOpen: false },
  { id: "sample-search", toolName: "search_code", name: "Search code", target: "redirect destination", detail: "3 matches in 3 files", state: "passed", duration: "42ms", defaultOpen: false },
  { id: "sample-terminal", toolName: "run_terminal", name: "Terminal", target: "npm test -- auth", detail: "17 passed · 1 failed", state: "failed", statusText: "exit 1", defaultOpen: true },
  { id: "sample-process", toolName: "start_terminal", name: "Start process", target: "npm run dev", detail: "PID 4821 · port 4173", state: "running", statusText: "running", defaultOpen: false },
  { id: "sample-code", toolName: "execute_code", name: "Execute code", target: "4 inner calls", detail: "Programmatic tool batch", state: "passed", duration: "318ms", defaultOpen: false },
  { id: "sample-verify", toolName: "verify_ui_workspace", name: "Verify UI", target: "Authentication flow", detail: "Typecheck + browser + assertions", state: "running", statusText: "2 / 3", defaultOpen: false },
  { id: "sample-web", toolName: "web_fetch", name: "Fetch page", target: "https://docs.example.dev/oauth", detail: "200 OK · 18.4 KB", state: "passed", duration: "640ms", defaultOpen: false },
  { id: "sample-browser", toolName: "browser_snapshot", name: "Browser snapshot", target: "http://localhost:4173/callback", detail: "1280 × 800 · 24 nodes", state: "passed", duration: "180ms", defaultOpen: false },
  { id: "sample-session", toolName: "session_search", name: "Search sessions", target: "OAuth callback", detail: "2 sessions · zero model calls", state: "passed", duration: "18ms", defaultOpen: false },
  { id: "sample-subagent", toolName: "delegate_to_subagent", name: "Delegate", target: "Trace callback flow", detail: "Research agent · 2 child tools", state: "running", statusText: "working", defaultOpen: false },
  { id: "sample-scaffold", toolName: "scaffold_nextjs", name: "Scaffold Next.js", target: "apps/web", detail: "7 files · app router", state: "passed", duration: "1.2s", defaultOpen: false },
];
