# Branch flow v5.4: branches, work, landing, testing, review, promotion

Status: the flow this release builds (`codeteam-land`, `[land] enabled = true` in a team manifest).
Replaces branch flow v5.2. Worktree cutting, warm clones and disk cleanup are as in earlier versions, except where §2 and Stage 1 below say where worktrees are cut from.

## 1. Principle

A commit is promoted only if everything in it has been tested and reviewed clean. Worktrees start only from proven code. Unproven work is kept on its own branch until it is proven.

## 2. Branches (per team)

| Branch | Holds | Moved by |
|---|---|---|
| base (the manifest's `base`, e.g. `main` or `develop/1.1.x`) | Proven code | Stage 7 only, by fast-forward |
| `integration` | A copy of base | Stage 7 only, fast-forwarded to base right after base moves |
| `landing` (`[land].landing`) | Work that has landed and is not yet proven | Stage 4 only |
| worktree | One work order | Its agent |

No folder has `landing` or `integration` checked out. A git hook refuses any change to either branch except by the landing tool.

## 3. Test groups

| Group | Reaches | Written by | Runs in |
|---|---|---|---|
| Unit | One zone only. Isolated, deterministic, milliseconds | The coder | Stages 1 and 2 |
| Integration | The edited zone and its direct dependents | Nagatha | Stages 2 and 5 |
| Validation | Performance and accuracy | The lane that owns the code; the repo's orchestrator sets the measures and thresholds | Stage 6 |

If X changes, B calls X, and A calls B: run X's tests and B's tests, not A's.

**Hang rule.** A test with no output and under 1% CPU for 10 minutes is killed and recorded as hung. Hung counts as a failure. Nothing else is ever killed.

## Stage 1: Work

**Who:** the coder (lead, with subagents). **Where:** the work order's own worktree, cut from `integration` by `wo-cut`.

1. Write the code and its unit tests.
2. Run the zone's unit tests through zone-tool, which records the result against the commit.
3. Repeat until they pass on the final commit. Every subagent has finished.
4. Run `codeteam-land land <wo>`. That starts Stage 2.

## Stage 2: Check before landing

**Who:** the `land` command. Its test jobs go through the build queue. **Where:** the same worktree.

1. No passing unit-test record for the final commit: run the zone's unit tests now.
2. Merge `integration` into the work order. This brings in proven code only.
3. Conflict: print the files and exit 2. The coder resolves it and runs `land` again.
4. The merge changed the zone's own files: run the zone's unit tests again. Fail: print the failures and exit 3.
5. Compile the zone and its direct dependents.
6. The integration tests are not run here: a work order that builds is queued with its integration step owed, and a docs-only or comment-only one owes nothing. A work order whose own delta is documents, comment-only changes and at least one test move compiles nothing and runs no unit test; it owes the integration step only for the zones of tests moved into integration (none when every move is into validation). The owed step runs once per batch at queue-run, on `integration`'s tip, before landing (Stage 4 step 1).
7. Any failure: print it and exit 3. The coder fixes it and runs `land` again.
8. Write each step's name, result and seconds to the work order record.
9. All pass: send the work order to Stage 3.

## Stage 3: Review before landing

**Who:** Kong alone. Several reviews may run at once. `[land].security_paths` has no reader. Perkins reviews landed work when his orchestrator asks and records findings with `codeteam-land finding`; a finding of his holds nothing. **Where:** the work order's own commits, `integration..tip`.

1. Review the work order's own commits.
2. Comment and doc findings: a comment or doc finding is not filed and never sends the work order back. Kong fixes it in the work order's tree and runs `codeteam-land <manifest> doc-fix <wo> -m <message>`, which commits it as the new tip with no rebuild and no tests (the Stage 2 pass stands), then reads that commit and records his verdict. What the comment-only detector reads as code (docstrings, doc tests, directive comments, new or deleted code files) doc-fix refuses, and it goes back as a finding. Only changes to code go back through the entire process. A test in the wrong group is moved with doc-fix the same way: moved or renamed unchanged into its group's folder, or only its TEST_GROUP gate changed where no folder decides; a move into unit is refused and filed as a finding.
3. No findings: record the verdict "land" against the tip. The work order joins the landing queue.
4. Findings: send the work order back to the zone's coordinator with the findings. The worktree is kept. Nothing lands. After the fix, the lead runs `land` again: Stage 2, then a review of the new commits.

A verdict covers the work order's own commits. It does not expire when `landing` or `integration` moves. Whether the work combines correctly with other work is the tests' job (Stages 2 and 5).

## Stage 4: Landing

**Who:** the team's landing runner (`queue-run`), one batch at a time. **Where:** `land/itest` for a batch's integration step, under the lock Stage 5's recheck also takes; `landing` itself moves by its pointer only.

1. Take the ready queue entries: not held, reviewed "land", in priority order, then queue order. Priority 0: an entry whose work orders fix a finding of severity 1 or 2; 1: new work, slow-tests follow-ups and a fix whose finding is no longer found; 2: an entry whose work orders fix only findings of severity 3. An entry moved by `land-next` comes before every class. The first ready one without an owed integration step lands alone (steps 2 to 5), so such an entry lands ahead of a batch whatever its priority: a merge with no test run. Otherwise every ready owed entry, in that order, is one batch, tested once: on `integration`'s tip, merge each entry's member tips in that order without moving `landing` (an entry whose merge conflicts goes back, and the chain goes on without it); compile, and only when that passes, run the integration tests of the union of the batch's zones and files, under the hang rule. Pass: every entry lands in order through steps 2 to 5. Fail: no bisect and no rerun. Each failing step's frames (the repo files and lines in its stack, then the failing tests' CodeGraph callees) are matched against each entry's diff from `integration`'s tip. An entry a step matches goes back to its zone's coordinator, its worktree kept, naming only the steps that matched it and their frames. The entries no step matched land. A failing step that matches no entry becomes a test finding for the zone that owns the step. A failed `itest` checkout lands nothing and sends nothing back; the entries stay queued for the next pass.
2. Merge the work order's tip into the current `landing` with git.
3. Conflict: send it back to the coder with the files and the landed work orders it conflicts with. The coder never merges `landing`: the work order waits until that work is promoted, then runs `land` again, and the conflict shows when Stage 2 merges `integration` (steps 2 and 3).
4. No conflict: move `landing` to the merge commit, M, only if `landing` has not moved meanwhile. Delete the worktree. Record the landing, with Stage 2's step results, in `landed.log`.
5. Work orders on `landing` that are neither in the `integration` commit the work order merged nor in any of its members' tips (by ancestry, not by time) changed the zones Stage 2 tested: add M to `land/recheck.jsonl` with the zones. Otherwise nothing more. A landing already in the work order's tree is no overlap: Stage 2 tested it.

## Stage 5: Recheck

**Who:** the recheck runner. **Where:** `land/itest`, a permanent worktree whose build output is never deleted.

1. Take every pending recheck line whose M is the newest pending M (M*) or an ancestor of it: one recheck covers everything landed since the last. A pending migration move line goes alone and first; a line off M*'s history waits for a later batch.
2. Check out M* in `itest`, under the lock the landing runner's batch step also takes.
3. Compile the union of the lines' zones and run their integration tests once, for the union of their files, under the hang rule.
4. Write the result to `land/integration-results.jsonl`.
5. A test fails or hangs: open one fix work order per failing test, naming the test and M*, against the newest line whose landing reached the failing step's zone, else the newest line. A test already failing with a fix open: add M* to it.
6. A test with a fix open now passes: close it.

## Stage 6: Validation

**Who:** the validation runner. **Where:** its own permanent clone: on this machine by default (`[land.validate]`), or on a remote build machine over ssh (`[land.remote]`).

1. Take the newest `landing` commit whose rechecks are all finished: every recheck line at that commit or an ancestor of it.
2. Run the validation tests under the hang rule.
3. Write the result to `land/validation-results.jsonl`.
4. Compare each test with the previous run. Newly failing: one fix work order for the owning zone. Already failing with one open: add the commit to it. Now passing: close it.

## Stage 7: Promotion

**Who:** the validation runner, automatically.

1. Take the newest `landing` commit C where:
   - Stage 6 passed on C; and
   - every recheck or validation failure at or before C was fixed by a commit at or before C.
   A failure is fixed at the commit that closed it: the landing of the work order that names it with `--fixes`, or the commit whose recheck or validation passed the test. 'At or before C' means C or an ancestor of C.
2. Fast-forward base to C.
3. Fast-forward `integration` to base.
4. Tell the coordinator of every open work order whose zone, or a direct dependency of it, changed between the old and new `integration`: what was promoted, which of its zones it changes, and "merge integration at your next stopping point". No one else is told.

No findings list is consulted. Review findings on new work never reach `landing` (Stage 3). Findings on work already there, from the move-over review (Moving a team over, step 4) or Nagatha's rounds after landing, become fix work orders and never hold promotion. So only test failures can hold promotion, and those are broken code.

### Restart after a promote

When the promote changes the programs themselves (codeteam's `main`, which every team runs):

1. Restart a landing runner, recheck runner, validation runner or the build queue only when it has no Stage 2, 5 or 6 job running.
2. If one is running, wait for it to finish, then restart. While a restart is pending, that program starts no new job.
   The build queue is the exception: it is restarted at once, as it adopts the jobs it was running, and nothing waits
   for it.
3. Post each restart on General with the program's name and the jobs it waited for.

## Moving a team over

One command per team:

1. Rename the team's current `integration` branch to `landing`. Records keep their hashes.
2. Create `integration` at base.
3. Queue one recheck of every zone at `landing`'s tip, so nothing promotes before every zone's integration tests have run on it once. From then on, Stages 6 and 7 take only that tip or commits after it.
4. Kong reviews each zone's whole diff between base and `landing` once, in place of a review per landed work order. His findings become fix work orders, which follow Stage 3 like any other.
5. Work orders open at the move were cut from what is now `landing`. Stage 3 reviews only their commits not already on `landing`.

The command is `codeteam-land <manifest> migrate-v54`; run it once per team, while the team is halted. A new team starts on v5.4 and needs no move.

## Removed from v5.2

| Removed | Why |
|---|---|
| Kong's review after landing, its hand-off and cut-over records | Review is before landing (Stage 3) |
| Stage 7's check of open findings (`refuse_open_fixes`) | Findings never reach `landing` |
| The check that a commit predates its fixes (`predates_fixes`) | Same |
| Perkins's feature rounds after landing | No feature round: Perkins reviews landed work when his orchestrator asks, and his findings hold nothing |
| Worktrees cut from the branch work lands on | Worktrees are cut from `integration`, a copy of base |

Nagatha's rounds after landing stay as test-writing work. Their findings open work orders and never hold promotion; her tests hold it through Stages 5 and 6.
