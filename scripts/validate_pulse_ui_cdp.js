#!/usr/bin/env node
/* Provider-free Pulse Agent/Manager desktop smoke over raw Chrome DevTools Protocol. */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const port = Number(process.env.PULSEAI_CDP_PORT || '9222');
const evidenceDir = path.resolve(process.argv[2] || 'bench-results/agent-ui-cdp-desktop');
const prompt = 'Pulse Agent UI provider-free CDP smoke';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

class CdpClient {
  constructor(url) {
    this.url = url;
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
  }

  async connect() {
    this.ws = new WebSocket(this.url);
    this.ws.addEventListener('message', event => {
      const message = JSON.parse(String(event.data));
      if (message.id) {
        const pending = this.pending.get(message.id);
        if (!pending) return;
        this.pending.delete(message.id);
        if (message.error) pending.reject(new Error(`${pending.method}: ${JSON.stringify(message.error)}`));
        else pending.resolve(message.result || {});
      } else {
        this.events.push(message);
      }
    });
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('CDP websocket connection timed out')), 10_000);
      this.ws.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
      this.ws.addEventListener('error', () => { clearTimeout(timer); reject(new Error('CDP websocket connection failed')); }, { once: true });
    });
  }

  call(method, params = {}, timeoutMs = 15_000) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, timeoutMs);
      this.pending.set(id, {
        method,
        resolve: value => { clearTimeout(timer); resolve(value); },
        reject: error => { clearTimeout(timer); reject(error); },
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  close() { this.ws?.close(); }
}

async function waitForEndpoint(timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const targets = await response.json();
      const page = targets.find(target => target.type === 'page' && target.webSocketDebuggerUrl);
      if (page) return page;
      lastError = new Error('No page target');
    } catch (error) { lastError = error; }
    await delay(500);
  }
  throw new Error(`CDP endpoint unavailable on ${port}: ${lastError?.message || 'timeout'}`);
}

async function main() {
  fs.mkdirSync(evidenceDir, { recursive: true });
  const report = {
    started_at: new Date().toISOString(),
    cdp_port: port,
    provider_requests: 0,
    prompt,
    checks: {},
    snapshots: {},
    console_errors: [],
    screenshots: [],
    overall: 'FAIL',
  };
  let cdp;

  const evaluate = async expression => {
    const response = await cdp.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.text || 'Runtime.evaluate failed');
    return response.result?.value;
  };
  const waitFor = async (description, expression, timeoutMs = 30_000) => {
    const deadline = Date.now() + timeoutMs;
    let value;
    while (Date.now() < deadline) {
      value = await evaluate(expression);
      if (value) return value;
      await delay(250);
    }
    throw new Error(`Timed out waiting for ${description}`);
  };
  const screenshot = async name => {
    const result = await cdp.call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false }, 30_000);
    const file = path.join(evidenceDir, name);
    fs.writeFileSync(file, Buffer.from(result.data, 'base64'));
    report.screenshots.push(name);
  };
  const snapshot = async (name, selector) => {
    const value = await evaluate(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return {
        selector: ${JSON.stringify(selector)}, x: r.x, y: r.y, width: r.width, height: r.height,
        visible: r.width > 0 && r.height > 0 && style.visibility !== 'hidden' && style.display !== 'none',
        enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
        text: (el.textContent || '').trim().slice(0, 500),
        clientWidth: el.clientWidth, scrollWidth: el.scrollWidth,
      };
    })()`);
    report.snapshots[name] = value;
    return value;
  };
  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
    report.checks[message] = 'PASS';
  };

  try {
    const target = await waitForEndpoint();
    report.target = { id: target.id, title: target.title, url: target.url };
    cdp = new CdpClient(target.webSocketDebuggerUrl);
    await cdp.connect();
    await Promise.all([
      cdp.call('Runtime.enable'),
      cdp.call('Page.enable'),
      cdp.call('Log.enable'),
    ]);

    // Open/focus Pulse using its registered Windows keybinding.
    await cdp.call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'l', code: 'KeyL', modifiers: 2, windowsVirtualKeyCode: 76, nativeVirtualKeyCode: 76 });
    await cdp.call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'l', code: 'KeyL', modifiers: 2, windowsVirtualKeyCode: 76, nativeVirtualKeyCode: 76 });

    await waitFor('Pulse composer', `Boolean(document.querySelector('textarea.pulseai-composer-input'))`, 30_000);
    await waitFor('Pulse ready state', `document.querySelector('.pulseai-engine-status')?.textContent?.includes('Pulse ready')`, 30_000);

    const composer = await snapshot('agent_composer', 'textarea.pulseai-composer-input');
    const header = await snapshot('agent_header', '.pulseai-agent-header');
    const shell = await snapshot('agent_shell', '.pulseai-agent-shell');
    const managerButton = await snapshot('manager_button', '.pulseai-agent-header-actions .pulseai-icon-button');
    assert(composer?.visible && composer?.enabled, 'Agent composer is visible and enabled');
    assert(header?.visible && managerButton?.visible, 'Agent header and Manager button are visible');
    assert(shell && shell.scrollWidth <= shell.clientWidth + 1, 'Agent shell has no horizontal overflow');
    await screenshot('01-agent-ready.png');

    // At the normal auxiliary-bar width the <=420px responsive rules should be active.
    assert(shell.width <= 420, 'Agent narrow responsive width is active');
    await screenshot('02-agent-narrow.png');

    await evaluate(`document.querySelector('textarea.pulseai-composer-input').focus()`);
    await cdp.call('Input.insertText', { text: prompt });
    await cdp.call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
    await cdp.call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });

    await waitFor('completed echo turn', `(() => {
      const answer = document.querySelector('.pulseai-assistant-copy')?.textContent || '';
      const receipt = document.querySelector('.pulseai-turn-receipt')?.textContent || '';
      return answer.includes(${JSON.stringify(prompt)}) && receipt.includes('Run completed');
    })()`, 45_000);
    const transcript = await snapshot('completed_transcript', '.pulseai-transcript-lane');
    const answer = await snapshot('assistant_echo', '.pulseai-assistant-copy');
    assert(answer?.text?.includes(prompt), 'Assistant response contains exact echo text');
    assert(transcript?.text?.includes('Run completed'), 'Completed transcript contains completion receipt');
    await screenshot('03-agent-echo-completed.png');

    await evaluate(`document.querySelector('.pulseai-agent-header-actions .pulseai-icon-button').click()`);
    await waitFor('Pulse Manager editor', `Boolean(document.querySelector('.pulseai-manager-shell'))`, 20_000);
    const manager = await snapshot('manager_shell', '.pulseai-manager-shell');
    const managerMain = await snapshot('manager_main', '.pulseai-manager-main');
    assert(manager?.visible && managerMain?.visible, 'Pulse Manager opens as a visible editor surface');
    assert(manager.scrollWidth <= manager.clientWidth + 1, 'Pulse Manager has no horizontal overflow');
    await screenshot('04-manager-wide.png');

    // Exercise the Manager's responsive breakpoint through the actual Electron window.
    try {
      const windowInfo = await cdp.call('Browser.getWindowForTarget', { targetId: target.id });
      report.original_window_bounds = windowInfo.bounds;
      if (windowInfo.bounds?.windowState && windowInfo.bounds.windowState !== 'normal') {
        await cdp.call('Browser.setWindowBounds', { windowId: windowInfo.windowId, bounds: { windowState: 'normal' } });
        await delay(500);
      }
      await cdp.call('Browser.setWindowBounds', { windowId: windowInfo.windowId, bounds: { width: 760, height: 800 } });
      await delay(800);
      const responsive = await evaluate(`(() => {
        const inspector = document.querySelector('.pulseai-manager-inspector');
        const main = document.querySelector('.pulseai-manager-main');
        return { inspectorDisplay: inspector ? getComputedStyle(inspector).display : null, mainWidth: main?.getBoundingClientRect().width || 0 };
      })()`);
      report.snapshots.manager_responsive = responsive;
      assert(responsive?.inspectorDisplay === 'none' && responsive.mainWidth > 0, 'Pulse Manager responsive inspector behavior is active');
      await screenshot('05-manager-responsive.png');
    } catch (error) {
      report.checks['Pulse Manager responsive inspector behavior is active'] = `FAIL: ${error.message}`;
      throw error;
    }

    const protocolErrors = cdp.events.filter(event => event.method === 'Runtime.exceptionThrown' ||
      (event.method === 'Log.entryAdded' && event.params?.entry?.level === 'error'));
    report.console_errors = protocolErrors;
    assert(protocolErrors.length === 0, 'No renderer exceptions or console errors were observed');
    report.overall = 'PASS';
  } catch (error) {
    report.failure = { message: error.message, stack: error.stack };
  } finally {
    report.finished_at = new Date().toISOString();
    fs.writeFileSync(path.join(evidenceDir, 'cdp-ui-result.json'), JSON.stringify(report, null, 2));
    cdp?.close();
  }

  console.log(JSON.stringify({ overall: report.overall, evidenceDir, checks: report.checks }, null, 2));
  if (report.overall !== 'PASS') process.exitCode = 1;
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
