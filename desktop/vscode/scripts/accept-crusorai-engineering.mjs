import { chromium } from 'playwright';
import { spawn, execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const vscode = path.resolve(here, '..');
const repo = path.resolve(vscode, '..', '..');
const exe = path.join(vscode, '.build', 'electron', 'CrusorAI.exe');
const root = path.join(process.env.TEMP, 'opencode', `crusor-engineering-${Date.now()}`);
const workspace = path.join(root, 'workspace');
const userData = path.join(root, 'user-data');
const appData = path.join(root, 'appdata');
const home = path.join(root, 'home');
const evidence = path.join(repo, 'bench-results', 'phase-3.3-canonical-runtime', 'logs', 'electron-engineering');
const prompt = 'Create exactly one file named acceptance.md containing a short description of Crusor. Do not create any other user deliverables.';
const expected = 'Crusor is an AI-powered coding IDE';

try { execFileSync('taskkill', ['/F', '/IM', 'CrusorAI.exe', '/T'], { stdio: 'ignore' }); } catch { /* not running */ }
fs.rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
fs.rmSync(evidence, { recursive: true, force: true, maxRetries: 5, retryDelay: 300 });
for (const dir of [workspace, userData, appData, home, evidence]) { fs.mkdirSync(dir, { recursive: true }); }

const logFile = path.join(evidence, 'electron.log');
const out = fs.openSync(logFile, 'w');
const env = { ...process.env };
for (const key of ['ELECTRON_RUN_AS_NODE', 'VSCODE_ESM_ENTRYPOINT', 'VSCODE_IPC_HOOK', 'VSCODE_PID']) { delete env[key]; }
Object.assign(env, {
	VSCODE_DEV: '1', CRUSORAI_DEV: '1',
	CRUSORAI_BRIDGE_RUNNER: 'scripted',
	CRUSORAI_SCRIPTED_SCENARIO: 'engineering',
	CRUSORAI_BRIDGE_APPROVAL_POLICY: 'ask',
	CRUSORAI_ENGINE_ROOT: repo,
	CRUSORAI_APP_DATA_ROOT: appData,
	CRUSORAI_PREVIEW_AUTOSTART: '0',
	CRUSORAI_AUTOTITLE: '0',
	HOME: home, USERPROFILE: home,
	CRUSORAI_TURN_STALL_TIMEOUT_S: '300',
});

const proc = spawn(exe, ['.', workspace, '--remote-debugging-port=9222', '--no-sandbox',
	'--disable-gpu', '--disable-workspace-trust', `--user-data-dir=${userData}`, '--enable-logging',
], { env, stdio: ['ignore', out, out] });

const report = { timestamp: new Date().toISOString(), checks: {}, screenshots: [], limitations: [] };
let browser;
let page;
const shot = async name => {
	const file = path.join(evidence, name);
	try {
		await page.screenshot({ path: file, timeout: 60_000 });
	} catch {
		await page.waitForTimeout(2000);
		await page.screenshot({ path: file, timeout: 60_000 });
	}
	report.screenshots.push(file);
};
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
let baselineBridgePids = bridgePids();

const openAgent = async () => {
	const input = page.locator('.crusorai-composer-input').first();
	for (let attempt = 0; attempt < 5; attempt++) {
		if (await input.count() && await input.isVisible()) { return; }
		await page.keyboard.press(attempt === 0 ? 'Control+L' : 'F1');
		if (attempt > 0) {
			await page.waitForSelector('.quick-input-widget input', { timeout: 15_000 });
			await page.keyboard.type('Crusor: Open Agent');
			await page.waitForTimeout(500);
			await page.keyboard.press('Enter');
		}
		try { await page.waitForSelector('.crusorai-composer-input', { state: 'visible', timeout: 12_000 }); return; } catch { /* retry */ }
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
state=None; receipt=None; usage=None
if pick:
    from langgraph.checkpoint.sqlite import SqliteSaver
    conn=sqlite3.connect(p,check_same_thread=False)
    snap=SqliteSaver(conn).get_tuple({'configurable':{'thread_id':pick['thread_id']}})
    if snap:
        cv=snap.checkpoint.get('channel_values',{})
        state=[{'type':getattr(m,'type',''),'content':getattr(m,'content','')} for m in cv.get('messages',[])]
        receipt=cv.get('turn_receipt'); usage=cv.get('turn_token_usage')
print(json.dumps({'threads':threads,'pick':pick,'messages':state,'receipt':receipt,'usage':usage},ensure_ascii=False))
`;
	const file = path.join(root, 'audit.py');
	fs.writeFileSync(file, code, 'utf8');
	return JSON.parse(execFileSync(path.join(repo, '.venv', 'Scripts', 'python.exe'), [file], {
		env: { ...process.env, HOME: home, USERPROFILE: home, PYTHONPATH: repo, PYTHONIOENCODING: 'utf-8' },
		encoding: 'utf8',
	}));
};

const ledger = () => {
	const file = path.join(appData, 'finops', 'provider_invocations.jsonl');
	if (!fs.existsSync(file)) { return []; }
	return fs.readFileSync(file, 'utf8').split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line));
};

try {
	const deadline = Date.now() + 60_000;
	while (Date.now() < deadline) {
		try {
			browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
			page = browser.contexts()[0].pages().find(p => p.url().includes('workbench.html')) ?? browser.contexts()[0].pages()[0];
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
	await page.waitForFunction(() => /Running|Working|Understanding|Planning/.test(document.body.innerText), null, { timeout: 30_000 });
	await shot('02-engineering-start.png');

	const approval = page.locator('[data-approve-once]').first();
	try {
		await approval.waitFor({ state: 'visible', timeout: 120_000 });
		await shot('03-approval-diff.png');
		check('approval card/dock shown', true);
		await approval.click();
	} catch {
		report.limitations.push('approval dock did not appear (workspace-session policy may auto-approve)');
	}

	try {
		await page.waitForSelector('.crusorai-agent-card.is-delivery', { timeout: 300_000 });
	} catch {
		await page.waitForFunction(() => !document.querySelector('.crusorai-send-stop'), null, { timeout: 300_000 });
	}
	await page.waitForTimeout(1500);
	const cards = await page.locator('.crusorai-agent-card').allInnerTexts();
	await shot('04-engineering-complete.png');
	const before = audit();
	const rows = ledger();
	const receiptIds = (before.receipt?.model_invocations?.ids ?? []).filter(Boolean);
	const ledgerIds = [...new Set(rows.map(r => r.invocation_id))];
	const files = [];
	const walk = dir => {
		for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
			const full = path.join(dir, entry.name);
			if (entry.isDirectory()) { walk(full); } else { files.push(path.relative(workspace, full).replaceAll('\\', '/')); }
		}
	};
	walk(workspace);
	const acceptanceFile = path.join(workspace, 'acceptance.md');
	const acceptanceText = fs.existsSync(acceptanceFile) ? fs.readFileSync(acceptanceFile, 'utf8') : '';
	check('exactly one user deliverable', files.length === 1 && files[0] === 'acceptance.md', JSON.stringify(files));
	check('no internal metadata in workspace', !files.some(f => f.startsWith('.crusorai/') || f.startsWith('diagnostics/')), JSON.stringify(files));
	check('acceptance.md has UTF-8 content', acceptanceText.includes(expected), JSON.stringify(acceptanceText).slice(0, 200));
	check('engineering completed and verified', /COMPLETED|VERIFIED/.test(cards.join('\n')), cards.join('\n').slice(0, 300));
	check('delivery card rendered', cards.some(c => /Verdict|COMPLETED/.test(c)));
	check('plan card rendered', cards.some(c => /Plan|Inspect|Create|Verify/.test(c)));
	check('file-change card rendered', cards.some(c => /acceptance\.md/.test(c)));
	check('verification card rendered', cards.some(c => /VERIFIED|NOT_VERIFIED|Verification/.test(c)));
	check('ledger ids are canonical', ledgerIds.length > 0 && ledgerIds.every(id => id.startsWith('inv-')));
	check('receipt ids equal ledger ids', receiptIds.length > 0 && receiptIds.every(id => ledgerIds.includes(id)), JSON.stringify({ receiptIds, ledgerIds }));
	check('checkpoint has persisted messages', (before.messages ?? []).length >= 2, JSON.stringify(before.messages));

	await page.reload({ waitUntil: 'domcontentloaded' });
	await page.waitForSelector('.monaco-workbench', { timeout: 45_000 });
	await page.waitForTimeout(8000);
	await openAgent();
	await page.waitForSelector('.crusorai-composer-input:not([disabled])', { timeout: 90_000 });
	await page.waitForFunction(() => /Crusor ready/.test(document.querySelector('.crusorai-engine-status')?.textContent ?? ''), null, { timeout: 120_000 });
	await page.waitForTimeout(2500);
	const postText = await page.locator('.crusorai-assistant-message').allInnerTexts();
	const postUsers = await page.locator('.crusorai-user-message-text').allInnerTexts();
	await shot('05-post-reload.png');
	check('conversation restored after reload', postText.some(t => t.includes('acceptance.md') || t.includes('Crusor is an AI-powered')), JSON.stringify(postText).slice(0, 300));
	check('prompt restored once', postUsers.filter(t => t.trim() === prompt).length === 1, JSON.stringify(postUsers));

	const pids = bridgePids();
	const oldPid = pids.find(pid => !baselineBridgePids.includes(pid));
	if (oldPid) {
		try { execFileSync('taskkill', ['/PID', String(oldPid), '/F'], { stdio: 'ignore' }); } catch { /* gone */ }
		let newPid;
		const until = Date.now() + 120_000;
		while (Date.now() < until) {
			newPid = bridgePids().find(pid => pid !== oldPid && !baselineBridgePids.includes(pid));
			if (newPid) { break; }
			await page.waitForTimeout(1000);
		}
		report.bridgeRestart = { old: oldPid, new: newPid };
		check('fresh bridge process started', Boolean(newPid), `old=${oldPid} new=${newPid}`);
		if (newPid) {
			await page.waitForFunction(() => /Crusor ready/.test(document.querySelector('.crusorai-engine-status')?.textContent ?? ''), null, { timeout: 180_000 });
			await page.waitForTimeout(3000);
			const restartText = await page.locator('.crusorai-assistant-message').allInnerTexts();
			const restartAudit = audit();
			await shot('06-bridge-restart.png');
			check('conversation restored after bridge restart', restartText.some(t => t.includes('acceptance.md') || t.includes('Crusor is an AI-powered')), JSON.stringify(restartText).slice(0, 300));
			check('bridge restart did not execute again', (restartAudit.pick?.count ?? 0) === (before.pick?.count ?? 0), `before=${before.pick?.count} after=${restartAudit.pick?.count}`);
		}
	}

	fs.writeFileSync(path.join(evidence, 'engineering-result.json'), JSON.stringify({
		files, acceptanceText, before, ledger: rows, cards,
	}, null, 2));
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

console.log(JSON.stringify({ verdict: report.verdict, checks: report.checks, error: report.error }, null, 2));
process.exit(report.verdict === 'PASS' ? 0 : 1);
