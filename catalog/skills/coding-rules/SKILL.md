---
name: coding-rules
description: Rules every coder follows whatever the language - read before writing against code, no partial migrations, stop when a rule blocks. Preloaded by coders and reviewers.
---

# Coding rules

- **Read the dependency before writing against it.** Confirm the real API (CodeGraph `node`), never a remembered one.
- **No partial migrations.** No bridges (old and new paths both live), no shims, no adapters kept "for now", no
  deprecated-but-still-called functions. Migrate every call site in the same change, or stop and say the full set
  cannot be done in one request.
- **When a rule blocks the request, stop and report.** Never work around it, never add a bridge to avoid it, never
  leave a TODO promising compliance later.
- Delete dead code you create; never leave it "for later".

## Slop: patterns to avoid (SlopCodeBench, arXiv 2603.24755)

Measured on agents: these cut verbosity by a quarter to a third and complexity concentration by a third to a
half at the first write. The slop receipt (`make slop-check`) measures them after you; the lead sends work back
over the bound.

- No defensive checks or try/catch beyond what the contract or the called API requires.
- No casts, `as`, `unsafe`, `!` or `Any` to get past the type checker.
- No variable used once after its declaration: use the expression.
- No comment a human maintainer would not write. The code says what; a comment says why, when why is not obvious.
- No trivial wrappers: a function whose body is one call to another function.
- No heavy nesting, no if/else ladders: early return, `match`/`switch`, `guard`.
- No helper sprawl: do not split a function to make it look simpler; split it when two callers need the part.
- No god functions: logic patched into an already-large function goes into a new focused one. Cyclomatic
  complexity over 10 in a function you touched is a finding against you. The helper-sprawl rule above does not
  apply to a function over 10: there, moving one whole responsibility into a focused function is the fix, even
  with one caller.
- No scratch files, debug output, or generated copies left in the tree. What you create to work, you delete.
- Small files (CHARTER-small-code-files): a file an agent can read in one pass.
