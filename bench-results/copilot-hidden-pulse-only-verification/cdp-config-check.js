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

  // Check context keys
  var contextKeys = await ev(ws,
    "JSON.stringify({" +
    "chatSetupHidden: !!document.querySelector('[class*=\"chat\"]') ? 'exists' : 'no'," +
    "})" +
    "var cs = typeof require !== 'undefined' ? require('vs/platform/contextkey/common/contextkey') : null;" +
    "JSON.stringify({test: true})"
  );
  console.log('Context check:', contextKeys);

  // Check the actual configuration value
  var configValue = await ev(ws,
    "JSON.stringify({" +
    "chatDisableAI: typeof monaco !== 'undefined' ? 'monaco exists' : 'no monaco'," +
    "})"
  );
  console.log('Config:', configValue);

  // Just check what we can see in DOM
  var chatElements = await ev(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('[class*=\"chat\"]')).map(function(e){return {cls:e.className.substring(0,80),visible:e.offsetWidth>0}}).filter(function(e){return e.visible}).slice(0,5))"
  );
  console.log('Visible chat elements:', chatElements);

  // Check the status bar entry specifically
  var statusBar = await ev(ws,
    "JSON.stringify(Array.from(document.querySelectorAll('.statusbar-item')).map(function(e){return {id:e.id,label:(e.querySelector('.statusbar-item-label')||{}).textContent||'',codicon:e.querySelector('[class*=\"codicon\"]')?e.querySelector('[class*=\"codicon\"]').className:''}}).filter(function(e){return /copilot|chat/i.test(e.label+e.codicon+e.id)}))"
  );
  console.log('Copilot status bar:', statusBar);

  ws.close();
  process.exit(0);
}
main().catch(function(e) { console.error(e.message); process.exit(1); });
