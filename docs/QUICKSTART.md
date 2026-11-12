# Quickstart

This walks the example team in `teams/example.toml` from nothing to running sessions. The example product,
acme-widgets, is made up: you create an empty repo for it below, so the team has somewhere to work.

## 1. Prerequisites

- macOS (the tool uses launchd, `lockf`, APFS copy-on-write clones and Terminal/herdr panes).
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code), signed in (`claude` on PATH).
- [herdr](https://herdr.dev): `brew install herdr`.
- Python 3.12 or newer as `python3` on PATH (Homebrew's is fine), with `pytest` if you want to run the tests.
- git 2.54 or newer (`brew install git`).
- Optional: `sccache` (`brew install sccache`) to share compiled Rust crates between worktrees.
- Optional: the CodeGraph MCP server (`codegraph` on PATH) for code search; without it, those steps are skipped.

## 2. Install

```bash
git clone <this repository> ~/codeteam-gamma-preview
export CODETEAM_HOME=~/codeteam-gamma-preview
export PATH="$CODETEAM_HOME/bin:$CODETEAM_HOME/v2/bin:$PATH"
```

Settings (environment variables; all optional):

| Setting | Default | What it is |
|---|---|---|
| `CODETEAM_HOME` | the checkout the command runs from | this repository |
| `CODETEAM_WORKSPACE` | `~/codeteam-work` | where team folders, bare repos (`.repos/`) and `team-links/` live |
| `CODETEAM_PYTHON` | `python3` | the interpreter hooks and generated commands use |
| `CODETEAM_LAUNCHD_PREFIX` | `com.codeteam` | prefix of every launchd label codeteam installs |
| `CODETEAM_CATALOG` | `$CODETEAM_HOME/catalog` | the agent catalog |
| `CODETEAM_OWNER` | `Owner` | your name as a message sender and recipient |
| `CODETEAM_METRICS_DIR` | `$CODETEAM_WORKSPACE/metrics` | where the status line hook writes |

To give every session the CodeGraph MCP server: `cp mcp.example.json mcp.json`.

## 3. A repo for the example product

```bash
mkdir -p ~/codeteam-work/acme-widgets && cd ~/codeteam-work/acme-widgets
git init -b main && cargo init --name acme-widgets && git add -A && git commit -m "start"
```

(`teams/example.toml` names this path in `repo`; change it there for a real product.)

## 4. Build the example team's agents

The catalog turns role files, skills and a product layer into one team's agent files, then installs them into the
team's claude home:

```bash
python3 -I "$CODETEAM_HOME/catalog/generate.py" example --install ~/codeteam-work/team-acme-widgets
```

## 5. Create the team and start it

```bash
cd "$CODETEAM_HOME"
codeteam init teams/example.toml --all-lanes       # tiers, worktrees, channels, role prompts; safe to re-run
codeteam-land teams/example.toml install-hook      # only the landing tool may move landing, integration and base
codeteam-land teams/example.toml service install   # launchd jobs: queue, recheck and validation runners
codeteam-check-team example                        # every check a machine can make; fix what it lists
codeteam2 up teams/example.toml                    # the staff sessions and the loop, in herdr
herdr session attach codeteam                      # watch (ctrl+b q detaches; everything keeps running)
```

Background jobs (once per machine; launchd jobs run in your login session):

```bash
share/install-buildq-plist.sh      # the build queue runner every zone-test goes through (--print shows the plist)
codeteam-watchdog install          # every 5 minutes: restarts a dead team loop, frees disk from idle build output
crontab -e                         # then add, for each team manifest:
#   * * * * *  $CODETEAM_HOME/bin/codeteam wake   $CODETEAM_HOME/teams/example.toml
#   13 * * * * $CODETEAM_HOME/bin/codeteam tick   $CODETEAM_HOME/teams/example.toml
#   7 * * * *  $CODETEAM_HOME/bin/codeteam rotate $CODETEAM_HOME/teams/example.toml
#   23 * * * * $CODETEAM_HOME/bin/codeteam sweep  $CODETEAM_HOME/teams/example.toml
# (cron has no $CODETEAM_HOME: write the paths out in full.)
```

Talk to the team: `codeteam2 say teams/example.toml general Owner REQUEST Orc-Acme-widgets "..."`.
Stop it: `codeteam2 down teams/example.toml`. A file `team/HALTED` in the team folder keeps every session from
starting until you remove it.

## 6. How landing works

Every change is a work order in its own worktree, cut from `integration` (a copy of proven code). The coder runs the
zone's unit tests, then `codeteam-land <manifest> land <wo>`: the tool merges `integration` in, reruns what the merge
touched, compiles the zone and its direct dependents and runs their integration tests (Stage 2). Kong reviews the
work order's own commits (Stage 3); a clean verdict queues it, and the landing runner merges it onto `landing`, one
entry at a time (Stage 4). Landings that overlap other unproven work are rechecked (Stage 5), the newest landing whose
rechecks are done is validated in its own clone (Stage 6), and a commit that passed with every earlier failure fixed
is fast-forwarded onto the base branch and `integration` (Stage 7). Only test failures hold promotion. The full rules
are in `docs/SPEC-branch-flow-v5.4.md`; setting up a real team is in `docs/new-team.md`.
