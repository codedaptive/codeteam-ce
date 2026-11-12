---
name: gate-procedures
description: How review gates are performed - blast radius counts, contract parity, path equivalence, test evidence. Preloaded by reviewers and guards.
---

# Gate Procedures

How the review gates are actually performed. Agent files say which
check to run; this says how.

## Blast radius verification

Claimed sites are a hypothesis. Count real ones.

1. For every symbol the request names, `rg -n '\bSYMBOL\b'` across the
   repo, excluding build output.
2. Count call sites, not matches — a definition and a comment are not
   call sites.
3. Compare to the request's claim. Under-count is a blocker; the
   request does not know its own reach.
4. Check both ports where the repo is dual-port. A symbol changed in
   one and not the other is a partial migration.
5. Report `claimed N / found M`, and name the sites the request missed.

## Contract parity

Applies to any new or modified data contract — a struct, row, payload,
or schema that parallels an existing surface.

1. Identify the surface the new contract parallels.
2. List every field of the parallel surface.
3. List every field of the new contract.
4. Any field present in one and absent in the other is a parity failure
   unless the request states why it is intentional.
5. Check the serialization key set matches the stored field set.
6. Report field-by-field, not as a verdict alone.

## Path equivalence

Where two code paths should produce the same result:

1. Name both paths.
2. Identify the inputs each accepts and the outputs each produces.
3. Any input handled by one and not the other is a divergence.
4. Error behavior counts: one throwing where the other returns a
   sentinel is a divergence.

## Test execution verification

A pass claim is worthless without evidence.

1. Re-run the project test command yourself.
2. Compare pass count to the recorded baseline.
3. A drop is a regression even if the suite is green.
4. Paste the command and its tail output. No paste, no claim.

## Estate query — before starting

Search the wings named in PROJECT.md for prior work on the target
symbols, prior blast radius reports, and prior reverts. A previously
reverted approach is a blocker until the request explains what changed.
