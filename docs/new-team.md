# Starting a new codeteam team

How to bootstrap a team so it builds fast and works on its product from day one. Written from what went wrong with
earlier teams: a lane layout that did not match the code's dependencies, a build that recompiled the whole crate on
every edit, release builds in daily work, vendored code rebuilt in every worktree, tests leaking temp files, agent
files and MCP servers left from other teams, and an orchestrator doing lane work. Each step below says what to check
and what it costs to skip.

The team does not start until every step is done: `team/HALTED` stays in place until the last one.

`teams/example.toml` and `catalog/products/example/` are a worked example of the files this page asks for.

## 1. The mission (the owner writes; the designer refines)

Use the mission template (`docs/mission-template.md`). Besides what to build and what it must match, a mission
answers four questions before any lane exists:

1. **Layout.** The packages or crates, and which depends on which. Lanes follow this graph (step 3).
2. **Build and test.** The commands for a quick check, one zone's tests, and the full suite; how long each should
   take; what never runs in daily work (release, benchmarks, live services).
3. **Fixed inputs.** Vendored or pinned code that never changes here (a parser kernel, a pinned SDK, another
   team's libraries): it is built once, not per worktree (step 5).
4. **Done.** The acceptance test that says the product is finished, and who runs it.

## 2. The repo

- A git repository with an HTTPS remote (for example `gh repo create <owner>/<name> --private`); every remote is
  `https://github.com/<owner>/<repo>.git` (gh's token; never an ssh address).
- The base checkout at `$CODETEAM_WORKSPACE/<name>` (default `~/codeteam-work/<name>`, or under `.repos/`), linked
  as `team-<name>/design/<name>-<base>`.
- `.gitignore` covers the build output (`cargo-target/`, `target/`, `.build/`, `node_modules/`, `.codegraph/`).

## 3. Lanes from the dependency graph

- **One lane per package or crate where possible.** A lane that owns a module inside one big crate pays for every
  other lane's edits: each edit anywhere rebuilds the whole crate (one team with one crate and seven lanes spent
  39 of 69 job-hours a day compiling).
- **Draw the dependency graph first** (which package uses which, in production code). Lanes at the bottom (used by
  others, using few) split cleanly; a cycle between would-be lanes is either one lane or a refactor to do first.
- **A single-crate repo that must stay one product is still a workspace:** one crate per lane, one binary crate
  on top. The product ships the same.
- Each lane owns its package folder and its tests (`path` lanes where the package is a folder; `owns` only where a
  lane's code is scattered). The orchestrator owns the workspace root (`Cargo.toml`, `Package.swift`, the
  Makefile) and whatever no lane owns.

## 4. Build setup (the manifest's [env])

Set all of these in the new team's manifest before the first session starts, and check them with one build:

| Setting | Why |
|---|---|
| `CODETEAM_CARGO_TARGET = "1"` | builds go to `<worktree>/cargo-target`, which warm clones and the sweep clean |
| `CODETEAM_WARM = "1"` | every new request worktree starts as a copy-on-write clone of its lane's build |
| `RUSTC_WRAPPER = ".../bin/sccache-wt/sccache"`, `SCCACHE_CACHE_SIZE = "20G"` (optional, needs sccache) | compiled dependencies shared machine-wide |
| `CARGO_INCREMENTAL = "1"` | a small edit recompiles only what changed (sccache-wt sends these compiles straight to rustc) |
| `CARGO_PROFILE_DEV_DEBUG = "line-tables-only"`, same for TEST | smaller build folders, backtraces keep file:line |
| `CARGO_PROFILE_RELEASE_LTO = "false"`, `..._CODEGEN_UNITS = "16"` | a stray `--release` costs minutes, not an hour |
| Swift: `CODETEAM_SWIFT_XCODE = "1"` (or the product's equivalent) | Swift through Xcode's compile cache |

Then check: two request worktrees in a row, the second's first build should take seconds, not minutes.

## 5. Fixed inputs are built once

Vendored code that never changes (a parsing kernel, generated grammars, C sources) goes in its own package, and the
product depends on it through a fixed path: a `[[pins]]` checkout codeteam keeps at `team-<name>/<pin>/current`.
Every worktree then sees the same path and reuses the compiled result. Built from a path inside each worktree, it
recompiles in every worktree (one team rebuilt five C grammars in every request).

## 5a. A CodeGraph index in every worktree (optional)

When CodeGraph is installed, `codeteam init` pins each standing worktree in CodeGraph and seeds its index from a
sibling that has one (`codeteam-seed-index`, about a second); the worktree hook does the same for request worktrees.
A worktree with no index sends its agents back to grep. The first index in a new repo is built once, by the first
query in its base checkout. Without CodeGraph these steps are skipped with a warning.

## 6. Make targets the agents use

The product's Makefile (or codeteam's zone.mk defaults) must have, before lanes start:
- `make check`: a type-check, the push gate, in seconds.
- `make zone-test-one DIR=<package>`: one package's tests, through the build queue, with a record. One call per
  port for a whole zone; a filter only for a handful.
- `make zone-test`: the zone's whole suite (its `ZONE_TEST`), through the build queue at the `full` class by default.
- `make warm`: what codeteam's worktree hook runs.
- `make zone-clean`: removes the worktree's build output (codeteam's zone.mk gives it to every team; a product
  Makefile may add its own `clean`).

Write the exact commands, per port, in the product notes' "Test calls" table, including a **whole zone** row.

## 7. Tests

- No test leaves files behind: temp folders are dropped at the end (one team's tests once left 1,714 repos).
- A test over 5 seconds alone is fixed or carries `// slow: <reason>`.
- Nothing in daily work reaches a live service, a model or the network.
- `--release`, benchmarks and performance runs only when the owner says (a ruling in the mission).

## 8. Agents

- Build the team's agents from the catalog: a product in `catalog/products/<name>/` (`product.toml`,
  `rules/product.md`, `rules/team-layout.md`), then
  `python3 -I catalog/generate.py <name> --install $CODETEAM_WORKSPACE/team-<name>`. Never hand copies: they drift
  and miss fixes (stale references, missing hooks).
- `rules/product.md` says what the product is, its ports, its test calls (step 6) and its layout (step 3), and is
  checked against the repo before the team starts: a wrong command there costs every lane.
- Every standing role gets `refocus`; the `zone-tests` skill is preloaded where anyone builds.
- The team's `claude/hooks` has `capture-metrics.sh` (the status line) and settings link codeteam's hooks.

## 9. MCP and permissions

- `mcp.json` at the top of the codeteam checkout gives every team's sessions its MCP servers (copy
  `mcp.example.json` to enable CodeGraph); team-only servers go in the manifest's `[v2] mcp_extra`.
- No `.mcp.json` in the repo unless the product needs one (a stray one shadows the shared servers).
- The global settings allow the MCP tools agents use daily; nothing an agent needs every day is "ask".

## 10. Staff and rules

- Orchestrator routes and merges; it starts no leads for lane work. Work that crosses lanes but is one job
  (upstream PRs, a release) is its own lane, not the orchestrator's.
- A designer from day one: it holds the discussions with the owner and the plan; the orchestrator keeps the queue.
- The harness rule is in every role file (codeteam adds it); the owner's specs are fixed (clarify, never change).
- Models from the roster (the manifest's `orc_model`, `lane_model` and the product's `[models]`).

## 10a. Branch flow v5.4: every team lands

A new team starts on branch flow v5.4 (`docs/SPEC-branch-flow-v5.4.md`), never on exchange and push-up:

- The manifest has `[land] enabled = true` and the zones. Stage 6's validation tier defaults to a local `validate-suite`
  in `<worktree_root>/land/validate`; `[land.validate]` (`local = true`, `path`, `suite`) sets a team's own local tier,
  and `[land.remote]` (`host`, `path`, `suite`) runs it on another machine over ssh.
- `codeteam-land <manifest> install-hook` (integration and base change only by landing; the append-only logs merge
  by union), `alpha-install` (the validation clone), `service install` (the queue, recheck and validation runners:
  `queue-run`, `recheck-run`, `validate-run`).
- No standing lane worktrees: coordinators work in `workcrews/<lane>`; every lead's tree is cut from integration.
- The orchestrator's and designer's own edits land as `orc` work orders.

## 11. Before unhalting

Run `codeteam-check-team <name>`: it checks every step above that a machine can check (build settings, ignores,
make targets, the catalog install, skills, hooks, MCP, a designer, the plugin, the landing hook, queue, recheck and
validation runners and the validation tier) and lists what to fix. Then one work order end to end on a throwaway change:
a lead in its own tree cut from integration, warm in seconds, units green (Stage 1), `codeteam-land land` (Stage 2,
the check in the tree), Kong's review (Stage 3), the landing runner's merge (Stage 4), Stage 6's `validate-run`
passing on the new tip (its row in `land/validation-results.jsonl`), and Stage 7 promoting it. Then remove
`team/HALTED` and `codeteam2 up`.
