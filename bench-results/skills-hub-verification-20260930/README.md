# Skills Hub (Phase 1 + 2) Verification — 2026-09-30

Branch: `arena/01a0f348-pulseairepo` @ `91906549d408cf224db29bc92314a2cba5191144`

## Steps

| Step | Result | Evidence |
|---|---|---|
| 1. Pull | OK — HEAD matches expected: `91906549` (hash re-pin), `f4e6cadf` (Phase 2), `ac9dcd35` (Phase 1) | git-rev.txt |
| 2. Focused tests | **PASS — 150 passed, 1 skipped, 1 xfailed, EXIT=0** (first run had 1 flaky timeout in `test_bridge_accepts_only_allowlisted_read_only_host_capabilities`; passed in isolation and on full re-run) | focused-tests.log |
| 3. Full suite | `20 failed, 2213 passed, 10 skipped, 1 xfailed` in 1052s. All 20 failures triaged as **pre-existing / env-dependent**: identical failures reproduced on base commit `3f645332` (see base-triage.log) — test_grace_summary_hermes_law, test_model_endpoint_metadata ×2, test_review12 subagent depth cap, test_stream_stall_discipline ×2, test_lsp_performance, plus hermes parity/lab/observability/selective-manifest files that fail identically on base. **No regression introduced by the Skills Hub branch.** | full-suite.log, base-triage.log |
| 4. Live Hub CLI | `search "security"` OK (c-review, agentic-actions-auditor listed). `install c-review` **FAILED**: `archive has 2117 entries (cap 2000)` — see Known Issue below. `list` / `update` / `remove` behave consistently. | hub-cli.log |
| 5. Compile | **EXIT=0**, `done: out/ is ready` after 9.35 min. Re-emitted out/ artifacts refresh BUILD_INFO to commit `91906549` and add `skills_hub_op` / `skills_hub_result` to `crusorAIProtocol.generated.js` (the repo-pinned artifacts predated Phase 2). | compile.log |

## Known Issue (functional bug, found in step 4)

`python scripts/skills_hub_cli.py install c-review` fails with
`archive has 2117 entries (cap 2000)`.

Root cause: the catalog entry points at the full `trailofbits/skills` repo
tarball (2117 entries at SHA `82fe822...`). `install_skill` downloads the
whole repo archive and `safe_extract` enforces `_MAX_REPO_FILES = 2000`
against **all** tar members *before* the entry's `subdir`
(`plugins/c-review/skills/c-review`) is applied — the target subdir itself
contains only SKILL.md. Fix direction: filter tar members to `subdir`
inside/before `safe_extract` (so the cap applies to the extracted skill, not
the whole upstream repo), or raise/spawn the cap for subdir installs.

Not covered by any test in `src/tests/test_skills_hub.py` (repo-file-cap
overflow path is untested).
