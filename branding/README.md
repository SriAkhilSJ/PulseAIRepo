# PulseAI IDE branding

The canonical mark is `pulseai-mark.svg`: a cyan execution pulse on the deep-navy PulseAI IDE shell, ending in the violet agent node.

## Palette

| Token | Hex | Use |
|---|---:|---|
| Pulse cyan | `#22D3EE` | active intelligence, focus, streaming, primary brand |
| Agent violet | `#9B8CFF` | delegated agents and the endpoint node |
| Deep navy | `#071118` | application icon and branded workbench chrome |
| Verified green | `#49D190` | completed verification |
| Approval amber | `#EFB75C` | permission and attention |
| Failure red | `#ED727C` | failed or destructive state |

Run `python branding/generate_icons.py` after changing the canonical geometry. It writes the Windows, macOS, Linux, server, and browser assets consumed by the canonical fork (`desktop/vscode/resources/`). Pillow is required only for this branding generation step.

The app icon intentionally contains no text so it remains legible at 16–32 px. Product copy uses **PulseAI IDE**; the in-product agent remains **Pulse**.
