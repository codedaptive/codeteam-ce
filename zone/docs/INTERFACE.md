# INTERFACE

The public surface other zones may use.

## share/claude-hooks/lane_walls.py: what a lane may edit

The one rule for "what may this lane edit". `share/claude-hooks/zone-guard.py` uses it for every edit by a zoned or walled
lane (an unwalled `.` lane is checked only for orchestrator-owned paths, see the guard paragraph below).
`codeteam push-up` uses it too (`walls_refusals` in bin/codeteam), listing each refused path with its
owner, so the hook and the push give one answer. Import it by path: put
`<CODETEAM_HOME>/share/claude-hooks` on `sys.path` and `import lane_walls` (the folder name has a hyphen, so it is
not a package). Pure stdlib, Python 3.11. Importing it reads no environment and no file.

- `Walls(lane, zone, owns, lanes, zone_docs, orchestrator_owns=())`: a frozen dataclass of one lane's facts. `lanes` is team.json's
  `"lanes"` as is (an entry may lack `owns` or `path`; one that is not a dict is skipped); `zone_docs` is
  `zone/zone-docs.json` (keys starting `_` are comments); `orchestrator_owns` (a tuple, the last field, default `()`, so an existing
  `Walls(...)` construction keeps working) is the manifest's list of paths the orchestrator owns. Methods: `others()` is `[(lane, path or glob)]` that
  other lanes own (their zone folder, unless it is `""` or `"."`, and their `owns`); `walled()` is true for a
  whole-repo lane (zone `"."`) when `others()` is not empty; `orchestrator_owned(rel)` is true when `rel` matches an entry of
  `orchestrator_owns` the way `owns` matches (the folder and what is under it, an exact file, or a glob), or matches one with
  case folded on both sides; `in_area(rel)`; `owns_doc(rel)`.
- `load_walls(*, lane, zone, owns, team_json, codeteam_home, manifest=None) -> Walls`: strips whitespace and `/` from `zone` and
  each `owns` entry (empties dropped), reads `team_json` (a path, or `None`) for the lanes and
  `<codeteam_home>/zone/zone-docs.json`. A team.json that is missing, unreadable, not JSON or without a `"lanes"`
  object gives `{lane: {"path": zone}}` (no other lane's area); a missing, unreadable or non-object zone-docs.json gives `{}`. Call it
  explicitly; nothing runs at import. `manifest` (a path, or `None`) is the team's manifest TOML (`teams/<team>.toml`,
  the path in `CODETEAM_MANIFEST`); it is read with `tomllib`, only inside `load_walls`, for the top-level list
  `orchestrator_owns`, whose entries get the same strip as `owns` (whitespace and `/`, empties
  dropped). `None`, a missing or unreadable file (a folder too), bad TOML, an absent key, or a value that is not a
  list gives `()`: a team whose manifest does not set the key changes nothing. A top-level key must come before the
  first `[[lanes]]` table, or TOML puts it inside that table and it is not seen.
- `refused_by(rel, walls) -> str | None`: `rel` is repo-relative, as git records it. First rule, ahead of every other
  (lockfiles, the lane's own area and `owns`, its own SPEC and INTERFACE): when `walls.orchestrator_owned(rel)` is
  true it returns `ORCHESTRATOR`, for every lane (zoned, walled or an unwalled `.` lane).
  Otherwise `None` means the lane may edit it: a lockfile anywhere (`Cargo.lock`, `Package.resolved`), a path in `walls.in_area`, or the lane's own SPEC and
  INTERFACE (`walls.owns_doc`). One exception to `in_area`: for a walled lane, `refused_by` does not
  take `in_area`'s word for a file in `docs/reference`, `docs/_public/reference` or `docs/internal/reference` named for another lane, or listed in
  `zone_docs` for another zone; it returns that doc's owner, as below (`in_area` itself still says True). Zoned lanes
  and an unwalled `.` lane are unchanged. Otherwise it returns the owner, so push-up can
  list each refused path with its owner: for a file in one of those three folders whose name `zone_docs` lists, the lane whose
  zone `zone_docs` names (`ORCHESTRATOR` when no lane has that zone); for one carrying a lane's zone name, that
  lane; else the first lane in team.json order whose area (zone folder and `owns`) matches,
  else the same match with case folded, else `ORCHESTRATOR` (no lane owns it). A walled lane is never its own
  owner. The guard needs only `None` against not `None`.
- Constants: `ORCHESTRATOR` (`"orchestrator"`), `LOCKFILES`, `OWNED_DOC_DIRS`
  (`("docs/reference", "docs/_public/reference", "docs/internal/reference")`): the folders where a zone's SPEC and
  INTERFACE and their copies live, named for the zone.

The guard (`zone-guard.py`) builds its `Walls` through `load_walls` and passes `manifest=manifest()`, which is
`CODETEAM_MANIFEST` when set (both launchers export it), else `<codeteam home>/teams/<team>.toml`. Its `holds_zone`
(staging a folder that holds the zone or its docs is fine) treats `docs`, each `OWNED_DOC_DIRS` folder and their
parents (`docs/_public`, `docs/internal`) alike.

For an unwalled whole-repo lane (zone `"."`, no other lane's area in team.json) the pretool hook also runs when the
manifest's top-level `orchestrator_owns` is non-empty, and for that lane it refuses two kinds of change to a path
`walls.orchestrator_owned` matches, inside the lane's own worktrees under `$CODETEAM_WORKSPACE` or `$CODETEAM_HOME` (the folders the guard guards for every lane).
The first is a write: Edit, Write, MultiEdit, NotebookEdit, and the shell writes the guard parses (redirects, `tee`, `sed`
or `perl -i`, `cp`, `mv`, `rsync`, `install`, `ln`, `ditto`, `rm`, `rmdir`, `touch`, `truncate`, `unlink`, `patch`). The
second is `git add`, `git rm` and `git mv` (for `git mv`, the source and the destination are both judged). The housekeeping exceptions of any lane (classify's "own" rules, listed under
"Not in it" below) apply to both. For the git commands, the guard skips the pathspecs it skips for every lane: `.`, `:/`,
`-A`, `:`-magic pathspecs, `$`-paths, a relative path after a `cd $VAR` (the folder is unknown), and folders that hold the zone or its docs (the repo root, `docs`, the reference
folders and their parents). `git restore`, `git checkout`, `git commit`, `git push` and other subcommands are not checked
for that lane, and the scratch-clone refusal does not apply to it. Push-up's walls check still refuses a push that
changes such a path. Nothing else is refused for that lane: no zone fence, no test-route, make or build refusal. The
refusal names the orchestrator (`Orc-<Product>`) and the manifest's `orchestrator_owns`. A manifest without the key makes
the pretool hook return early for such a lane. Zoned and walled lanes are unchanged.

Case: paths match exactly (`V2/x` is not inside `v2`, and a glob is matched with `fnmatchcase`). Case is folded
only to refuse more: a walled lane's `in_area` refuses a case-only match of another lane's area, and `refused_by`
names an owner for a case-only match. A zoned lane (zone not `"."`) never has `V2/x` in its area, and `refused_by`
may name the lane itself for such a path. A whole-repo lane with no other lane's area owns every path.

Not in it, and still the guard's alone (classify's "own" rules): the lane's scratchpad and ledger, `/.claude/`
and `.claude/`, `.ledger.md`, `cargo-target*`, `.test-record-*.json`, a path outside any worktree, and an untracked
file at a worktree's top (one that matches no tracked top entry even with case ignored). They are worktree
housekeeping, not what a push may change. Nor does it say what a push may change: it answers only who owns a path.

## share/codeteam_launchd.py: reinstalling a launchd job

Import by path: put `<CODETEAM_HOME>/share` on `sys.path` and `import codeteam_launchd`, as bin/zone-tool imports
`codeteam_hang`. Pure stdlib, Python 3.11; importing it runs no command.

- Constants: `POLLS = 100`, `POLL_S = 0.2`, `RETRY_S = 2.0`.
- `wait_for_bootout(target, *, run=None, sleep=None, polls=POLLS, poll_s=POLL_S, timeout=None) -> bool`:
  runs `launchctl print` on `target` up to `polls` times; True at the first non-zero return code (treated as unloaded),
  False if no print returns non-zero. It sleeps `poll_s` between prints, never after the last: a non-zero first print means one print and no sleep;
  the default bound is 100 prints and 99 sleeps, about 19.8 s of sleep plus launchctl's run time.
- `bootstrap(domain, plist, *, run=None, sleep=None, retry_s=RETRY_S, timeout=None) -> str | None`:
  None on success; a non-zero return code gets one retry after `retry_s`. A second failure returns that attempt's
  stripped stderr, possibly empty: test with `is not None`.
- `reinstall(label, plist, uid, *, run=None, sleep=None, wait_s=20.0, poll_s=POLL_S, retry_s=RETRY_S, timeout=None) -> ReinstallResult`:
  bootout `gui/<uid>/<label>` (its result ignored), wait for up to `round(wait_s/poll_s)` prints, then bootstrap
  `gui/<uid> <plist>`. Still loaded: `ReinstallResult(False, "still loaded 20 s after bootout; not reinstalled")`
  at the default wait, and no bootstrap. Bootstrap failed twice: `ReinstallResult(False, "launchctl bootstrap failed: <stderr>")`.
  Else `ReinstallResult(True)`.
- `ReinstallResult` is a frozen dataclass `(installed: bool, reason: str | None = None)`; results returned by `reinstall` have reason None on success and a string on failure.

Every launchctl call passes `capture_output=True`, `text=True`, and `timeout` only when one is given. `run` and
`sleep` default to `subprocess.run` and `time.sleep` looked up at call time, so a caller's test patching those modules
reaches this module.

## bin/zone-tool ledger: the ledger files are git-excluded

The ledger lives at git top inside a checkout, else in the current folder (such as a v5 zone folder).
Outside a checkout, nothing is excluded and there is no exclude warning.

In a checkout, every `zone-tool ledger` write (add, stage, close, first) adds missing `/.ledger.md` and
`/.ledger-closed` lines to the shared `info/exclude` (`git rev-parse --git-path info/exclude`), which every
worktree reads. It never rewrites other lines. An update failure warns but does not fail the ledger write. The
entries keep untracked ledger files out of `git add -A`, so push-up does not refuse them. A file already tracked
stays tracked. `zone-tool`'s test-record hash skips both files.

## bin/zone-tool test: test records

`zone-tool test` writes `.test-record.json`, or `.test-record-<key hash>.json` for a keyed run.
These fields belong to the test record, not the queue job:

| field | meaning |
|---|---|
| `commit` str or null | Full HEAD commit SHA at the start of the run; null when there is no HEAD |
| `clean` bool | At the start of the run, HEAD exists, no tracked path has staged or unstaged changes against HEAD, and there are no untracked non-ignored files except bookkeeping names `.test-record.json`, `.ledger.md`, `.ledger-closed`, `.comment-review` and names starting `.test-record`. `ZONE_HASH_IGNORE` does not exempt tracked changes or untracked files from this check |
| `group` str | `CODETEAM_TEST_GROUP`, stripped; unset or empty means `unit` |
| `result` str | `PASS` (exit 0), `FAIL` (nonzero exit without an out-of-space match), `HUNG` (the hang rule stopped the tree, exit 124), or `BROKEN` (nonzero exit and output containing, case-insensitively, `no space left on device`, `database or disk is full`, or `out of space`, unless HUNG). Only `PASS` and `FAIL` can answer `--cached` or `--single`; `test-status` treats every current non-PASS, including records with `TIMEOUT`, as a failure |
| `reason` str or null | `HUNG`: a `hung:` reason naming silent seconds, CPU seconds and the threshold; `BROKEN`: `out of space: <first matching output line>`, stripped, cut to at most 200 characters around the matched phrase; null for other results. This is distinct from the queue job's `reason` |

`--timeout N` and `--timeout=N` are accepted and ignored, with no effect since v5.2. There is no absolute runtime
limit. The hang rule requires both no output line for at least the whole window and CPU used by the root and
its descendants below the CPU threshold over that trailing window. HUNG takes precedence over an out-of-space
signature. The tree receives TERM, then KILL if the root has not exited within 15 seconds. Stderr says
`zone-test: HUNG: <reason>; stopped the run and every process under it`.

The shared settings are `CODETEAM_HANG_WINDOW` (seconds, default `600`) and `CODETEAM_HANG_CPU_PCT` (percent of one CPU,
default `1`). A missing, non-numeric, non-finite or non-positive value uses that setting's default. Both settings
reach zone-tool under the runner through the submitted job's `env`.

While `--single` waits for another run's lock, it prints
`zone-test: a run is already going in this worktree; waiting for its result` at once, with repeats scheduled every
`CODETEAM_HANG_WINDOW / 4` seconds using the job's environment settings. Waiting for the lock is not testing;
these lines provide output for the runner's hang backstop while the caller waits.

CPU samples include each live process's own and reaped-children CPU, so workers that start and exit between samples
still count. A failed process listing, missing root or failed per-pid CPU read makes the sample unknown; an unknown
sample in the trailing window prevents a hang decision, so a tree whose descendants keep exiting may be judged only
once a whole window of known samples passes. No sample in the trailing window also prevents a hang decision: no evidence is not evidence of idleness. Output lines and CPU at or above the threshold prevent a hang decision;
quieter or lower-CPU work can be judged hung. A descendant reparented out of the tree by a double fork to launchd
takes its CPU with it, so that work is not observed.

## bin/zone-tool commit-record: clean unit proof for a commit

Usage: `zone-tool commit-record <commit> [--key K]`.

Every finished `test` run with a commit appends one JSON line to
`<git_dir(root)>/zone-test-commits.jsonl`, in this worktree's own git directory, not in the working tree or the
common git directory of linked worktrees. Each line has `commit`, `clean`, `group`, `key`, `result`, `exit`, `time`
and `record` (the record's file name). Results include PASS, FAIL, HUNG and BROKEN.

A matching cached or single-run record also appends a line with `answered: true` when the tree is clean now and the
record's group (missing means `unit`) equals the current group. This applies both to `test` and to `job submit`'s
record-hit path. The line names the current commit and answer time, but carries the answering record's result and
exit; the original run's commit, cleanliness and group fields in the record are not rewritten. The snapshot used
for the existing cache lookup is reused. Cached answers, scope hits, `test-status` and `covered` keep their existing
outputs and exits.

The lookup resolves `<commit>` with `git rev-parse --verify <commit>^{commit}` and keeps log lines at that full SHA
with `clean: true` and `group: "unit"`. With `--key K`, only that key counts; K is normalized as for `test --key`
(`" ".join(K.split())`). File order decides the newest eligible line per key, not timestamps.

- Exit 0 when every key's newest line is PASS; print the newest PASS.
- Exit 1 when any key's newest line is non-PASS; print the newest non-PASS among those lines.
- Both use one line: `<result> <time> commit=<sha> key=<key or "zone suite"> record=<file>`.
- Exit 2 when no eligible line exists, or the commit does not resolve; print
  `none: no clean unit-group record at <sha or the given text>`.
- Bad usage exits 2 with `usage: zone-tool commit-record <commit> [--key K]` on stderr.

Without `--key`, any key counts, including a filtered run. For proof of the zone's unit run, land must pass that
run's key: zone-test-one's normalized `one <DIR> ...` key, or the zone suite's empty key (`--key ""`). A passing
filtered run alone is not proof of the whole zone's unit run.

## The build queue: job files, the runner's state, and `zone-tool job`

Every test run and every gated build (`swift`, `cargo`, `xcodebuild` through `bin/codeteam-slot`) is one job file in the
queue folder Q. One runner (`bin/codeteam-buildq`) decides which job starts; nothing else starts a queued job.
Design: `zone/docs/build-queue.md`.

**Paths.** Q is `$CODETEAM_QUEUE_DIR`, else `<codeteam>/run/queue`, created 0700 because a run job holds the submitter's
whole environment. `Q/..` is `<codeteam>/run`. The config is `$CODETEAM_QUEUE_CONF`, else `Q/../queue.toml`; it is read at
every decision, and a missing or unreadable file means the defaults.

**What is in Q.** `Q/<ticket>.json` is a job; `Q/<ticket>.log` is a run job's output; every name starting with `.` is
private (`.lock`, `.runner.lock`, `.<ticket>.json.tmp`). A reader of Q (the deck, `zone-tool job status`, a waiter)
reads only `*.json` and skips names starting with `.` and `*.tmp`. The ticket is `YYYYmmdd-HHMMSS-` plus 6 hex digits.
Beside Q: `queue.toml` (config), `queue-runner.json` (the runner's state, below), `queue-history.jsonl` (one line per
finished run job: `hkey`, `class`, `cpu_seconds`, `wall_seconds`, `finished`; `hkey` is the job's `key`, or
`"suite " + " ".join(command)` when the key is empty), `buildq.log` (the runner log).

**Writing.** A job file is written atomically (a temporary `.<ticket>.json.tmp`, then `os.replace`), mode 0600. Every
read-modify-write of a job file holds `flock(Q/.lock)` (LOCK_EX), briefly: never across a wait or a build. Readers take
no lock. The runner holds `flock(Q/.runner.lock)` for its whole life: a free lock means no runner.

**Job file.** Times are epoch seconds except `stopped`, which uses monotonic seconds for signal escalation. A run job is `zone-tool test`; a slot job is a build that `codeteam-slot` will exec
once the runner marks it running.

| field | meaning |
|---|---|
| `ticket` str | the job's id |
| `kind` | `"run"` or `"slot"` |
| `class` | `"land"`, `"full"`, `"post"`, `"pre"`, `"dev"` |
| `key` str | the record key (run); `"slot <tool>"` (slot) |
| `command` [str] | argv: after `--` for a run job; `[tool, *args]` for a slot job |
| `worktree` str or null | the git top level of the submitter's folder |
| `env` {str: str} | run: the submitter's whole environment, kept in every state (queued, running, done, broken), adopted and fallback jobs included, so a job can be re-run exactly; slot: `{}`. The deck never shows it |
| `team` str or null | the first `team-<x>` folder in `worktree` |
| `session` str or null | `CODETEAM_SESSION`; empty is null |
| `submitted`, `started`, `finished` | `started` and `finished` are null until they happen |
| `pid` int or null | run: the `zone-tool test` child (null from marking to spawn); slot: the waiting `codeteam-slot` process, which execs the tool and keeps the pid |
| `state` | `"queued"`, `"running"`, `"done"`, `"broken"` |
| `record` str or null | run: absolute path of the record `zone-tool test` writes; slot: null |
| `cost` float or null | CPU units against the budget; see build-queue.md |
| `estimated_start` float or null | refreshed at each decision, for queued jobs |
| `position` int or null | 1-based place among the queued jobs of the same class, in start order; null once not queued |
| `hold` str or null | why a queued job is not starting, written at each decision: `"warm"` (its `warm_lock` is flock-held) or `"swap"` (the guard holds its class); null otherwise and once not queued |
| `warm_lock` str or null | `<git dir>/codeteam-warm.lock`; null when `CODETEAM_WARMING` is set. A held lock keeps the job queued |
| `test_flags` [str] | run: the `zone-tool test` options (`--key`, `--salt`, `--scope`, `--timeout`, `--cached`, `--single`); slot: `[]` |
| `tool` str | run: absolute path of the `zone-tool` that submitted; slot: the wrapped tool's name |
| `record_mtime` float or null | run: the record's mtime just before the start (null if none); a record counts as this run's only when it is newer |
| `exit` int or null | the process's exit; null for a slot job and for an adopted job that ended without one |
| `result` str or null | the record's `result` (`PASS`, `FAIL`, `HUNG`, `BROKEN`; existing `TIMEOUT` records still read). `BROKEN` denotes an out-of-space phrase match as described above; it never answers `--cached` |
| `reason` str or null | why `broken`, `"fallback: ..."` when the submitter ran it itself, or `"hung: ..."` for a run job the backstop stopped |
| `fallback` bool | the submitter ran it itself because the queue was unavailable |
| `answered` bool | only on a `done` run job that `zone-tool test` answered from an existing record instead of running (`--cached` or `--single` found one): true. Its `result` and `exit` are that record's, and the history gets no line |
| `stopped` float | only after a hung run job's stop: monotonic seconds when SIGTERM was sent (SIGKILL follows on a later decision at least 10 s later) |

States. A submitter writes `queued`. The runner marks `running` (a run job gets its `pid` a moment later), then `done`
or `broken`. A submitter or `codeteam-slot` that cannot get a runner marks its own job `running` with `fallback: true`
only while it is still `queued` (a compare-and-swap under `Q/.lock`), runs the work itself, and marks `done` at the end.
`broken` means the job cannot finish: pid null while running; a run job, one the runner started or one it adopted after a
restart, whose process is gone without a fresh record (the record's mtime not newer than `record_mtime`; reason
`process gone without a fresh record`), whatever the exit code; a run job stopped by the hang backstop whose process is gone (with its `hung:` reason);
a queued slot job whose submitter is gone; or a start that failed. The one exception to the record rule is a job `zone-test`
answered from an existing record: the runner skips any number of leading
`--single` wait lines (`zone-test: a run is already going in this worktree; waiting for its result`) in the job's log,
with each read capped at 512 characters. The first other line decides; no later line counts, so the test's own
output cannot claim it. That line matching
`^zone-test: (PASS|FAIL|TIMEOUT) at \d\d:\d\d already recorded` (what `zone-tool test --cached` and `--single` print on a
hit, an exact one or one that restamped the record), together with a record that exists and says PASS or FAIL, makes the
job `done` with that record's result and exit, `answered: true`, and no history line. The line is checked first, so a
restamped (fresh) record is answered too. A run job stopped by the backstop stays broken even if a record exists.
A restart settles every job from the files alone; none runs twice.

**Hang backstop.** The runner judges a run job using the shared hang settings from the job's submitted `env` only,
the environment handed to the child; the runner's own environment does not supply missing settings.
Each ticket's in-memory watch starts at its first observation and uses twice `CODETEAM_HANG_WINDOW`, so
zone-tool's own watchdog gets the first chance to record HUNG. Log size growth counts as output; CPU sampling uses
one process table per decision for all running run jobs, excluding the runner and its subtree. Only a silent,
low-CPU window stops a run job, with TERM then KILL after 10 seconds on a later decision. A restarted runner starts
a fresh watch window. Slot jobs are never killed: their output is not visible to the runner, so it cannot prove
silence under the full hang rule. A slot job settles done only when its pid is gone or no longer runs its tool.

**Retention.** The runner removes a `done` or `broken` job and its `.log` once `finished` is older than `retention_hours`
(24).

**The runner's state: `Q/../queue-runner.json`** (not in Q, so every `Q/*.json` is a job). Rewritten
atomically at every decision:
`{"pid", "beat" (epoch), "budget", "used" (sum of running costs), "swap", "swap_max", "swap_hold"}`. A `beat` older than `CODETEAM_BUILDQ_STALE` (60 s) while the runner lock is held means a hung runner.
What each client does with a hung or missing runner:

- `codeteam-slot`: runs the build itself on any exception on the queue path, with no runner (none alive within
  `CODETEAM_BUILDQ_START_WAIT`), or with a stale beat while its job is still queued.
- `zone-tool job submit`: the same three, and the stale beat counts during `--wait` too, while the job is still queued.
- `zone-tool job wait`: never runs the test; it starts a runner that is gone, and on a stale beat prints
  `WAITING: the runner is not responding (last beat N s ago)` and exits 4.

Each fallback is a compare-and-swap under `Q/.lock`: it marks the job `running` with `fallback: true` only while the job is
still `queued`, and a job the runner already started is the runner's (it is never run twice).

**Starting the runner.** When no runner holds the queue lock, the clients request a start. For the live queue,
`zone-tool` and `codeteam-slot` run `/bin/launchctl kickstart gui/<uid>/com.codeteam.codeteam-buildq` (prefix from
`CODETEAM_LAUNCHD_PREFIX`, default `com.codeteam`). launchd starts the
runner in its own scheduling context, outside the client's process tree and throttled context.
`zone-tool` waits for the lock and a fresh heartbeat; `codeteam-slot` waits for the lock. The runner never signals itself
or its intermediate ancestors, and does not descend through itself, when it stops a hung run job's tree. The job's
own pid is signaled even if it is an ancestor; a signal to a parent does not reach its children.

Without `CODETEAM_BUILDQ_LAUNCH`, kickstart is sent only if the queue's realpath is `BUILDQ_LIVE_QUEUE`,
`<CODETEAM_HOME>/run/queue`, the queue served by the installed job. For any other queue, including a worktree's
default or a scratch `CODETEAM_QUEUE_DIR`, nothing is started; the reason names both queues and `CODETEAM_BUILDQ_LAUNCH`.
A submitter falls back to running the build or test with `build queue unavailable` on stderr; `job wait` does not run it.

`CODETEAM_BUILDQ_LAUNCH` selects a program in place of `/bin/launchctl` for any queue, with the same `kickstart
gui/<uid>/com.codeteam.codeteam-buildq` arguments and `CODETEAM_QUEUE_DIR` and `CODETEAM_BUILDQ_LOG` in its environment.
The test seam `zone/tests/fake-launchctl` starts `$CODETEAM_BUILDQ` (default `<repo>/bin/codeteam-buildq`) in the
background, or exits 113 with `Could not find service` if it is not executable. Only the fake reads `CODETEAM_BUILDQ`.
A not-loaded job (exit 113 or `Could not find service`) reports `build-queue runner job com.codeteam.codeteam-buildq is not
loaded in launchd (...); install it: launchctl bootstrap gui/<uid> ~/Library/LaunchAgents/com.codeteam.codeteam-buildq.plist`.
Another exit reports `cannot start the runner: <command> exited <rc>: <output>`.

**`queue.toml`** (all keys optional; unknown keys such as `load_max` are ignored): `budget` (6; else `CODETEAM_BUILD_BUDGET`),
`swap_max` (0.9), `retention_hours` (24), `slot_cost` (1), `land_jobs` (6: a `land` job's least
`CODETEAM_BUILD_JOBS`, whatever the budget gives), and per class `[classes.<c>] guaranteed`, `ceiling` (0 means no ceiling):
`full` 1/1, `post` 1/2, `pre` 1/2, `dev` 1/0. Each key is read on its own: a value of the wrong type or not finite
(`budget = "x"`, `classes = 3`), a whole number too big for a float (a 400-digit integer), or bad TOML, gives that key its
default. A job file that is not JSON or lacks a key the
runner indexes (`ticket`, `kind`, `class`, `state`, `key`, `command`, `submitted`; a run job also `tool`, `env` and `record`,
in every state; a slot job `tool`; and `ticket` must equal the file name) is skipped by the runner and left as it
is. The runner lists and reads Q once per decision and keeps what it wrote in that snapshot, so a job submitted during a
decision is seen at the next (one tick later).

**`zone-tool job`** (run from inside a worktree):

- `job submit [--class land|full|post|pre|dev] [--wait SECONDS|auto] [--key T] [--salt T] [--scope DIR] [--timeout S] [--cached]
  [--single] -- <command>`: queues `zone-tool test` with those options (class as requested, default `dev`; an unknown class exits 2).
  Without `--wait` it prints the ticket alone on one line and exits 0. With `--cached` or `--single`, a record that
  answers is printed as `zone-tool test --cached` prints it, and no job is written (exit 0 without `--wait`; with it, 0 for
  a PASS and 1 otherwise). With `--single`, a queued or running job with the same worktree, key, salt and command answers
  with its ticket. `--wait S` then waits like `job wait`: exit 0 when the test passed, 1 when it ran and did not (never 3 or
  4), 4 still waiting (last line `WAITING: zone-tool job wait <ticket>`), 3 broken; `--wait 0` waits with no limit.
  Inside a running job (`CODETEAM_BUILDQ_TICKET` set) it runs `zone-tool test` in-process, with no job file. When the
  queue is unavailable (any exception on the queue path, no runner, or a stale beat while the job is still queued,
  during `--wait` too) it prints `zone-tool: build queue unavailable (<why>); running the test here` on stderr and runs
  the test itself, after marking its job `running` with `fallback: true`, `started` and `record_mtime` (only while still
  `queued`; a job the runner already started carries on as a wait). `--wait auto` waits `BASH_DEFAULT_TIMEOUT_MS` / 1000
  less 60 seconds when that variable is set (1740 in a codeteam session), at least 30, else 100.
- `job wait <ticket> [--max SECONDS]` (default 540): exit 0 DONE (prints the job's log, then
  `zone-test: <result> (exit N); record <path>`, or `zone-test: <result> (exit N); answered from record <path>` for an
  `answered` job; a FAIL is still 0), 4 WAITING (`WAITING: queued, number N in class C,
  estimated start HH:MM` or `unknown`, with `, held: <hold>` added when `hold` is set, or `WAITING: running for M min`;
  then `WAITING: zone-tool job wait <ticket>`), 3 BROKEN (`BROKEN: <reason>`), 2 no such ticket. A wait that finds the
  runner dead starts it again; on a stale beat it prints `WAITING: the runner is not responding (last beat N s ago)` and
  exits 4. It never runs the test.
- `job status [<ticket>]`: exit 0. First line `budget <used>/<budget> swap <s>/<max>[ HOLD dev]`
  (`runner: not running` without a runner), then one line per queued and running job (with a ticket: that job in any
  state): `<ticket> <class> <state> <team|-> <session|-> <worktree|-> cost=<c> <queued N s|running N s|done exit N|broken: why>`.

**zone.mk.** `make zone-test` submits class `$(or $(CLASS),full)`, `make zone-test-one` class `$(or $(CLASS),dev)`, each with
`--wait $(ZONE_JOB_WAIT)`. `ZONE_JOB_WAIT` is `auto` by default: the session's own shell limit minus a minute (1740 s
where `BASH_DEFAULT_TIMEOUT_MS` is 1800000, never under 30 s), else 100 s for Claude Code's default 120 s limit. A job
still waiting then makes make fail with zone-tool's exit 4 (make reports "Error 4") and print
`WAITING: zone-tool job wait <ticket>`; `ZONE_JOB_WAIT=0` waits until the job is done (gates and scripts).
`CODETEAM_TEST_GROUP` passes through the queue and zone-tool `test-one` to the tests; its non-unit value adds
` test-group=<group>` to the `zone-test-one` record key, separate from `GROUP`'s ` group=<group>` term. Unset or
`unit` keeps the existing key, and a pass in one group cannot satisfy another group's whole-run retry guard.
`PYTEST_ARGS` and `PYTEST_ADDOPTS`, when non-empty after stripping whitespace, append ` pytest=<value>` and
` pytest-addopts=<value>` before the group terms; unset, empty or whitespace-only values leave the key unchanged.
`PYTEST_ARGS` can reach a repo Makefile's `test-one`, but zone.mk's own does not pass it to pytest. An exported
`PYTEST_ADDOPTS` reaches zone.mk's pytest; a repo Makefile controls whether it reaches pytest there. The labels distinguish these from
unlabelled SWIFT/CARGO terms, with two accepted collision limits: values containing label words can still collide,
and `zone-tool job submit` collapses whitespace in `--key`, so values differing only in inner whitespace share a record.
Either variable with a non-whitespace value makes the key a filtered run for zone-tool's whole-run guard: `_key_parts` treats any word
after `one DIR` other than `owns=`, `group=` or `test-group=` metadata as a filter.

**zone-check.** `make zone-check DIR=<path>` runs `zone-tool check <DIR>`, the type-check also used by the test
submission guard. The guard skips it for joined jobs, build-queue tickets and landings, as well as recorded answers.
It uses the manifest's `ZONE_CHECK_CMD` if set, else the product Makefile's `check` target if present, else no check.
`ZONE_CHECK=0` turns it off.

With `ZONE_CHECK_CMD`, DIR's paths are separate arguments: the command runs as
`sh -c '<ZONE_CHECK_CMD> "$@"' zone-check <paths...>`. `ZONE_CHECK_CMD` must accept a list of path arguments after
it; `bin/py-syntax-check` takes paths. Paths are never pasted into the command string. A `DIR` resolving to the repo
root (`.` or `./`) means the lane's owned paths: each `CODETEAM_OWNS` entry glob-expanded from the root, as for
`test-one`. With no non-empty `CODETEAM_OWNS` entries the command gets no arguments; `bin/py-syntax-check` then checks
the whole repo. When non-empty entries match nothing, the check is clean without running. Any other `DIR` is passed as
given. The `make check` fallback gets no argument, since make would treat it as a target; it sees `DIR` through the
environment. The command or Makefile determines what is actually checked.

The latest result is stored in the worktree's git dir (`codeteam-test-guards.json`), keyed by tree hash and normalized
`DIR`, plus `CODETEAM_OWNS` at the root. Only a clean result is reused; a check for another key replaces it. As with
every zone target, `DIR` values containing whitespace or `;` are not supported.

**Environment knobs** (defaults are production): `CODETEAM_QUEUE_DIR`, `CODETEAM_QUEUE_CONF`, `CODETEAM_BUILD_BUDGET`
(budget when `queue.toml` has none); `CODETEAM_BUILDQ_TICK` (seconds between decisions and polls, 1.0);
`CODETEAM_BUILDQ_IDLE_EXIT` (seconds of an empty queue before the runner exits, 0 = never);
`CODETEAM_BUILDQ_LOAD_FILE` (a file whose second whitespace-separated word is the swap fraction, read instead of the machine; the first word is ignored; a missing second word gives 0.0, and an unreadable file or invalid fraction falls back to the machine);
`CODETEAM_BUILDQ_START_WAIT` (seconds a client waits for a runner it started, 10); `CODETEAM_BUILDQ_STALE` (60);
`CODETEAM_BUILDQ_LAUNCH` (launchctl substitute for any queue); `CODETEAM_BUILDQ` (runner used only by the test fake,
default `<repo>/bin/codeteam-buildq`); `CODETEAM_JOBS_PER_SLOT` (compiler jobs per build, 4).

**`bin/codeteam-slot`.** A gated command writes a slot job (class `dev`), makes sure a runner runs, waits until the job is
`running`, sets `CODETEAM_SLOT_HELD=1` and execs the tool. A command that is not gated, or that has `CODETEAM_SLOT_HELD` or
`CODETEAM_BUILDQ_TICKET` (inside a job), runs at once and writes nothing. While its job is queued it says once that the
worktree is still being warmed when `hold` is `"warm"`. Any fault on the queue path, no runner, or a stale beat while the
job is still queued runs the build at once and says so on stderr. It writes no slot lock files and reads neither `CODETEAM_COMPILE_SLOTS` nor `CODETEAM_SLOT_DIR`.

## The warm lock's holder record

`share/claude-hooks/worktree-create.py` writes one JSON object on one line, ending in a newline, over the contents of
`<git dir>/codeteam-warm.lock` (truncate, then write) through the held lock fd once the detached warm has started:
`{"pid": int, "team": str|null, "session": str|null, "worktree": str|null, "tool": "warm", "since": int}`. `pid` is the
detached warm's (the `python -c` wrapper that runs `make warm`), `since` is epoch seconds, `team` is the first `team-<x>`
folder in the worktree's path, `session` is `CODETEAM_SESSION` (an empty value counts as null).

Best effort: any error building or writing the record is swallowed, and the warm goes on as it would without it. Nothing
clears the record, so it outlives its holder; a reader counts it only while its `pid` is alive. The write is not atomic,
so a reader can see an empty file or the previous holder's record for a moment; an empty, old-format or unreadable file
means unknown. The flock is the only truth: the runner probes it (try, release at once) to keep a job queued while its
worktree is still being warmed, and readers never take, test or release it for any other reason.

Tests: `zone/tests/test_buildq_launch.py` (kickstart, queue guard, override and errors), `zone/tests/buildq-sched.sh`, `buildq-restart.sh`, `buildq-plist.sh`, `buildq-e2e.sh` (the runner),
`zone-job.sh`, `zone-job-mk.sh` (the verbs and make targets), `slot-queue.sh`, `slot-record.sh` (codeteam-slot),
`warm-lock-record.sh` (the warm lock record).
