#!/usr/bin/env node
/* Provider-free Manager Skills tab smoke over raw Chrome DevTools Protocol.
 *
 * Verifies the Phase 2 desktop slice end-to-end against the RUNNING app:
 *   - Manager opens and the tab-state model works (Session <-> Skills)
 *   - the Skills tab paints the live list from the bridge (skills_hub_op)
 *   - the "what the model sees" pane shows the ENGINE's skills manifest
 *   - a toggle round trip crosses renderer -> service -> bridge -> engine
 *     and comes back (and the original enabled state is restored)
 *
 * Usage: node scripts/verify_manager_skills_tab_cdp.js <evidence-dir>
 * The app must be running with --remote-debugging-port=9222.
 * Zero provider requests: no prompt is ever submitted.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const port = Number(process.env.CRUSORAI_CDP_PORT || '9222');
const evidenceDir = path.resolve(process.argv[2] || `bench-results/skills-tab-verification-${new Date().toISOString().replace(/[:.]/g, '-')}`);
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

async function listTargets() {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function waitForEndpoint(timeoutMs = 90_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const targets = await listTargets();
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
    checks: {},
    snapshots: {},
    console_errors: [],
    screenshots: [],
    overall: 'FAIL',
  };
  let origCdp;
  let managerCdp;
  let originalToggle; // { rowName, badge } for best-effort restore

  const clientFor = async cdp => {
    const evaluateRaw = async (client, expression) => {
      const response = await client.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
      if (response.exceptionDetails) throw new Error(response.exceptionDetails.text || 'Runtime.evaluate failed');
      return response.result?.value;
    };
    return {
      evaluate: expression => evaluateRaw(cdp, expression),
      waitFor: async (description, expression, timeoutMs = 30_000) => {
        const deadline = Date.now() + timeoutMs;
        let value;
        while (Date.now() < deadline) {
          value = await evaluateRaw(cdp, expression);
          if (value) return value;
          await delay(250);
        }
        throw new Error(`Timed out waiting for ${description}`);
      },
    };
  };

  const assert = (condition, message) => {
    if (!condition) throw new Error(message);
    report.checks[message] = 'PASS';
  };

  const findManagerSurface = async origClient => {
    // The Manager may mount in-page (editor mode) or in an auxiliary window
    // (separate target). Probe both; return { cdp, scope }.
    const origHelpers = await clientFor(origClient);
    if (await origHelpers.evaluate(`Boolean(document.querySelector('.crusorai-manager-shell'))`)) {
      return { cdp: origClient, scope: 'same-page' };
    }
    const deadline = Date.now() + 25_000;
    const probed = new Set();
    while (Date.now() < deadline) {
      const targets = await listTargets();
      for (const target of targets) {
        if (target.type !== 'page' || !target.webSocketDebuggerUrl
          || target.webSocketDebuggerUrl === origClient.url || probed.has(target.id)) continue;
        probed.add(target.id);
        let probe;
        try {
          probe = new CdpClient(target.webSocketDebuggerUrl);
          await probe.connect();
          const response = await probe.call('Runtime.evaluate', {
            expression: `Boolean(document.querySelector('.crusorai-manager-shell'))`,
            returnByValue: true,
          }, 8_000);
          if (response.result?.value) return { cdp: probe, scope: `target:${target.title || target.id}` };
          probe.close();
        } catch { probe?.close(); }
      }
      await delay(750);
    }
    return undefined;
  };

  try {
    const target = await waitForEndpoint();
    report.target = { id: target.id, title: target.title, url: target.url };
    origCdp = new CdpClient(target.webSocketDebuggerUrl);
    await origCdp.connect();
    await Promise.all([origCdp.call('Runtime.enable'), origCdp.call('Log.enable')]);
    const orig = await clientFor(origCdp);

    // Open/focus Crusor using its registered Windows keybinding (same trick
    // as validate_crusor_ui_cdp.js — the composer only exists once the view
    // is mounted).
    await origCdp.call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'l', code: 'KeyL', modifiers: 2, windowsVirtualKeyCode: 76, nativeVirtualKeyCode: 76 });
    await origCdp.call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'l', code: 'KeyL', modifiers: 2, windowsVirtualKeyCode: 76, nativeVirtualKeyCode: 76 });

    await orig.waitFor('Crusor composer', `Boolean(document.querySelector('textarea.crusorai-composer-input'))`, 45_000);
    report.checks['Agent composer present (main window ready)'] = 'PASS';

    // Open the Manager through the Agent header button (host.openManager).
    await orig.evaluate(`(() => {
      const btn = document.querySelector('.crusorai-agent-manager-button');
      if (btn) btn.click();
      return Boolean(btn);
    })()`) || assert(false, 'Agent header Manager button exists');

    const surface = await findManagerSurface(origCdp);
    assert(surface, 'Crusor Manager surface opened (editor or auxiliary window)');
    if (surface.cdp !== origCdp) { managerCdp = surface.cdp; }
    const manager = await clientFor(managerCdp || origCdp);
    report.snapshots.manager_scope = surface.scope;

    await manager.waitFor('Manager shell', `Boolean(document.querySelector('.crusorai-manager-shell'))`, 20_000);
    const tabs = await manager.evaluate(`Array.from(document.querySelectorAll('.crusorai-manager-tabs button')).map(b => ({ text: b.textContent.trim(), active: b.classList.contains('is-active') }))`);
    report.snapshots.tabs = tabs;
    assert(tabs.length === 4, 'Manager renders four tabs (Session / Tools / Changes / Skills)');
    assert(tabs[0].text.startsWith('Session') && tabs[0].active, 'Session is the default active tab');

    // --- Switch to the Skills tab ---
    const clicked = await manager.evaluate(`(() => {
      const btn = Array.from(document.querySelectorAll('.crusorai-manager-tabs button')).find(b => b.textContent.trim().startsWith('Skills'));
      if (btn) btn.click();
      return Boolean(btn);
    })()`);
    assert(clicked, 'Skills tab button exists and was clicked');
    await manager.waitFor('Skills pane', `Boolean(document.querySelector('.crusorai-skills-pane'))`, 10_000);
    report.checks['Skills tab renders its pane'] = 'PASS';

    const probeExpr = `(() => {
      const pane = document.querySelector('.crusorai-skills-pane');
      if (!pane) return null;
      return {
        rows: pane.querySelectorAll('.crusorai-skill-row').length,
        loading: /Loading the installed skills|Refreshing…/.test(pane.textContent || ''),
        error: pane.querySelector('.crusorai-error-row')?.textContent || null,
        hasManifestHead: /WHAT THE MODEL SEES/.test(pane.textContent || ''),
        manifestIndex: /=== SKILLS INDEX ===/.test(pane.textContent || ''),
        manifestEmpty: /No skills are enabled/.test(pane.textContent || ''),
        summary: pane.querySelector('.crusorai-skills-summary')?.textContent || '',
      };
    })()`;

    // The pane paints instantly; the three bridge ops land async. Wait for
    // the loading state to settle before judging rows/manifest content.
    await manager.waitFor('skills data loaded', `(() => {
      const pane = document.querySelector('.crusorai-skills-pane');
      if (!pane) return false;
      if (/Loading the installed skills|Refreshing…/.test(pane.textContent || '')) return false;
      return /WHAT THE MODEL SEES/.test(pane.textContent || '');
    })()`, 25_000);

    let loaded = await manager.evaluate(probeExpr);
    // The pane talks to the engine; tolerate a slow/erroring first boot via Refresh.
    for (let attempt = 0; attempt < 4 && loaded && loaded.error; attempt++) {
      await manager.evaluate(`(() => { const b = Array.from(document.querySelectorAll('.crusorai-skills-refresh')).find(x => !x.disabled); if (b) b.click(); })()`);
      await manager.waitFor(`skills reload ${attempt}`, `(() => {
        const pane = document.querySelector('.crusorai-skills-pane');
        if (!pane) return false;
        return !/Loading the installed skills|Refreshing…/.test(pane.textContent || '');
      })()`, 20_000);
      loaded = await manager.evaluate(probeExpr);
    }
    report.snapshots.skills_pane = loaded;
    assert(loaded && loaded.hasManifestHead, 'Skills pane shows the "what the model sees" section (engine manifest op)');
    assert(!loaded.error, `Skills list loaded from the bridge without error (${loaded.error || 'clean'})`);
    assert(loaded.rows >= 1, `Live skill rows rendered (${loaded.rows} row(s))`);
    assert(loaded.manifestIndex || loaded.manifestEmpty, `Manifest content present (${loaded.manifestIndex ? 'SKILLS INDEX' : 'empty-state'})`);

    // --- Toggle round trip: renderer -> service -> bridge -> engine -> back ---
    originalToggle = await manager.evaluate(`(() => {
      const rows = Array.from(document.querySelectorAll('.crusorai-skill-row'));
      const row = rows.find(r => r.querySelector('.crusorai-skill-name'));
      if (!row) return null;
      const name = row.querySelector('.crusorai-skill-name').textContent.trim();
      const badge = row.querySelector('.crusorai-skill-badge')?.textContent.trim() || '';
      const btn = Array.from(row.querySelectorAll('.crusorai-skill-action')).find(b => /^(Enable|Disable)$/.test(b.textContent.trim()));
      if (btn) btn.click();
      return { name, badge, clicked: Boolean(btn) };
    })()`);
    assert(originalToggle?.clicked, `Toggle clicked for "${originalToggle?.name}" (was ${originalToggle?.badge})`);
    const flipped = await manager.waitFor('toggle result', `(() => {
      const rows = Array.from(document.querySelectorAll('.crusorai-skill-row'));
      const row = rows.find(r => r.querySelector('.crusorai-skill-name')?.textContent.trim() === ${JSON.stringify(originalToggle.name)});
      if (!row) return false;
      const badge = row.querySelector('.crusorai-skill-badge')?.textContent.trim() || '';
      const busy = Boolean(row.querySelector('.crusorai-skill-busy'));
      return !busy && badge !== ${JSON.stringify(originalToggle.badge)};
    })()`, 20_000);
    assert(flipped, `Enabled badge flipped live for "${originalToggle.name}"`);
    report.snapshots.toggle = { ...originalToggle, flipped_to: await manager.evaluate(`(() => {
      const row = Array.from(document.querySelectorAll('.crusorai-skill-row')).find(r => r.querySelector('.crusorai-skill-name')?.textContent.trim() === ${JSON.stringify(originalToggle.name)});
      return row?.querySelector('.crusorai-skill-badge')?.textContent.trim();
    })()`) };

    // Restore the original enabled state IMMEDIATELY — still on the Skills
    // pane, where the row exists — and prove the second round trip too.
    const restoreClick = await manager.evaluate(`(() => {
      const row = Array.from(document.querySelectorAll('.crusorai-skill-row')).find(r => r.querySelector('.crusorai-skill-name')?.textContent.trim() === ${JSON.stringify(originalToggle.name)});
      if (!row) return 'gone';
      const btn = Array.from(row.querySelectorAll('.crusorai-skill-action')).find(b => /^(Enable|Disable)$/.test(b.textContent.trim()));
      if (btn) { btn.click(); return 'clicked'; }
      return 'no-button';
    })()`);
    report.snapshots.toggle_restore = restoreClick;
    const restored = await manager.waitFor('toggle restore', `(() => {
      const row = Array.from(document.querySelectorAll('.crusorai-skill-row')).find(r => r.querySelector('.crusorai-skill-name')?.textContent.trim() === ${JSON.stringify(originalToggle.name)});
      if (!row) return false;
      const badge = row.querySelector('.crusorai-skill-badge')?.textContent.trim() || '';
      const busy = Boolean(row.querySelector('.crusorai-skill-busy'));
      return !busy && badge === ${JSON.stringify(originalToggle.badge)};
    })()`, 20_000);
    assert(restored, `Original enabled state restored for "${originalToggle.name}" (round trip 2)`);

    // --- Back to Session: tab-state round trip ---
    await manager.evaluate(`(() => {
      const btn = Array.from(document.querySelectorAll('.crusorai-manager-tabs button')).find(b => b.textContent.trim().startsWith('Session'));
      if (btn) btn.click();
      return Boolean(btn);
    })()`);
    await manager.waitFor('Session column restored', `!document.querySelector('.crusorai-skills-pane') && Boolean(document.querySelector('.crusorai-manager-tabs button.is-active'))`, 10_000);
    const activeAfter = await manager.evaluate(`document.querySelector('.crusorai-manager-tabs button.is-active')?.textContent.trim() || ''`);
    assert(activeAfter.startsWith('Session'), `Session tab is active again (was "${activeAfter}")`);
    report.checks['Tab-state round trip Session <-> Skills'] = 'PASS';

    const protocolErrors = (origCdp.events.concat(managerCdp ? managerCdp.events : []))
      .filter(event => event.method === 'Runtime.exceptionThrown'
        || (event.method === 'Log.entryAdded' && event.params?.entry?.level === 'error'));
    report.console_errors = protocolErrors.slice(0, 10);
    assert(protocolErrors.length === 0, 'No renderer exceptions or console errors observed');

    // Screenshot is evidence garnish — never the reason a check fails
    // (the 2026-08-27 run died on Page.captureScreenshot timeouts).
    if (managerCdp) {
      try {
        await managerCdp.call('Page.enable');
        const shot = await managerCdp.call('Page.captureScreenshot', { format: 'png' }, 15_000);
        fs.writeFileSync(path.join(evidenceDir, 'skills-tab.png'), Buffer.from(shot.data, 'base64'));
        report.screenshots.push('skills-tab.png');
      } catch (error) { report.snapshots.screenshot_error = error.message; }
    }

    report.overall = 'PASS';
  } catch (error) {
    report.failure = { message: error.message, stack: error.stack };
  } finally {
    // Best-effort state restore: re-open nothing, just flip back if we know
    // the original badge and the surface is still reachable.
    try {
      if (originalToggle && (managerCdp || origCdp)) {
        const helper = await clientFor(managerCdp || origCdp);
        await helper.evaluate(`(() => {
          const row = Array.from(document.querySelectorAll('.crusorai-skill-row')).find(r => r.querySelector('.crusorai-skill-name')?.textContent.trim() === ${JSON.stringify(originalToggle.name)});
          if (!row) return false;
          const badge = row.querySelector('.crusorai-skill-badge')?.textContent.trim() || '';
          if (badge === ${JSON.stringify(originalToggle.badge)}) return true;
          const btn = Array.from(row.querySelectorAll('.crusorai-skill-action')).find(b => /^(Enable|Disable)$/.test(b.textContent.trim()));
          if (btn) { btn.click(); return true; }
          return false;
        })()`);
      }
    } catch { /* surface may be gone — originalToggle is recorded in the report */ }
    report.finished_at = new Date().toISOString();
    fs.writeFileSync(path.join(evidenceDir, 'cdp-skills-tab-result.json'), JSON.stringify(report, null, 2));
    managerCdp?.close();
    origCdp?.close();
  }

  console.log(JSON.stringify({ overall: report.overall, evidenceDir, checks: report.checks }, null, 2));
  if (report.overall !== 'PASS') process.exitCode = 1;
}

main().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
