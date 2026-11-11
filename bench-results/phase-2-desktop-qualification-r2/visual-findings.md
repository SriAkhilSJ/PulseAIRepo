# Visual findings — r2

Real screenshots only (`screenshots/*.png`), 1878×1000 workbench.

## Fixed — approval dock at 299 px

`02_approval_dock_fixed_299px.png`: the strip fits the default auxiliary bar.
Measured `overflow: 0`; the question occupies 257 px on one line; `Deny` /
`Allow always` share one row; `Allow once` wraps to its own row, fully visible
(148×32); `Review change` remains visible. In r1 the same dock had 120 px of
overflow and a clipped primary action.

`03_approval_allowed.png`: after clicking `Allow once`, the dock disappears and
the tool card settles to `Approved write applied to notes.md.`

## Fixed — typography contract

The four raw sizes in `crusorAI.css` (context chip, chip remove glyph,
suggestion title/detail) now use `--crusorai-text-meta`,
`--crusorai-text-micro` and `--crusorai-text-body`. The type-grammar test and a
new selector-level regression pass.

## New finding — light theme leaves the Crusor pane black (MEDIUM)

`04_approval_dock_light_theme.png`: with the built-in `Default Light Modern`
theme, the workbench (activity bar, explorer, editor, title bar) is light while
the whole Crusor pane stays black (`panelBg: rgb(0,0,0)`). The approval dock is
still readable and fits, but the pane does not follow the host theme. This is a
theme-derivation defect in the pane surface, independent of the dock fix.

## Startup diagnostics (all non-blocking, none new)

| Message | Classification |
|---|---|
| `Cannot find module './build/Release/iselevated'` | expected — optional native module not built in this checkout |
| `Unable to create workbench contribution 'chat.contextContributions'` | product defect in the built-in chat contribution (DI), unrelated to Crusor |
| `Unknown channel: agentHostClientProxy` | harmless IPC probe |
| crashpad `CreateFile: ... 0x2` | environment; crash reporter registration in the disposable profile |

No renderer crash, blank pane, boot loop, or clipped layout other than the
theme issue above.

## Ctrl/Cmd+L

OS-level input injection never reached the app in this session (AppActivate
False; `Ctrl+Shift+P` control chord also ignored), and CDP key delivery did not
open the pane. The command palette command works. Recorded as NOT PROVEN, not as
a visual defect.

## Manager

`08_manager_render.png`: three-pane layout, aligned tabs and breadcrumb, sidebar
count `1 session(s) remembered · none running`, inspector `19/30` capabilities.
No clipping or overlap.

`09_cold_manager_empty_transcript.png`: session row restored after restart,
empty transcript (echo seam), layout intact.

## Passed checks

- Approval dock readable and complete at 299 px (dark and light workbench).
- Running / cancelled / completed / approval states visually distinct.
- Manager and Agent layouts stable; no horizontal overflow in the pane.
- Native buttons/textarea are focusable; keyboard tab order exists.
- Dark theme renders correctly.

## Not exercised

- Light-theme paint of the Crusor pane (it fails; no further themes tested).
- RTL, high-DPI scaling, screen-reader announcements.
- Window widths below the default auxiliary bar (fixed 299 px is the default).
