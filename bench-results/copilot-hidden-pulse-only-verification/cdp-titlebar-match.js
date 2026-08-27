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

  // Check the specific selector the verification script uses
  var titlebarMatch = await ev(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('[class*=\"titlebar\"] [class*=\"copilot\"], [class*=\"titlebar\"] [class*=\"sparkle\"]')).map(function(e){return {tag:e.tagName,cls:e.className.substring(0,80),visible:e.offsetWidth>0,parentCls:e.parentElement?e.parentElement.className.substring(0,60):''}}))"
  );
  console.log('Titlebar copilot/sparkle matches:', titlebarMatch);

  // Check the parent chain of the sparkle element
  var sparkleChain = await ev(ws,
    "var el = document.querySelector('.agent-status-badge-section.sparkle'); " +
    "var chain = []; " +
    "while (el && chain.length < 5) { chain.push({tag:el.tagName,cls:(el.className||'').substring(0,60)}); el = el.parentElement; } " +
    "JSON.stringify(chain)"
  );
  console.log('Sparkle parent chain:', sparkleChain);

  ws.close();
  process.exit(0);
}
main().catch(function(e) { console.error(e.message); process.exit(1); });
