---
name: zone-tests
load: demand
description: Load before you build or run any test. Building and testing through make and zone-tool - which target to run, test records, cached answers, when a run is waste. Preloaded by every role that builds or tests.
---

# Building and testing

## The only ways to build and test
| Need | Command |
|---|---|
| **The whole zone** (most of its tests, or a set of more than ~5 groups) | `make zone-test-one DIR=<the zone's package>`, and for a second port its own `DIR=` (the product layer's "whole zone" row): one call per port |
| A handful of tests while coding (up to ~5 groups) | `make zone-test-one DIR=<path>` with a filter (the product layer gives the forms) |
| The type-check, after each batch of edits (seconds) | `make zone-check DIR=<path>` |
| What the current records say | `make zone-test-status` |
| Your lane's whole suite (coordinator only, before a push) | `make zone-test` |
| A new worktree ready to build | `make warm` |

Never run `cargo`, `swift build`, `swift test` or a test binary directly: the make targets go through codeteam's build
queue and write the test record. A run outside them leaves no record, so for this team it did not happen. The zone
guard refuses them, and `make test-one`, `make test-repeat` and the runner's own scripts, for the same reason
(2026-11-01); `make zone-test` is refused to every subagent.
The product layer (`rules/product.md`) names this repo's packages, modules and filter forms.

## Proof by level
| Level | Proof | Who runs it | Means |
|---|---|---|---|
| Request | **Request check**: the red set plus the tests `codegraph affected` names for the changed files, filtered | coders while coding; the lead's test-runner once at the end | this change does what the order asks |
| Lane | **Lane receipt**: the lane's whole zone green on the accepted tree, one call per port (v5: the landing gate's run of the zones a landing reaches) | the zone coordinator after accepting (v5: the landing tool) | this lane works on its own |
| Integration | **Integration receipt**: the whole product suite green on integration's tip, in the background, never blocking | codeteam (locally, or on the remote validation machine) | this code works in the product; "done" |

"Receipt" means only the lane and integration records. A request carries a check, never a receipt, and no reviewer
asks a request for one.

## Hold your tests until you have made a batch of changes
A day of the queue showed lanes kept to their zones but reran their whole zone after every small edit: about 36 of 79
whole-zone hours were reruns on worktrees that had already passed. Every run builds a test binary. So:
- **While editing, type-check; do not test.** `make zone-check DIR=<path>` after each batch of edits. Tests run when
  the unit's edits are all in and the check is clean: once.
- **After a FAIL, one round.** Fix every failure the record lists, check clean, rerun only the failing tests (a
  filter), then the whole set once.
- **The test tool enforces it** (exit 5, `REFUSED`, with the reason and what to do): it runs the type-check itself
  first and refuses a run on code that fails it; it refuses a whole rerun of a DIR straight after its FAIL until a
  filtered run of the failing tests has passed; and a request worktree gets 4 whole runs per DIR (baseline, the final
  set, review rounds). Past that, the lead returns to its coordinator, which can grant one more with a reason. A
  refusal is the answer: never resubmit it unchanged.

## Whole zone, or a handful: never dozens of submits
- **A test set that is most of the zone is run whole:** one `make zone-test-one` per port with no filter. Two
  calls, two records. Each answers at once from its record while its port is unchanged.
- **Filters are for a handful:** up to about five groups, while a coder checks its own work.
- **Never split a set into many filtered submits.** A record goes stale whenever anything in its package changes,
  not only the files a group tests, so twenty filtered groups go stale together and rerun together: twenty jobs
  where one would do. Submit them one call per port.
- Submitting several calls at once is fine: the queue runs one per worktree and port at a time.

## The build queue
Every make target submits its run to codeteam's build queue and waits for it there, not inside your shell's time
limit. Each run has a class, which sets its turn:

| Class | Run | Who names it |
|---|---|---|
| `full` | the whole suite, integration and exchange builds (`make zone-test`, its default) | orchestrator, builder |
| `post` | the changed functions' tests on finished work | change-reviewer |
| `pre` | choosing and proving the test set | preflight-checker |
| `dev` | coders, test-runner while coding; any build not submitted with a class (`make zone-test-one`'s default) | coders, test-runner |

Your role file names your class once; use it (`CLASS=<class>`), and nobody else decides it.

**WAITING is not a result.** When a make call ends with exit 4 and the last line `WAITING: zone-tool job wait
<ticket>`, the run is still queued or running. Run exactly that line, and again each time it prints WAITING, until it
exits 0 (DONE: the record follows; a failed test is still exit 0, read PASS or FAIL in the record). Exit 3 is BROKEN:
the job died without a record; report it. Never resubmit a waiting job, and never report WAITING as a failure.
`zone-tool job status` shows the whole queue.

## No test fails for load
"There is no such thing as a test that fails for load." A test that fails, times out or runs slowly because the
machine is busy is not a defect in the work. It waits on a clock, a real process or a real file event, so it is an
integration or validation test in the unit run by mistake. When you see one, move it to its group (integration or
validation) as a small patch riding with your work; a move is not a fix and blocks nothing. Never: hold or bounce
work for it, open fix work for it, re-run it to see if it passes, or report it as a failure. A test run ended by its
time limit is unfinished, not failed. The `// slow: <reason>` comment and the 5-second rule are gone.

## Three kinds of test

What each kind is: the rules every agent loads, rule 11. Who writes each and where it runs:

| | Unit | Integration | Validation |
|---|---|---|---|
| Written by | coders and the test-writer | Nagatha | the orchestrator |
| Runs | in your own runs and at landing | on the quiet machine | on the quiet machine |
| For example | | | the benchmarks |

**Which kind you write:** your role decides it, as the "Written by" row says. If a test you need is another kind, don't
write it. Say so in your return: what it would check and which kind it is. The work goes to whoever owns that kind.

**Which kind an existing test is:**
- If it needs anything real beyond the code under test, it is not a unit test.
- If its result is a measurement compared with a target, it is a validation test.
- A test in the wrong group is moved to the right one, as a small patch that blocks nothing.

**A check on how the code is written is not a test of any kind:** names, which literals may appear where, who may
call what. It is a rule in the product's rules file (`rules/product.md`, "Code conventions"): the change-reviewer
checks it on each change, and Nagatha checks the code already landed when she reviews each feature. Never write a test
that reads the repo's source files to enforce one.

## A test must be able to fail

A test proves something only if wrong code would make it fail. Take the expected value from somewhere the code under
test did not produce it: the contract, the spec, or a worked example written out by hand as a literal.

Four kinds of test can't fail, so never write them:
- **It computes the expected value the way the code does** (`assert sum(5, 3) == 5 + 3`). Write `8`.
- **It sets a fake to return a value, then checks that value came back.** That tests the fake. Check what the code did
  with the value.
- **It runs the code and checks nothing.** Finishing without an error is not a result.
- **It compares a value with itself,** or a constant with itself.

Before you keep a test, ask: if the code were wrong in the way this test is meant to catch, would the test fail? If
not, rewrite it.

Where the contract states a rule rather than examples (a round trip returns the input; order doesn't matter), test the
rule over many inputs instead of copying one.

## Records, not reruns
- Every run writes a record: result, counts, the last lines of a failure, CPU seconds. Read it with
  `make zone-test-status`.
- A record that matches the current code is the answer. Running unchanged code again is waste; the target
  answers from the record (`--cached`) anyway.
- Run once per finished batch of changes, never per edit (above).
- **Never run a test again to be sure.** `make zone-test-one` answers from its record until something the tests can
  touch changes (their package and the packages it depends on by path, plus the test scripts), not when anything
  else in the worktree changes. A record that matches is the answer.
- **After a commit, rerun only the groups that cover what it changed.** The two ports have their own records: a
  Rust-only commit leaves the Swift records current, and a Swift-only one the Rust records. Rerunning the whole
  set is fine because unchanged groups answer from their records at once, but don't rerun what you know is current.
- Re-sending the same `make zone-test-one` while it is queued or running joins that job; it never starts a second.
- Never run the whole product suite. The orchestrator runs it once, on the merged result.

## Red before green, only where it means something
- A fix to existing behaviour: the new test fails on the old code at an assertion, read from the record, then passes.
- A new API: failing to compile first is enough.
- A comment-only change: no test run; `git diff` showing only comment lines changed is the proof.
