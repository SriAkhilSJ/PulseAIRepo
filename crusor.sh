#!/usr/bin/env bash
# Source-tree launcher for macOS and Linux. The agent bridge starts the Preview
# proxy when a workspace session binds, so this wrapper only delegates to the
# vendored Code OSS launcher (no extra terminal or proxy process required).
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CODE_LAUNCHER="${CRUSORAI_CODE_LAUNCHER:-${REPO_ROOT}/desktop/vscode/scripts/code.sh}"

if [[ ! -x "${CODE_LAUNCHER}" ]]; then
  printf '[crusor] Code OSS launcher is missing or not executable: %s\n' "${CODE_LAUNCHER}" >&2
  printf '[crusor] Build the desktop checkout first; see desktop/README.md.\n' >&2
  exit 1
fi

exec "${CODE_LAUNCHER}" "$@"
