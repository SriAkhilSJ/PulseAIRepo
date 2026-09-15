# CrusorAI IDE

This directory is the **vendored [Code OSS](https://github.com/microsoft/vscode) fork** that powers the CrusorAI IDE desktop app — an AI-native code editor with a first-party autonomous coding agent (**Crusor**) built in.

- **Upstream:** `microsoft/vscode` pinned at commit `6c27443ce6fdf6ac798c64025d45175e2e23c4b4` (see `desktop/UPSTREAM_PIN`)
- **Fork docs:** [`desktop/README.md`](../README.md) — overlay layout, build invariants, manifest
- **Project docs:** root [`README.md`](../../README.md) — architecture, runtime, bridge, benchmarks
- **Branding:** [`branding/`](../../branding/) — canonical CrusorAI mark and icon generation
- **Agent contribution:** [`src/vs/workbench/contrib/crusorai/`](src/vs/workbench/contrib/crusorai/) — the Crusor workbench panel

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
