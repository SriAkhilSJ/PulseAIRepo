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

  // Check the status bar entry's visibility condition
  // The entry checks sentiment.hidden which reads from chatSetupHidden context key
  // Let's check if the status bar entry's update method would hide it
  var statusCheck = await ev(ws,
    "JSON.stringify({" +
    "hasStatusBarEntry: !!document.querySelector('#chat.statusBarEntry')," +
    "statusBarVisible: document.querySelector('#chat.statusBarEntry') ? document.querySelector('#chat.statusBarEntry').offsetWidth > 0 : false," +
    "chatViewGone: !document.querySelector('[class*=\"activity-workbench-view-extension-copilot-chat\"]')," +
    "auxBarChatIcon: !!document.querySelector('.activitybar [class*=\"copilot-chat\"]')" +
    "})"
  );
  console.log('Status check:', statusCheck);

  ws.close();
  process.exit(0);
}
main().catch(function(e) { console.error(e.message); process.exit(1); });
