> **Update 2026-09-20:** LSP perf (0.91ms baseline), breathing 5s pulse, scroll fix, pulse-webview removed, engine snapshot 1.5s timeout, hard watchdog 12s greeting, AgentOps launcher (auto-detect ~/.crusorai), CopilotKit disabled by default — see README.md Recent Changes.
# GitHub Copilot vs. CrusorAI Agent: Permission Handling & Diff View

This document provides the architectural comparison between **GitHub Copilot** (VS Code extension + CLI runtime) and **CrusorAI Agent** (`PulseAIRepo`), along with the implementation details integrated into CrusorAI.

---

## 1. Permission Handling: Architecture & Comparison

### How GitHub Copilot Handles Permissions

Copilot Chat & Copilot CLI structure tool execution permissions into discrete categories (`read`, `write`, `shell`, `mcp`, `url`, `custom-tool`):

1. **Auto-Approval Boundaries**:
   - **`read`**: Auto-approves reading files inside the session workspace, workspace folders, session state files (e.g. `plan.md`), and attached files. Out-of-workspace reads prompt the user with `CoreConfirmationTool`.
   - **`write`**: Auto-approves file creation, edits, and replacements when inside the workspace folder or working directory, provided the target file is not protected and isolation mode is not breached.
2. **Interactive Confirmation with Rich Context**:
   - For **`write`** operations requiring confirmation (e.g., protected paths or out-of-workspace writes), Copilot formats a unified diff preview (`formatDiffAsUnified`) showing the file name, target path, action (edit/create/insert), and unified diff with added/removed lines before requesting confirmation.
   - For **`shell`** operations, Copilot cleans up redundant command prefixes (stripping redundant `cd <dir> &&` via `getCdPresentationOverrides`), identifies sandbox elevation/bypass flags (`sandboxBypass`, `sandboxBypassReason`), and presents the user with command text, purpose, and confirmation controls.
   - For **`mcp`** operations, Copilot displays the server name, tool title, and formatted JSON arguments.
3. **Decision Options & Scopes**:
   - Supports `approve-once`, `allow-for-session` (sticky session grant), and `denied-interactively-by-user`.

---

### How CrusorAI Handled Permissions (Before)

1. **`SafetyGuard`**:
   - Used the "git can restore it" rule: tracked files are safe to overwrite autonomously (since git provides undo); git-ignored files require human consent every time.
   - Maintained a sensitive-path veto (`.env`, `.ssh`, `.aws`, private keys) that outranks any autonomous mode.
   - Filtered shell commands with `approval_detection.py` (e.g. recursive `rm`, `taskkill /F`, privilege escalation).
2. **Gaps in CrusorAI**:
   - **Pre-execution Diff Missing in Approval Dock**: When a file mutation required approval, `approvalDock` displayed only a "Review change" button to open an external editor tab; it did **not** render an inline diff preview in the approval dock itself.
   - **Shell Risk Reason Lost**: The safety guard generated precise danger reasons (e.g., recursive deletion, command substitution), but `SafeToolNode._diff_payload` returned `None` for shell commands, and `crusorAIRendererService` did not store `warning` in the model's approval state.
   - **File Write Diff Payloads Incomplete**: `_diff_payload` previously returned only `{path, old_text, new_text}` without formatting unified diff hunks, stats (`+added, -removed`), or action tags (`create`, `modify`, `copy`).

---

## 2. Diff View: Architecture & Comparison

### How GitHub Copilot Handles Diffs

1. **In-Chat Diff Display**:
   - Formats unified diffs into syntax-tinted lines: additions (`+`), removals (`-`), context (` `).
   - Displays hunk headers and line stats (+added, -removed).
2. **Native Editor Diff Integration (`open_diff`)**:
   - Generates virtual read-only documents for both the original file and modified file using `createReadonlyUri`.
   - Opens the diff editor using `vscode.diff`.
3. **Diff State & Context Tracking**:
   - `DiffStateManager` manages active diffs (`diffId`, `sessionId`, `originalUri`, `modifiedUri`, `newContents`).
   - Dynamically manages the VS Code context key `github.copilot.chat.copilotCLI.hasActiveDiff` when the user focuses the diff editor tab.
4. **In-Editor Action Controls**:
   - Registers `acceptDiff` (checkmark icon) and `rejectDiff` (cross icon) in the editor title bar (`editor/title`, `when: hasActiveDiff`).
   - The user can inspect the proposed diff in full screen and click **Accept Change** or **Reject Change** directly from the diff editor toolbar, which applies or rejects the change and closes the diff tab.

---

### How CrusorAI Handled Diffs (Before)

1. **In-Chat Diff**:
   - Possessed `diffPreview(diff)` and `diffStats(diff)`, but only used them for completed file mutation cards when the tool result had a diff string.
   - When a tool was pending approval, `approvalDock` did not render any inline diff.
2. **Native Editor Diff**:
   - Possessed `workbenchService.openInlineDiff` with virtual URI scheme `crusorai-diff://crusorai/...`.
   - **Defect on `write_file`**: Clicking "Open native diff" on executed `write_file` tools crashed with `"This tool receipt does not include inline text or native original/modified diff resources"` because `tool.arguments` had `content` instead of `new_text`, and `old_text` was not present.
   - **No Diff State Tracking or Editor Title Actions**: When viewing a diff tab in VS Code, there was no `hasActiveDiff` context key, and **no Accept/Reject buttons** in the diff editor toolbar. The user had to switch back to the sidebar chat to click "Run" or "Reject".

---

## 3. Implementation in CrusorAI Agent

All enhancements have been implemented and verified with automated test suites:

### A. Rich Diff & Risk Payloads in Engine (`src/graphs/chat_graph.py`)
- Upgraded `SafeToolNode._diff_payload`:
  - **File Mutations (`write_file`, `edit_file`, `copy_file`)**: Automatically computes unified diff text via `difflib.unified_diff`, counts exact additions and deletions (`stats: {added, removed}`), identifies the action type (`create`, `modify`, `copy`), and populates `diff`, `path`, `relative_path`, `old_text`, and `new_text`.
  - **Terminal / Shell Tools (`run_terminal`, `terminal`, `execute_code`)**: Emits structured shell metadata `{ kind: "shell", command: cmd, risk: risk_explanation }`.

### B. In-Chat Inline Diff Preview & Warnings in Approval Dock (`crusorAIRenderer.ts`)
- **Warning Banner**: When `approval.warning` is present (e.g. git-ignored file or dangerous command), displays a distinct warning box with a shield/warning icon and reason.
- **Inline Diff Card**: If `approval.diff` contains unified diff data, displays:
  - An action badge (`Create`, `Edit`, `Copy`).
  - Target file path.
  - Diff stats badge (`+added âˆ’removed`).
  - An inline syntax-tinted diff preview directly in `approvalDock`, giving the user immediate visual confirmation before clicking Run.
- **Shell Risk Badge**: For terminal commands, displays a dedicated risk badge highlighting the reason (e.g., recursive deletion, command substitution).
- **Preserved Shortcuts**: Run (âŒ˜/Ctrl+Enter), Reject (Esc), and session-allow dropdown remain intact.

### C. Active Diff State Management & Editor Title Commands (`crusorAIWorkbenchService.ts`, `crusorAI.contribution.ts`)
- Added context key `crusorai.hasActiveDiff` bound to `IContextKeyService`.
- Added active diff tracking in `CrusorAIWorkbenchService` that tracks `openInlineDiff` requests and listens to `onDidActiveEditorChange`.
- Registered workbench commands:
  - `crusorai.acceptDiff` (**Accept Change**, `Codicon.check`, `navigation@1`)
  - `crusorai.rejectDiff` (**Reject Change**, `Codicon.close`, `navigation@2`)
  - Both surfaced in `MenuId.EditorTitle` whenever `crusorai.hasActiveDiff` is active.
- Added `onDidResolveDiff` event emitter connecting editor title actions back to `crusorAIRendererService` (`replyToSafety(toolId, approved)`), automatically closing the diff tab upon resolution.

### D. Robust Diff Opening & Webview Parity
- **Robust Diff Opening (`crusorAIRendererService.ts`)**: Fixed `openDiff(toolId)` to recognize `write_file` (`content` property) and `relative_path`, defaulting `originalText = ''` for newly created files instead of throwing errors.
- **Webview UI Parity (`crusor-webview/`)**:
  - `crusor-webview/src/hermes-ui/crusor/normalize.ts`: Extracted `diff.diff` and `relative_path` into `approval.diff`.
  - `crusor-webview/src/hermes-ui/components/tool-card.tsx`: Rendered `FileDiffPanel` inside `ApprovalRow` whenever approval diff payloads exist.
  - `crusor-webview/src/hermes-ui/model/fallback-model.ts`: Extended `inlineDiffFromResult` to handle backend receipts formatted with `Diff preview:\n...`.
  - `crusor-webview/src/hermes-ui/model/changed-files.ts`: Derived exact `lines added: X, removed: Y` stats from backend tool results.


---

## 4. Test Verification Summary

- `src/tests/test_copilot_parity_permission_diff.py`: **6 passed**
- `src/tests/test_safety_guard_consent.py`: **18 passed**
- `src/tests/test_desktop_renderer_architecture.py`: **53 passed, 1 skipped, 1 xfailed**
- `src/tests/test_hermes_run_summary_parity.py`: **2 passed, 2 skipped**
- `src/tests/test_hermes_activity_parity.py`: **4 passed, 6 skipped**
- **Overall**: **83 passed, 8 skipped, 1 xfailed (strict), 0 failed.**

