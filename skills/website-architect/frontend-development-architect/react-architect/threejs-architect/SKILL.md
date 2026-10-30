---
name: threejs-architect
description: Architect-level Three.js and WebGL guidance — scene graph and render-loop architecture, asset pipeline and draw-call budgets, camera and sizing strategy, interaction and raycasting boundaries, and when React Three Fiber is the right layer. Use when designing a 3D web experience, not for shader math.
license: MIT
compatibility: three r150+; optional @react-three/fiber + drei
metadata:
  crusor-domain: website-architect
  crusor-path: frontend-development-architect/react-architect
  crusor-origin: original
  crusor-sources: "threejs.org/docs; threejs.org/manual (optimize lots of objects); r3f docs"
  crusor-triggers: "threejs, three.js, webgl, 3d, react-three-fiber, r3f, scene-graph, shaders, gpu, render-loop"
  crusor-verified-on: "2026-10-30"
---

# Three.js Architect

A 3D web app is a **frame budget** problem wrapped in a scene graph. Every
decision is judged against 16.6 ms, not against how the code reads.

## When to use

- Product configurators, data visualisation in 3D, immersive marketing, games.
- Existing Three.js scene is slow, leaks GPU memory, or melts mobile.
- Deciding between vanilla Three.js and React Three Fiber.

## When NOT to use

- 2D data visualisation (use SVG/canvas libraries).
- Decorative 3D that costs more than it communicates — say so and offer a
  lighter alternative.

## Decision 1 — Layer choice

| Situation | Choose |
|---|---|
| React app, state-driven scene | React Three Fiber + drei |
| Static/imperative scene, no React | vanilla Three.js |
| Heavy custom pipeline / post-processing | vanilla or R3F with a custom render loop |
| Simplest possible embed (one model, rotate) | `<model-viewer>` — do not ship a renderer for this |

R3F is a reconciliation layer, not a performance win: the same draw-call and
geometry rules apply.

## Decision 2 — Frame budget

- Target: 60 fps desktop, 30 fps mobile; measure with a real device profile.
- One `requestAnimationFrame` loop for the app; never a loop per component.
- Render on demand when the scene is static (`invalidate()` in R3F) instead of
  burning frames for nothing.
- Pause the loop when the canvas is off-screen or the tab is hidden.
- Keep per-frame work allocation-free: no `new Vector3()` in `update()`.

## Decision 3 — Draw calls and assets

- Budgets: **< 100 draw calls**, < 1M triangles, < 100 MB textures on mobile.
- Instance repeated geometry (`InstancedMesh`); merge static geometry.
- Reuse materials and geometries; dispose on unmount (`geometry.dispose()`,
  `material.dispose()`, `texture.dispose()`).
- Compress assets: glTF + Draco/Meshopt, KTX2 textures, LODs, power-of-two sizes.
- Load behind a real progress state; never block first paint on a 40 MB model.

## Decision 4 — Scene architecture

```
app shell (canvas sizing, DPR, error boundary)
  scene root (lights, environment, camera rig)
    layer groups (world / ui-3d / effects)
      features (each owns its meshes + disposal)
```

- Units and up-axis agreed once (metres, Y-up) — mixing them is a rewrite.
- Camera rig is a first-class object (orbit, follow, cinematic), not ad-hoc
  position math per component.
- Raycasting is opt-in per interactive layer; hit-testing the whole scene each
  pointer move is a frame killer.
- Accessibility: every 3D interaction has a DOM fallback and a non-3D path.

## Decision 5 — Sizing and device pixel ratio

- Canvas sized by CSS, resolution by `renderer.setPixelRatio(min(dpr, 2))`.
- Resize observer, debounced; resize the renderer *and* the camera projection.
- Context loss is an event, not a crash: listen for `webglcontextlost`.

## Failure modes at scale

- GPU memory leak from textures created per mount and never disposed.
- 500 draw calls from imported models left unmerged.
- Render loop running at full speed for an idle scene.
- Post-processing stack that costs more than the content.
- Mobile tested on a desktop browser's emulation instead of a device.

## Verification receipts

1. FPS + frame-time trace on a mid-tier mobile device.
2. `renderer.info`: draw calls, triangles, textures, geometries after load.
3. Memory check across mount/unmount cycles (no growth).
4. Lighthouse/INP impact of the canvas on the host page.
5. Fallback path verified with WebGL disabled.
