# CrusorAI IDE branding

The canonical mark is `crusorai-mark.png` (mirrored as a self-contained `crusorai-mark.svg`): the CrusorAI logo — a silver monochrome mark centered on a black square.

## Palette

| Token | Hex | Use |
|---|---:|---|
| Crusor cyan | `#22D3EE` | active intelligence, focus, streaming, primary accent |
| Agent violet | `#9B8CFF` | delegated agents and semantic seeds |
| Verified green | `#49D190` | completed verification |
| Approval amber | `#EFB75C` | permission and attention |
| Failure red | `#ED727C` | failed or destructive state |
| Logo black | `#000000` | application icon and logo field |
| Logo silver | `#E0E0E0` | logo mark strokes |

The UI accent palette is unchanged from the previous identity; the logomark itself is monochrome silver on black.

Run `python branding/generate_icons.py` after replacing the canonical logo. It derives the Windows, macOS, Linux, server, and browser assets consumed by the canonical fork (`desktop/vscode/resources/`) from `crusorai-mark.png`. Pillow is required only for this branding generation step.

The app icon intentionally contains no text so it remains legible at 16–32 px. Product copy uses **CrusorAI IDE**; the in-product agent remains **Crusor**.

File icons live in `desktop/vscode/extensions/theme-crusor-icons` and are the default `workbench.iconTheme` (`crusor`). Regenerate them from the approved sheets with `python branding/generate_file_icons.py`.
