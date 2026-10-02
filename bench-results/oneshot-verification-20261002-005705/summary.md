# One-Shot + linter verification — 372bfdcb (final HEAD 6062b970)

Expected: pull 372bfdcb · pytest 14+7+45 · gulp compile (new TS module) · full
restart kills stale build · logs here · commit + push.

Remote moved twice during the run (`0e1a9f63` marketplace entry point) —
integrated via rebase, so everything below is verified against the final tree.

| Step | Command | Result |
|---|---|---|
| 1. Pull | `git pull origin arena/01a0f348-pulseairepo` | fast-forward `77bd1bd9..372bfdcb` ✓ |
| 2. Tests | `pytest src/tests/test_oneshot.py src/tests/test_skills_invalidation.py src/tests/test_skills_hub.py -q` | **66 passed** at 372bfdcb (14 + 7 + 45) ✓ — `pytest.log`; after integrating `0e1a9f63` (+1 remote test): **67 passed** ✓ (re-run overwrote `pytest.log`) |
| 3. Compile | `npx gulp compile` (desktop/vscode) | exit 0 — `crusorAIOneShot.js` emitted (4987 B) ✓ — `compile.log`; re-run after rebase for the marketplace TS: exit 0 — `compile-final.log` |
| 4. Restart | kill all CrusorAI + bridge processes (verified 0/0), relaunch `scripts\code.bat D:\pulseAIagent\PulseAIRepo` | bridges pid 5984/20020 at 01:10:05; **engine build: 6062b970**; workbench sha256 match ("panel is current") ✓ — `engine-stamp.log`, `processes.txt` |
| 5. Smoke | `src.prompts.oneshot` / `handle_hub_op('list')` | templates = `[commit_message, rename_ideas, summarize, title_session]`; hub list `ok` with `c-review`, `vercel-react-best-practices` ✓ — `smoke-*.log` |

Evidence: `bench-results/oneshot-verification-20261002-005705/`
