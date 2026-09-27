import fs from 'node:fs';
import path from 'node:path';
import { execSync } from 'node:child_process';

const ROOT = path.resolve(new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const SRC = path.join(ROOT, 'src', 'vs', 'workbench', 'contrib', 'crusorai');
const OUT = path.join(ROOT, 'out', 'vs', 'workbench', 'contrib', 'crusorai');

const list = (d) => {
  let r = [];
  if (!fs.existsSync(d)) return r;
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) r = r.concat(list(p));
    else r.push(p);
  }
  return r;
};

// ── 1. git-tracked crusorai sources ─────────────────────────────────────────
let tracked = [];
try {
  tracked = execSync('git ls-files -- src/vs/workbench/contrib/crusorai', { cwd: ROOT, encoding: 'utf8' })
    .split('\n').map(s => s.trim()).filter(Boolean);
} catch (e) {
  console.log('GIT-LS-FILES failed:', e.message);
}
console.log('git-tracked crusorai src files:', tracked.length);

// ── 2. src <-> out mapping (ts -> js, media copied verbatim) ────────────────
let missingOnDisk = 0, missingInOut = 0;
const outSet = new Set(list(OUT).map(p => path.relative(OUT, p).replace(/\\/g, '/')));
for (const rel of tracked) {
  const abs = path.join(ROOT, rel);
  if (!fs.existsSync(abs)) { console.log('  SRC-MISSING-ON-DISK:', rel); missingOnDisk++; continue; }
  const outRel = rel.replace(/^src\//, 'out/').replace(/\.ts$/, '.js');
  if (!fs.existsSync(path.join(ROOT, outRel))) {
    // media and non-ts files keep their path verbatim under out/
    if (!outSet.has(rel.replace(/^src\//, 'out/').replace(/\\/g, '/'))) {
      console.log('  OUT-MISSING:', outRel); missingInOut++;
    }
  }
}
console.log('src missing on disk:', missingOnDisk, '| tracked src w/o out counterpart:', missingInOut);

// ── 3. src-on-disk files NOT tracked in git (user assets like crusorai-spa) ─
const onDisk = list(SRC).map(p => path.relative(ROOT, p).replace(/\\/g, '/'));
const trackedSet = new Set(tracked);
const extra = onDisk.filter(f => !trackedSet.has(f));
console.log('src-on-disk but untracked:', extra.length);
for (const f of extra.slice(0, 8)) console.log('  UNTRACKED:', f);

// ── 4. preview pipeline specifics ───────────────────────────────────────────
const previewBits = [
  'out/vs/workbench/contrib/crusorai/browser/crusorAIPreviewService.js',
  'out/vs/workbench/contrib/crusorai/browser/media/crusor-preview/index.html',
  'out/vs/workbench/contrib/crusorai/browser/media/crusor-preview/preview.js',
  'out/vs/workbench/contrib/crusorai/browser/media/crusor-preview/preview.css',
  'out/vs/workbench/contrib/crusorai/browser/media/crusor-preview/overlay',
  'out/vs/workbench/contrib/crusorai/common/crusorAIPreview.js',
];
console.log('--- preview pipeline bits ---');
for (const b of previewBits) {
  console.log(fs.existsSync(path.join(ROOT, b)) ? '  OK   ' + b : '  GONE ' + b);
}

// ── 5. stamps ───────────────────────────────────────────────────────────────
for (const s of ['SOURCES_HASH', 'BUILD_INFO.json']) {
  const p = path.join(OUT, 'browser', s);
  if (fs.existsSync(p)) {
    const ageMin = ((Date.now() - fs.statSync(p).mtimeMs) / 60000).toFixed(0);
    console.log('stamp', s, 'age_min=' + ageMin);
  } else console.log('stamp', s, 'MISSING');
}
