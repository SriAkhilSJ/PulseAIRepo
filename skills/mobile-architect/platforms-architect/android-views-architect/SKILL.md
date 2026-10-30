---
name: android-views-architect
description: Architect-level work in Android View codebases — Activity and Fragment lifecycles, ViewBinding, RecyclerView performance, Navigation Component, and the incremental migration path to Compose that does not require a rewrite. Use when maintaining or modernising a Jetpack View app.
license: MIT
compatibility: Android Views, ViewBinding, RecyclerView, Navigation Component
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/platforms-architect/android-views-architect
  crusor-origin: original
  crusor-sources: "developer.android.com/develop/ui/views; developer.android.com/topic/libraries/view-binding; developer.android.com/guide/navigation"
  crusor-triggers: "android views, recyclerview, fragment lifecycle, viewbinding, navigation component, xml layouts, android legacy, activity lifecycle"
  crusor-verified-on: "2026-10-30"
---

# Android Views Architect

Views are **lifecycle plus adapters plus XML**. Most legacy problems are fragments
talking to each other and adapters doing work they should not.

## When to use

- Maintaining an existing XML/View app.
- Migrating screens to Compose incrementally.
- RecyclerView performance or fragment lifecycle bugs.

## When NOT to use

- Greenfield Android UI → `android-compose-architect`.
- Cross-platform UI → `react-native-architect` / `flutter-architect`.

## Decision 1 — Structure

- One Activity hosting fragments via Navigation Component; multiple activities only for
  deep-link entry points or separate tasks.
- `ViewModel` per screen surviving configuration change; no state in fragment fields.
- Fragment-to-fragment communication through the nav graph or a shared view model, never
  direct references.
- ViewBinding everywhere; `findViewById` is a source of NPEs and typos.

## Decision 2 — Lifecycle

- Register listeners in `onViewCreated`/`onStart`, remove in `onDestroyView`/`onStop`.
- `viewLifecycleOwner` for LiveData/Flow collection in fragments — using the fragment's
  lifecycle leaks views.
- Do not retain view references in the view model.
- Process death: state in `SavedStateHandle` if a user would notice losing it.

## Decision 3 — Lists

- RecyclerView with `ListAdapter` + `DiffUtil`; identity by stable id, not position.
- Avoid nested scrollables; a RecyclerView inside a ScrollView loses recycling.
- Images loaded with a bounded cache and downsampling.
- View holder binding is cheap: no network, no heavy formatting per bind.

## Decision 4 — Layout

- ConstraintLayout for complex screens; LinearLayout/FrameLayout for simple ones.
- Fixed heights around text break at large font scales — use wrap content and scroll.
- Include `layout-land`/`layout-sw600dp` only where the design genuinely differs.
- Dark mode and dynamic colour from day one; hardcoded colours are a migration.

## Decision 5 — Migration to Compose

- Compose inside a fragment via `ComposeView`, or a Compose activity for new flows.
- Migrate leaf screens first; keep navigation in one system until the end.
- Share the design system: one set of tokens, both toolkits, or they diverge.
- Do not maintain the same screen twice for long — feature-flag the new one and delete
  the old.

## Failure modes at scale

- Fragments holding direct references to each other; leaks and crashes on rotation.
- Flow collected with the fragment lifecycle; views updated after `onDestroyView`.
- DiffUtil comparing whole models; full rebinds on every change.
- RecyclerView inside a NestedScrollView; jank and lost state.
- Half-migrated navigation with two back stacks.

## Verification receipts

1. Screen inventory with View/Compose status and migration order.
2. LeakCanary report clean after a navigation sweep.
3. RecyclerView frame timing on the heaviest list.
4. Rotation and process-death test on a form screen.
5. One screen migrated with tests still passing.
