# PulseAI desktop host

`pulseAI.desktop.contribution.ts` registers the desktop-only engine service.

```text
Workbench renderer (no Node privileges)
  → IUtilityProcessWorkerWorkbenchService
  → pulseAIWorkerMain utility process
  → PulseAIWorkerProcessService (Node child_process)
  → python -m src.bridge
```

The common/web contribution never imports this directory. The worker validates absolute engine roots, bridge existence, one-line typed JSON frames, a 1 MiB frame limit, shell-free process spawning, bounded stderr lines, graceful shutdown, and forced termination after a short grace period.
