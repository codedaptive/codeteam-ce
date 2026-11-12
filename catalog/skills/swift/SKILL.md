---
name: swift
description: Swift rules for coders, test writers and reviewers - tests through make, Swift Testing, safe numeric conversion, value types.
---

# Swift

- **Build and test only through the make targets the product layer names.** Never `swift build` or `swift test`
  directly.
- **Swift Testing, not XCTest.** `xcodebuild` only for GUI work SwiftPM cannot drive, and the report says so and
  names the surface.
- A pass count lower than the baseline is a regression, even when the suite is green. Report it.
- **No unguarded narrowing:** `Int(d)`, `Int64(d)`, `UInt(d)` on a `Double` trap outside the range. Value from
  input, arithmetic or a parse: guard it, or format it as text (`String(format: "%.0f", x)`).
- **Value trees conform to `Equatable`** (enums and structs for trees, ASTs, tokens, pure values tests compare).
  `Sendable` is additive, never a substitute.
- SwiftUI view work: load the `swiftui` skill. User-visible text: load the `localization` skill.
