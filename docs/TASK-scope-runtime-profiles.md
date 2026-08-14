# Task: Apply Hermes Runtime Values to PulseAI for Scope IDE Agent

**Status:** IN PROGRESS  
**Goal:** Keep Scope a broad IDE agent—not coding-only—while giving each task a small, deterministic capability surface.

## Why

PulseAI's existing toolset waist is coding-first: even a greeting sees file-write and terminal tools. That conflicts with Scope's product direction (research, documents, data, browser work, system tasks, and coding) and wastes tool-schema tokens.

Hermes value being adopted:

- broad product capability at the edges;
- narrow tool waist per active posture;
- declarative, immutable runtime profile;
- deterministic tool order for prompt-cache stability;
- behavior-contract tests rather than frozen tool counts.

## Work plan

- [x] Remove disposable pytest temp directories.
- [x] Add a frozen `RuntimeProfile` resolver with compound capabilities.
- [x] Refactor toolset resolution to consume profiles.
- [x] Preserve explicit IDE/client capability overrides.
- [x] Add behavior tests for general, research, artifact, system, coding, and UI work.
- [x] Replace stale fixed tool-count tests with invariants.
- [x] Extend delivery evidence to PDF/Office/data/media artifacts.
- [x] Add a portable tree-sitter fallback when global esbuild is unavailable.
- [x] Make the previously Windows-only regression tests portable.
- [x] Run focused tests: 90/90 and 76/76 passed.
- [x] Run the README-equivalent suite: **569 passed, 1 warning**.
- [ ] Record Test-3 baseline metrics before the API-key live retest.
- [ ] Run the live Test-3 comparison after the founder supplies the API key.

## Success criteria

1. Scope remains able to perform non-coding work.
2. Pure conversation does not expose mutation/terminal/browser tools.
3. Research receives web tools without code mutation tools.
4. Document/data/artifact creation receives workspace and execution tools.
5. Coding receives read/write/terminal/verification tools.
6. UI coding receives browser tools in addition to coding tools.
7. Same task + same config always resolves to byte-identical ordered tools.
8. Explicit client capabilities can extend a profile without enabling the full registry.
9. No fixed total-tool-count assertion remains.
