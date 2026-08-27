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
  await new Promise(function(r) { setTimeout(r, 3000); });

  // Broad search for anything copilot-related in the DOM
  var copilotAll = await ev(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('*')).filter(function(e){return /copilot/i.test(e.className+' '+e.id+' '+(e.getAttribute('aria-label')||''))}).map(function(e){return {tag:e.tagName,cls:e.className.substring(0,80),id:e.id,visible:e.offsetWidth>0}}).slice(0,10))"
  );
  console.log('All copilot elements:', copilotAll);

  // Check for sign-in button specifically
  var signIn = await ev(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('[class*=\"titlebar\"] button, [class*=\"titlebar\"] [role=\"button\"]')).map(function(e){return {text:(e.textContent||'').trim().substring(0,30),title:e.getAttribute('title')||'',cls:e.className.substring(0,60)}}).filter(function(e){return e.text.length>0}))"
  );
  console.log('Titlebar buttons:', signIn);

  // Check auxiliary bar specifically for chat
  var auxbar = await ev(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('.activitybar .action-item')).map(function(e){return {label:(e.querySelector('.action-label')||{}).textContent||'',title:e.getAttribute('title')||''}}))"
  );
  console.log('AuxBar items:', auxbar);

  ws.close();
  process.exit(0);
}
main().catch(function(e) { console.error(e.message); process.exit(1); });
