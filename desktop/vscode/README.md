# CrusorAI IDE

This directory is the **vendored [Code OSS](https://github.com/microsoft/vscode) fork** that powers the CrusorAI IDE desktop app — an AI-native code editor with a first-party autonomous coding agent (**Crusor**) built in.

- **Upstream:** `microsoft/vscode` pinned at commit `6c27443ce6fdf6ac798c64025d45175e2e23c4b4` (see `desktop/UPSTREAM_PIN`)
- **Fork docs:** [`desktop/README.md`](../README.md) — overlay layout, build invariants, manifest
- **Project docs:** root [`README.md`](../../README.md) — architecture, runtime, bridge, benchmarks
- **Branding:** [`branding/`](../../branding/) — canonical CrusorAI mark and icon generation
- **Agent contribution:** [`src/vs/workbench/contrib/crusorai/`](src/vs/workbench/contrib/crusorai/) — the Crusor workbench panel

## Welcome Screen

The empty-window editor displays a branded welcome screen with:

- **CrusorAI logo** (center, from `crusorai-mark.svg` embedded as base64 PNG)
- **"Crusor AI"** title + **"AI-Powered Code Intelligence"** subtitle
- **4 action cards:** Open Project, Open File, Clone from GitHub, New File — each triggers the corresponding VS Code command
- **Recent Projects** section (populated from workbench history storage)
- **Grey theme** (`crusorai-dark.json`) — buttons, badges, focus borders, and links use a cohesive grey palette (`#2d2d2d` / `#3c3c3c`)

Icons are created via `createElementNS` (TrustedTypes-safe, no DOMParser needed).

## Building

The build runs directly inside this directory (see the fork docs for the full pipeline):

```bash
cd desktop/vscode
npm install
npm run compile
```

## Licensing & attribution

CrusorAI IDE is built on the open-source **Code - OSS** project. The upstream
license and third-party notices are preserved verbatim:

- [`LICENSE.txt`](LICENSE.txt)
- [`ThirdPartyNotices.txt`](ThirdPartyNotices.txt)

Visual Studio Code is a trademark of Microsoft Corporation. CrusorAI is an
independent project and is not affiliated with or endorsed by Microsoft.
