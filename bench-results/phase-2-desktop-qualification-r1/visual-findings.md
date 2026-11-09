# Visual findings — native desktop

All findings are from real captured windows (`screenshots/*.png`), not DOM
assertions. The qualification ran on Windows 11 Pro 10.0.26200, 1878×1000
workbench window, dark theme ("Dark 2026") default.

## Surfaces inspected

| Screenshot | Surface | State |
|---|---|---|
| `01_workbench_startup.png` | workbench shell, Explorer, welcome editor | empty workspace, dark |
| `02_agent_panel_open.png` | Crusor Agent view | empty composer |
| `04_manager_open.png` | Crusor Manager editor | populated, 3-pane |
| `05_isolated_workbench.png` | workbench shell, second profile | empty |
| `06_cancel_inflight.png` | Agent | running (`Thinking`, `Esc to interrupt`) |
| `07_cancel_result.png` | Agent | cancelled receipt |
| `08_before_reload.png` | Agent | two completed turns + cancellation |
| `09_worker_killed.png` | Agent | `Engine starting` |
| `10_after_recovery_turn.png` | Agent | post-recovery completed turn |
| `11_cold_manager.png` | Manager | cold start, session restored |
| `12_approval_dock.png` | Agent | approval dock |
| `13_approval_approved.png` | Agent | approved tool result |
| `14_approval_denied.png` | Agent | denied tool result |
| `15_theme_picker_attempt.png` | Agent + theme picker | failure-card rendering |
| `16_theme_setting_attempt.png` | Agent | after profile theme write attempt |
| `17_approval_dock_layout.png` | Agent | approval dock, measured overflow |

## Finding 1 — approval dock clips its primary action (HIGH)

At the default auxiliary-bar width the approval dock is wider than its column:

```
auxiliary bar clientWidth : 299 px
approval dock clientWidth : 299 px
approval dock scrollWidth : 419 px   (120 px overflow)
Allow once button         : x=1255  w=148      -> right edge 1403
dock right edge           : x=985 + 299 = 1284 (119 px of the button clipped)
question text             : collapses to a 1-character column, dock height 303 px
```

The primary `Allow once` verdict is partially outside the panel and the question
wraps vertically. The panel has `overflow` clipping rather than a scrollbar
(`scrollWidth - clientWidth === 0` on the part), so the action cannot be reached
by scrolling. Deny and Allow always remain visible. This is a usability defect
in the most safety-critical surface; it is reproducible on every approval in this
build.

## Finding 2 — denied tool result renders raw JSON (LOW)

The failed tool card prints the result object verbatim:

```
Failed
{
  "ok": false,
  "reason": "denied by user"
}
```

Functionally clear, visually unpolished; expected copy would be a human sentence
(which the following assistant line does provide).

## Finding 3 — Manager row label vs session title (LOW)

The sidebar row is labelled `Crusor session` while the main pane title is the
first prompt (`phase2 qualification ping`). State (`Finished`) and recency (`1m`)
agree, so this is naming consistency only.

## Finding 4 — echo test mode is not announced in the transcript

The bridge emits a `runtime_degraded` notice saying no model was called and the
reply is the user's own text, but the painted transcript shows only the echoed
text plus the generic "Agent Core evidence capture is degraded" row. A tester
reading only the panel could mistake the echo for a real answer. Test-seam
behaviour, not a shipping-path defect.

## Passed visual checks

- Three-pane Manager layout is aligned and unclipped at 1878 px.
- No horizontal overflow in the Agent panel or the transcript (`0` in both).
- Running, completed, cancelled, denied and recovered states are visually
  distinct (icon + copy + receipt class).
- Empty vs populated transcript states are distinct.
- Toolbar, title bar, command center, activity bar and status bar render
  correctly; the Crusor command-center icon is present.
- Interactive controls are native focusable elements (`button`, `textarea`);
  tab order includes Manager, Copy, send, mode chips and tabs.
- No renderer crash, no white flash, no stuck spinner after the worker kill.

## Not exercised

- Light theme: the dev build's theme picker returned marketplace entries only;
  writing `workbench.colorTheme` into the disposable profile was reset to `{}`
  on reload. Both attempts left the dark theme active.
- High-DPI scaling, RTL, and screen-reader announcement.
- Narrow window widths below the default panel width.
