# Mission: <product>

The owner's decisions, <date>. Contains only those.

## What
What is built, and why. What is not part of this mission.

## Who and where
- Team: team-<name>. Repo: <owner>/<repo> (HTTPS remote).
- Other teams this one depends on or feeds, and how (pins, path dependencies, links).

## Layout
The packages or crates and the dependency graph between them (who uses whom, in production code). Lanes follow
this graph: one lane per package where possible. Any cycle is named here with how it is resolved (one lane, or a
refactor first).

## Fixed inputs
Code this team uses and never changes (vendored kernels, pinned SDKs, other teams' kits): where each comes from,
pinned at what, and that it is built once (a pin), not per worktree.

## Build and test
| Purpose | Command | Should take |
|---|---|---|
| Quick check (push gate) | | seconds |
| One zone's tests (per port) | | under a few minutes |
| Full suite (merge gate, orchestrator) | | |

What never runs in daily work: release builds, benchmarks, performance runs, live services, models. Each of those
runs only when the owner says.

## What it must match
The behaviour, interfaces and data it must be compatible with, and where each is specified.

## Done
The acceptance test that says the product is finished: what it runs, on what, and who runs it.

## How the code is written
The charter or rules all new code follows.
