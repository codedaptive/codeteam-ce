---
name: swiftui
description: Load when building or changing SwiftUI views, gestures, drag-reorder or platform layout. Platform decisions, native-first drag and swipe, cross-platform mappings.
---

# Swift / SwiftUI Rules — Path-Scoped Always-Applies

These rules apply to any work touching a `.swift` file in any
product. Procedural patterns (the *how* — gesture stacks,
view composition, reorder implementation steps) live in the
skills under `agents/_skills/`. This rule covers the *what* and the
*never*.

## Platform decision (always)

All apps
use **SwiftUI as the primary UI framework**. UIKit is used only via
`UIViewRepresentable` bridges (or `NSViewRepresentable` on macOS) for
specific interactions where UIKit produces demonstrably better results
than SwiftUI's gesture system or view system — and, since iOS 27 /
macOS 27, that set of interactions no longer includes drag-reorder or
swipe actions (see below).

Bridges must be:

- **Small** — typically ~40 lines of wrapper code per interaction.
- **Surgical** — wrapping JUST the specific interaction, not whole
  view hierarchies.
- **Well-isolated** — testable as a standalone component, applied to
  any list/view that needs it.

If a bridge would exceed ~100 lines or wrap an entire screen, that's
not a surgical bridge — that's a UIKit screen, and it's not allowed
without an explicit ADR.

## Why SwiftUI (rationale, summary)

These are the reasons the platform decision exists, in order of
durability:

- **Multi-platform compilation.** SwiftUI views compile directly for
  iOS, iPadOS, macOS, and visionOS with minimal changes. Outline view,
  detail pane, spider graph — all shared code. A UIKit app needs a
  complete rewrite using AppKit for macOS and has essentially zero
  path to spatial computing.
- **Free platform features.** Animations, transitions, dark mode,
  Dynamic Type, accessibility, RTL layout — all essentially free.
  UIKit requires manual wiring for all of these.
- **Declarative composition.** Custom visual components (spider
  graphs, dot indicators, legal pad styling) are dramatically less
  code in SwiftUI than in `drawRect`/`CALayer` UIKit.
- **Input device abstraction.** `.onTapGesture` → trackpad click,
  `.onLongPressGesture` → click-and-hold, drag gestures → click-drag,
  all automatic. Pinch and swipe need `#if os(macOS)` adaptations,
  but adaptation, not rewriting.

UIKit is in maintenance mode. WWDC since 2019 has pushed SwiftUI
harder every year. WidgetKit, App Intents, visionOS — all SwiftUI-first
or SwiftUI-only. iOS 27 closed the last interaction gap this rule
tracked (drag-reorder + context-menu coexistence).

## Drag-reorder and swipe actions: NATIVE-FIRST (iOS 27 / macOS 27 floor)

For any product whose deployment floor is iOS 27 / macOS 27 or later,
drag-reorder and swipe actions are built on the **native SwiftUI
interaction APIs**, not a UIKit bridge:

- `.reorderable()` — per-row reorder participation.
- `reorderContainer(for:isEnabled:move:)` — container-level reorder
  coordination; the `move:` closure is the commit hook.
- `swipeActionsContainer()` + `.swipeActions` — swipe actions outside
  `List`.

All four are `@available(iOS 27, macOS 27)`, verified in the Xcode 27
beta SDK swiftinterface. Products at the 27 floor need no availability
guards. This doctrine replaced the previous bespoke UIKit-adjacent drag
stack.

### Measured truths (verified on real hardware)

These are load-bearing facts about the native stack. Do not relearn
them by trial and error; design against them:

1. **The `move:` closure is the commit hook.** When
   `reorderContainer` consumes a drop, `performDrop` NEVER fires. Do
   not put commit logic in a `DropDelegate.performDrop` and expect it
   to run — model mutation belongs in the container's `move:` closure.
2. **Context menu + native lift arbitrate by motion, not by timing
   tricks.** A press held stationary ≥0.5s presents the context menu;
   movement during the press lifts the row for drag. Both coexist on
   the same row with no custom gesture arbitration — do not add one.
3. **Drag-band tracking via a `DropDelegate` coordinate feed works and
   is fast.** Proven on real hardware at ~55Hz. Use the delegate's
   coordinate stream for drop-zone highlighting and band positioning;
   do not poll or approximate.
4. **`swipeActionsContainer` rows expose NO custom accessibility
   actions** (unlike `List`, which surfaces swipe actions to VoiceOver
   automatically). Every swipe action outside `List` MUST be mirrored
   with explicit `.accessibilityActions` on the row. This is a
   blocking accessibility requirement, not a nice-to-have.
5. **There is no free VoiceOver reorder** on the native stack.
   MoveTargetPicker (or equivalent explicit a11y move actions) remains
   MANDATORY for reorderable content. Shipping native reorder without
   an assistive-tech path is a CRITICAL accessibility finding.

## LEGACY path: the UIKit drag-reorder bridge (sub-27 floors only)

The previous doctrine — `UIViewRepresentable` wrapping a
`UILongPressGestureRecognizer` (`minimumPressDuration: 0.3`), with the
matching `NSViewRepresentable` + `NSPressGestureRecognizer` on macOS —
is retained ONLY for products whose deployment floor is below
iOS 27 / macOS 27, where the native APIs above do not exist.

**Which products that is:** check each product's deployment target
before choosing a path; do not assume either way. New products start at
the 27 floor and use the native path.

If you believe you need the legacy bridge, first confirm the product's
deployment floor in its project settings. Introducing the bridge into a
27-floor product is a doctrine violation and will be flagged at review.

For the legacy implementation pattern, read
`agents/_skills/drag-reorder-pattern/SKILL.md` — and note that skill
documents the LEGACY path.

## What NOT to do in SwiftUI gesture handling

These prohibitions apply to any new code touching `.swift` files:

1. **Do not build a UIKit/AppKit drag-reorder bridge in a 27-floor
   product.** The native APIs (`.reorderable()`, `reorderContainer`)
   are the doctrine. The bridge is legacy-only (see above).
2. **Do not put reorder commit logic in `DropDelegate.performDrop`
   when `reorderContainer` owns the drop.** It never fires; the
   `move:` closure is the commit hook.
3. **Do not add custom gesture arbitration between context menu and
   drag lift on reorderable rows.** The system arbitrates by motion
   (stationary ≥0.5s → menu; movement → lift). Custom timers or
   competing `LongPressGesture` instances fight the system behavior.
4. **Do not compose `LongPressGesture.sequenced(before: DragGesture())`**
   for production drag reorder. It still breaks when `.contextMenu` is
   attached; the native reorder APIs exist precisely so this
   composition is never needed.
5. **Do not ship `swipeActionsContainer` rows without explicit
   `.accessibilityActions`** mirroring each swipe action, and do not
   ship reorderable content without an explicit assistive-tech move
   path (MoveTargetPicker or equivalent). Neither comes free.

## Cross-platform mappings (always-applies)

| Platform | Reorder / swipe implementation | Why |
|---|---|---|
| iOS (27+) | Native: `.reorderable()` + `reorderContainer(for:isEnabled:move:)`; `swipeActionsContainer()` + `.swipeActions` | First-party APIs; motion-based menu/lift arbitration; no bridge to maintain |
| iPadOS (27+) | Same as iOS, plus Stage Manager window support (free from SwiftUI scenes) | Native APIs are size-class-agnostic; window management is SwiftUI |
| macOS (27+) | Same native APIs (`@available(macOS 27)`) | Shared code; pointer press-and-move maps to the same lift semantics |
| visionOS | Native SwiftUI spatial gestures | Was already native-only; unchanged |
| Any product below the 27 floor | LEGACY UIKit/AppKit bridge (see legacy section) | Native APIs unavailable pre-27; check the product's deployment target |

One native code path across iOS, iPadOS, and macOS — the legacy table
row exists only as an escape hatch for sub-27 floors.

## What lives where

- **Always-applies (this rule):** the platform decision, the bridge
  policy, the native-first reorder/swipe doctrine and its measured
  truths, the don't-do list, the cross-platform mapping rule.
- **Procedural (skills):**
  - `agents/_skills/swiftui-platform-strategy/SKILL.md` — extended
    rationale and decision context for the platform choice (read
    when justifying or revisiting the decision).
  - `agents/_skills/drag-reorder-pattern/SKILL.md` — LEGACY bridge
    implementation pattern (sub-27 floors only; needs its own
    revision to match this rule).

If you're touching `.swift` files, this rule applies always. The
skills load when the work is specifically about platform strategy or
reorder implementation.
