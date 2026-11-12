---
name: rust-cargo
description: Rust rules for coders, test writers and reviewers - builds through make only, lockfiles, dependencies, errors, unsafe.
---

# Rust

- **Build, test, type-check and format only through the make targets the product layer names.** Never call cargo
  directly: make sets the shared build folder and the compile slots; a bare cargo cold-builds a stray `target/`.
- A `Cargo.lock` change is a real change: commit it with the change that caused it.
- **No new dependency** unless your brief names it.
- **No `unwrap()` or `expect()`** outside tests. Return a typed error.
- **No `unsafe`** unless the brief allows it and the file's header comment says why.
- No `println!` for diagnostics in library code.
- Clippy warnings the repo treats as errors are errors.
