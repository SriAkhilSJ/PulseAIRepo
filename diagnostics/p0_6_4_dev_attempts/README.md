# P0.6.4 harness development attempts

These are intermediate runs of the same harness while its launcher was being
corrected. They are kept for transparency, not as evidence of anything.

| Attempt | What was wrong | What it taught |
| --- | --- | --- |
| `p0_6_4_attempt1_failed` | The workspace path was passed as Electron's **app** path, so the binary printed "Cannot find module" in an error dialog and never started the workbench. | The first positional argument must be the workbench tree (`desktop/vscode`); the folder comes second. |
| `p0_6_4_attempt2_failed` | Correct app path, but the harness only watched the port it *requested*. | The app binds its own port (9222); the endpoint must be discovered. |
| `p0_6_4_attempt3_failed` | Discovery from stderr only; crash surfaced as a 75–150 s timeout. | Read `DevToolsActivePort`, and treat process exit as an immediate failure. |

The authoritative run is `../p0_6_4/` (run id in `p0_6_4/run.json`); its
blockers are documented in `../p0_6_4/FINDINGS.md`.
