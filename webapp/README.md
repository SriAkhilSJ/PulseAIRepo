# PulseAI SPA — hermes chat surface as a website

The chat rendering tier of the hermes desktop app (`apps/desktop/src/components/chat/`),
ported verbatim, rendered as a standalone website AND served as the workbench
Webview panel bundle.

- **Website:** `npm run dev` (or `npm run build && npm run preview`).
- **Webview panel:** the built bundle is copied to
  `desktop/vscode/src/vs/workbench/contrib/pulseai/browser/media/pulseai-spa/`,
  where `pulseAIViewPane.ts` loads it in an iframe
  (`vs/.../media/pulseai-spa/index.html`, mapped 1:1 into `out/` by the fork
  compile). This fixes the field error
  `Not allowed to load local resource: .../media/pulseai-spa/index.html` —
  the folder simply never existed.

## Ported so far (verbatim from hermes)

`disclosure-row.tsx`, `scaffold-row.tsx`, `code-card.tsx`, `expandable-block.tsx`
(+ `ui/disclosure-caret.tsx`, `ui/codicon.tsx`, `lib/utils.ts` `cn`,
`hooks/use-resize-observer.ts`), the `--ui-*` token derivation chain and the
conversation metrics block from `styles.css` (nous dark theme seeds applied
statically), the codicon font subset, and the scaffold resting-fade rule.

## Rebuild + copy after changing webapp sources

```bash
cd webapp
npm install   # first time only
npm run build
rm -rf ../desktop/vscode/src/vs/workbench/contrib/pulseai/browser/media/pulseai-spa
mkdir -p ../desktop/vscode/src/vs/workbench/contrib/pulseai/browser/media/pulseai-spa
cp -r dist/* ../desktop/vscode/src/vs/workbench/contrib/pulseai/browser/media/pulseai-spa/
```

Then `cd desktop/vscode && npm run compile` on the owner machine so `out/`
picks it up (`pulseai_doctor.py` step [5] checks this).

## Next turns

- Live bridge: turn frames (assistant prose, tool rows, question cards)
  streamed into these components instead of the static demo transcript.
- Shiki code blocks (`shiki-block.tsx`), status rows, terminal output card.
