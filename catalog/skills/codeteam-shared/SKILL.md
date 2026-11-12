---
name: codeteam-shared
description: How a codeteam team works - worktrees, zone walls, starting and waiting for agents by level, handing back once, messages without ceremony. Preloaded by every team role.
---

# codeteam: how this team works

## Where you work
- Your worktree is your write surface. Never `git checkout` or branch inside it; the coordinator cuts worktrees.
- Your lane owns some folders (its `owns` list). Edit only those. Read anything. The zone guard refuses an edit,
  build or test outside your walls and says why: that work belongs to another lane. Do not look for a way around it.
- An agent you start works under your walls. Brief it with them.

## Starting agents and waiting for them
- **You are a subagent** (lead, coder, checker, writer, reviewer, runner): start agents with
  `run_in_background: false`; the call returns their report. Never end your turn while one is running. If a call
  still says "Async agent launched", wait inside your turn: `watch-agent <id>` (it blocks for your Bash limit less a minute) (exit 0 done, 4 call
  again, 3 stalled: say so). Hand back once, when everything you started is back.
- **You are a session** (orchestrator, coordinator, designer): start a lead with `run_in_background: true`, then
  END YOUR TURN. Mail reaches you between turns; you are told when the lead finishes. Never wait inside a turn.
  A lead you think is hung: one look, `watch-agent <id> --max 30`; exit 3 is a finding for the orchestrator.
- A `[handback-send-enforce]` reminder is not an order to return. If something you started is running, keep waiting.

## Messages
Rule 7 in `rules/global.md` says when a message is sent and to whom. A session answers its `[codeteam]` prompts; a subagent sends nothing and hands back once.

## Never claim what you did not run
A test passes or a build is clean only if you ran it and its record says so. Quote the record, not memory.
