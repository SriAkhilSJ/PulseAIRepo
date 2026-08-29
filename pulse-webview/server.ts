import "dotenv/config";
import { createServer } from "node:http";
import { CopilotRuntime, CopilotKitIntelligence } from "@copilotkit/runtime/v2";
import { createCopilotNodeListener } from "@copilotkit/runtime/v2/node";
import { HttpAgent } from "@ag-ui/client";

/**
 * The Python agent (src/server.py) exposes an **AG-UI** endpoint via
 * `add_langgraph_fastapi_endpoint`, so the runtime must talk to it with an
 * AG-UI `HttpAgent`.
 *
 * Previously this used `LangGraphHttpAgent` (the v1/LangGraph-Platform client)
 * together with `CopilotKitIntelligence`. That combination routed every run
 * through CopilotKit Cloud (`api.intelligence.copilotkit.ai`) and never
 * reached the Python agent at all.
 */
const deploymentUrl =
  process.env.LANGGRAPH_DEPLOYMENT_URL || "http://localhost:8123/";

const pulseAgent = new HttpAgent({ url: deploymentUrl });

/**
 * CopilotKit Intelligence is optional. When `INTELLIGENCE_API_KEY` is absent
 * the runtime runs in plain SSE mode and talks to `pulseAgent` directly, so
 * the app still works without a CopilotKit Cloud account.
 */
const intelligenceApiKey = process.env.INTELLIGENCE_API_KEY;
const intelligence = intelligenceApiKey
  ? new CopilotKitIntelligence({ apiKey: intelligenceApiKey })
  : undefined;

const runtime = new CopilotRuntime({
  agents: {
    pulse_agent: pulseAgent,
    default: pulseAgent,
  },
  ...(intelligence ? { intelligence } : {}),
  a2ui: { injectA2UITool: false, agents: ["pulse_agent", "default"] },
  identifyUser: (request) => ({
    id: request.headers.get("x-user-id") ?? "anonymous",
    name: request.headers.get("x-user-name") ?? "Anonymous",
  }),
});

const port = Number(process.env.COPILOT_RUNTIME_PORT ?? 8200);

// A dropped upstream socket (agent restart, crash mid-stream) must not take
// the runtime process down with it — otherwise the whole webview 502s until
// someone restarts the server by hand.
process.on("unhandledRejection", (reason) => {
  console.error("[copilot-runtime] unhandled rejection:", reason);
});
process.on("uncaughtException", (error) => {
  console.error("[copilot-runtime] uncaught exception:", error);
});

createServer(
  createCopilotNodeListener({
    runtime,
    basePath: "/api/copilotkit",
    cors: true,
  }),
).listen(port, "0.0.0.0", () => {
  console.log(
    `Copilot Runtime listening at http://0.0.0.0:${port}/api/copilotkit`,
  );
  console.log(`  agent backend : ${deploymentUrl}`);
  console.log(
    `  mode          : ${intelligence ? "intelligence (CopilotKit Cloud)" : "sse (direct to agent)"}`,
  );
});
