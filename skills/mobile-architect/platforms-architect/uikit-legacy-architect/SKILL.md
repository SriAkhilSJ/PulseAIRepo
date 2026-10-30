---
name: uikit-legacy-architect
description: Architect-level work in UIKit codebases — view controller lifecycles and containment, Auto Layout at scale, diffable data sources, Combine and delegation boundaries, and the incremental migration path to SwiftUI that does not require a rewrite. Use when maintaining or modernising a UIKit app.
license: MIT
compatibility: UIKit, iOS 15+, Swift
metadata:
  crusor-domain: mobile-architect
  crusor-path: mobile-architect/platforms-architect/uikit-legacy-architect
  crusor-origin: original
  crusor-sources: "developer.apple.com/documentation/uikit; developer.apple.com/documentation/uikit/views_and_controls/collection_views/updating_collection_views_using_diffable_data_sources"
  crusor-triggers: "uikit, view controller, autolayout, diffable data source, storyboard, combine, uitableview, ios legacy, xib"
  crusor-verified-on: "2026-10-30"
---

# UIKit Architect

UIKit is **explicit lifecycle and manual layout**. Its failures are retain cycles,
layout thrash, and view controllers doing five jobs — not missing frameworks.

## When to use

- Maintaining an existing UIKit app.
- Migrating incrementally to SwiftUI without a rewrite.
- Performance or layout problems in a mature iOS codebase.

## When NOT to use

- Greenfield iOS UI → `ios-swiftui-architect`.
- Cross-platform UI → `react-native-architect` / `flutter-architect`.

## Decision 1 — Structure

- One view controller, one responsibility; child controllers via containment instead
  of a 900-line controller.
- MVVM or MVI with a view model owning state; the controller renders, nothing more.
- Navigation in a coordinator/router, not scattered `present` calls.
- Dependency injection at composition root; no singletons reached from cells.

## Decision 2 — Layout

| Approach | Use |
|---|---|
| Auto Layout anchors in code | default: reviewable, diffable |
| stack views | most forms and lists |
| storyboards | small flows; merge conflicts and review pain at scale |
| manual frames | animation/performance hotspots only |

- Set `translatesAutoresizingMaskIntoConstraints = false` deliberately.
- Constraint count is performance: prefer stack views over dozens of constraints in
  cells.
- Self-sizing cells need estimated heights and stable constraints, or scrolling
  janks.

## Decision 3 — Lists

- `UICollectionView` with compositional layout + diffable data source for anything
  non-trivial.
- Stable, hashable item identifiers; identity changes cause full reloads and lost
  animations.
- Prefetch for images; decode off the main thread.
- Reuse identifiers per cell type; registering by class prevents silent mis-reuse.

## Decision 4 — Async and state

- `async`/`await` for new work; completion handlers wrapped where they remain.
- Combine only where a stream is genuinely needed; it is easy to build an
  unmaintainable pipeline.
- Cancel work in `viewWillDisappear`/task cancellation; leaked tasks duplicate network
  calls.
- Retain cycles: `[weak self]` in escaping closures and delegates — audit with the
  memory graph.

## Decision 5 — Migration to SwiftUI

- Host SwiftUI screens in a `UIHostingController` behind the existing navigation.
- Move leaf screens first; keep navigation and lifecycle in UIKit until the edges are
  SwiftUI.
- Share design tokens across both; two design systems drift immediately.
- Do not run two navigation stacks; pick one owner per flow.

## Failure modes at scale

- Massive view controllers with networking, layout, and analytics inline.
- Storyboard merge conflicts resolved by regenerating the file.
- Diffable data source with non-hashable identity; every update reloads the list.
- Retain cycles through closures holding the controller.
- Half-migrated app with two navigation systems and broken back gestures.

## Verification receipts

1. Screen inventory: UIKit, SwiftUI, or hosted — with the migration order.
2. Instruments trace of a heavy list scroll.
3. Memory graph audit showing no controller leaks after navigation.
4. Layout test at the largest text size and smallest device.
5. One screen migrated end to end with tests still passing.
