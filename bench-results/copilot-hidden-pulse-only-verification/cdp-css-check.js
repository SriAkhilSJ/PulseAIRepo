const WebSocket = globalThis.WebSocket || require('ws');
const http = require('http');
function getWsUrl() {
  return new Promise(function(resolve, reject) {
    http.get('http://127.0.0.1:9222/json', function(res) {
      var data = '';
      res.on('data', function(c) { data += c; });
      res.on('end', function() {
        var targets = JSON.parse(data);
        var target = targets.find(function(t) { return t.type === 'page'; });
        if (target) resolve(target.webSocketDebuggerUrl);
        else reject(new Error('No target'));
      });
    }).on('error', reject);
  });
}
var id = 1;
function send(ws, method, params) {
  params = params || {};
  return new Promise(function(resolve, reject) {
    var msgId = id++;
    var timeout = setTimeout(function() { reject(new Error('Timeout')); }, 10000);
    var handler = function(e) {
      var data = JSON.parse(e.data);
      if (data.id === msgId) { clearTimeout(timeout); ws.removeEventListener('message', handler); resolve(data.result); }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id: msgId, method: method, params: params }));
  });
}
async function ev(ws, expr) {
  var r = await send(ws, 'Runtime.evaluate', { expression: expr, returnByValue: true });
  return r.result && r.result.value;
}
async function main() {
  var wsUrl = await getWsUrl();
  var ws = new WebSocket(wsUrl);
  await new Promise(function(r) { ws.addEventListener('open', r); });
  await new Promise(function(r) { setTimeout(r, 2000); });

  // Check if our CSS rule is applied to the status bar entry
  var statusEntry = await ev(ws,
    "var el = document.querySelector('#chat\\\\.statusBarEntry'); " +
    "if (!el) el = document.getElementById('chat.statusBarEntry'); " +
    "if (!el) el = document.querySelector('[id*=\"chat\"][id*=\"statusBar\"]'); " +
    "JSON.stringify({found: !!el, display: el ? getComputedStyle(el).display : 'N/A', id: el ? el.id : 'N/A', cls: el ? el.className : 'N/A'})"
  );
  console.log('Status entry:', statusEntry);

  // Check open-in-agents
  var agents = await ev(ws,
    "var el = document.querySelector('.open-in-agents-titlebar-widget'); " +
    "JSON.stringify({found: !!el, display: el ? getComputedStyle(el).display : 'N/A', visible: el ? el.offsetWidth > 0 : false})"
  );
  console.log('Open in Agents:', agents);

  // Check copilot codicon
  var copicon = await ev(ws,
    "var els = document.querySelectorAll('.codicon-copilot'); " +
    "JSON.stringify(Array.from(els).map(function(e){return {display:getComputedStyle(e).display,visible:e.offsetWidth>0}}))"
  );
  console.log('Copilot codicons:', copicon);

  ws.close();
  process.exit(0);
}
main().catch(function(e) { console.error(e.message); process.exit(1); });
