const WebSocket = globalThis.WebSocket || require('ws');
const http = require('http');

function getWsUrl() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:9222/json', (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        const targets = JSON.parse(data);
        const target = targets.find(t => t.type === 'page' || t.type === 'window');
        if (target) resolve(target.webSocketDebuggerUrl);
        else reject(new Error('No window target'));
      });
    }).on('error', reject);
  });
}

let id = 1;
function send(ws, method, params = {}) {
  return new Promise((resolve, reject) => {
    const msgId = id++;
    const timeout = setTimeout(() => reject(new Error('Timeout: ' + method)), 15000);
    const handler = (e) => {
      const data = JSON.parse(e.data);
      if (data.id === msgId) {
        clearTimeout(timeout);
        ws.removeEventListener('message', handler);
        if (data.error) reject(new Error(JSON.stringify(data.error)));
        else resolve(data.result);
      }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id: msgId, method, params }));
  });
}

async function evaluate(ws, expression) {
  const r = await send(ws, 'Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: false
  });
  return r.result?.value;
}

async function main() {
  const wsUrl = await getWsUrl();
  const ws = new WebSocket(wsUrl);

  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve);
    ws.addEventListener('error', reject);
  });

  // Wait for workbench to be ready
  await new Promise(r => setTimeout(r, 5000));

  const checks = {};

  // 1. AuxBar: no CHAT tab
  const auxBarText = await evaluate(ws,
    "Array.from(document.querySelectorAll('.activitybar .actions-container .action-item .action-label')).map(function(e){return e.textContent||e.getAttribute('title')||''}).filter(function(t){return t.length>0})"
  );
  checks.auxbar_entries = auxBarText;
  checks.auxbar_no_chat = !auxBarText.some(function(t){ return /chat|copilot/i.test(t); });

  // 2. Watermark: no "Open Chat"
  const watermarkText = await evaluate(ws,
    "document.querySelector('.empty-editor-watermark') ? document.querySelector('.empty-editor-watermark').textContent : 'NOT_FOUND'"
  );
  checks.watermark_text = watermarkText;
  checks.watermark_no_open_chat = !/chat|open chat|ctrl/i.test(watermarkText);

  // 3. Title bar: no VISIBLE Copilot sparkle (hidden-by-CSS elements and Pulse elements excluded)
  const titlebarCopilot = await evaluate(ws,
    "Array.from(document.querySelectorAll('[class*=\"titlebar\"] [class*=\"copilot\"], [class*=\"titlebar\"] [class*=\"sparkle\"]')).some(function(e){return e.offsetWidth>0 && !/pulseai|pulse|agent-status/i.test(e.className)})"
  );
  checks.titlebar_no_copilot_sparkle = !titlebarCopilot;

  // 4. Pulse composer visible
  const pulseComposer = await evaluate(ws,
    "!!document.querySelector('.pulseai-composer') || !!document.querySelector('[class*=\"pulseai\"][class*=\"composer\"]') || !!document.querySelector('[class*=\"pulseai\"][class*=\"view\"]')"
  );
  checks.pulse_composer_visible = pulseComposer;

  // 5. Mode menu present (Agent/Plan/Debug/Ask)
  const modeMenu = await evaluate(ws,
    "Array.from(document.querySelectorAll('[role=\"menuitemradio\"], [role=\"menuitem\"]')).map(function(e){return e.textContent||''}).filter(function(t){return /agent|plan|debug|ask/i.test(t)})"
  );
  checks.mode_menu_entries = modeMenu;
  checks.mode_menu_all_four = ['agent','plan','debug','ask'].every(function(m){
    return modeMenu.some(function(e){ return new RegExp(m, 'i').test(e); });
  });

  // 6. Chat view container hidden
  const chatView = await evaluate(ws,
    "!!document.querySelector('[class*=\"chat-view\"]') || !!document.querySelector('[data-view-id*=\"chat\"]')"
  );
  checks.no_copilot_chat = !chatView;

  // 7. No MCP invoke surface
  const mcpInvoke = await evaluate(ws,
    "!!document.querySelector('[class*=\"mcp-invoke\"]') || !!document.querySelector('[class*=\"mcp\"][class*=\"invoke\"]')"
  );
  checks.no_mcp_invoke = !mcpInvoke;

  // 8. Pulse view in auxiliary bar
  const pulseView = await evaluate(ws,
    "!!document.querySelector('[class*=\"pulseai\"]') || !!document.querySelector('[data-view-id*=\"pulseai\"]')"
  );
  checks.pulse_view_present = pulseView;

  // 9. Screenshot (skip if timeout)
  try {
    const screenshot = await send(ws, 'Page.captureScreenshot', { format: 'png' });
    require('fs').writeFileSync(process.argv[2] + '/01-full-page.png', Buffer.from(screenshot.data, 'base64'));
  } catch(e) {
    console.error('Screenshot skipped:', e.message);
  }

  const result = {
    overall: 'PASS',
    checks: checks,
    timestamp: new Date().toISOString()
  };

  // Determine overall
  for (var key in checks) {
    if (typeof checks[key] === 'boolean' && checks[key] === false) {
      result.overall = 'FAIL';
      result.first_failed_boundary = key;
      break;
    }
  }

  console.log(JSON.stringify(result, null, 2));
  ws.close();
  process.exit(0);
}

main().catch(function(err) {
  console.error('ERROR:', err.message);
  process.exit(1);
});
