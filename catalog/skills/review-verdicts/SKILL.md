---
name: review-verdicts
description: How a reviewer reports - PASS or FAIL with findings, what counts as a FAIL, the reason field on every finding, report and stop. Preloaded by change-reviewer.
---

# Verdicts

- **PASS** - the change does what the work order asks and its tests prove it; nothing blocking.
- **FAIL** - one or more blocking findings. Each finding: `file:line`, what is wrong, what correct looks like.
- **PASS WITH FINDINGS** - it can land; list the findings for the lead to weigh.
- **NOTE** - not a verdict and never blocking: a line after the verdict for something another lane must handle,
  such as a dependent outside this request's walls that the change breaks (codegraph skill §3), or for a test in
  the wrong group, which the request's own lane moves. Write
  `NOTE <lane>: <file:line> <what goes wrong>`. Notes do not count in `Reasons:`.

**A FAIL is** a defect: wrong behaviour, a broken contract, a missing case the work order names, a failing or
missing test for changed behaviour, a charter or comment breach in the diff.
**Not a FAIL:** a missing or stale receipt or test record (receipts belong to the lane and integration levels,
not to a request: zone-tests "Proof by level"), how evidence was recorded, style you would prefer, work outside the order, a finding you are not
sure of (report it with your confidence instead), a dependent the radius check reached that still works, a
break outside the walls (a NOTE for its lane), and a test in the wrong group (rule 11: it is moved and blocks
nothing; a NOTE to the request's own lane naming the group it belongs in), and codeteam's own commit trailers
(`Agent:`, `Model:`, `Effort:`, `Worktree:`, `Request:`, `Work-Order:`, `Zone:`, `Landed-By:`, `Doc-Level:`).

## Three checks, every review

Do each check and write its result. Each has a yes or no answer and a fixed consequence.

1. **Would the test fail if the code were wrong?** For every assertion the diff adds or changes, name one wrong
   output the code could produce and say whether the assertion fails on it. An assertion that still passes on a
   plausible wrong output (a `contains` that also matches the broken form, a count with no content check, a bound
   wide enough for the old behaviour) proves nothing: FAIL, `Reason: evidence-missing`, with the wrong output it
   lets through.
2. **Is every checkable claim in a changed comment true?** A comment or doc line in the diff that states a count, an
   order, an equality, a range, a unit or a reference ("five steps", "the names differ at their first letter",
   "per cookbook § 12.4", "in nats"): open what it cites or the code it describes and check the claim. False: FAIL,
   `Reason: comment-false`, quoting the claim and what the source says.
3. **Is every item of the order's done list done?** List the work order's done items one by one: done (with the
   file:line or record that shows it) or missing. A missing item the order requires: FAIL, `Reason: code-wrong`.
   Version bumps need their changelog entry; a renamed or moved symbol needs every doc that names it.

Write them after the verdict line as:
`Checks: assertions <n checked, n weak>; claims <n checked, n false>; done list <n of m>`.

## Reason, on every finding

Every finding, blocking or not, carries one line `Reason: <value>` with exactly one of these values:

- `code-wrong` - the code does not do what the work order asks, or breaks something it reached.
- `comment-false` - the code is right; a comment, doc or contract line says something untrue about it.
- `evidence-missing` - the code is right, but a test does not prove what it claims: a weakened assertion, a wrong
  expectation, or a case the work order names with no test. Never a missing or stale receipt or record.
- `needs-ruling` - the work order is ambiguous or conflicts with a rule; you cannot say right or wrong without
  the operator.

The verdict line is followed by one line `Reasons: <value> <count>, ...` summing the findings, or `Reasons: none`
on a clean PASS. Pick the value by what is wrong, not by where you found it: a comment that is stale because the
behaviour moved is `comment-false`; a test that asserts the wrong thing is `evidence-missing`; a test that fails
because the code is wrong is `code-wrong`. These lines are read by a tool; do not vary the words.

A test record that contradicts the code (the code is wrong and a record shows it) is `code-wrong`, quoting the
record's failing line.

**Report and stop.** Never start a coder, never edit code. Rework is the lead's. When the lead resumes you to
re-review, check the diff since your last review against your earlier findings and what the fix touched, and say
for each earlier finding: fixed, not fixed, or moved.
