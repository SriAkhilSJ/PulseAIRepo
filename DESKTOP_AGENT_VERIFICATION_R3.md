# INSTRUCTIONS — Desktop Agent: Round 3 (retry of R2)

**Verify tip:** `053ad488` or newer · **Branch:** `arena/01a02fe3-pulseairepo`
**Zero credits. No model calls. No source edits.**

> **R2 was my fault.** I removed `product.defaultChatAgent`, which bricked the
> renderer. Your control test — same `out/`, swap only `product.json` — is what
> located the crash. That was the right experiment and I could not have found it
> without you.
>
> One correction: you concluded the stale `8/21 out/` was built against the old
> product shape and recommended rebuilding. **Your own control test rules that
> out.** `product.json` is never compiled into `out/`; it is injected at runtime
> via `globalThis._VSCODE_PRODUCT_JSON` (`platform/product/common/product.ts:37`).
> Both runs executed identical JavaScript and only the injected data differed.
> A rebuild would have cost hours and fixed nothing. **Do not rebuild `out/` for
> this round.**
>
> Actual crash: `contrib/welcomeOnboarding/browser/onboardingVariationA.ts:80`
> runs `assertDefined(product.defaultChatAgent, …)` at **module top level**,
> bundled via `workbench.common.main.ts:402`. The throw aborts bundle
> evaluation, so the renderer dies before painting.

**Reverted, and the new fix changes ZERO TypeScript.** It is three settings
defaults added to the same `configurationDefaults` block that successfully
delivered `PulseAI Dark` in R1.

---

## 1. Sync

```powershell
cd <repo root>
git fetch origin
git checkout arena/01a02fe3-pulseairepo
git pull origin arena/01a02fe3-pulseairepo
git log --oneline -1          # MUST be 2fbd25d6 or newer
```

Pre-flight — **all three lines must match, or STOP and report**:

```powershell
python -c "import json;d=json.load(open(r'desktop\vscode\product.json'));print('defaultChatAgent' in d, 'voiceWsUrl' in d)"
# expect:  True False        <-- defaultChatAgent is RESTORED on purpose

python -c "import json;print(json.load(open(r'desktop\vscode\extensions\theme-defaults\package.json'))['contributes']['configurationDefaults'])"
# expect:  {'workbench.colorTheme': 'PulseAI Dark', 'chat.disableAIFeatures': True, 'workbench.welcomePage.experimentalOnboarding': False, 'workbench.startupEditor': 'none'}

python -m pytest src/tests/ -q
# expect:  32 passed
```

---

## 2. Compile (the 205 errors are fixed), then refresh `.build`

### Then refresh `.build`

If `npm run compile` succeeded it should already have synced
`extensions/theme-defaults` into `.build\extensions\`. Do the copy anyway — it
is cheap, idempotent, and in R1 you found `.build` can go stale:

```powershell
$src = "desktop\vscode\extensions\theme-defaults"
$dst = "desktop\vscode\.build\extensions\theme-defaults"
New-Item -ItemType Directory -Force -Path "$dst\themes" | Out-Null
Copy-Item "$src\package.json"              "$dst\package.json"              -Force
Copy-Item "$src\package.nls.json"          "$dst\package.nls.json"          -Force
Copy-Item "$src\themes\pulseai-dark.json"  "$dst\themes\pulseai-dark.json"  -Force

# CONFIRM the copy actually carries the new settings:
python -c "import json;print(json.load(open(r'desktop\vscode\.build\extensions\theme-defaults\package.json'))['contributes']['configurationDefaults'])"
```

**If that last line does not show `chat.disableAIFeatures: True`, everything
below is invalid.** Stop and report.

### The 205 compile errors are fixed — please compile normally

My earlier instruction to skip `npm run compile` is **withdrawn**. You were right
that the `codex` protocol gap was real and pre-existing; it is now repaired.

They were never 205 independent bugs. **Two whole directories were missing from
the vendored fork**, and every other error — the `TurnStartParams` mismatch, the
implicit `any` on `candidate`/`left`/`right`, the un-narrowed `unknown`, the `M`
vs `string` generics, the missing return paths — cascaded from the absent types:

| Missing directory | Files | Broken imports |
|---|---:|---:|
| `src/vs/platform/agentHost/node/codex/protocol/` | 702 | 130 |
| `src/vs/workbench/contrib/logs/` | 6 | 7 |

All 708 restored byte-identically from the pin
`microsoft/vscode@6c27443ce6fdf6ac798c64025d45175e2e23c4b4`, verified by
recomputing each file's git blob SHA-1 against the upstream tree (723/723 match).

```powershell
npm run compile
```

**Expected: 0 errors.** If `compile-client` still fails, capture the FULL error
list and stop — do not fix anything. A short scan tells us instantly whether it
is another vendoring hole:

```powershell
# lists every relative import in the fork whose target file does not exist
python - <<'EOF'
import os,re,collections
os.chdir(r'desktop\vscode')
i1=re.compile(r'''^\s*(?:import|export)\b[^'"]*?from\s+['"](\.[^'"]+)['"]''',re.M)
i2=re.compile(r'''^\s*import\s+['"](\.[^'"]+)['"]''',re.M)
m=collections.Counter()
for dp,dn,fn in os.walk('src'):
    for f in fn:
        if not f.endswith('.ts'): continue
        s=open(os.path.join(dp,f),encoding='utf-8',errors='ignore').read()
        for r in i1.findall(s)+i2.findall(s):
            if not (r.endswith('.js') or r.endswith('.css')): continue
            t=os.path.normpath(os.path.join(dp,r))
            c=[t[:-3]+'.ts',t[:-3]+'.d.ts',t] if t.endswith('.js') else [t]
            if not any(os.path.exists(x) for x in c): m[os.path.dirname(t)]+=1
print('unresolved:',sum(m.values()))
for k,v in m.most_common(10): print('  ',k,v)
EOF
```

**Expected output: `unresolved: 1`** — and that one
(`aiCustomizationManagement.css`) is missing from upstream too, so it is
harmless. Anything higher means another directory did not survive vendoring;
report the list and stop.

---

## 3. Launch — fresh profile, `pulseai-check-r3`

```powershell
cd desktop\vscode
Remove-Item -Recurse -Force .freebuff\pulseai-check-r3 -ErrorAction SilentlyContinue
.\.build\electron\PulseAI.exe . --user-data-dir .freebuff\pulseai-check-r3 --new-window --disable-workspace-trust
```

- **New directory name** (`r3`) — the R1/R2 profiles have seeded settings that
  would mask the result.
- **Do NOT seed `settings.json`. Do NOT pass `--disable-extension`.** The point
  is out-of-the-box first-run behaviour.
- **If a dialog appears, screenshot it — do not dismiss it.**

---

## 4. The checks

| # | Check | Expected |
|---|---|---|
| **0** | **It boots** | Workbench paints within ~30 s. Explorer + editor visible. Title becomes `PulseAIRepo - PulseAI IDE Dev`. `logs\window1\` exists. **If black, this round fails at check 0 — go to §6.** |
| **1** | **No sign-in modal** | No GitHub Device Code, no "Sign in to use GitHub Copilot", no centered onboarding wizard with Sign In / Google / Apple. You should land straight in the editor with no modal at all. |
| **2** | **Single Pulse header** | `View: Toggle Secondary Side Bar` → **ONE** header reading `Pulse`. No `CHAT | PULSE` tab strip above it. |
| **3** | **No CHAT tab** | Only Pulse in the auxiliary bar. |
| **4** | **Reversible** (replaces R2's check 4) | Open Settings, search `chat.disableAIFeatures`, set it **false**, reload window (`Developer: Reload Window`). **Chat should come back** — `CHAT` reappears in the auxiliary bar. Then set it back to **true** and reload. This proves we hid Chat rather than broke it. |

Check 4 changed deliberately. R2 asked whether chat commands still exist; we are
now *intentionally* hiding them, so that question no longer measures anything.
Reversibility is the honest equivalent — it proves `contrib/chat` is intact and
one setting away.

**Also re-capture the two rows that were only ever verified statically:**

- **Row 7** — click a file in Explorer → selected row is a deep blue wash
  (`#0C1A30`) with white text.
- **Row 9** — open a file, add a deliberate syntax error (e.g. `func(`), and
  modify a git-tracked file → squiggles and git decorations must still be
  **red / amber / green**, never blue.

Plus a quick sanity pass: still true black, focus rings still blue, no teal.

---

## 5. Report

Screenshots to `.freebuff\evidence\theme-r3\` (gitignored):

1. `git log --oneline -1` + the three pre-flight lines + the `.build` confirm line
2. **A** — the very first screen after launch (checks 0 and 1)
3. **B** — top of the secondary side bar (checks 2 and 3)
4. **C** — Chat restored after flipping the setting (check 4)
5. **D** — Explorer with a row selected (row 7)
6. **E** — syntax error + git decorations (row 9)
7. Pass/fail for 0–4, and for rows 7 and 9
8. Anything odd — error toasts, console errors, missing UI

---

## 6. If it is black again

Then my model of the fix is wrong and I want the evidence, not a workaround.
**Do not try to fix it.** Capture:

- `.freebuff\pulseai-check-r3\logs\<timestamp>\main.log`
- whether `logs\window1\` exists
- relaunch with `--verbose` and capture stdout/stderr
- confirm the one-line revert works:
  ```powershell
  # temporarily blank the new settings to isolate them
  python -c "import json,collections;p=r'desktop\vscode\.build\extensions\theme-defaults\package.json';d=json.load(open(p),object_pairs_hook=collections.OrderedDict);d['contributes']['configurationDefaults']={'workbench.colorTheme':'PulseAI Dark'};json.dump(d,open(p,'w'),indent=2)"
  ```
  then relaunch with a fresh `pulseai-check-r3b` profile and report whether it
  paints. That isolates the settings from everything else — the same control
  technique you used in R2, which is what cracked it.

Restore the file afterwards with `git checkout -- .` if you edited the source
copy (you should only have edited the `.build` copy).

---

## 7. Constraints

- **Zero credits.** No model calls, no `.env` changes.
- **No source edits.** `.build\` copies are build artifacts and are fine.
- **Never touch** `desktop\vscode\src\vs\workbench\contrib\chat\` or
  `desktop\vscode\extensions\copilot\`.
- **No pushing from the laptop.**
- **`npm run compile` is now expected to pass.** If it fails, report the
  errors — do not fix them.
- Hang > 10 min → `taskkill /T /F /PID <pid>`, then report.

---

**Background:** `docs/DESIGN/FORK_REBRANDING.md` §2c (why the last attempt
bricked) and §2d (why this one should not).
