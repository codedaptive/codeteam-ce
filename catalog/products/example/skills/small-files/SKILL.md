---
name: small-files
description: acme-widgets' small-code-files rules - one public symbol per file, 150 lines, naming, sibling tests, where a function lives. Preloaded by coders, test writers and reviewers.
---

# Small code files

Applies to all new code.

1. **One public symbol per file:** one public function, type or trait, plus private helpers nothing else uses.
   A type's methods each get their own file (one `impl` block per file).
2. **Named after the symbol,** snake_case: `open_database.rs`. Folders follow the module path.
3. **At most 150 lines,** comments included; test files don't count. Over the limit: stop and ask the lead to
   split it. A file allowed past the limit says why in its header comment.
4. **Bridges:** each folder's `mod.rs` declares its files and `pub use`s the public symbols; `lib.rs` is the crate's.
5. **Tests:** each source file has a sibling `<name>_tests.rs`, declared test-only in `mod.rs`. Tests of pieces
   working together go in the crate's `tests/` folder, against the public surface.
6. **Where a function lives:** the lowest level that covers all its callers (crate-internal, then a lower crate).
   When a second caller elsewhere needs it, it moves down to the crate both depend on; it is never copied. Moving
   code into another lane's crate needs the orchestrator's approval: ask, don't do.
7. **Identical behaviour is centralized; similar functions stay separate** until they converge.

A reviewer reports any breach as a finding with the file and the rule number.
