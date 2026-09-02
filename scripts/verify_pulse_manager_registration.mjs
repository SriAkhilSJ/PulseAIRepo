#!/usr/bin/env node
/*
 * One command, provider-free: launch the fork with arguments Electron actually accepts, wait for CDP,
 * run the existing manager-only harness, then read the Agent Manager's session rows over CDP and write
 * them next to the harness's own report.
 *
 * Why this exists: `--user-data-dir D:\path` (space-separated) is not valid Chromium syntax -- the flag
 * needs `--user-data-dir=D:\path`, and the bare path that follows becomes a positional argument, which
 * this build reads as "the thing to load" rather than "the folder to open". The workbench then comes up
 * with no folder, Pulse's composer stays disabled, and the CDP checks time out blaming the UI. An
 * operator should not have to know that, so it is encoded here and pinned by
 * src/tests/test_pulse_session_registration_parity.py.
 *
 * Usage:
 *   node scripts/verify_pulse_manager_registration.mjs <evidenceDir>
 *   node scripts/verify_pulse_manager_registration.mjs <evidenceDir> --no-launch      # attach to a running IDE
 *   node scripts/verify_pulse_manager_registration.mjs <evidenceDir> --dry-run       # print argv, run nothing
 *
 *   --folder-uri  carry the workspace as --folder-uri=file:///... instead of a trailing positional
 *
 * Env: PULSEAI_CDP_PORT (9222) · PULSE_IDE (path to the built exe) · PULSE_WORKSPACE (folder to open)
 *      PULSE_PROFILE (user-data-dir) · PULSE_LAUNCH_TIMEOUT_MS (90000)
 */
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const evidenceDir = path.resolve(process.argv[2] || path.join(REPO, 'bench-results', 'pulse-manager-cdp'));
const port = Number(process.env.PULSEAI_CDP_PORT || '9222');
const flags = new Set(process.argv.slice(3));
const noLaunch = flags.has('--no-launch');
const dryRun = flags.has('--dry-run');
const useFolderUri = flags.has('--folder-uri');
const launchTimeoutMs = Number(process.env.PULSE_LAUNCH_TIMEOUT_MS || '90000');

function __filename_or_self() { return fileURLToPath(import.meta.url); }

function idePath() {
  if (process.env.PULSE_IDE) return path.resolve(process.env.PULSE_IDE);
  const name = process.platform === 'win32' ? 'PulseAI.exe' : 'PulseAI';
  return path.join(REPO, 'desktop', 'vscode', '.build', 'electron', name);
}

function workspacePath() {
  if (process.env.PULSE_WORKSPACE) return path.resolve(process.env.PULSE_WORKSPACE);
  // A folder must be open or Pulse's composer is disabled and every check downstream blames the UI.
  // A scratch directory outside the repo keeps the checkout clean and the workspace small.
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pulse-cdp-ws-'));
  fs.writeFileSync(path.join(dir, 'PulseCdpProbe.txt'), 'open this folder so the Pulse composer enables\n', 'utf8');
  return dir;
}

function profilePath() {
  return process.env.PULSE_PROFILE
    ? path.resolve(process.env.PULSE_PROFILE)
    : path.join(os.tmpdir(), 'pulse-cdp-profile');
}

function appDirArg(ide) {
  /*
   * `.build/electron/PulseAI.exe` is bare Electron with the fork's `product.json` next to it, so it
   * needs to be TOLD which app to load. That is what `desktop/vscode/scripts/code.bat:48` does:
   *     %CODE% . %DISABLE_TEST_EXTENSION% %*
   * The `.` is the app directory, and it is the FIRST positional. A build that has already copied the
   * app into `resources/app` is self-locating and must NOT be given it -- there the first positional
   * would be read as a folder instead. Decided from disk, not remembered.
   */
  const packaged = fs.existsSync(path.join(path.dirname(ide), 'resources', 'app', 'package.json'));
  return packaged ? null : path.resolve(path.dirname(ide), '..', '..');   // -> desktop/vscode
}

function launchArgv(ide, workspace, profile) {
  // `=` form for every value-bearing flag: a space-separated value is a separate argv entry, which
  // Chromium then treats as a new positional -- the mistake that opened a folder as "the app to load".
  const args = [
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    `--disable-workspace-trust`,
    '--disable-extensions',     // the fork ships Copilot as an extension: off means provably off
    '--no-sandbox',             // irrelevant on Windows, keeps a Linux run possible
  ];
  if (useFolderUri) args.push(`--folder-uri=${fileUri(workspace)}`);
  const app = appDirArg(ide);
  // Order is code.bat's: the app directory first, flags next, then the folder as a trailing positional
  // -- unless --folder-uri carries it, in which case a second positional would only confuse the parser.
  return [ide, ...(app ? [app] : []), ...args, ...(useFolderUri ? [] : [workspace])];
}

function fileUri(localPath) {
  const posix = localPath.replace(/\\/g, '/');
  return posix.startsWith('/') ? `file://${posix}` : `file:///${posix}`;
}

async function waitForEndpoint(deadlineMs) {
  const started = Date.now();
  let lastError = 'not attempted';
  while (Date.now() - started < deadlineMs) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const targets = await response.json();
      const page = targets.find(target => target.type === 'page' && /vscode-webview|workbench/i.test(target.url || target.title || ''));
      if (page?.webSocketDebuggerUrl) return page;
      lastError = `no workbench page target yet (${targets.length} targets)`;
    } catch (error) {
      lastError = error.message;
    }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new Error(`CDP endpoint on ${port} never exposed a workbench page: ${lastError}`);
}

async function evaluate(cdpUrl, expression) {
  const ws = new WebSocket(cdpUrl);
  const send = (id, method, params) => ws.send(JSON.stringify({ id, method, params }));
  const waiters = new Map();
  const onMessage = event => {
    const message = JSON.parse(String(event.data));
    if (!message.id) return;
    const settle = waiters.get(message.id);
    if (!settle) return;
    waiters.delete(message.id);
    if (message.error) settle.reject(new Error(`${JSON.stringify(message.error)}`));
    else settle.resolve(message.result || {});
  };
  await new Promise((resolve, reject) => {
    ws.addEventListener('message', onMessage);
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', () => reject(new Error('CDP websocket failed -- is the IDE up with --remote-debugging-port?')), { once: true });
    setTimeout(() => reject(new Error('CDP websocket open timed out')), 15_000).unref?.();
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = waiters.size + 1;
    waiters.set(id, { resolve, reject });
    send(id, method, params);
    setTimeout(() => { waiters.delete(id); reject(new Error(`${method} timed out`)); }, 30_000).unref?.();
  });
  try {
    const response = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) {
      throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text || 'evaluate threw');
    }
    return response.result?.value;
  } finally {
    ws.close();
  }
}

const ROW_EXPRESSION = `(() => {
  const rows = [...document.querySelectorAll('.pulseai-session-row')];
  const text = node => node ? String(node.textContent).replace(/\\s+/g, ' ').trim() : null;
  return {
    found: rows.length > 0 || !!document.querySelector('.pulseai-manager-shell'),
    managerShell: !!document.querySelector('.pulseai-manager-shell'),
    composerDisabled: !!document.querySelector('.pulseai-composer-input[disabled]'),
    rows: rows.length,
    classes: rows.map(row => row.className),
    state: rows.map(row => text(row.querySelector('.pulseai-session-state'))),
    detail: rows.map(row => text(row.querySelector('.pulseai-session-detail'))),
    label: rows.map(row => text(row.querySelector('strong'))),
    empty: rows.some(row => row.classList.contains('is-empty')),
    active: rows.map(row => row.classList.contains('is-active') ? 1 : 0),
    footer: text(document.querySelector('.pulseai-manager-sidebar-footer')),
    agentColumnInManager: !!document.querySelector('.pulseai-manager-main .pulseai-transcript-scroll'),
    // A row must never print a number nobody measured; the field is absent by design.
    inventedFileCounts: /\\+\\d+\\s.\\d+/.test(rows.map(row => row.textContent).join(' ')) ? 1 : 0,
  };
})()`;

async function main() {
  const ide = idePath();
  const workspace = workspacePath();
  const profile = profilePath();
  const argv = launchArgv(ide, workspace, profile);
  fs.mkdirSync(evidenceDir, { recursive: true });
  fs.writeFileSync(path.join(evidenceDir, 'launch-argv.txt'), argv.join('\n') + '\n', 'utf8');
  console.log(`launch: ${argv.join(' ')}`);
  if (dryRun) {
    console.log('--dry-run: nothing spawned, nothing attached.');
    return 0;
  }
  if (!noLaunch && !fs.existsSync(ide)) {
    console.error(`IDE not found at ${ide}\nBuild it first (cd desktop\\vscode && npm run compile) or set PULSE_IDE.`);
    return 2;
  }

  const child = noLaunch ? null : spawn(ide, argv.slice(1), { stdio: 'ignore', detached: process.platform !== 'win32' });
  let target;
  try {
    target = await waitForEndpoint(launchTimeoutMs);
  } catch (error) {
    console.error(`${error.message}\nIf the IDE is already open, re-run with --no-launch. If it came up with no folder,`
      + ` open one (Ctrl+K Ctrl+O -> ${workspace}) and re-run with --no-launch.`);
    if (child) child.kill();
    return 3;
  }

  const preflight = await evaluate(target.webSocketDebuggerUrl, `(() => ({
    composer: !!document.querySelector('.pulseai-composer-input'),
    composerDisabled: !!document.querySelector('.pulseai-composer-input[disabled]'),
    noWorkspace: /Open a folder to start a Pulse session/.test(document.body.innerText || ''),
    folders: (document.querySelectorAll('.pulseai-workspace-choices .pulseai-button, .pulseai-workspace-choice')?.length ?? 0),
  }))()`).catch(error => ({ error: String(error?.message || error) }));
  fs.writeFileSync(path.join(evidenceDir, 'preflight.json'), JSON.stringify(preflight, null, 2) + '\n', 'utf8');
  console.log('preflight: ' + JSON.stringify(preflight));
  if (preflight.composerDisabled || preflight.noWorkspace) {
    console.error(`The workbench came up with NO folder open, so Pulse's composer is disabled and every check
downstream would report the UI as broken. It is an argv problem, not a product one. Try the flag form:
    node ${path.relative(REPO, __filename_or_self())} ${evidenceDir} --no-launch --folder-uri
(Or open ${workspace} by hand with Ctrl+K Ctrl+O, then re-run with --no-launch.)`);
    if (child) child.kill();
    return 5;
  }

  const harness = spawnSync(process.execPath, [path.join(REPO, 'scripts', 'validate_pulse_ui_cdp.js'), evidenceDir, '--manager-only'],
    { stdio: 'inherit', cwd: REPO });
  const rows = await evaluate(target.webSocketDebuggerUrl, ROW_EXPRESSION);
  fs.writeFileSync(path.join(evidenceDir, 'session-rows.json'), JSON.stringify({
    captured_at: new Date().toISOString(),
    cdp_target: { title: target.title, url: target.url },
    harness_exit: harness.status,
    rows,
  }, null, 2) + '\n', 'utf8');
  console.log('\nsession-rows.json:\n' + JSON.stringify(rows, null, 2));
  console.log(harness.status === 0
    ? '\nHarness: PASS. Compare the fields above with docs/DESKTOP_MANAGER_REGISTRATION_VERIFY.md section D.'
    : `\nHarness: exit ${harness.status} -- read ${path.join(evidenceDir, 'cdp-ui-result.json')}.`);
  if (child) child.kill();
  return 0;
}

if (typeof WebSocket !== 'function') {
  console.error('This script needs node >= 21 for the global WebSocket (CDP without a dependency).');
  process.exit(4);
}
main().catch(error => {
  console.error(error.stack || String(error));
  process.exit(1);
});
