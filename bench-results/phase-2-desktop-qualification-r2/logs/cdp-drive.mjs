// Bounded CDP driver for Phase 2 desktop qualification.
// Usage: node cdp-drive.mjs '<json-command>'
// Commands: {op:"eval",js:"..."} | {op:"screenshot",path:"..."} |
//           {op:"press",key:"Control+l"} | {op:"type",text:"..."} |
//           {op:"click",selector:"..."} | {op:"wait",ms:1000} |
//           {op:"state"} | {op:"logs"}
import { createRequire } from 'node:module';
const require = createRequire((process.env.CRUSORAI_REPO_ROOT || '.') + '/desktop/vscode/package.json');
const { chromium } = require('playwright');

const raw = process.env.CDP_CMD || process.argv[2] || '{"op":"state"}';
const cmd = JSON.parse(raw);
const collected = [];

const port = process.env.CDP_PORT || '9222';
const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 30000 });
const contexts = browser.contexts();
const ctx = contexts[0];
const page = ctx.pages()[0];
page.on('console', m => collected.push({ type: m.type(), text: m.text().slice(0, 4000) }));
page.on('pageerror', e => collected.push({ type: 'pageerror', text: String(e).slice(0, 4000) }));

let result;
try {
    switch (cmd.op) {
        case 'eval':
            result = await page.evaluate(cmd.js);
            break;
        case 'screenshot':
            await page.screenshot({ path: cmd.path });
            result = { path: cmd.path };
            break;
        case 'press':
            await page.keyboard.press(cmd.key);
            result = { pressed: cmd.key };
            break;
        case 'type':
            await page.keyboard.type(cmd.text, { delay: cmd.delay ?? 20 });
            result = { typed: cmd.text };
            break;
        case 'click':
            await page.click(cmd.selector, { timeout: cmd.timeout ?? 10000 });
            result = { clicked: cmd.selector };
            break;
        case 'wait':
            await page.waitForTimeout(cmd.ms ?? 1000);
            result = { waited: cmd.ms ?? 1000 };
            break;
        case 'state':
        default:
            result = await page.evaluate(() => ({
                title: document.title,
                url: location.href,
                ready: document.readyState,
                parts: ['.monaco-workbench', '.part.titlebar', '.part.activitybar', '.part.sidebar', '.part.editor', '.part.statusbar', '.part.panel']
                    .map(s => [s, Boolean(document.querySelector(s))]),
            }));
            break;
    }
} catch (error) {
    result = { error: String(error) };
}
console.log(JSON.stringify({ result, collected }, null, 2));
await browser.close();
