# Retest-3 Visual Recovery — Preserved Evidence

**Date:** 2026-08-14  
**Workspace:** `/home/user/test3_ws_visual` (preserved)  
**Screenshot:** `screenshots/retest-visual-proof.png` (preserved)  

## Honest verdict

The autonomous visual-proof run was **not a clean agent PASS**. Its initial fresh attempt was interrupted after npm installation timed out. A fresh-thread recovery delivered both components and installed dependencies, but the watchdog later terminated it at 240 seconds because `typecheck_workspace` had been called five times across changing code states. That external repetition rule was too broad for verification calls.

Before termination, the recovery agent had:

- copied both required components;
- installed project and type dependencies;
- repaired generated `LayoutProps`;
- achieved a clean typecheck before adding the render page;
- added the render page;
- diagnosed the wrong named import and changed it to the default `Html` import.

It left one remaining render-page typo: JSX still referenced `<Demo />` after changing the import to `Html`. The evaluator repaired that one reference, reran TypeScript successfully, started the real Next.js server, and captured a real Chromium screenshot.

## Final preserved artifact evidence

- `npx tsc --noEmit`: **PASS**
- `hero-futuristic.tsx`: source/destination SHA-256 `f66c4f9cc10f4e1b81713b25fe360626f3684287a063859a4ed88191ee9ddd00`
- `demo.tsx`: source/destination SHA-256 `cf8e41c97ef8df5280e2803ba0231e6faa4009a3a8609016a2b9993467041543`
- Screenshot: `screenshots/retest-visual-proof.png`
- Screenshot SHA-256: `cefa8d3b36c46fc5069752951c3733da9f5ccc35aa49350eb00d7b313a895b57`
- Screenshot dimensions: 1280 × 800

## Visual caveat

The real page renders the component's `Scroll to explore` control and the proof badge. The Three.js WebGPU scene is black in the headless Chromium capture, consistent with unavailable/limited WebGPU rendering and external texture behavior in this environment. The screenshot is authentic and is not AI-generated.

## Preservation

The workspace, dependencies, logs, reports, and screenshot were intentionally **not deleted**.
