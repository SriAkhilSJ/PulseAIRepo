# Research Report: `bakery` folder (testCRUSOR workspace)

## Structure
```
bakery/
├── index.html   (6.5 KB) — single-page site
├── styles.css   (8.9 KB) — custom stylesheet
├── app.js       (1.3 KB) — vanilla JS, ~49 lines
└── assets/      — 4 photos: hero.jpg, sourdough.jpg, croissant.jpg, cinnamon-rolls.jpg
```

## Tech stack
- **Static HTML + CSS + vanilla JavaScript.** No frameworks, no build tools, no package.json,
  no dependencies. Plain semantically-structured HTML with a `<script src="app.js">`.

## Entry point
- **`index.html`** — opened directly in a browser (or any static file server). No server code.

## Purpose
- Marketing/landing page for a fictional artisan bakery, **"Crumb & Craft"**.
  Features: hero section, product highlights (sourdough, croissants, cinnamon rolls),
  contact and "order ahead" (pre-order whole loaves 48h ahead) via mailto links,
  and a footer with CC-credited stock photos (StockSnap / Flickr CC0 & CC BY 2.0).

## JS behavior (app.js)
- Mobile hamburger menu toggle (open/close, close on link click, close on Escape,
  auto-reset when viewport exceeds 701px breakpoint).
- Auto-updates the footer copyright year.
