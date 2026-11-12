# The build queue

The rules are in `SPEC.md`; the interface (job file, verbs, exit codes, environment knobs) is in `INTERFACE.md`. This
file holds the working notes: what the queue is and how to install it.

## What it is

One runner, `bin/codeteam-buildq`, decides which build or test starts. Every `make zone-test`, `make zone-test-one`
(through `zone-tool job submit`) and every gated `swift`, `cargo` or `xcodebuild` call (through `bin/codeteam-slot`) is a
job file in `run/queue/`. A submitter gets a ticket at once and waits in bounded steps, so it can stop waiting while the
job remains queued or running. The runner starts a run job as a detached `zone-tool test` (own session, its class's nice: `land` 0, `full` 2, `pre` and `post` 5, `dev` 10, never below
the runner's own; the
submitter's environment, its output to `Q/<ticket>.log`), and marks a slot job `running` so the waiting `codeteam-slot`
execs its tool.

- **Budget.** CPU units, 6 by default. A job's cost is its expected CPU share (cpu seconds over wall seconds of its last
  5 runs, 1 to the budget; 1 with no history, 4 for a `full` job; `slot_cost` (1) for a slot job).
- **Classes**, in start order: `land` (guaranteed 2, no ceiling), `full` (1, 1), `post` (1, 2), `pre` (1, 2), `dev` (1, no ceiling). A job
  may start when its class is under its guaranteed share, or when the budget has room for its cost plus what the other
  classes' waiting jobs reserve, and its class is under its ceiling. Inside a class the next job is the oldest of the team
  whose last start in that class is least recent (round-robin by team).
- **Guards.** Load never holds a start. Over `swap_max` (0.9) no `dev` job starts. A job whose worktree is still being
  warmed (its `codeteam-warm.lock` is flock-held) is skipped until the warm ends.
- **Restart.** The runner settles every job from the files alone: its own children by `Popen.poll`, adopted ones by pid and
  the record's mtime. A run job (its own child or an adopted one) whose process is gone without a fresh record, newer
  than `record_mtime`, is `broken` ("process gone without a fresh record"), whatever its exit code; none runs twice. The
  exception to the fresh-record rule is a job `zone-test` answered from an existing record: `done`, `answered: true`.
  A run job stopped by the runner's hang backstop settles `broken` with its `hung:` reason when its process is gone.
- **Hang backstop.** The runner judges a run job using the shared `CODETEAM_HANG_WINDOW` and `CODETEAM_HANG_CPU_PCT`
  settings from the job's submitted `env` only, the environment handed to the child; the runner's own environment
  does not supply missing settings. The runner requires both no growth in the job's log
  and tree CPU below the threshold over twice the configured window, giving zone-tool's own watchdog the first
  chance to write HUNG. Each ticket's watch starts at its first observation; a restart starts a fresh window.
  One process table is shared by the run jobs at each decision, excluding the runner and its subtree from CPU.
  A hung tree gets TERM, then KILL after 10 seconds on a later decision if still alive.
- **The environment.** A run job carries the submitter's whole environment (`env`) for the life of its file, in every
  state (queued, running, done or broken). The runner starts the child with it.
- **One read per decision.** A decision lists and reads Q once and updates that snapshot as it writes.
- **Fallback.** The queue never fails a build; each client falls back on exactly these, with one line on stderr:
  - `codeteam-slot`: any exception on the queue path; no runner (none alive after `CODETEAM_BUILDQ_START_WAIT`); a
    heartbeat older than `CODETEAM_BUILDQ_STALE` (60 s) while its job is still queued. It marks its job `running` with
    `fallback: true` (only while it is still `queued`) and execs the tool.
  - `zone-tool job submit`: the same three, and the stale heartbeat counts during `--wait` too, while the job is still
    queued. It marks its job `running` with `fallback: true` and `record_mtime` (only while still `queued`) and runs
    `zone-tool test` in-process. A job the runner already started is not run again: submit carries on as a wait.
  - `zone-tool job wait`: never runs the test. It starts a runner that is gone, and on a stale heartbeat prints
    `WAITING: the runner is not responding (last beat N s ago)` and exits 4.
- **Why a job waits.** The runner writes `hold` into every queued job file at each decision: `"warm"` (its worktree's
  warm lock is held), `"swap"` (the guard holds its class), or null; null once the job is not queued.
  `job wait` adds `, held: <hold>` to its WAITING line, and `codeteam-slot` says once that the worktree is being warmed.
- **Starting the runner.** When no runner holds the queue lock, the clients request a start. For the live queue they run
  `/bin/launchctl kickstart gui/<uid>/com.codeteam.codeteam-buildq` (the label prefix is `CODETEAM_LAUNCHD_PREFIX`,
  default `com.codeteam`). launchd starts the runner outside the client's process tree
  and throttled scheduling context (a Swift build started from a session ran much slower there). `zone-tool` waits for the lock and a fresh heartbeat;
  `codeteam-slot` waits for the lock. The tree walk never signals the runner or its intermediate ancestors and does
  not descend through the runner. The job's own pid is signaled even if it is an ancestor, since a signal to a parent
  does not reach its children.
  Without `CODETEAM_BUILDQ_LAUNCH`, the clients send kickstart only for the realpath of `BUILDQ_LIVE_QUEUE`,
  `<CODETEAM_HOME>/run/queue`; for other queues they start nothing and name both queues and the override in the
  reason. Submitters fall back with `build queue unavailable` on stderr; `job wait` does not run the test. The override
  selects a launchctl substitute for any queue; see `INTERFACE.md` for the test seam and errors.

Files: Q is `run/queue/` (0700, its files 0600); `run/queue.toml` (config, read at every decision), `run/queue-runner.json` (the runner's
heartbeat and state), `run/queue-history.jsonl`, `run/buildq.log`.

**Known limit.** The runner cannot see a slot job's output because `codeteam-slot` execs the tool on the caller's
own stdout. Under the spec's rule (no output AND under 1% CPU), the runner therefore never kills a slot job. A hung
direct `swift test` or `cargo test` holds its slot until someone stops it. Zone-tool runs, which Stage 1 and land's
jobs use, are under the full rule in zone-tool and the runner's backstop on run jobs.

## Install (by hand, once)

The installed job is `com.codeteam.codeteam-buildq`, at `~/Library/LaunchAgents/com.codeteam.codeteam-buildq.plist`.
It runs `<CODETEAM_HOME>/bin/codeteam-buildq --standby` with KeepAlive; standby waits for the runner lock.
Install or update it using the instructions in `share/codeteam-buildq.plist` (fill in your own paths first); updating a
loaded job first unloads it, stopping the runner.

The repo's `share/codeteam-buildq.plist` matches the installed job: the same label, keys and values;
`plutil -convert json` of the two files gives the same dict. Without the installed job, a start reports that it is not
loaded and a build or test falls back to running locally. A waiter finding the runner dead attempts to start it again.
