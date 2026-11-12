---
name: localization
description: Load when writing or changing any View, ViewModel or code that produces user-visible text. String(localized:), ordinals, plurals, leading/trailing.
---

# Localization

Four rules that apply to every View, ViewModel, and any code that
produces user-visible text. Violations are CRITICAL blocking findings.

## 1. Zero string literals in display text

No hardcoded strings in any View or ViewModel that produces text
the user sees. Use String(localized:) or LocalizedStringKey.

```swift
// CORRECT
Text(String(localized: "settings.appearance.title"))

// WRONG
Text("Appearance")
```

## 2. Ordinals via NumberFormatter

All ordinal numbers formatted through NumberFormatter, never
string interpolation.

```swift
// CORRECT
let fmt = NumberFormatter()
fmt.numberStyle = .ordinal
let label = fmt.string(from: NSNumber(value: position))

// WRONG
let label = "\(position)st"
```

## 3. Plurals via .stringsdict

All plural forms handled through .stringsdict rules, never
conditional string building.

```swift
// CORRECT — .stringsdict handles "1 item" vs "2 items"
String(localized: "items.count.\(count)")

// WRONG
let label = count == 1 ? "1 item" : "\(count) items"
```

## 4. Semantic layout directions

All layout uses `.leading` / `.trailing`, never `.left` / `.right`.

```swift
// CORRECT
.padding(.leading, 16)
HStack { ... } // leading-to-trailing by default

// WRONG
.padding(.left, 16)
```

## AI-generated display text

AI prompts that produce UI-visible text must include a target
locale parameter so the model generates in the correct language.
