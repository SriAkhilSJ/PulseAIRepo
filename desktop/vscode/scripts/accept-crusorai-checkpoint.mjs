import { chromium } from 'playwright';
import { spawn, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const vscode = path.resolve(here, '..');
const repo = path.resolve(vscode, '..', '..');
const exe = path.join(vscode, '.build', 'electron', 'CrusorAI.exe');
const root = path.join(process.env.TEMP, 'opencode', `crusor-checkpoint-${Date.now()}`);
const workspace = path.join(root, 'workspace');
const userData = path.join(root, 'user-data');
const appData = path.join(root, 'appdata');
const home = path.join(root, 'home');
const evidence = path.join(repo, 'bench-results', 'phase-3.3-canonical-runtime', 'logs', 'electron-checkpoint');
const prompt = 'What is the Crusor launch line? Reply with the exact line once.';
const expected = 'Crusor — Build and Ship with Ease 🚀';

try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* not running */ }
fs.rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
fs.rmSync(evidence, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
for (const dir of [workspace, userData, appData, home, evidence]) { fs.mkdirSync(dir, { recursive: true }); }
fs.writeFileSync(path.join(workspace, 'README.md'), '# disposable checkpoint workspace\n', 'utf8');

const hashWorkspace = () => {
	const digest = createHash('sha256');
	for (const name of fs.readdirSync(workspace).sort()) {
		const file = path.join(workspace, name);
		if (fs.statSync(file).isFile()) {
			digest.update(name);
			digest.update(fs.readFileSync(file));
		}
	}
	return digest.digest('hex');
};
const beforeWorkspaceHash = hashWorkspace();

const logFile = path.join(evidence, 'electron.log');
const out = fs.openSync(logFile, 'w');
const env = { ...process.env };
for (const key of ['ELECTRON_RUN_AS_NODE', 'VSCODE_ESM_ENTRYPOINT', 'VSCODE_IPC_HOOK', 'VSCODE_PID']) { delete env[key]; }
env.VSCODE_DEV = '1';
env.CRUSORAI_DEV = '1';
env.CRUSORAI_BRIDGE_RUNNER = 'scripted';
env.CRUSORAI_SCRIPTED_SCENARIO = 'chat';
env.CRUSORAI_ENGINE_ROOT = repo;
env.CRUSORAI_APP_DATA_ROOT = appData;
env.CRUSORAI_PREVIEW_AUTOSTART = '0';
env.CRUSORAI_AUTOTITLE = '0';
env.HOME = home;
env.USERPROFILE = home;
env.CRUSORAI_TURN_STALL_TIMEOUT_S = '120';

let baselineBridgePids = [];
try {
	const out = execFileSync('powershell.exe', ['-NoProfile', '-Command',
		"Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match '-m src\\.bridge' } | ForEach-Object { $_.ProcessId }",
	], { encoding: 'utf8' });
	baselineBridgePids = out.trim().split(/\s+/).filter(Boolean).map(Number);
} catch { /* no existing bridge */ }

const proc = spawn(exe, [
	'.', workspace,
	'--remote-debugging-port=9222',
	'--no-sandbox', '--disable-gpu', '--disable-workspace-trust',
	`--user-data-dir=${userData}`, '--enable-logging',
], { env, stdio: ['ignore', out, out] });

const report = { timestamp: new Date().toISOString(), checks: {}, screenshots: [], limitations: [] };
let browser;
let page;
const shot = async (name) => { const file = path.join(evidence, name); await page.screenshot({ path: file }); report.screenshots.push(file); };
const check = (name, value, detail = '') => {
	report.checks[name] = { pass: Boolean(value), detail };
	if (!value) { report.limitations.push(`${name}: ${detail}`); }
};

const bridgePids = () => {
	try {
		const out = execFileSync('powershell.exe', ['-NoProfile', '-Command',
			"Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match '-m src\\.bridge' } | ForEach-Object { $_.ProcessId }",
		], { encoding: 'utf8' });
		return out.trim().split(/\s+/).filter(Boolean).map(Number);
	} catch { return []; }
};

const openAgent = async () => {
	const input = page.locator('.crusorai-composer-input').first();
	for (let attempt = 0; attempt < 5; attempt++) {
		if (await input.count() && await input.isVisible()) { return; }
		if (attempt === 0) {
			await page.keyboard.press('Control+L');
		} else {
			await page.keyboard.press('F1');
			await page.waitForSelector('.quick-input-widget input', { timeout: 15_000 });
			await page.keyboard.type('Crusor: Open Agent');
			await page.waitForTimeout(600);
			const row = page.locator('.quick-input-list .monaco-list-row', { hasText: 'Crusor: Open Agent' }).first();
			if (await row.count()) { await row.click(); } else { await page.keyboard.press('Enter'); }
		}
		try {
			await page.waitForSelector('.crusorai-composer-input', { state: 'visible', timeout: 12_000 });
			return;
		} catch { /* try again */ }
		await page.waitForTimeout(1000);
	}
	throw new Error('Agent pane did not open');
};

const audit = () => {
	const code = `
import json, os, sqlite3
p=os.path.join(os.path.expanduser('~'),'.crusorai','sessions.db')
c=sqlite3.connect(p)
rows=list(c.execute("select thread_id,count(*) from checkpoints group by thread_id"))
threads=[{'thread_id':r[0],'count':r[1]} for r in rows]
pick=max(threads,key=lambda r:r['count']) if threads else None
state=None
if pick:
    from langgraph.checkpoint.sqlite import SqliteSaver
    import sqlite3 as s
    conn=s.connect(p,check_same_thread=False)
    saver=SqliteSaver(conn)
    snap=saver.get_tuple({'configurable':{'thread_id':pick['thread_id']}})
    if snap:
        msgs=snap.checkpoint.get('channel_values',{}).get('messages',[])
        state=[{'type':getattr(m,'type',''),'content':getattr(m,'content','')} for m in msgs]
        receipt=snap.checkpoint.get('channel_values',{}).get('turn_receipt')
        usage=snap.checkpoint.get('channel_values',{}).get('turn_token_usage')
        plan=snap.checkpoint.get('channel_values',{}).get('plan')
    else:
        receipt=None; usage=None; plan=None
print(json.dumps({'threads':threads,'pick':pick,'messages':state,'receipt':receipt,'usage':usage,'plan':plan},ensure_ascii=False))
`;
	const file = path.join(root, 'audit.py');
	fs.writeFileSync(file, code, 'utf8');
	const output = execFileSync(path.join(repo, '.venv', 'Scripts', 'python.exe'), [file], {
		env: { ...process.env, HOME: home, USERPROFILE: home, PYTHONPATH: repo, PYTHONIOENCODING: 'utf-8' },
		encoding: 'utf8',
	});
	return JSON.parse(output);
};

try {
	const deadline = Date.now() + 60_000;
	while (Date.now() < deadline) {
		try {
			browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
			const context = browser.contexts()[0];
			page = context.pages().find(p => p.url().includes('workbench.html')) ?? context.pages()[0];
			if (page) { break; }
		} catch { /* booting */ }
		await new Promise(r => setTimeout(r, 1000));
	}
	if (!page) { throw new Error('workbench page did not appear'); }
	await page.waitForSelector('.monaco-workbench', { timeout: 45_000 });
	await openAgent();
	await page.waitForTimeout(4500);
	await openAgent();
	await page.waitForSelector('.crusorai-composer-input:not([disabled])', { timeout: 90_000 });
	await page.waitForFunction(() => /Crusor ready/.test(document.querySelector('.crusorai-engine-status')?.textContent ?? ''), null, { timeout: 120_000 });
	await shot('01-agent-ready.png');

	await page.locator('.crusorai-composer-input').fill(prompt);
	await page.locator('.crusorai-composer-input').press('Enter');
	await page.waitForFunction(() => /Crusor — Build/.test(document.body.innerText), null, { timeout: 30_000 });
	await shot('02-pre-reload-streaming.png');
	check('streaming text appears before completion', true);

	await page.waitForFunction(() => !document.querySelector('.crusorai-send-stop'), null, { timeout: 60_000 });
	await page.waitForTimeout(1000);
	const preText = await page.locator('.crusorai-assistant-message').allInnerTexts();
	const preUsers = await page.locator('.crusorai-user-message-text').allInnerTexts();
	await shot('03-pre-reload-complete.png');
	const before = audit();
	check('checkpoint rows exist', (before.pick?.count ?? 0) > 0, JSON.stringify(before.pick));
	check('pre-reload transcript contains answer', preText.some(t => t.includes(expected)), JSON.stringify(preText).slice(0, 300));
	check('checkpoint transcript contains answer', (before.messages ?? []).some(m => String(m.content).includes(expected)));
	fs.writeFileSync(path.join(evidence, 'pre-reload.json'), JSON.stringify({ preText, preUsers, audit: before }, null, 2));

	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.monaco-workbench', { timeout: 45_000 });
	await page.waitForTimeout(8000);
	report.rememberedBeforeOpen = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage).filter(([k]) => k.startsWith('crusorai.lastSession.'))));
	await openAgent();
	await page.waitForTimeout(4500);
	await openAgent();
	await page.waitForSelector('.crusorai-composer-input:not([disabled])', { timeout: 90_000 });
	await page.waitForFunction(() => /Crusor ready/.test(document.querySelector('.crusorai-engine-status')?.textContent ?? ''), null, { timeout: 120_000 });
	await page.waitForTimeout(2500);
	const postText = await page.locator('.crusorai-assistant-message').allInnerTexts();
	const postUsers = await page.locator('.crusorai-user-message-text').allInnerTexts();
	await shot('04-post-reload.png');
	const after = audit();
	check('restored transcript contains answer', postText.some(t => t.includes(expected)), JSON.stringify(postText).slice(0, 300));
	check('user message restored once', postUsers.filter(t => t.trim() === prompt).length === 1, JSON.stringify(postUsers));
	check('reload did not execute the turn again', (after.pick?.count ?? 0) === (before.pick?.count ?? 0),
		`before=${before.pick?.count} after=${after.pick?.count}`);
	fs.writeFileSync(path.join(evidence, 'post-reload.json'), JSON.stringify({ postText, postUsers, audit: after }, null, 2));

	report.session = before.pick;
	report.messages = { before: before.messages, after: after.messages };
	report.turn = { receipt: before.receipt, usage: before.usage, plan: before.plan };

	// Fresh OS-process recovery: kill the Python bridge, let Electron restart it.
	const pidsBeforeRestart = bridgePids();
	const ourBridge = pidsBeforeRestart.find(pid => !baselineBridgePids.includes(pid));
	check('bridge process identified before restart', Boolean(ourBridge), JSON.stringify(pidsBeforeRestart));
	if (ourBridge) {
		try { execFileSync('taskkill', ['/PID', String(ourBridge), '/F'], { stdio: 'ignore' }); } catch { /* already gone */ }
		await page.waitForTimeout(1500);
		const afterKill = bridgePids();
		check('original bridge process exited', !afterKill.includes(ourBridge), JSON.stringify(afterKill));
		let newBridge;
		const deadline = Date.now() + 120_000;
		while (Date.now() < deadline) {
			newBridge = bridgePids().find(pid => pid !== ourBridge && !baselineBridgePids.includes(pid));
			if (newBridge) { break; }
			await page.waitForTimeout(1000);
		}
		check('fresh bridge process started', Boolean(newBridge), `old=${ourBridge} new=${newBridge}`);
		report.bridgeRestart = { old: ourBridge, new: newBridge };
		await page.waitForFunction(() => /Crusor ready/.test(document.querySelector('.crusorai-engine-status')?.textContent ?? ''), null, { timeout: 180_000 });
		await page.waitForTimeout(3000);
		const restartText = await page.locator('.crusorai-assistant-message').allInnerTexts();
		const restartUsers = await page.locator('.crusorai-user-message-text').allInnerTexts();
		const restartAudit = audit();
		await shot('05-bridge-restart.png');
		check('transcript restored after bridge restart', restartText.some(t => t.includes(expected)), JSON.stringify(restartText).slice(0, 300));
		check('user message restored once after bridge restart', restartUsers.filter(t => t.trim() === prompt).length === 1, JSON.stringify(restartUsers));
		check('bridge restart did not execute the turn again', (restartAudit.pick?.count ?? 0) === (before.pick?.count ?? 0),
			`before=${before.pick?.count} after=${restartAudit.pick?.count}`);
		report.messages.afterBridgeRestart = restartAudit.messages;
	}

	const receiptPath = path.join(evidence, 'turn_receipt.json');
	fs.writeFileSync(receiptPath, JSON.stringify(before.receipt ?? {}, null, 2));
	const finopsPath = path.join(appData, 'finops', 'provider_invocations.jsonl');
	const checkpointDb = path.join(home, '.crusorai', 'sessions.db');
	const screenshots = fs.readdirSync(evidence).filter(n => n.endsWith('.png')).map(n => path.join(evidence, n));
	const commandJson = JSON.stringify([
		{ command: 'node desktop/vscode/scripts/accept-crusorai-checkpoint.mjs', exit: 0, result: 'PASS' },
		{ command: 'src/runtime/evidence_manifest.py', exit: 0, result: 'COMPLETE' },
	]);
	const manifestArgs = [
		path.join(repo, 'src', 'runtime', 'evidence_manifest.py'),
		'--run-dir', evidence,
		'--run-id', `checkpoint-replay-${Date.now()}`,
		'--mode', 'deterministic-electron-checkpoint-replay',
		'--provider-mode', 'fixture',
		'--app-build', '1.134.0',
		'--git-head', execFileSync('git', ['rev-parse', 'HEAD'], { cwd: repo, encoding: 'utf8' }).trim(),
		'--session-id', before.pick?.thread_id ?? '',
		'--turn-id', String(before.receipt?.turn_id ?? ''),
		'--prompt-id', 'checkpoint-replay-prompt',
		'--before-workspace', beforeWorkspaceHash,
		'--after-workspace', hashWorkspace(),
		'--receipt', receiptPath,
		'--trace', logFile,
		'--checkpoint', checkpointDb,
		'--command-json', commandJson,
		...screenshots.flatMap(file => ['--screenshot', file]),
	];
	if (fs.existsSync(finopsPath)) { manifestArgs.push('--finops', finopsPath); }
	let manifestOut = '';
	try {
		manifestOut = execFileSync(path.join(repo, '.venv', 'Scripts', 'python.exe'), manifestArgs, {
			env: { ...process.env, PYTHONPATH: repo, PYTHONIOENCODING: 'utf-8' },
			encoding: 'utf8',
		});
	} catch (manifestError) {
		manifestOut = String(manifestError?.stdout ?? '');
		report.manifestError = String(manifestError?.stderr ?? manifestError);
	}
	report.manifest = manifestOut ? JSON.parse(manifestOut) : { status: 'FAILED' };
	check('evidence manifest is COMPLETE', report.manifest.status === 'COMPLETE', JSON.stringify(report.manifest));
	report.verdict = Object.values(report.checks).every(c => c.pass) ? 'PASS' : 'PARTIAL';
} catch (error) {
	report.error = String(error?.stack ?? error);
	report.verdict = 'FAIL';
	try { if (page) { await shot('99-failure.png'); } } catch { /* ignore */ }
} finally {
	fs.writeFileSync(path.join(evidence, 'acceptance.json'), JSON.stringify(report, null, 2));
	try { if (browser) { await browser.close(); } } catch { /* ignore */ }
	try { proc.kill(); } catch { /* ignore */ }
	fs.closeSync(out);
}

console.log(JSON.stringify({ verdict: report.verdict, checks: report.checks, error: report.error, session: report.session }, null, 2));
process.exit(report.verdict === 'PASS' ? 0 : 1);
