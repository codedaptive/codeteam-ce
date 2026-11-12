---
name: entity-style
description: Persisted-entity and storage rules (products with an entity store) - booleans as Int64 bitmaps, dates as ISO8601 TEXT, entity schema invariants. Preloaded by coders, test writers and reviewers on products that persist entities.
---

# House style (violations are blocking findings)

## Booleans are bitmaps

**No `Bool` stored property on a persisted entity. Ever.**

All boolean state lives in an `Int64` bitmap field. Bool is a computed
accessor over a bit.

```swift
public var operationalBitmap: Int64 = 0
public var isArchived: Bool {
    get { operationalBitmap & (1 << 3) != 0 }
    set { ... }
}
```

Every system carries a bitmap field or bitmap table for booleans,
flags, and filters. If you are about to store a boolean, you are about
to assign a bit instead.

Before touching entity code read the `bitmap-patterns-core` skill
for current bit assignments. Then:

- NEVER reuse a bit position once assigned
- NEVER change the `Int64` value of an existing constant
- NEVER assign bit 63 (sign bit)
- NEVER put a computed Bool in a serialization key set
- ALWAYS `Int64`, never `Int` or `Int32`
- ALWAYS test bitwise: `flags & constant != 0`
- ALWAYS update the assigned-bits comment block when adding a flag

## Dates are TEXT

ISO8601 strings. Never `REAL`, never Unix timestamps.

```sql
created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
```


## Entities
Every commit that touches an entity type (Drawer, Tunnel, KGFact, DiaryEntry, or any new noun) must comply with the
rules above. Before writing entity code, read the `bitmap-patterns-core` skill for the current bit
assignments.
