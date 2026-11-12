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
| Validation | Performance and accuracy | The repo's orchestrator | Stage 6 |

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
6. Run the integration tests of the zone and its direct dependents, under the hang rule.
7. Any failure: print it and exit 3. The coder fixes it and runs `land` again.
8. Write each step's name, result and seconds to the work order record.
9. All pass: send the work order to Stage 3.

## Stage 3: Review before landing

**Who:** Kong. On teams with Perkins, Perkins also, for work orders that change security-relevant files. Several reviews may run at once. Security-relevant files are the globs in `[land].security_paths`. With no list, Perkins reviews nothing before landing. **Where:** the work order's own commits, `integration..tip`.

1. Review the work order's own commits.
2. No findings: record the verdict "land" against the tip. The work order joins the landing queue.
3. Findings: send the work order back to the zone's coordinator with the findings. The worktree is kept. Nothing lands. After the fix, the lead runs `land` again: Stage 2, then a review of the new commits.

A verdict covers the work order's own commits. It does not expire when `landing` or `integration` moves. Whether the work combines correctly with other work is the tests' job (Stages 2 and 5).

## Stage 4: Landing

**Who:** the team's landing runner, one queue entry at a time. **Where:** no worktree. It moves the `landing` pointer only.

1. Take the oldest reviewed queue entry.
2. Merge the work order's tip into the current `landing` with git.
3. Conflict: send it back to the coder with the files and the landed work orders it conflicts with. The coder never merges `landing`: the work order waits until that work is promoted, then runs `land` again, and the conflict shows when Stage 2 merges `integration` (steps 2 and 3).
4. No conflict: move `landing` to the merge commit, M, only if `landing` has not moved meanwhile. Delete the worktree. Record the landing, with Stage 2's step results, in `landed.log`.
5. Work orders on `landing` that are not in the `integration` commit the work order merged (by ancestry, not by time) changed the zones Stage 2 tested: add M to `land/recheck.jsonl` with the zones. Otherwise nothing more.

## Stage 5: Recheck

**Who:** the recheck runner. **Where:** `land/itest`, a permanent worktree whose build output is never deleted.

1. Take the oldest recheck line.
2. Check out M in `itest`.
3. Compile the listed zones and run their integration tests, under the hang rule.
4. Write the result to `land/integration-results.jsonl`.
5. A test fails or hangs: open one fix work order for the zone, naming the test and M. A test already failing with a fix open: add M to it.
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
| Perkins's feature rounds after landing | Perkins reviews before landing |
| Worktrees cut from the branch work lands on | Worktrees are cut from `integration`, a copy of base |

Nagatha's rounds after landing stay as test-writing work. Their findings open work orders and never hold promotion; her tests hold it through Stages 5 and 6.
