// One-off: dump live workbench DOM state for diagnosis.
const PORT = Number(process.env.CDP_PORT || 9222);
(async () => {
  const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
  const ts = await res.json();
  const t = ts.find(x => x.type === 'page' && /workbench.*\.html/.test(x.url || ''));
  if (!t) { console.log('NO TARGET'); process.exit(1); }
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  let id = 1;
  const p = new Map();
  ws.addEventListener('message', e => {
    const m = JSON.parse(String(e.data));
    if (m.id && p.has(m.id)) { const s = p.get(m.id); p.delete(m.id); m.error ? s.rej(new Error(JSON.stringify(m.error))) : s.res(m.result || {}); }
  });
  await new Promise((res2, rej) => { ws.addEventListener('open', res2, { once: true }); ws.addEventListener('error', () => rej(new Error('ws err')), { once: true }); });
  const call = (method, params = {}) => new Promise((res2, rej) => { const i = id++; p.set(i, { res: res2, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
  const expr = `(() => ({
    workbench: !!document.querySelector('.monaco-workbench'),
    bodyLen: (document.body.innerText || '').length,
    bodyHead: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 500),
    crusoraiEls: document.querySelectorAll('[class*=crusorai]').length,
    engineStatus: !!document.querySelector('.crusorai-engine-status'),
    agentHeader: !!document.querySelector('.crusorai-agent-header'),
    quickOpen: !!document.querySelector('.quick-input-widget'),
    quickOpenHidden: document.querySelector('.quick-input-widget')?.classList.contains('hidden') ?? null,
    dialogs: [...document.querySelectorAll('.monaco-dialog-box')].map(d => (d.textContent || '').replace(/\\s+/g, ' ').slice(0, 150)),
    activityBar: document.querySelectorAll('.activitybar .action-label, .activitybar .monaco-action-bar .action-label').length,
    titles: [...document.querySelectorAll('.pane-header .title, .composite.title, .view-title')].map(x => (x.textContent || '').trim()).slice(0, 10),
    focused: document.activeElement ? (document.activeElement.className || document.activeElement.tagName) : null,
  }))()`;
  const r = await call('Runtime.evaluate', { expression: expr, returnByValue: true });
  console.log(JSON.stringify(r.result?.value ?? r, null, 2));
  ws.close();
})().catch(e => { console.error('ERR', e); process.exit(1); });
