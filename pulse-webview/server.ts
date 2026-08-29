import "dotenv/config";
import { createServer } from "node:http";
import { CopilotRuntime, CopilotKitIntelligence } from "@copilotkit/runtime/v2";
import { createCopilotNodeListener } from "@copilotkit/runtime/v2/node";
import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";

const intelligence = new CopilotKitIntelligence({
  apiKey: process.env.INTELLIGENCE_API_KEY!,
});

const pulseAgent = new LangGraphHttpAgent({
  url: process.env.LANGGRAPH_DEPLOYMENT_URL || "http://localhost:8123",
});
const runtime = new CopilotRuntime({
  agents: {
    pulse_agent: pulseAgent,
    default: pulseAgent,
  },
  intelligence,
  a2ui: { injectA2UITool: false, agents: ["pulse_agent", "default"] },
  identifyUser: (request) => ({
    id: request.headers.get("x-user-id") ?? "anonymous",
    name: request.headers.get("x-user-name") ?? "Anonymous",
  }),
});

const port = 8200;

createServer(
  createCopilotNodeListener({
    runtime,
    basePath: "/api/copilotkit",
    cors: true,
  }),
).listen(port, () => {
  console.log(`Copilot Runtime listening at http://localhost:${port}/api/copilotkit`);
});
