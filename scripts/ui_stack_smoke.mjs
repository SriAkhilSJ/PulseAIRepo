#!/usr/bin/env node
/**
 * Live UI stack smoke — browser-free, provider-free, zero credits.
 *
 * Why this exists: the webview's own tests prove the transcript *paints* from a
 * fixture, and `scripts/validate_pulse_ui_cdp.js` proves it paints inside a real
 * VS Code window over CDP. Neither proves the three hops *between* them are up:
 *   engine (src/server.py, AG-UI on :8123)  ->  runtime (pulse-webview/server.ts, :8200)
 *   ->  webview (vite dev / built assets, :5173)
 * A webview that renders a fixture while the runtime cannot see the agent is exactly
 * the "looks fine in tests, blank in the editor" failure. This walks the chain in the
 * order a request actually travels it and fails on the first hop that does not answer.
 *
 *   node scripts/ui_stack_smoke.mjs
 *   node scripts/ui_stack_smoke.mjs --agent http://127.0.0.1:8123/ --runtime http://127.0.0.1:8200 --web http://127.0.0.1:5173
 *
 * To drive it without a provider key, point the engine at the local stub:
 *   python scripts/stub_provider_server.py &                      # :8765
 *   LLM_PROVIDER=custom LLM_MODEL=stub-1 \
 *   CUSTOM_BASE_URL=http://127.0.0.1:8765/v1 CUSTOM_API_KEY=stub \
 *   AUX_LLM_PROVIDER=custom AUX_LLM_MODEL=stub-1 \
 *   python -m uvicorn src.server:app --host 0.0.0.0 --port 8123
 */

const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const AGENT = arg("agent", process.env.PULSEAI_AGENT_URL || "http://127.0.0.1:8123/");
const RUNTIME = arg("runtime", process.env.PULSEAI_RUNTIME_URL || "http://127.0.0.1:8200");
const WEB = arg("web", process.env.PULSEAI_WEB_URL || "http://127.0.0.1:5173");
const THROUGH_PROXY = arg("via-proxy", "1") !== "0";

const results = [];
let failed = false;

const check = async (name, fn, hint) => {
  const started = Date.now();
  try {
    const detail = await fn();
    results.push({ ok: true, name, detail, ms: Date.now() - started });
  } catch (err) {
    failed = true;
    results.push({
      ok: false,
      name,
      detail: `${err.message}${hint ? `\n      fix: ${hint}` : ""}`,
      ms: Date.now() - started,
    });
  }
};

const get = async (url, options = {}) => {
  const res = await fetch(url, { ...options, signal: AbortSignal.timeout(30_000) });
  return res;
};

// 1. The engine answers an AG-UI run with a complete turn.
await check(
  "engine: AG-UI run streams a full turn",
  async () => {
    const res = await get(AGENT, {
      method: "POST",
      headers: { "content-type": "application/json", accept: "text/event-stream" },
      body: JSON.stringify({
        threadId: `ui-smoke-${Date.now()}`,
        runId: `ui-smoke-run-${Date.now()}`,
        state: {},
        messages: [{ id: "m1", role: "user", content: "ui_stack_smoke: reply with one word." }],
        tools: [],
        context: [],
        forwardedProps: {},
      }),
    });
    if (!res.ok) throw new Error(`POST ${AGENT} -> http ${res.status}`);
    let raw = "";
    for await (const chunk of res.body) raw += Buffer.from(chunk).toString("utf8");
    const types = new Set(
      [...raw.matchAll(/"type":"([A-Z_]+)"/g)].map((m) => m[1])
    );
    for (const required of ["RUN_STARTED", "MESSAGES_SNAPSHOT", "RUN_FINISHED"]) {
      if (!types.has(required)) {
        throw new Error(`stream is missing ${required} (saw: ${[...types].join(", ") || "nothing"})`);
      }
    }
    if (types.has("RUN_ERROR")) throw new Error("engine reported RUN_ERROR");
    const assistant = [...raw.matchAll(/"role":"assistant","content":"((?:[^"\\]|\\.)*)"/g)].pop();
    return `events: ${[...types].sort().join(", ")}; reply: ${
      assistant ? JSON.parse(`"${assistant[1]}"`).slice(0, 60) : "(no assistant text parsed)"
    }`;
  },
  "start the engine: python -m uvicorn src.server:app --host 0.0.0.0 --port 8123"
);

// 2. The runtime registered that agent (the failure mode the fixture tests cannot see).
await check(
  "runtime: /api/copilotkit/info advertises pulse_agent",
  async () => {
    const res = await get(`${RUNTIME}/api/copilotkit/info`);
    if (!res.ok) throw new Error(`http ${res.status}`);
    const info = await res.json();
    const agents = Object.keys(info.agents || {});
    if (!agents.includes("pulse_agent")) {
      throw new Error(`pulse_agent not registered (agents seen: ${agents.join(", ") || "none"})`);
    }
    return `runtime ${info.version}, mode ${info.mode}, agents: ${agents.join(", ")}`;
  },
  "start the runtime: cd pulse-webview && npm run runtime (it must reach the engine on 8123)"
);

// 3. The same contract through the webview's own proxy — the path a browser takes.
await check(
  "webview proxy: /api/copilotkit forwards to the runtime",
  async () => {
    if (!THROUGH_PROXY) return "skipped by --via-proxy 0";
    const res = await get(`${WEB}/api/copilotkit/info`);
    if (!res.ok) throw new Error(`http ${res.status} — the dev proxy is not forwarding`);
    const info = await res.json();
    if (!Object.keys(info.agents || {}).includes("pulse_agent")) {
      throw new Error("proxy answered but pulse_agent is missing behind it");
    }
    return "same info through the browser-facing origin";
  },
  "vite proxies /api/copilotkit to COPILOT_RUNTIME_ORIGIN (default http://localhost:8200)"
);

// 4. The ported transcript's stylesheet really loads. A missing CSS import 404s in
//    dev and renders an unstyled pane that every DOM assertion still passes.
await check(
  "webview: hermes-ui stylesheet is served",
  async () => {
    const res = await get(`${WEB}/src/hermes-ui/styles/hermes-ui.css`);
    if (!res.ok) throw new Error(`http ${res.status} for the stylesheet`);
    const body = await res.text();
    if (!/transcript|pulseai|hermes/i.test(body)) {
      throw new Error("200 but the body has no hermes-ui rules — wrong file?");
    }
    return `${body.length} bytes of CSS, ${res.headers.get("content-type")}`;
  },
  "the dev server must be running from pulse-webview/ (npm run dev)"
);

// 5. The app shell itself mounts (entry module compiles and is served).
await check(
  "webview: app shell + entry module served",
  async () => {
    const html = await (await get(`${WEB}/`)).text();
    if (!/id=["']root["']/.test(html)) throw new Error("no #root in index.html");
    const entry = await get(`${WEB}/src/main.tsx`);
    if (!entry.ok) throw new Error(`main.tsx -> http ${entry.status}`);
    const body = await entry.text();
    if (!/App/.test(body)) throw new Error("main.tsx served but does not reference App");
    return "index.html + transformed main.tsx";
  },
  "npm run dev from pulse-webview/"
);

const pad = (n) => String(n).padStart(5);
console.log("\nui_stack_smoke — engine -> runtime -> webview\n");
for (const r of results) {
  console.log(`${r.ok ? "PASS" : "FAIL"}  ${pad(r.ms)}ms  ${r.name}`);
  for (const line of String(r.detail).split("\n")) {
    console.log(`        ${line}`);
  }
}
console.log(
  `\n${results.filter((r) => r.ok).length}/${results.length} hops healthy` +
    (failed ? "  <-- a real browser will not show a working agent until these pass" : "") +
    "\n"
);
process.exit(failed ? 1 : 0);
