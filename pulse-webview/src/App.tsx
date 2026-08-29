import { CopilotKitProvider, CopilotChat } from "@copilotkit/react-core/v2";
import { useAgentContext } from "@copilotkit/react-core/v2";
import { catalog } from "./a2ui/catalog";
import { useState, useEffect } from "react";

function WorkspaceContextBridge() {
  const [workspaceFiles] = useState([
    "src/server.py",
    "src/graphs/chat_graph.py",
    "src/a2ui_schemas/pulse_task_schema.json",
  ]);

  useAgentContext({
    description: "Pulse workspace context",
    value: {
      files: workspaceFiles,
      workspace: "/project",
      note: "Only these files are available. If user asks about other entities, refuse and name what is missing.",
    },
  });
  return null;
}

export default function App() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;
  return (
    <CopilotKitProvider
      // Relative URL: the Vite dev server (and any reverse proxy) forwards
      // /api/copilotkit to the Copilot Runtime on :8200. Hard-coding
      // http://localhost:8200 breaks every non-localhost origin.
      runtimeUrl="/api/copilotkit"
      useSingleEndpoint={false}
      a2ui={{ catalog }}
    >
      <WorkspaceContextBridge />
      <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
        <header style={{ padding: "12px", borderBottom: "1px solid #eee", fontWeight: 600 }}>
          PulseAI — Pulse Agent
        </header>
        <div style={{ flex: 1 }}>
          <CopilotChat agentId="pulse_agent" />
        </div>
      </div>
    </CopilotKitProvider>
  );
}
