# acme-widgets: repo-level instructions for agents

The product layer. Role files say how to do a job; this file says what this product is.

## Read first
- `docs/MISSION.md`: what acme-widgets is and what done looks like.
- `docs/SPEC.md`: the behaviour each crate must meet.

## What this repo is
`acme-widgets`, base branch `main`: a Cargo workspace that builds one command, `acme-widgets`, for keeping a list of
widgets in a local SQLite file. Every crate is a folder `crates/<crate>/` with its own `src/` and `tests/`.
Each lane owns the crates of its code:
- core: `widget-core` (the widget model, validation, pure functions)
- store: `widget-store` (SQLite schema, migrations, queries)
- cli: `widget-cli` (argument parsing, output, the commands)
- the orchestrator: the workspace root (`Cargo.toml`, `Cargo.lock`), the `Makefile`, and anything no lane owns.

A crate depends only on crates below it (cli -> store -> core); a new dependency upward is a design question for the
designer, not a lane's choice.

## Ports
One port: Rust. "Both ports" or "parity" in a role file means Rust alone.

## Test calls (all through make; see the zone-tests skill)
| Purpose | Command |
|---|---|
| **The whole zone** | `make zone-test-one DIR=crates/<crate>` for each crate the lane owns |
| One module's unit tests | `make zone-test-one DIR=crates/<crate>/src/<module>` (filter: `CARGO_TEST_ARGS=<name>`) |
| One crate's integration tests | `make zone-test-one DIR=crates/<crate>/tests` |
| Records | `make zone-test-status` |
| Type-check (the landing gate) | `make check` |
| Format | `make fmt` |
| Whole suite (orchestrator only, merged result) | `make zone-test` |

## Code conventions

Rules on how the code is written: names, which literals may appear where, who may call what. The change-reviewer
checks each one on the changed lines; Nagatha checks the code already landed when she reviews a feature. One line each:
the rule, and why. None yet.
