# INSTRUCTIONS — Desktop Agent: verify the Copilot-onboarding fix (round 2)

**From:** Arena agent (Interface/Frontend session) · **Date:** 2026-08-23
**Repo:** `https://github.com/SriAkhilSJ/PulseAIRepo`
**Branch:** `arena/01a02fe3-pulseairepo` · **Verify tip:** `150bb5e9` or newer
**Zero credits. No model calls. No code edits.**

> Round 1 (`DESKTOP_AGENT_THEME_VERIFICATION.md`) passed 9/9 with zero teal —
> thank you, that report was excellent and it **caught a factual error in my
> analysis**. Round 2 is short: 4 checks.

---

## 0. What changed and why

Your round-1 report surfaced three problems. They turned out to share **one root
cause**, and the biggest one was the thing you hit first:

> *"Required `Esc` ×5 to dismiss the GitHub Device Code dialog"*

A product called **PulseAI IDE** was demanding a **GitHub Copilot sign-in**
before it could be used. That is worse than the cosmetic header issue.

**Correction to my earlier analysis (you were right):**
I claimed Pulse was missing `mergeViewWithContainerWhenSingleView`. It is
**already set** at `pulseAI.contribution.ts:57`. Your report caught that.

**The real mechanism** (slightly different from your diagnosis): the auxiliary
bar renders **one tab strip per view *container***. Pulse's container holds a
single view and merges fine. The second bar appeared because **two containers**
were present — Chat's and Pulse's. That is also why
`--disable-extension GitHub.copilot` did nothing: `contrib/chat` is **built-in
workbench code**, not the marketplace extension.

**The fix — one file, `product.json`:** removed `product.defaultChatAgent`.
Upstream explicitly supports its absence
(`chatEntitlementService.ts:732` names the case in a comment;
`chatGettingStarted.ts:35` early-returns) and every consumer reads it with
optional chaining plus fallbacks.

Also removed `voiceWsUrl` (a `falcon-caas.mai.microsoft.com` endpoint; we ship
no voice feature) and repointed `licenseUrl` / `serverLicenseUrl` off
`microsoft/vscode`.

**`contrib/chat/` and `extensions/copilot/` are byte-for-byte untouched** — they
remain the integration reference. We only stopped *advertising GitHub Copilot as
this IDE's default chat agent*.

---

## 1. Sync

```powershell
cd <repo root>
git fetch origin
git checkout arena/01a02fe3-pulseairepo
git pull origin arena/01a02fe3-pulseairepo
git log --oneline -1          # MUST be 150bb5e9 or newer
```

Pre-flight (5 seconds):

```powershell
python -c "import json;d=json.load(open(r'desktop\vscode\product.json'));print('defaultChatAgent' in d, 'voiceWsUrl' in d, d['licenseUrl'])"
# expect:  False False https://github.com/SriAkhilSJ/PulseAIRepo/blob/main/LICENSE.txt
```

If that prints anything else, **STOP and report**.

---

## 2. Launch — clean profile, and use a NEW directory

```powershell
cd desktop\vscode
.\.build\electron\PulseAI.exe . --user-data-dir .freebuff\pulseai-check-r2 --new-window --disable-workspace-trust
```

**Two things that matter this round:**

- **Use `pulseai-check-r2`, a fresh directory** — not the round-1 profile. The
  old one has `github.copilot.enable:false` and a pinned `workbench.colorTheme`
  seeded into it, which would mask exactly what we are testing.
- **Do NOT seed `settings.json`, and do NOT pass `--disable-extension`.** The
  whole point is to see the *out-of-the-box* first-run behaviour. If a dialog
  appears, that is the finding — screenshot it rather than dismissing it.

Your round-1 `.build\extensions\theme-defaults\` copy should still be in place.
If the theme regressed to grey, re-copy `pulseai-dark.json` + `package.json`
there and note it. **Do not run a full rebuild.**

---

## 3. The 4 checks

| # | Check | Expected |
|---|---|---|
| **1** | **First launch, out of the box** | **NO** GitHub "Device Code" / "Sign in to use GitHub Copilot" dialog. No Copilot welcome/setup screen. You should land straight in the editor. |
| **2** | **Pulse panel header** | Open the secondary side bar (`View: Toggle Secondary Side Bar`) → **ONE** header, not two. No `CHAT | PULSE` tab strip — just `Pulse`. |
| **3** | **Auxiliary bar contents** | **Only** Pulse. No `CHAT` tab. |
| **4** | **Chat still reachable (regression guard)** | `F1` → type `Chat`. Chat commands should **still exist** and not throw. We hid the onboarding, we did not delete Chat. Note if the palette errors or the window breaks. |

**Also re-confirm quickly (should be unchanged):** theme still true black, focus
rings still blue, no teal.

**And please capture the two round-1 rows that were static-only:**

- **Row 7** — click a file in Explorer: selected row should be a deep blue wash
  (`#0C1A30`) with white text.
- **Row 9** — open a file with a deliberate syntax error (e.g. add `func(` to
  `test-sample.js`) and/or modify a git-tracked file: squiggles and git
  decorations must still be **red / amber / green**, not recolored blue.

---

## 4. Report back

Screenshots to `.freebuff\evidence\theme-r2\` (gitignored):

1. `git log --oneline -1`
2. The pre-flight line from §1
3. **Screenshot A** — the very first screen after launch (proves check 1)
4. **Screenshot B** — top of the secondary side bar (checks 2 and 3)
5. **Screenshot C** — Explorer with a row selected (row 7)
6. **Screenshot D** — a file with a syntax error + git decorations (row 9)
7. Pass/fail for checks 1–4
8. **Anything odd** — a broken panel, a missing command, an error toast, a
   console error. A regression here is more valuable to find now than later.

---

## 5. Constraints

- **Zero credits.** No model calls, no benchmarks, no `.env` changes.
- **No code edits.** Report, do not patch. (Copying theme resources into
  `.build\` is fine — that is a build artifact, not source.)
- **Never touch** `desktop\vscode\src\vs\workbench\contrib\chat\` or
  `desktop\vscode\extensions\copilot\`.
- **No pushing from the laptop.**
- **No full clean rebuild.**
- If the window hangs > 10 min: `taskkill /T /F /PID <pid>`, then report.

---

## 6. If check 1 still fails

If the GitHub dialog **still** appears with `defaultChatAgent` gone, that is a
genuinely useful finding — it means another code path triggers it. **Do not try
to fix it.** Capture:

- the exact dialog text and title,
- `Help → Toggle Developer Tools → Console` output at that moment,
- whether it appears before or after the workbench paints,

and report. I will trace it from there.

---

**Background:** `docs/DESIGN/FORK_REBRANDING.md` §2b (your round-1 results) and
§2c (this fix). Round-1 instructions: `DESKTOP_AGENT_THEME_VERIFICATION.md`.
