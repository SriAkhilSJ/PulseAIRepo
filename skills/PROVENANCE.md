# Provenance — where the library's content comes from

The library is a mix of **authored** books (`crusor-origin: original`) and books
**adapted** from public agent-skill repositories (`crusor-origin: adapted`). Every
book carries its provenance in frontmatter; this file records the survey behind it.

Adapted material keeps the upstream terms: the license and copyright line are named
per source, and the adaptation is a rewrite into the architect format (decisions,
failure modes, verification receipts) rather than a copy of the upstream body.

## Sources adopted

| Upstream | Pinned at | License | Adapted into | What was taken |
|---|---|---|---|---|
| [`yetone/native-feel-skill`](https://github.com/yetone/native-feel-skill) | `9bd88c6` | MIT (c) 2026 yetone | `desktop-architect/runtimes-architect/native-feel-architect` | the native-shell + system-WebView + shared-core architecture, the Electron/Tauri control-loss argument, hidden-window throttling and first-paint fixes, the baseline-versus-margin memory accounting |
| [`vercel-labs/agent-desktop`](https://github.com/vercel-labs/agent-desktop) | `da8a0c2` | Apache-2.0 | `desktop-architect/platform-architect/desktop-automation-architect` | accessibility-tree-as-API, snapshot-bound refs going stale, overlay surfaces, TCC/Accessibility first-contact failures, verify-by-observation over return codes |

Licence texts and copyright lines: `THIRD-PARTY-NOTICES.md`. The Apache-2.0 book
declares `license: Apache-2.0`, the MIT book `license: MIT` — a derivative may not be
relabelled under different terms than its upstream.

Both were re-authored at architect resolution: the upstream files are tool guides or
deep-dive references, while the books state decisions, failure modes and receipts.

## Sources surveyed and not adopted

Checked against the tree and license on 2026-10-30. "Thin" means the skill is a
framework guideline catalogue (snippets plus principles) that adds nothing over the
existing books at architect resolution.

| Upstream | License | Verdict |
|---|---|---|
| [`anthropics/skills`](https://github.com/anthropics/skills) | none declared (no LICENSE file) | **reference only.** Shaped the architect framing of `frontend-development-architect`; no licence is granted, so the book is `original` and the repo is cited as reference, not as a source of text. |
| [`vercel-labs/agent-skills`](https://github.com/vercel-labs/agent-skills) | none declared (no LICENSE file) | **reference only.** Informed `react-core-architect` and the metadata format; same reasoning — cited, not adapted. |
| [`openai/skills`](https://github.com/openai/skills) | none declared | **rejected — no license.** Includes curated `winui-app` and related Windows skills; readable as a cross-check, not adaptable. |
| [`twostraws/SwiftUI-Agent-Skill`](https://github.com/twostraws/SwiftUI-Agent-Skill) | MIT | **reference only.** Excellent review-rules corpus (11 `references/` files); it is a code-review instrument, not an architecture one. Adopting it wholesale would turn a planning book into a lint list. |
| [`Mindrally/skills`](https://github.com/Mindrally/skills) | Apache-2.0 | **thin.** 265 per-topic guideline files (electron, tauri, kafka, terraform, flutter, i18n…). Useful as a coverage checklist; content is below the books' resolution. |
| [`majiayu000/claude-skill-registry`](https://github.com/majiayu000/claude-skill-registry) | MIT | **thin / aggregator.** Large registry, mixed provenance, duplicates third-party skills without clear attribution — not a source of record. |
| [`dpearson2699/swift-ios-skills`](https://github.com/dpearson2699/swift-ios-skills) | NOASSERTION | **rejected.** Per-framework Swift skills (AVKit, PDFKit, PassKit, SwiftData…) — the file granularity is right, the license is not clear. |
| [`mmiani/kotlin-kmp-claude-agent-skills`](https://github.com/mmiani/kotlin-kmp-claude-agent-skills) | NOASSERTION | **rejected.** Closest match to `kotlin-multiplatform-architect`; license unresolved. |
| [`obra/superpowers`](https://github.com/obra/superpowers) | MIT | **out of scope.** Methodology and workflow skills, not domain architecture. |
| [`mattpocock/skills`](https://github.com/mattpocock/skills) | MIT | **out of scope.** Engineering-practice skills; nothing per-framework to adapt. |

## Corrections

Two website books (`frontend-development-architect`, `react-core-architect`) were
previously labelled `crusor-origin: adapted` while citing `anthropics/skills` and
`vercel-labs/agent-skills` — repositories that ship no LICENSE file. No licence means
no adaptation. Both are now `original` with the upstreams recorded as reference, and
the audit (`scripts/audit_skills.py`) fails any adapted book without a permissive
licence and a pinned SHA.

## Policy

1. **License first.** Only MIT, Apache-2.0 or BSD-licensed upstream text is adapted.
   `NOASSERTION` or missing license means read-only reference, never adaptation.
2. **Pin and cite.** `crusor-sources` names `owner/repo@<sha>` plus the license, so a
   reader can diff the upstream at the exact commit that was used.
3. **Rewrite, don't paste.** Adapted books follow the same architecture: when to use,
   numbered decisions, failure modes at scale, verification receipts.
4. **Never claim derivation that does not exist.** A book is `original` until
   upstream text actually shaped it.
5. **Note the drift risk.** Public skills are young; a fact pulled from one is stamped
   with `crusor-verified-on` so a later pass knows what to re-check.
