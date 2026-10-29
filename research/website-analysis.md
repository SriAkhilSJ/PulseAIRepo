# Research Report: `website` folder analysis

Target: `C:/Users/Administrator/Downloads/testCRUSOR/website`

## Structure (max depth 2, deps excluded)
- `app/` — Next.js App Router: `layout.tsx`, `page.tsx`, `globals.css`
- `components/` — `timeline-demo.tsx` (demo), `ui/timeline.tsx` (reusable component)
- Config: `package.json`, `next.config.mjs`, `tailwind.config.ts`, `postcss.config.mjs`, `tsconfig.json`
- Build artifacts: `.next/` (pre-built), `package-lock.json`

## Tech stack
- Next.js ^15.3 (App Router) + React 19.1 + TypeScript ^5.7
- Tailwind CSS ^3.4 (PostCSS + autoprefixer)
- GSAP ^3.13 — animation library; `@gsap/react` is NOT installed (a local `useGSAP` shim is inlined in the component)
- Scripts: `dev` / `build` / `start` (standard Next.js)

## Entry points
- `app/layout.tsx` — root layout, sets metadata ("Horizontal scroll journey timeline built with GSAP"), Tailwind base classes on `<body>`
- `app/page.tsx` — single home page; client-side GSAP-driven horizontal scroll timeline
- `components/ui/timeline.tsx` — the reusable horizontal-scroll timeline component

## Purpose
A single-page demo site showcasing a horizontal-scroll journey timeline animated with GSAP, styled with Tailwind. No API routes, no backend — purely presentational.
