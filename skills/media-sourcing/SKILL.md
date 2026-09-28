---
name: media-sourcing
description: "Find, download and wire real photos/videos for UI work."
version: 1.0.0
author: Hermes Agent (inspired by hermes web skills), ported for CrusorAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [images, video, media, assets, product-photos, ui, stock, ecommerce]
    related_skills: [rest-graphql-debug, code-wiki]
---

**Triggers:** image, images, photo, photos, picture, product image, product photo, video, videos, media, hero banner, banner, thumbnail, avatar, wallpaper, background image, stock

# Media Sourcing for UI Work

## Overview

Give the site REAL assets. When a task touches any UI that shows pictures or video (product pages, hero sections, galleries, avatars), source actual media — never ship broken placeholders, gray boxes, or hotlinked URLs. Two runtime tools do the work: `media_search` (find openly-licensed images/videos) and `media_download` (save them into the workspace).

## The Workflow (always in this order)

### 1. Search

```
media_search(query="luxury perfume bottle product shot", media_type="image")
media_search(query="perfume spray slow motion", media_type="video")
```

- `media_type`: `"image"`, `"video"`, or `"all"`. Images are the reliable path; videos come from Wikimedia Commons (.webm/.ogv play in `<video>`) and Pexels (mp4) when `PEXELS_API_KEY` is set.
- Iterate the query, don't give up: "perfume bottle" → "fragrance bottle" → "perfume product photography". Search like a stock-site searcher: noun + style, no brand names (brands rarely license).
- Each result line carries: direct URL, dimensions, license, source page.

### 2. Download into the workspace (never hotlink)

```
media_download(url="<direct URL from results>", filename="assets/perfume-hero.jpg")
```

- Validates content-type, caps at 15MB images / 60MB video, sniffs the real type when the server lies.
- Path must be workspace-relative (`assets/...`, `public/images/...`) — absolute paths and `..` are rejected.
- Pick dimensions that fit: a 300x300 thumbnail stretched to a hero banner looks broken. Prefer ≥1200px wide for heroes.

### 3. Wire it into the markup

```html
<img src="assets/perfume-hero.jpg" alt="Amber glass perfume bottle on silk"
     width="1200" height="800" loading="lazy">
<video src="assets/perfume-loop.webm" autoplay muted loop playsinline></video>
```

- **Always** write `alt` text, `width`/`height` (prevents layout shift), `loading="lazy"` below the fold.
- Reference the LOCAL downloaded path — hotlinked remote URLs break offline, leak user IPs, and rot.
- Verify with `verify_ui_workspace` (screenshot shows the actual image, not a broken icon).

## Licensing (do not skip)

- Openverse/Wikimedia results are openly licensed but **CC BY requires attribution** — add a credit line or footer comment when the license says so. Public domain (CC0) needs nothing.
- Pexels license: free to use, attribution appreciated not required.
- Never scrape copyrighted studio imagery from brand sites into user projects.

## Failure Playbook

| Symptom | Move |
|---|---|
| 0 results | Broaden query; try `media_type="all"`; drop brand words |
| All sources error (network) | Tell the user plainly — do NOT invent image URLs from memory (hallucinated URLs 404) |
| Download says "not media" | You passed a page URL, not the direct file URL from the result line |
| No fitting photo exists | Generate a tasteful CSS gradient/placeholder block and SAY so — honest fallback beats a broken `<img>` |
| `media_search` unavailable | Check `CRUSORAI_WEB_TOOLS` env (off = disabled) or run_terminal + curl as last resort |

## Invariants

- Every `<img>`/`<video>` you ship must point at a file you downloaded and verified exists (or an honest CSS fallback).
- Never fabricate remote image URLs.
- Report what you sourced: file, source, license — the user may need to swap licensed assets before going live.
