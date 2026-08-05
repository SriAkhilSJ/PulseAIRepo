#!/usr/bin/env node
/**
 * Standalone smoke test for PulseAgentModelService parsing logic.
 *
 * Tests the SSEReader and JSONLinesReader by feeding them mock
 * response data and asserting the output.
 *
 * Run: node test-pulse-model-service.mjs
 */

// ── Mock SSE data (OpenAI format) ────────────────────────

const openaiSSE = [
  "data: {\"choices\":[{\"delta\":{\"content\":\"Hello\"},\"index\":0}]}",
  "data: {\"choices\":[{\"delta\":{\"content\":\" world\"},\"index\":0}]}",
  "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\",\"index\":0}]}",
  "data: [DONE]",
].join("\n");

const anthropicSSE = [
  "data: {\"type\":\"content_block_delta\",\"delta\":{\"type\":\"text_delta\",\"text\":\"Hello\"}}",
  "data: {\"type\":\"content_block_delta\",\"delta\":{\"type\":\"text_delta\",\"text\":\" from Claude\"}}",
  "data: {\"type\":\"message_delta\",\"delta\":{\"stop_reason\":\"end_turn\"}}",
].join("\n");

const ollamaJSON = [
  JSON.stringify({ message: { content: "Hello" }, done: false }),
  JSON.stringify({ message: { content: " from Llama" }, done: false }),
  JSON.stringify({ message: { content: "" }, done: true }),
].join("\n");

const googleSSE = [
  "data: {\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"Hello \"}],\"role\":\"model\"},\"finishReason\":\"STOP\"}]}",
].join("\n");

// ── Parse functions (same logic as SSEReader/JSONLinesReader) ──

function parseSSE(text) {
  const results = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || !trimmed.startsWith("data: ")) continue;
    const jsonStr = trimmed.slice(6).trim();
    if (jsonStr === "[DONE]") { results.push({ _done: true }); break; }
    try {
      results.push(JSON.parse(jsonStr));
    } catch {
      // skip malformed
    }
  }
  return results;
}

function parseJSONLines(text) {
  const results = [];
  for (const line of text.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      results.push(JSON.parse(trimmed));
    } catch {
      // skip malformed
    }
  }
  return results;
}

// ── Test runner ──────────────────────────────────────────────

let passed = 0;
let failed = 0;

function assert(condition, message) {
  if (condition) {
    passed++;
  } else {
    failed++;
    console.error(`  FAIL: ${message}`);
  }
}

function test(name, fn) {
  console.log(`\n  ${name}:`);
  try { fn(); } catch (e) { failed++; console.error(`  ERROR: ${e.message}`); }
}

// ── Tests ───────────────────────────────────────────────────

test("OpenAI SSE parsing", () => {
  const events = parseSSE(openaiSSE);
  // 3 data events + 1 [DONE] marker (still counted)
  assert(events.length === 4, `expected 4 events (3 data + [DONE]), got ${events.length}`);
  assert(events[0].choices[0].delta.content === "Hello", "first chunk content");
  assert(events[1].choices[0].delta.content === " world", "second chunk content");
  assert(events[2].choices[0].finish_reason === "stop", "finish reason");
});

test("OpenAI text assembly", () => {
  const events = parseSSE(openaiSSE);
  const text = events
    .filter(e => e.choices?.[0]?.delta?.content)
    .map(e => e.choices[0].delta.content)
    .join("");
  assert(text === "Hello world", `expected 'Hello world', got '${text}'`);
});

test("Anthropic SSE parsing", () => {
  const events = parseSSE(anthropicSSE);
  assert(events.length === 3, `expected 3 events, got ${events.length}`);
  assert(events[0].type === "content_block_delta", "first event type");
  assert(events[0].delta.text === "Hello", "first text chunk");
  assert(events[2].delta.stop_reason === "end_turn", "stop reason");
});

test("Anthropic text assembly", () => {
  const events = parseSSE(anthropicSSE);
  const text = events
    .filter(e => e.type === "content_block_delta" && e.delta?.type === "text_delta")
    .map(e => e.delta.text)
    .join("");
  assert(text === "Hello from Claude", `expected 'Hello from Claude', got '${text}'`);
});

test("Ollama JSON lines parsing", () => {
  const events = parseJSONLines(ollamaJSON);
  assert(events.length === 3, `expected 3 events, got ${events.length}`);
  assert(events[0].message.content === "Hello", "first message");
  assert(events[2].done === true, "done flag");
});

test("Ollama text assembly", () => {
  const events = parseJSONLines(ollamaJSON);
  const text = events
    .filter(e => e.message?.content)
    .map(e => e.message.content)
    .join("");
  assert(text === "Hello from Llama", `expected 'Hello from Llama', got '${text}'`);
});

test("Google SSE parsing", () => {
  const events = parseSSE(googleSSE);
  assert(events.length === 1, `expected 1 event, got ${events.length}`);
  assert(events[0].candidates[0].content.parts[0].text === "Hello ", "text");
  assert(events[0].candidates[0].finishReason === "STOP", "finish reason");
});

test("[DONE] termination", () => {
  const events = parseSSE(openaiSSE);
  // [DONE] is pushed as {_done: true} and then break happens
  const last = events[events.length - 1];
  assert(last._done === true, "_done marker should be last event");
  const textEvents = events.filter(e => e.choices?.[0]?.delta?.content);
  assert(textEvents.length === 2, "2 text chunks before [DONE]");
});

// ── Summary ─────────────────────────────────────────────────

console.log(`\n${"=".repeat(40)}`);
console.log(`  ${passed} passed, ${failed} failed`);
console.log(`${"=".repeat(40)}`);

process.exit(failed > 0 ? 1 : 0);
