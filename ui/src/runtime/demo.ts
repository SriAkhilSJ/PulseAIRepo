import { createMemo, createSignal, onCleanup } from "solid-js";
import type { DemoStage, ToolRun } from "../types";

const RESPONSE =
  "I traced the redirect loop to a stale session cookie surviving the OAuth callback. I’ll repair the callback guard, preserve the intended route, and prove the flow in the browser.";

export function createDemoRun() {
  const [stage, setStage] = createSignal<DemoStage>("approval");
  const [streamed, setStreamed] = createSignal(RESPONSE);
  const [inputTokens, setInputTokens] = createSignal(12_840);
  const [cacheTokens, setCacheTokens] = createSignal(9_420);
  const timers = new Set<number>();

  const later = (fn: () => void, ms: number) => {
    const id = window.setTimeout(() => {
      timers.delete(id);
      fn();
    }, ms);
    timers.add(id);
  };

  const clear = () => {
    for (const id of timers) window.clearTimeout(id);
    timers.clear();
  };

  const replay = () => {
    clear();
    setStage("streaming");
    setStreamed("");
    setInputTokens(12_120);
    setCacheTokens(8_960);

    let cursor = 0;
    const tick = () => {
      cursor = Math.min(RESPONSE.length, cursor + 3);
      setStreamed(RESPONSE.slice(0, cursor));
      setInputTokens((value) => value + 8);
      setCacheTokens((value) => value + 5);
      if (cursor < RESPONSE.length) later(tick, 24);
      else later(() => setStage("approval"), 650);
    };
    later(tick, 180);
  };

  const approve = () => {
    if (stage() !== "approval") return;
    setStage("verifying");
    later(() => {
      setInputTokens(14_268);
      setCacheTokens(10_840);
      setStage("verified");
    }, 1700);
  };

  const deny = () => {
    if (stage() !== "approval") return;
    setStage("denied");
  };

  const tools = createMemo<ToolRun[]>(() => {
    const value = stage();
    return [
      {
        id: "read-auth",
        toolName: "read_file",
        name: "Read",
        target: "src/auth/callback.ts",
        detail: "152 lines · session and redirect handling",
        state: value === "streaming" && streamed().length < 65 ? "running" : "passed",
        duration: "84ms",
      },
      {
        id: "terminal-auth-test",
        toolName: "run_terminal",
        name: "Terminal",
        target: "npm test -- auth",
        detail: "17 passed · 1 failed · callback redirect loop",
        state: value === "streaming" && streamed().length < 65 ? "queued" : "failed",
        duration: "2.8s",
        statusText: "exit 1",
      },
      {
        id: "edit-session",
        toolName: "edit_file",
        name: "Edit",
        target: "src/auth/session.ts",
        detail: "+12  −4 · clear stale state before redirect",
        state:
          value === "approval" ? "approval" :
          value === "denied" ? "failed" :
          value === "streaming" ? "queued" : "passed",
        duration: value === "verified" ? "112ms" : undefined,
      },
      {
        id: "verify-ui",
        toolName: "verify_ui_workspace",
        name: "Verify",
        target: "Authentication flow",
        detail: "Typecheck + browser navigation + callback assertion",
        state:
          value === "verified" ? "passed" :
          value === "verifying" ? "running" :
          value === "denied" ? "failed" : "queued",
        duration: value === "verified" ? "1.4s" : undefined,
      },
    ];
  });

  onCleanup(clear);

  return {
    stage,
    streamed,
    inputTokens,
    cacheTokens,
    tools,
    replay,
    approve,
    deny,
  };
}

export type DemoRun = ReturnType<typeof createDemoRun>;
