# TESTING

Tests run through `make zone-test-one DIR=<folder>` (one folder or file, recorded) and `make zone-test` (the zone
suite, recorded); `make zone-test-status` reads the records. In a repo with no root Makefile, codeteam's zone.mk
supplies `test-one`, which finds the Python and shell tests described below; `DIR=.` means each path in the lane's
`CODETEAM_OWNS`; an owned file runs only if it is a test by name, and with `CODETEAM_OWNS` empty `DIR=.` is refused.
In a repo with its own Makefile, that Makefile's `test-one` decides.
With zone.mk's `test-one`, run a group with `CODETEAM_TEST_GROUP=integration make zone-test-one DIR=<path>`; the group
reaches the tests through the build queue and `test-one`. Non-unit groups have separate records; unset and `unit` share one.
The record key includes `SWIFT_TEST_ARGS`, `CARGO_TEST_ARGS`, `PYTEST_ARGS` and `PYTEST_ADDOPTS`; see
`INTERFACE.md` for collision limits and which arguments reach the tests.

Both targets go through the build queue (`zone/docs/build-queue.md`): the run is a job the runner starts when its class
has a share free, and make waits `ZONE_JOB_WAIT` seconds for it (default `auto`: the session's shell limit minus a minute,
1740 s where `BASH_DEFAULT_TIMEOUT_MS` is 1800000, else 100 s; `INTERFACE.md` has the rule). A
job still queued or running then makes the recipe fail with zone-tool's exit 4 (make reports "Error 4") and print, as its last line,
`WAITING: zone-tool job wait <ticket>`. That is not a test failure: run that one line (`zone-tool job wait <ticket>`, which
blocks for the same shell limit less a minute; exit 0 and the record when done, 4 and the same line while waiting) until it answers. `ZONE_JOB_WAIT=0`
waits until the job is done (gates and scripts); `CLASS=full|post|pre|dev` picks the class (`zone-test-one` defaults to
`dev`, `zone-test` to `full`). A repeat on unchanged code is answered from its record without queueing. Make succeeds for a
PASS and fails ("Error 1") for a test that ran and failed. If the queue is unavailable, the test runs in the foreground and stderr says so.

The queue's shell tests under `zone/tests/` use scratch queues, runners (or fake ones) and repos; they do not touch the
live `run/queue`. `zone/tests/test_hang_rule.py` checks the hang window, output, strict CPU threshold, unknown samples,
short-lived workers, settings, CPU-time parsing, tree exclusions and the wait loop with fake processes, clocks and
CPU readers; it makes no real waits. `zone/tests/test_commit_record.py` checks clean-commit unit proof, dirty tracked
and untracked files, failed results, per-key newest results, group filtering and cached answers at a new commit;
these unit cases use scratch git repos and stub test commands, with no real waits.
`zone/tests/test_buildq_hang.py` checks the run-job backstop's doubled window, busy CPU, log growth, unknown samples,
fresh watches after restart, slot jobs never being killed and spawn not adding a time limit, using fake CPU samples
and signals with no real clock waits.
`zone/tests/test_launchd.py` checks the bootout wait's counts and sleeps, the one bootstrap retry, the combined
reinstall's order and reasons, the exact launchctl arguments with and without a timeout, and that import starts no
process, through a fake launchctl and sleep; it runs no launchctl and no real sleep.
`zone/tests/test_buildq_launch.py` is a pytest unit test of both clients' exact kickstart command,
the live-queue, other-queue and override branches, and the not-loaded and other-failure messages. Tests that start scratch
runners set `CODETEAM_BUILDQ_LAUNCH` to `zone/tests/fake-launchctl`, which receives the kickstart arguments and starts
`$CODETEAM_BUILDQ` in the background (default `<repo>/bin/codeteam-buildq`), or exits 113 with `Could not find service`
when it is not executable. Nothing on the queue path (the runner, `zone-tool job`, `codeteam-slot`) calls `tmutil`: every test that runs the runner, `zone-tool` or `codeteam-slot` puts a stub `tmutil` first on the
PATH it gives them, as a guard, so no test can reach the real one.
`buildq-sched.sh` (order, budget, cost, load, swap, warm lock, the `hold` field, modes, a malformed config or job file,
`env` kept in every state, a too-big number in queue.toml, a child that leaves no fresh record or answers from a record,
fifty finished files), `buildq-restart.sh` (20 checks across nine scenarios: a dead runner, adopted and broken jobs,
slot liveness, pruning, adopted jobs answered from a record and `env` kept in every state), `buildq-plist.sh` (the launchd
file), `buildq-e2e.sh` (the real runner with `zone-tool job` and `codeteam-slot`), `zone-job.sh` and `zone-job-mk.sh`
(the verbs and the make targets), `slot-queue.sh` and `slot-record.sh` (`codeteam-slot`), `warm-lock-record.sh` (the warm lock record).

Integration group. The following cases run only with `CODETEAM_TEST_GROUP=integration`, because they wait on a runner, process, clock or detached warm, or depend on a case that does: `buildq-e2e.sh` cases 1-6, `slot-record.sh` cases 1-4, `zone-test-enospc.sh` case 5 (HUNG wins over an out-of-space signature with a silent sleeping child), `slot-queue.sh` cases 1-6, 8-10, 12 and 14-18, `warm-lock-record.sh` checks 1-3, `zone-job.sh` case 30, and all of `zone-test-one.sh`. The unit run prints a `skip` line for each listed case or check, except `zone-test-one.sh`, which prints one for the whole file. Run one file with `CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/<file>`.

For race reproduction, `BUILDQ_RESTART_PS_DELAY` delays runner `ps` calls in `buildq-restart.sh`; `ZONE_JOB_RUNNER_DELAY` delays fake runner startup in `zone-job.sh`; `WARM_LOCK_HOOK_DELAY` delays the seed-index call after warm launch in `warm-lock-record.sh` (all in seconds). The warm-lock test clears inherited `CODETEAM_*` and other session settings, isolates HOME and Git config, and checks for its per-run names in the live repo.

## Swift

- Framework: Swift Testing (kits and libs), XCTest (GUI)
- Location and naming:
- Fixtures and helpers:
- Run: `make zone-test-one DIR=<folder>`, or `make zone-test` for the zone suite
- Example test:

## Rust

- Framework: `#[test]`, integration tests in `tests/`
- Location and naming:
- Fixtures and helpers:
- Run: `make zone-test-one DIR=<folder>`, or `make zone-test` for the zone suite
- Example test:

## Python

- Framework: pytest; files named `test_*.py` or `*_test.py`
- Location and naming:
- Fixtures and helpers:
- Run: `make zone-test-one DIR=<folder or test file>`
- Example test:

## Shell

- Framework: the `*.sh` files in a `tests/` folder, each a bash script that passes or fails by its exit status (by
  convention it prints `ok`/`PASS` and `FAIL` lines). A file named `run.sh` is never run by zone.mk's `test-one`: it
  is a manual runner.
- Location and naming:
- Fixtures and helpers:
- Run: `make zone-test-one DIR=<folder>`
- Example test:
