import { CopilotKitProvider, CopilotChat, useAgentContext } from "@copilotkit/react-core/v2";
import { useState, useEffect } from "react";
import { catalog } from "./a2ui/catalog";
import {
  PulseAgentThread,
  PulseComposer,
  usePulseThread,
  usePulseToolRenderer,
} from "./hermes-ui";
import "./hermes-ui/styles/hermes-ui.css";

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

type Surface = "agent" | "chat";

/**
 * Two surfaces over the SAME agent, toggled in the header:
 *
 * - `agent`  — the ported Hermes transcript (tool runs, tickers, diffs,
 *   approvals, plan/verification ledger). Reads `usePulseThread`, i.e. the
 *   agent's own messages + state, and answers approvals by handing the
 *   `safety_reply` frame to whoever hosts this iframe.
 * - `chat`   — stock `CopilotChat`. `usePulseToolRenderer()` still replaces its
 *   generic tool card with the same ported row, so the two surfaces cannot show
 *   different truths about one tool call.
 */
function PulseWorkspace({ surface }: { surface: Surface }) {
  usePulseToolRenderer();
  const thread = usePulseThread({ agentId: "pulse_agent" });

  if (surface === "chat") {
    return <CopilotChat agentId="pulse_agent" />;
  }

  return (
    <PulseAgentThread
      approvalRespond={(choice, approval) => thread.respondApproval(choice, approval)}
      composer={
        <PulseComposer
          onSubmit={thread.submit}
          onStop={thread.stop}
          signals={thread.signals}
        />
      }
      signals={thread.signals}
      transcript={thread.transcript}
    />
  );
}

export default function App() {
  const [mounted, setMounted] = useState(false);
  const [surface, setSurface] = useState<Surface>("agent");
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
        <header
          style={{
            padding: "10px 12px",
            borderBottom: "1px solid #eee",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <strong>PulseAI — Pulse Agent</strong>
          <span style={{ marginLeft: "auto", display: "flex", gap: 4, fontSize: 12 }}>
            {(["agent", "chat"] as const).map((option) => (
              <button
                key={option}
                onClick={() => setSurface(option)}
                style={{
                  border: "1px solid " + (surface === option ? "#0b6bcb" : "#ddd"),
                  background: surface === option ? "#0b6bcb" : "transparent",
                  color: surface === option ? "#fff" : "inherit",
                  borderRadius: 999,
                  cursor: "pointer",
                  fontSize: 12,
                  padding: "2px 10px",
                }}
                type="button"
              >
                {option === "agent" ? "Agent UI" : "Copilot chat"}
              </button>
            ))}
          </span>
        </header>
        <div style={{ flex: 1, minHeight: 0 }}>
          <PulseWorkspace surface={surface} />
        </div>
      </div>
    </CopilotKitProvider>
  );
}
