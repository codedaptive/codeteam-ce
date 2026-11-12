# SPEC

What this zone must do. Changes come from the user and the repo-orchestrator.

## The build queue

- Every test run (`make zone-test`, `make zone-test-one`) and every gated build (`swift`, `cargo`, `xcodebuild`) goes
  through one runner, `bin/codeteam-buildq`, which shares a CPU budget between five classes (`land`, `full`, `post`, `pre`,
  `dev`): each has a guaranteed share and may borrow what is idle up to its ceiling, round-robin by team inside a class.
  No load guard: load never holds a start. The swap guard holds dev starts when swap use exceeds `swap_max`
  (90% by default).
- A job is a file. A test run's submitter gets a ticket at once and waits in bounded steps (`zone-tool job submit`,
  `job wait`, `job status`), so a shell command can stop waiting while the job remains queued or running; killing the
  shell does not stop a run started by the runner. A gated build through `codeteam-slot` is a job file too, but it waits for its turn inside the caller's
  shell and then runs as that shell's child, as before the queue.
- The runner can die and come back at any time and settle every job from the files; no job runs twice.
- The queue never fails a build: when it is unavailable (any fault, no runner, or a hung runner), the build or test runs
  where it was asked, and says so. The live-queue runner starts through launchd outside the client's process tree,
  so killing a build's process tree cannot kill it.
- A repeat on unchanged code is answered from its record without queueing.
- Interface: `INTERFACE.md`. How the queue works: `build-queue.md`.
