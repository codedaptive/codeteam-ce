# codeteam v2: codeteam's runtime on herdr

The team runtime: it starts each session in a herdr pane, reads its real state, and delivers messages only
when the session is ready. The process (manifest, worktrees, roles, the zone guard, the git flow) stays in
`bin/codeteam` (v1), which v2 loads as a library.

## What it is

codeteam v1 does two jobs: the **process** (manifest, worktrees, roles, the zone guard, the git flow,
test records, the branch rule) and the **runtime** (windows, launching sessions, delivering messages,
guessing who is working or stuck, the lane cap, driving compaction). v2 keeps the process (it loads v1
as a library) and replaces the runtime with herdr:

| Runtime job | v1 | v2 |
|---|---|---|
| Windows | tmux groups, Terminal tabs | one herdr session `codeteam`: a workspace per team, a `staff` tab, a tab per lane |
| Starting a session | launch script + PID registry | the same launch script, run in the session's pane; herdr detects Claude and v2 names it `<team>-<session>` |
| Who is working or stuck | transcript age, PIDs, guesses | herdr's state per pane: working, blocked, done, idle |
| Delivering a message | channel files + a watcher the session runs and re-arms every turn | a message store (queue-shaped; MCP push later); delivered with herdr `agent prompt` only when the recipient is idle or done, never into a dialog, never while someone has unsent text in its input box, and nothing is typed while its pane shows a subagent's view; queued mail goes in one prompt; after three prompts with no turn the orchestrator gets one NOTE and the owner one notification (none again for mail already named), and all the recipient's mail waits until its state changes (status, a completed turn, herdr's state seq, a `[codeteam]` prompt in its transcript, or a loop restart); a session started for mail gets it in its first prompt |
| Lane cap and swap | cron `wake` on guessed idleness | the loop, on real state: wake for mail within the cap; at the cap, /exit a lane idle for `swap_idle_min` with nothing waiting (mail waiting behind a no-turn episode does not count), passing over a lane the owner put on hold (`team/held/<key>`) or one whose pane shows a subagent's view or unsent text in its input box (it keeps its slot; the next idle lane goes) |
| Idle sessions | tick: /compact at 3 h, /exit at 6 h | /exit after `idle_exit_h` (6) with nothing waiting (mail waiting behind a no-turn episode does not count), never the orchestrator or a designer, nor a session the owner put on hold (`team/held/<key>`) or one whose pane shows a subagent's view or unsent text in its input box; a session idle 50-58 min with at least 150k tokens of context and nothing waiting gets /refocus, /prepare-for-compact, /compact and /recover-from-compact while its cache is warm; below that, Claude Code's own idle compaction at 55 min |
| Stuck agents | patrol, after the fact | blocked longer than `blocked_alert_min`: a NOTE to the orchestrator and a herdr notification, once; an API error ending a turn: reported once |
| Patrol (idle/asleep lanes with work, dead leads, serial leads, branches) | cron every 30 min, a REQUEST that wakes the orchestrator | v1's same checks from the loop every `patrol_min`; findings ride along with the orchestrator's next prompt and show on the board, never waking it |
| Rate limits | typed resume lines after a backoff | Claude Code's own unattended retry mode (`CLAUDE_CODE_RETRY_WATCHDOG`) |
| Crash and reboot | cron, PID registry | v1's cron `wake` runs `codeteam2 ensure-loop` every minute for an up team: it starts herdr's server and the loop if they are down; the plugin's startup hook tries to bring back configured autostart teams that were up |
| Compaction | `codeteam compact-now` typing /compact | the hook queues `/compact` and the resume line; the loop types each when idle |

## Running a team on v2 (runbook)

```bash
V2="$CODETEAM_HOME/v2"   # CODETEAM_HOME: your checkout of this repository
# 1. Give the manifest a [v2] table (herdr_session = "codeteam" is enough), then:
$V2/bin/codeteam2 up teams/<team>.toml --loop-only   # the loop only; sessions start when mail comes
#    or: $V2/bin/codeteam2 up teams/<team>.toml       # and start the staff now
# 2. From then on v1's cron leaves the team's runtime alone (wake, tick, patrol skip it while
#    team/v2/up exists) and its wake keeps herdr's server and the loop running once the owner is logged in
#    (launchd's gui/<uid> domain). sweep and rotate still run.
# 3. To come back after the owner logs in following a reboot with its staff resumed, list it in the plugin's
#    teams.toml with autostart = true (see "The herdr plugin" below).
# 4. Back to v1:
$V2/bin/codeteam2 down teams/<team>.toml             # ends the sessions; v1's cron takes over again
```

What is safe and what is not, with herdr itself: see "Use" below and `herdr session attach codeteam`.
Never `herdr server stop` the `codeteam` session by hand unless you mean to stop every team in it (cron
brings it back within a minute for teams that are up).

## Use

```bash
V2="$CODETEAM_HOME/v2"   # CODETEAM_HOME: your checkout of this repository
$V2/bin/codeteam2 up <manifest>          # workspace, roles, staff sessions, and the loop in its own pane
$V2/bin/codeteam2 status <manifest>      # every session's real state and its mail
$V2/bin/codeteam2 say <manifest> general Owner REQUEST Orc-<Team> "..."   # talk to the team
$V2/bin/codeteam2 tail <manifest>        # follow the team's messages live
$V2/bin/codeteam2 deck [teams...] [--json|--pane] [--no-motion]   # read-only live dashboard of every team
herdr session attach codeteam            # watch it all live (ctrl+b q detaches; everything keeps running);
                                         # the sidebar names each pane (Coord-alpha) with its waiting mail
$V2/bin/codeteam2 drop <manifest> <id...>   # take queued, held, or prompted-but-no-turn-yet messages out of
                                            # the queue (kept on record); one line per id, exit 1 if any was not dropped
$V2/bin/codeteam2 down <manifest> [--close]
```

A team needs a `[v2]` table in its manifest; every key is optional:

| Key | Default | What it does |
|---|---|---|
| `herdr_session` | `codeteam` | the herdr session the team runs in |
| `cap` | 16 | lanes awake at once |
| `swap_idle_min` | 20 | at the cap, a lane idle this long with nothing waiting makes room |
| `idle_exit_h` | 6 | a session idle this long with nothing waiting is ended (0: never); never the orchestrator or a designer, nor a session the owner put on hold (`team/held/<key>`) or one whose pane shows a subagent's view or unsent text in its input box |
| `keep_awake` | [] | more sessions never ended for being idle |
| `refresh_idle_min` | 50 | an idle session's refresh starts this long after its last transcript record (0: off) |
| `refresh_cold_min` | 58 | and not this long after it: past it the 1-hour cache may be cold |
| `refresh_min_tokens` | 150000 | the least context (its last turn's input + cache tokens) worth a refresh |
| `refresh_skip` | [] | sessions never refreshed |
| `refresh_commands` | /refocus, /prepare-for-compact, /compact <keep the handoff>, /recover-from-compact | what a refresh types, one per turn |
| `blocked_alert_min` | 2 | a blocked session is reported after this long |
| `gather_s` | 30 | a cold session's mail waits up to this long for more to join its prompt |
| `warm_s` | 3300 on the 1-hour cache, 240 on 5 minutes | a session whose turn ended this recently gets its mail at once |
| `typing_guard` | true | hold a session's mail while its input box holds unsent text |
| `draft_alert_min` | 10 | tell the owner, once, when unsent text or a pane showing a subagent's view has held a session this long while real mail (not ride-along) is queued for it |
| `patrol_min` | 30 | v1's patrol checks (0: off) |
| `mail_in_first_prompt` | true | a session started for mail gets it in its first prompt |
| `retry_watchdog` | true | Claude Code's unattended retry mode for 429/529 and usage limits |
| `poll_s` | 2 | seconds the loop normally pauses between iterations; after deferring a planned action, it pauses for the shorter of 1 s and `poll_s`, at most 10 times in a row before one `poll_s` pause |
| `resume` | false | lanes the loop starts resume their last conversation instead of starting fresh |
| `lane_model`, `staff_model`, `agent`, `mcp` | manifest's | overrides for v2 sessions (`agent = ""`: no --agent) |

Process commands stay v1's: `codeteam unit|squash|push-up|integrate|promote|approve|sweep ... <manifest>`.

## Files

- `codeteam2/herdr.py`: herdr CLI client.
- `codeteam2/store.py`: the message store (SQLite now; one interface).
- `codeteam2/team.py`: the team (v1 loaded as a library), sessions, launch scripts, role rendering
  with the runtime verbs pointed at codeteam2.
- `codeteam2/scheduler.py`: layout in herdr, and the loop (`plan()` holds its rules as a pure function).
- `codeteam2/screen.py`: reading a session's screen: unsent text in its input box, an API error.
- `codeteam2/patrol.py`: v1's patrol checks, run by the loop.
- `codeteam2/cli.py`: the commands. `codeteam2/plugin.py` and `plugin/`: the herdr plugin.
- `tests/test_v2.py`: the loop's rules, the loop against a fake herdr, the plugin, the store, launch
  parity with v1, the role rewrites, the entry point.
- `teams/smoke.toml`, `smoke/claude/`: the smoke team (sandbox only).
- `smoke/run.py`: a repeatable smoke run (fresh project and team, one task, checked end to end;
  `--herdr-session` runs it away from real teams).
- `smoke/restart_test.py`: typing guard, loop death, server restart and rollback on a kept smoke team.
- `codeteam2/transport.py`: how a message reaches a session (herdr prompt now; MCP push planned).

## The herdr plugin (optional)

The plugin is a thin layer over the commands above: `codeteam2 plugin <command>`, run by herdr.

```bash
herdr plugin link "$CODETEAM_HOME/v2/plugin"            # once; global to your user, inert until teams are listed
$EDITOR "$(herdr plugin config-dir codeteam.v2)/teams.toml"  # the teams it manages
```

```toml
[[team]]
manifest = "~/codeteam-gamma-preview/teams/example.toml"
autostart = true      # on herdr server start, try to bring the team back if it was up
```

Startup runs each autostart team's `up` in turn for the current herdr session, allowing each 15 minutes; it continues after failures and exits 1 if any team failed.
Results are printed to herdr's plugin log (`herdr plugin log list --plugin codeteam.v2`) and appended to `$HERDR_PLUGIN_STATE_DIR/startup.log` when writable. If that environment variable is unset, the file defaults to `~/.local/state/codeteam2/plugin-startup.log`.

| Action | What it does |
|---|---|
| `codeteam.v2.board` | every team's sessions, state and mail, refreshed (q closes) |
| `codeteam.v2.say` | message the team from you: who to, what kind, what |
| `codeteam.v2.tail` | follow the team's messages |
| `codeteam.v2.questions` | the team's open questions (`team/questions.md`) |
| `codeteam.v2.wake` / `.sleep` | start or end the session in the focused pane (a lane still waits for the lane cap) |

To put them on keys, add to `~/.config/herdr/config.toml`:

```toml
[[keys.command]]
key = "prefix+B"
type = "plugin_action"
command = "codeteam.v2.board"
description = "codeteam board"

[[keys.command]]
key = "prefix+M"
type = "plugin_action"
command = "codeteam.v2.say"
description = "message the team"
```

The plugin acts only in herdr sessions that its teams use (a team's `[v2] herdr_session`, default `codeteam`).

## Settings (environment)

| Variable | Default | What it sets |
|---|---|---|
| `CODETEAM_OWNER` | `Owner` | your name as a message sender and recipient (`say ... general <you> ...`) |
| `CODETEAM_WORKSPACE` | `~/codeteam-work` | where team folders, the creator inbox, smoke sandboxes and metrics live |
| `CODETEAM_LAUNCHD_PREFIX` | `com.codeteam` | launchd label prefix for the herdr server agents (`<prefix>.codeteam2.herdr.<session>`) |
| `CODETEAM_PYTHON` | `python3` on PATH | the Python 3.11+ that `bin/codeteam2` and the plugin re-run under |
| `CLAUDE_METRICS_DIR` / `CODETEAM_METRICS_DIR` | `$CODETEAM_WORKSPACE/metrics` | the status-line metrics the deck reads |
