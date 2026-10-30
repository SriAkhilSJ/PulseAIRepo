---
name: desktop-automation-architect
description: Architect-level agent-operability for desktop apps — exposing a real accessibility tree on macOS, Windows and Linux, stable element references, overlays and surfaces that trap automation, permission prompts that block first contact, and observing results instead of trusting return codes. Use when an app must be operable by agents, scripts or assistive tech.
license: MIT
compatibility: NSAccessibility, UIA, AT-SPI; Chromium/Electron web accessibility; TCC
metadata:
  crusor-domain: desktop-architect
  crusor-path: desktop-architect/platform-architect/desktop-automation-architect
  crusor-origin: adapted
  crusor-sources: "github.com/vercel-labs/agent-desktop@da8a0c24fcec91442e47ca09945e6bc14ced7c83 (Apache-2.0)"
  crusor-triggers: "computer use, desktop automation, agent operable app, accessibility tree, ui automation refs, tcc permission, screen automation, gui agent, snapshot app, agent click, click through, automate desktop, automate our app, agent drive, automate our desktop"
  crusor-verified-on: "2026-10-30"
---

# Desktop Automation Architect

If an agent or a script has to drive your app, **the accessibility tree is your API**.
Apps that expose it well are automatable on day one; apps that draw their own
controls are not automatable at all.

Adapted from `vercel-labs/agent-desktop` (Apache-2.0), which drives macOS, Windows and
Linux apps through the OS accessibility tree and documents where that breaks.

## When to use

- Your app will be driven by agents, RPA, QA harnesses or kiosk scripts.
- Assistive-technology support and automation share one contract — build it once.
- Users ask for "computer use" support or an automation API over the GUI.

## When NOT to use

- A headless service with a documented API; expose the API, not the pixels.
- One-off internal scripting where a CLI already exists.

## Decision 1 — Expose the tree, not just pixels

- Native controls publish role, name, value, state and actions automatically; custom
  drawn surfaces must implement them explicitly (see `desktop-accessibility-architect`).
- Web content in Electron needs the Chromium accessibility bridge enabled and a tree
  that survives outside screen-reader mode; verify with an inspector, not by hope.
- Give every interactive element a stable, human-meaningful name — "Button 7" is
  unusable for both agents and screen readers.
- Distinguish semantic actions (invoke, set value, select) from physical events
  (click at coordinates); only the former survive layout changes.

## Decision 2 — Stable references

- Automation tools hand out opaque refs bound to a snapshot; they go stale as soon as
  the UI changes. Re-snapshot the region after each action rather than caching refs.
- Apps help by keeping element identity stable across rebuilds: same accessibility
  identifier for the same logical control, even when recycled in a list.
- Virtualised lists are the worst case — expose counts and scroll semantics, not just
  the visible rows.

## Decision 3 — Surfaces and overlays

- Menus, sheets, alerts and popovers are separate surfaces: while one is open, the
  window tree behind it is the wrong target.
- Automatable apps announce overlays when they open and return focus on close.
- Modality must be real: no invisible overlay swallowing clicks.

## Decision 4 — First contact and permissions

- macOS gates this behind Accessibility (and Screen Recording for screenshots)
  permissions granted to the *launching* app; plan for a guided setup and a clear
  failure state.
- Windows and Linux have their own trust prompts and udev/session limits; document
  per platform.
- Detect and report a missing permission as a distinct error, never as "element not
  found".

## Decision 5 — Verify by observation

- An action's return code does not prove an effect: platform APIs can report success
  for a no-op, and some apps acknowledge without acting.
- Re-read the affected region after every action; treat automation as
  observe → act → verify.
- Prefer waits on state change over fixed sleeps; a sleep is a race with a flaky
  outcome.
- Never retry an action the platform reported as unsafe to retry — a menu opened into
  an unresponsive app is not a transient.

## Failure modes at scale

- Canvas-drawn UI with no accessible names; nothing can drive it, including a screen
  reader.
- Refs cached across a re-render; the agent clicks the wrong control.
- Permission prompts dismissed as "app broken" in the first automation run.
- Automation asserting success on an action that silently did nothing.
- Overlay menus left open by a failed step; every later step targets the wrong tree.

## Verification receipts

1. Accessibility tree audit of the three core flows on each OS.
2. A scripted observe → act → verify run through those flows, recorded.
3. Stable-identifier convention applied in the component library.
4. Permission setup documented and exercised on a clean machine.
5. Failure taxonomy distinguishing missing permission, stale ref and unresponsive app.
