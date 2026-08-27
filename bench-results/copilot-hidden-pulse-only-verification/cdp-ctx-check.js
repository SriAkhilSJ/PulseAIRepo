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

  // Check the chat view container - is it in auxiliary bar or hidden?
  var chatContainer = await ev(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('[class*=\"activity\"]')).filter(function(e){return /copilot|chat/i.test(e.className)}).map(function(e){return {cls:e.className.substring(0,100),visible:e.offsetWidth>0,display:getComputedStyle(e).display}}))"
  );
  console.log('Chat containers:', chatContainer);

  // Check status bar
  var statusbar = await ev(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('[id*=\"chat\"]')).map(function(e){return {id:e.id,cls:e.className.substring(0,60),visible:e.offsetWidth>0}}))"
  );
  console.log('Chat status elements:', statusbar);

  // Check auxbar items with more detail
  var auxDetail = await ev(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('.activitybar .action-item')).map(function(e){var lbl=e.querySelector('.action-label');return {title:e.getAttribute('title')||'',cls:lbl?lbl.className.substring(0,80):'',badge:(e.querySelector('.badge')||{}).textContent||''}}))"
  );
  console.log('AuxBar detail:', auxDetail);

  ws.close();
  process.exit(0);
}
main().catch(function(e) { console.error(e.message); process.exit(1); });
