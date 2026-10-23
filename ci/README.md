# Continuous integration status

> **Status:** current runbook; broad workflow activated on this branch
> **Last reviewed:** 2026-10-23
> **Audit baseline:** `590fe542306ef89547e7909b89da01a9c730e55c`
> **Branch validation:** broad blocking lane 2,585 passed / 16 skipped

## Workflows installed on this branch

Two definitions now live under `.github/workflows/`:

- [`host-compatibility.yml`](../.github/workflows/host-compatibility.yml), the
  focused target-contract suite on `windows-latest`, `macos-latest`, and
  `ubuntu-latest`; and
- [`agent-core.yml`](../.github/workflows/agent-core.yml), a broad hermetic
  Linux/Python 3.11 core lane plus non-blocking desktop-panel parity.

The selected tests cover CI-report parsing, source launchers, target environment
detection, target plans/receipts, and preview probing. It also checks that the
Android target doctor reports missing SDKs as an actionable setup state rather
than an internal error.

Latest checked `main` result:

- commit: `590fe542306ef89547e7909b89da01a9c730e55c`;
- run: `39987746530`;
- result: passed on 2026-10-23.

The host result is useful cross-platform evidence, but it is not the broad
Agent Core lane. During this follow-up the host selection passed **78/78**, the
repaired focused evidence selection passed **98/98** (**102/102** with new
persistence-security tests), and the exact broad blocking selection passed
**2,585 tests with 16 skips** in the hermetic runner.

## Broad workflow policy and activation status

[`agent-core.yml`](agent-core.yml) is the reviewed source copied to
[`.github/workflows/agent-core.yml`](../.github/workflows/agent-core.yml). It
defines:

1. a blocking broad Python suite using `scripts/run_tests.sh`, with the two
   generated-desktop parity modules excluded; and
2. a non-blocking desktop-panel parity lane for those modules.

The separate local desktop run produced **116 passed, 8 skipped, 1 xfailed, and
2 failed**. One failure is tracked-output hash drift; the other is a renderer
parity pin. The lane remains visible and non-blocking so those facts are neither
hidden nor allowed to mislabel Agent Core behavior.

The workflow intentionally treats tracked desktop output separately. The
repository tracks 594 files under the Crusor contribution's `out/` slice,
including 541 orphaned generated `crusorai-spa` files. Resolve that
source/output issue before making desktop parity blocking.

The remaining activation checkpoint is the first clean GitHub run. If it is
green:

1. make the broad core job and host compatibility required in branch
   protection;
2. keep recording deterministic failures with command and environment;
3. fix the product or use only narrow, justified quarantines—never weaken the
   hermetic runner globally; and
4. make desktop parity blocking only after generated output is
   source-correspondent.

## Local equivalents

Use the repository wrapper; it removes provider credentials, creates a fresh
home, and pins timezone/locale.

```bash
# Full default Agent Core selection
scripts/run_tests.sh

# What the staged blocking lane intends to run
scripts/run_tests.sh src/tests \
  --ignore=src/tests/test_desktop_renderer_architecture.py \
  --ignore=src/tests/test_hermes_activity_parity.py

# Staged informational desktop lane
scripts/run_tests.sh -q --no-header \
  src/tests/test_desktop_renderer_architecture.py \
  src/tests/test_hermes_activity_parity.py

# Active host-compatibility selection
scripts/run_tests.sh \
  src/tests/test_ci_report_pytest.py \
  src/tests/test_crusor_shell_launcher.py \
  src/tests/test_target_environment.py \
  src/tests/test_target_pipeline.py \
  src/tests/test_preview_target_probe.py
```

## Coverage still needed for trusted shipping

Even with the broad workflow installed, a user-facing release gate also needs
blocking, candidate-bound checks for:

- frozen dependency installation and clean-room reproduction;
- secret scanning;
- dependency vulnerability policy;
- license/SBOM generation and policy;
- deploy-artifact identity and post-deploy probes;
- evidence-schema and report integrity;
- representative repeated-run/flakiness qualification.

See [`../docs/AGENT_CORE_CURRENT_STATE.md`](../docs/AGENT_CORE_CURRENT_STATE.md)
for the proposed ShipProof gate and rollout sequence.
