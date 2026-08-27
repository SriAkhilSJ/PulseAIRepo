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
    var timeout = setTimeout(function() { reject(new Error('Timeout: ' + method)); }, 10000);
    var handler = function(e) {
      var data = JSON.parse(e.data);
      if (data.id === msgId) {
        clearTimeout(timeout);
        ws.removeEventListener('message', handler);
        if (data.error) reject(new Error(JSON.stringify(data.error)));
        else resolve(data.result);
      }
    };
    ws.addEventListener('message', handler);
    ws.send(JSON.stringify({ id: msgId, method: method, params: params }));
  });
}
async function evaluate(ws, expr) {
  var r = await send(ws, 'Runtime.evaluate', { expression: expr, returnByValue: true });
  return r.result && r.result.value;
}
async function main() {
  var wsUrl = await getWsUrl();
  var ws = new WebSocket(wsUrl);
  await new Promise(function(r) { ws.addEventListener('open', r); });
  await new Promise(function(r) { setTimeout(r, 3000); });

  // Find title bar elements with copilot/sparkle
  var titlebar = await evaluate(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('[class*=\"titlebar\"]')).map(function(e){return {tag:e.tagName,cls:e.className,text:e.textContent.substring(0,50)}}).filter(function(e){return /copilot|sparkle/i.test(e.cls+e.text)}))"
  );
  console.log('Titlebar copilot elements:', titlebar);

  // Check all titlebar children
  var allTitlebar = await evaluate(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('.titlebar .actions-container .action-item')).map(function(e){return {text:(e.textContent||'').substring(0,30),title:e.getAttribute('title')||''}}).slice(0,15))"
  );
  console.log('Titlebar actions:', allTitlebar);

  ws.close();
  process.exit(0);
}
main().catch(function(e) { console.error(e.message); process.exit(1); });
