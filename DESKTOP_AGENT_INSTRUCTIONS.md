# INSTRUCTIONS — Desktop Agent (founder's Windows laptop)

**From:** Arena agent (CTO session) · **Date:** 2026-08-23
**Repo:** `https://github.com/SriAkhilSJ/PulseAIRepo`
**Read this whole file before running anything. Do not improvise beyond it.**

---

## 0. Mission (what I need from you)

Produce the first **real, paid benchmark evidence rows** for PulseAI, under a
hard credit budget, with watchdog protection. Concretely, in order:

1. Sync this laptop's clone to the latest branch (STEP 1) — **the local folder
   is stale; GitHub is ahead.**
2. Configure the NEW Sarvam key safely (STEP 2).
3. Run the guarded PBR-002 paid row (STEP 3) — this is the priority.
4. Run the keyless desktop CDP lane if the built IDE exists (STEP 4).
5. Report back EXACTLY the outputs listed in STEP 5 — never the key.

---

## 1. Sync the workspace (the laptop folder is NOT latest)

The latest code lives on branch **`arena/01a02a5c-pulseairepo`** on GitHub
(current tip: `8cbb12ea`). It contains 4 commits the laptop does not have:

```
f137f237  bench: guarded paid-runner script + provider-unreachable durability receipt
6ded717f  tests: fix silently-broken pins; declare pillow; keep test runs out of bench-results
83f144d0  benchmark: lane-aware grading (uncoverable checks = not_run)
54c2ccbb  security: remove live API key from README (was public on GitHub)
```

Run, from the repo root on the laptop:

```powershell
git status                     # note any dirty files
git stash push -u -m "pre-arena-sync"   # only if dirty; do NOT lose them
git fetch origin
git checkout arena/01a02a5c-pulseairepo
git pull origin arena/01a02a5c-pulseairepo
git log --oneline -1           # MUST show 8cbb12ea (or newer)
```

**Warnings:**
- The laptop's local `main` history contains the LEAKED API key (README).
  Never push local `main` anywhere. Work only on the branch above.
- `.env`, `.venv`, `desktop/vscode/.build/`, `bench-results/` are gitignored —
  a checkout/pull will NOT touch them. Your built IDE and venv are safe.

Verify sync: `scripts\run_paid_pbr002_guarded.ps1` must exist.

## 2. Configure the NEW key (100 credits — guard it)

The founder has a NEW Sarvam key. The OLD one is burned (public on GitHub).

- Put exactly one line in `.env` at the repo root (create/keep the rest):
  `CUSTOM_API_KEY=sk_the_new_key`
  plus the existing lines if not already there:
  `LLM_PROVIDER=custom`, `LLM_MODEL=sarvam-105b-conversations`,
  `CUSTOM_BASE_URL=https://api.sarvam.ai/v1`, `SUMMARIZER_LLM=aux`,
  `PROVIDER_SAFE_LIMIT=0`
- The key NEVER goes in README, code, chat, commits, or screenshots.
- The founder (human) rotates the old key in the Sarvam dashboard — remind him.
- Sanity: `git check-ignore .env` → must print `.env`; `git status` must NOT
  list `.env`.

Environment check (one-time):
```powershell
.\.venv\Scripts\python.exe -c "import PIL; import pydantic; print('deps ok')"
# if PIL missing: .\.venv\Scripts\pip.exe install pillow
```

## 3. THE PAID RUN — guarded PBR-002 (priority)

> **Update 2026-08-23:** the first run (founder-pbr002-1) exposed a real
> observability gap — fixed on the branch you just pulled (commit 8cbb12ea:
> the bridge now emits workspace.bound + llm.request; the harness records
> them and real token/cost usage). Re-run the SAME command; expect 3/3.

One command. It is self-protecting: 8-token probe first (~0.1 credit); if the
probe fails the benchmark never starts; watchdog checks every 30 s; kills the
whole process tree on 120 s stall or 10 min hard cap; prints graded checks +
token/cost usage at the end.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_paid_pbr002_guarded.ps1 -Workspace C:\pbr002-ws
```

Rules:
- Monitor it; do not interfere unless the watchdog fires (it kills by itself).
- If the probe fails: STOP. Report the probe error. Do not retry more than
  once without a diagnosis — each retry risks credits.
- If it passes: expected artifacts `bench-results\founder-pbr002-1\result.md`
  with outcome `passed` (3/3 coverable checks on the bridge lane).
- Do NOT run any other task (PBR-004/005/…/011) — those wait for founder
  approval of the next spend.

## 4. Keyless desktop lane (only if the built IDE exists)

If `desktop\vscode\.build\electron\PulseAI.exe` exists:

```powershell
scripts\run_keyless_cdp.bat C:\pbr002-ws
```

This grades the DOM checks for PBR-001/003 (composer blocked with no folder,
multi-root selection). Zero credits, zero model calls. If the IDE is not
built, SKIP and say so — do not attempt a build (multi-hour, out of scope).

## 5. Report back (paste this to the Arena agent — NEVER the key)

1. `git log --oneline -1` output (sync proof)
2. The guarded script's full console output (probe line, watchdog lines, graded result)
3. Contents of `bench-results\founder-pbr002-1\result.md` (if it exists)
4. Contents of `bench-results\report-card.md` (regenerate:
   `.\.venv\Scripts\python.exe -m benchmarks.pulse_reliability_v1.harness report --results-dir bench-results --out bench-results\report-card.md`)
5. For STEP 4 (if run): the report-card rows for PBR-001/003

## Hard constraints (do not cross)

- **Budget:** probe + PBR-002 only, ≈1.5 credits of 100. Nothing else paid.
- **No edits** to benchmark/engine code — if something looks wrong, STOP and
  report it instead of patching. The Arena agent owns code changes.
- **No key material** in any output, log, commit, or message.
- **No pushing** from the laptop (the local history contains the old key).
- If anything hangs beyond the watchdog: `taskkill /T /F /PID <pid>` on the
  python process, then report.
