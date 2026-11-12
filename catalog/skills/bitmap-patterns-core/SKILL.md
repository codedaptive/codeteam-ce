---
name: bitmap-patterns-core
description: >-
  Bitmap field pattern (the PRINCIPLE, product-neutral). Hard rule: no
  Bool stored fields on persisted entities — pack boolean state into an
  Int64 bitmap and expose computed accessors. Covers the rule, the
  reasoning, the accessor pattern, the test pattern, and the invariants.
  This skill is the HOW. The authoritative bit ledger (which bit means
  what, on which entity) is PRODUCT-SPECIFIC and lives in your repo's
  own bitmap-patterns skill — read that for ground truth. Trigger on:
  bitmap, bit assignment, Bool field, flag accessor, bitmap migration.
status: active-finalized
tags: [skill, engineering, fleet-generic]
last_reviewed: 2026-06-02
---


# Skill: Bitmap Patterns — Core Principle (product-neutral)

This skill is the **how**. It is identical across every product in the
fleet. It contains NO product ground truth — no real entity names, no
real bit assignments. Those are product-specific.

> **Before adding any bit, read your repo's own `bitmap-patterns`
> skill** (in this repo's `.claude/skills/bitmap-patterns/`). That
> product skill carries the authoritative bit ledger for THIS product:
> the real entities, the real bitmap fields, and which bit positions
> are already taken. This core skill tells you the rule and the
> mechanics; the product skill tells you the actual layout. Never copy
> bit positions or entity names from examples in this core skill — they
> are illustrative placeholders, not your product's truth.


## ⛔ THE HARD RULE — READ THIS FIRST

**Adding a `Bool` stored field to ANY persisted entity is a schema
violation.** No exceptions, on any entity, in any product.

If you are about to write `public var someFlag: Bool` as a stored
property, stop. Find the correct bitmap field for that entity and add a
bit. A stored Bool field on an entity will fail code review.

The reason: a stored Bool requires a new persistence column for every
new flag. A bitmap field absorbs unlimited new flags with zero schema
migrations, ever. This is the long-horizon design principle.

**The only acceptable Bool in entity code is a computed property that
reads from a bitmap.** That is not a stored field — it is a computed
accessor, and it is correct and required.


## Choosing the right bitmap

When you need a new boolean on an entity, pick the bitmap whose domain
the flag belongs to (behavior flags, feature toggles, privacy settings,
lifecycle state, etc.). **The list of real bitmap fields for your
entities is in your repo's product `bitmap-patterns` skill.** If a flag
clearly belongs to an existing bitmap's domain, use it. If genuinely
none fits, create a new `Int64` bitmap field — never a Bool.


## Adding a new flag — step by step

1. Open your repo's product `bitmap-patterns` ledger; identify the
   correct bitmap and the next FREE bit.
2. Add the constant to the correct `+Flags` extension.
3. Update the assigned-bits comment block (keep it complete).
4. Add the computed getter/setter (pattern below).
5. No persistence-schema change needed — the bitmap column exists.
6. Add the four tests per flag (pattern below).
7. Record the newly-taken bit position back in the product ledger.


## Canonical accessor pattern (illustrative entity — NOT real)

`Entity` and `entityFlags` below are PLACEHOLDERS. Substitute your
product's real entity and bitmap field from the product skill.

```swift
public extension Entity {

    // ASSIGNED BITS — never change a value, never reuse a position.
    // Keep this comment block complete and current.
    // bit 0:  flagExample
    // bit N:  YOUR_NEW_FLAG   <- add at the next free bit
    // remaining bits: reserved

    static let flagYourNewFlag: Int64 = 1 << N  // next free bit

    var yourNewFlag: Bool {
        get { entityFlags & Entity.flagYourNewFlag != 0 }
        set { entityFlags = newValue
              ? entityFlags | Entity.flagYourNewFlag
              : entityFlags & ~Entity.flagYourNewFlag }
    }
}
```


## Persistence storage

A bitmap field maps to an integer column, `NOT NULL DEFAULT <value>`,
where the default encodes the initial state (which bits start set).
Read and write it as `Int64` — never a narrower integer type.

```swift
let flags = readInt64(column)        // reading — always Int64
bindInt64(param, entity.entityFlags) // writing — always Int64
```


## Testing pattern — four tests per flag

```swift
// 1. Default is false
func testFlagDefaultIsFalse() {
    let e = Entity(/* minimal */)
    #expect(e.yourNewFlag == false)
}

// 2. Set true sets the bit
func testFlagSetTrue() {
    var e = Entity(/* minimal */)
    e.yourNewFlag = true
    #expect(e.yourNewFlag)
    #expect(e.entityFlags & Entity.flagYourNewFlag != 0)
}

// 3. Clear does not disturb other bits
func testFlagClearIsolated() {
    var e = Entity(/* minimal */)
    e.someOtherFlag = true
    e.yourNewFlag = true
    e.yourNewFlag = false
    #expect(e.yourNewFlag == false)
    #expect(e.someOtherFlag)   // unchanged
}

// 4. Serialization round-trip preserves the bit
func testFlagRoundTrip() throws {
    var e = Entity(/* minimal */)
    e.yourNewFlag = true
    let decoded = try roundTrip(e)
    #expect(decoded.yourNewFlag)
}
```

(Examples use swift-testing `#expect` / `@Test`. XCTest is retired —
do not write new XCTest suites.)


## Invariant — add once per entity

Never assign bit 63 (the `Int64` sign bit). Guard it:

```swift
func testNoSignBitInDefault() {
    #expect(Entity(/* minimal */).entityFlags & Int64.min == 0)
}
```


## Hard rules — violations break the schema

- **NEVER** add a `Bool` stored property to a persisted entity.
- **NEVER** reuse a bit position once assigned.
- **NEVER** change the `Int64` value of an existing constant.
- **NEVER** assign bit 63 (the sign bit).
- **NEVER** add computed Bool properties to the serialization key set.
- **ALWAYS** use `Int64` — never `Int`, never `Int32`.
- **ALWAYS** test with bitwise AND: `flags & constant != 0`.
  Never `flags == constant` (wrong once other bits are set).
- **ALWAYS** update the assigned-bits comment block AND the product
  ledger when adding a bit.
