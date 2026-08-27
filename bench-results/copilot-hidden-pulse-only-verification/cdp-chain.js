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

  // Full ancestor chain of the sparkle element
  var fullChain = await ev(ws,
    "var el = document.querySelector('.agent-status-badge-section.sparkle'); " +
    "var chain = []; " +
    "while (el && el !== document.body) { chain.push({tag:el.tagName,cls:(el.className||'').toString().substring(0,60)}); el = el.parentElement; } " +
    "JSON.stringify(chain)"
  );
  console.log('Full chain:', fullChain);

  // Check if the verification script's selector actually matches
  var matchCount = await ev(ws,
    "document.querySelectorAll('[class*=\"titlebar\"] [class*=\"sparkle\"]').length"
  );
  console.log('Selector match count:', matchCount);

  // List all matched elements with full parent chain
  var matches = await ev(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('[class*=\"titlebar\"] [class*=\"sparkle\"]')).map(function(e){var chain=[];var p=e;while(p&&chain.length<8){chain.push((p.className||'').toString().substring(0,40));p=p.parentElement;}return {cls:e.className.substring(0,60),chain:chain}}))"
  );
  console.log('Matches with chain:', matches);

  ws.close();
  process.exit(0);
}
main().catch(function(e) { console.error(e.message); process.exit(1); });
