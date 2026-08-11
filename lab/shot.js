const puppeteer = require('C:/Users/Administrator/AppData/Roaming/npm/node_modules/@modelcontextprotocol/server-puppeteer/node_modules/puppeteer');
(async () => {
  const browser = await puppeteer.launch({ headless: true, args: ['--no-sandbox', '--disable-gpu'] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  await page.goto('http://localhost:61264', { waitUntil: 'networkidle2', timeout: 90000 });
  await new Promise(r => setTimeout(r, 6000)); // let the Spline 3D scene mount
  await page.screenshot({ path: 'D:/pulseAIrepo/PulseAIRepo/docs/lab-spline-demo.png' });
  await browser.close();
  console.log('saved');
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
